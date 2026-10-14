"""Real bounded fake process groups exercise resource enforcement and originals."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import input_bundle as bundle
import training


WORKER = r'''
import argparse, hashlib, json, os, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('worker')
p.add_argument('--manifest')
p.add_argument('--result')
a = p.parse_args()
m = json.loads(Path(a.manifest).read_text())
request = m['request']
print('fake stage stdout', flush=True)
print('fake stage stderr', file=sys.stderr, flush=True)
if request['mode'] == 'exit':
    raise SystemExit(7)
if request['mode'] == 'success':
    time.sleep(1.1)
    Path(a.result).write_text(json.dumps({'stage': m['stage'],
        'manifest_sha256': hashlib.sha256(Path(a.manifest).read_bytes()).hexdigest(),
        'outputs': {}}))
    raise SystemExit(0)
child = os.fork()
if child == 0:
    allocation = bytearray(64 * 1024 * 1024) if request['mode'] == 'rss' else bytearray(1)
    Path(request['pid_file']).write_text(str(os.getpid()))
    while True:
        time.sleep(0.05)
while True:
    time.sleep(0.05)
'''


@unittest.skipUnless(sys.platform == 'linux', 'Linux /proc process-group supervision')
class InputSupervisionTests(unittest.TestCase):
    def run_fake(self, directory, mode, wall, rss, metric=None):
        worker = directory / 'tools/reversi-ai-training/input_bundle.py'
        worker.parent.mkdir(parents=True)
        worker.write_text(WORKER)
        manifest = directory / 'frozen.json'
        stage = 'calibration-generate'
        bundle.save(manifest, {'version': bundle.VERSION, 'stage': stage,
                              'producer': {}, 'cwd': str(directory), 'inputs': [],
                              'total_wall_budget_seconds': bundle.TOTAL_WALL_SECONDS,
                              'request': {'mode': mode, 'pid_file': str(directory / 'child.pid')},
                              'bounds': {'wall_seconds': wall, 'rss_bytes': rss, 'sample_seconds': 1}})
        output = directory / 'originals'
        diagnostics = io.StringIO()
        kwargs = {} if metric is None else {'metric_reader': metric}
        error = None
        with patch.object(bundle, 'verify_source'), patch.object(bundle, 'git', return_value=b''), \
             patch.dict(bundle.BOUNDS, {stage: (wall, rss)}), contextlib.redirect_stderr(diagnostics):
            try:
                bundle.supervise(manifest, output, heartbeat_seconds=0.1, **kwargs)
            except training.TrainingError as caught:
                error = caught
        return output, diagnostics.getvalue(), error

    def assert_descendant_stopped(self, pid):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            path = Path(f'/proc/{pid}/stat')
            try:
                fields = path.read_text().split(') ', 1)[1].split()
            except FileNotFoundError:
                return
            if fields[0] == 'Z':
                return  # The process is dead; its external parent may not yet reap it.
            time.sleep(0.02)
        self.fail(f'descendant {pid} is still running after supervision stopped')

    def assert_failed_originals(self, output, status):
        self.assertFalse((output / 'report.json').exists())
        self.assertTrue((output / 'manifest.json').is_file())
        report = json.loads((output / 'failure.json').read_text())
        self.assertEqual(report['status'], status)
        self.assertEqual(report['stdout_sha256'], training.sha256_file(output / 'stdout'))
        self.assertEqual(report['stderr_sha256'], training.sha256_file(output / 'stderr'))
        self.assertIn(b'fake stage stdout', (output / 'stdout').read_bytes())
        self.assertIn(b'fake stage stderr', (output / 'stderr').read_bytes())
        return report

    def test_wall_and_rss_stop_actual_descendants(self):
        for mode, wall, limit, status in (('wall', 1.3, 256 * bundle.MIB, 'wall-limit'),
                                          ('rss', 3, 32 * bundle.MIB, 'rss-limit')):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                def metric(group):
                    observed = bundle.process_metrics(group)
                    # Let the fake child finish allocating before evaluating the RSS bound.
                    if mode == 'rss' and not (directory / 'child.pid').exists():
                        return 0, observed[1], observed[2]
                    return observed
                output, diagnostics, error = self.run_fake(directory, mode, wall, limit, metric)
                self.assertIsNotNone(error)
                report = self.assert_failed_originals(output, status)
                child = int((directory / 'child.pid').read_text())
                self.assert_descendant_stopped(child)
                if mode == 'rss':
                    self.assertGreater(report['peak_observed_rss_bytes'], limit)
                self.assertIn('status=failed', diagnostics)
                self.assertNotIn('status=saved', diagnostics)

    def test_unavailable_metrics_and_interrupt_stop_actual_descendants(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                def metric(group):
                    if (directory / 'child.pid').exists():
                        if interrupted:
                            raise KeyboardInterrupt()
                        raise training.TrainingError('injected unavailable metrics')
                    return bundle.process_metrics(group)
                output, _, error = self.run_fake(directory, 'sleep', 4, 256 * bundle.MIB, metric)
                self.assertIsNotNone(error)
                self.assert_failed_originals(output, 'interrupted' if interrupted else 'metric-or-launch-failure')
                self.assert_descendant_stopped(int((directory / 'child.pid').read_text()))

    def test_nonzero_exit_keeps_originals(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, _, error = self.run_fake(Path(temporary), 'exit', 4, 256 * bundle.MIB)
            self.assertIsNotNone(error)
            self.assertEqual(self.assert_failed_originals(output, 'exit-failure')['exit_code'], 7)

    def test_heartbeat_progress_and_completion_are_published_last(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, diagnostics, error = self.run_fake(Path(temporary), 'success', 5, 256 * bundle.MIB)
            self.assertIsNone(error)
            self.assertTrue((output / 'report.json').is_file())
            self.assertFalse((output / 'failure.json').exists())
            lines = diagnostics.splitlines()
            self.assertGreaterEqual(sum('status=running' in line for line in lines), 2)
            self.assertIn('done=1 total=1 status=saved', lines[-1])
            for line in lines:
                self.assertRegex(line, r'^progress input-bundle stage=calibration-generate done=[01] total=1 status=(running|saved) elapsed_s=\d+\.\d{3} rss_bytes=\d+$')


if __name__ == '__main__':
    unittest.main()
