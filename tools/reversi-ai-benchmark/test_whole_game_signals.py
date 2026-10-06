"""Exercise actual runner death after durable saves, without expensive AI searches."""

import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import unittest

import whole_game

CHILD = r"""
import sys, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import test_whole_game as fixture
w = fixture.whole_game
root = Path(sys.argv[1])
args = SimpleNamespace(kind="cli", binary=root/"binary", artifact=root/"artifact",
    midgame_depth=8, cache_scope="game", timeout_seconds=2, max_rss_kib=1000,
    max_decisions=120, oracle_cwd=None, output=root/"report.json", progress_every=1,
    source_revision="fixture")
calls = []
def game(row, assignment, seats, kind, timeout, max_decisions):
    if sys.argv[2] == "interrupt" and len(calls) == 2:
        print("READY", flush=True)
        time.sleep(30)
    calls.append([row["id"], assignment])
    record = fixture.synthetic_game(row, assignment, 8)
    for step in record["steps"]:
        raw = {"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 100}
        step.update(legal_move_count=len(w.oracle.legal_moves(step["board"], step["side"])),
                    phase=w.decision_phase(step["board"]), resources=dict(raw),
                    resource_observations={"before": dict(raw), "after": dict(raw)})
        seats[step["seat"]].diagnostics[step["id"]] = step["search"]
    return record
with patch.object(w, "Seat", fixture.FakeSeat), patch.object(w, "game", game), patch.object(w, "proc_usage", return_value={"user_cpu_ns":0,"system_cpu_ns":0,"peak_rss_kib":100}):
    w.measure_resumable(args, "a"*64, "fixture", root/"checkpoints")
(root/"calls.json").write_text(__import__("json").dumps(calls))
"""


@unittest.skipUnless(sys.platform == "linux", "Linux measurement contract")
class SignalResumeTests(unittest.TestCase):
    def test_sigterm_and_sigkill_preserve_two_and_measure_only_six(self):
        for requested_signal in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=requested_signal), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "binary").write_bytes(b"fixture-cli")
                (root / "artifact").write_bytes(b"fixture-artifact")
                process = subprocess.Popen([sys.executable, "-c", CHILD, str(root), "interrupt"],
                    cwd=Path(__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                try:
                    self.assertTrue(select.select([process.stdout], [], [], 15)[0], "runner did not reach save boundary")
                    self.assertEqual(process.stdout.readline(), b"READY\n")
                    self.assertEqual(len(list((root / "checkpoints").glob("game-*.json"))), 2)
                    os.kill(process.pid, requested_signal)
                    process.wait(timeout=10)
                    self.assertNotEqual(process.returncode, 0)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
                    process.stdout.close()
                resumed = subprocess.run([sys.executable, "-c", CHILD, str(root), "resume"],
                    cwd=Path(__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
                self.assertEqual(resumed.returncode, 0, resumed.stderr.decode())
                self.assertEqual(len(json.loads((root / "calls.json").read_text())), 6)
                report = whole_game.read_canonical(root / "report.json")
                whole_game.verify(report)
                self.assertEqual(len({game["session_id"] for game in report["games"]}), 2)
