"""Stub-only orchestration tests; never starts self-play or the external Oracle."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import whole_game as wg

MODULE = Path(__file__).with_name("run-efficiency8-closeout.py")
SPEC = importlib.util.spec_from_file_location("efficiency8_closeout", MODULE)
assert SPEC and SPEC.loader
closeout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(closeout)


class Efficiency8CloseoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        (self.root / "tools/reversi-ai-oracle").mkdir(parents=True)
        (self.root / "tools/reversi-ai-oracle/oracle.py").write_text("# fixture\n")
        self.oracle_binary = self.base / "oracle"
        self.oracle_binary.write_bytes(b"fake oracle")
        self.oracle_binary.chmod(0o755)
        self.oracle_cwd = self.base / "oracle-data"
        (self.oracle_cwd / "resources").mkdir(parents=True)
        (self.oracle_cwd / "resources/eval.egev2").write_bytes(b"fake eval")
        self.output = self.base / "measurement-output"
        self.events = []
        self.cli = self.output / "build/target/release/reversi-ai-cli"
        self.identity = None
        self.report = None
        self.evidence = None

    def tearDown(self):
        self.temp.cleanup()

    def args(self, *, max_rss_kib=1000, progress_every=2):
        return SimpleNamespace(oracle_binary=self.oracle_binary, oracle_cwd=self.oracle_cwd,
                               output_dir=self.output, max_rss_kib=max_rss_kib,
                               progress_every=progress_every)

    def make_report(self, args):
        measurement_identity = {"source_revision": "a" * 40,
                                "settings": {"max_rss_kib": args.max_rss_kib}}
        games = [{"opening_id": f"opening-{index // 2 + 1}", "assignment": index % 2,
                  "wall_ns": (100 + index) * 1_000_000_000} for index in range(8)]
        report = {"schema_version": 4, "score_contract": wg.SCORE_CONTRACT,
                  "condition_id": "efficiency8", "identity": measurement_identity,
                  "settings": {"max_rss_kib": args.max_rss_kib}, "games": games,
                  "performance_summary": {"game_count": 8}}
        report["report_digest"] = hashlib.sha256(wg.canonical(report)).hexdigest()
        self.report = report
        return report

    def make_evidence(self, *args, **kwargs):
        self.events.append("oracle")
        self.evidence = {"schema_version": 3, "report_digest": "c" * 64,
            "positions": [{"id": "position-1", "queries": [{
                "role": "root", "board": "B" * 64, "side": "B", "effective_side": "B",
                "search": {"value": 4, "exact": True, "completed_depth": 16,
                           "nodes": 300, "elapsed_ms": 25},
                "process": {"wall_ns": 30_000_000, "resources": {
                    "user_cpu_ns": 20_000_000, "system_cpu_ns": 5_000_000,
                    "peak_rss_kib": 500}}}]}]}
        return self.evidence

    def setup_patches(self, stack):
        def build(root, output_dir, revision):
            self.events.append("build")
            self.cli.parent.mkdir(parents=True, exist_ok=True)
            self.cli.write_bytes(b"fake cli")
            self.cli.chmod(0o755)
            receipt = {"source_revision": revision, "command": [],
                       "cli": {"path": str(self.cli.resolve()), "sha256": wg.digest(self.cli)}}
            return receipt, 10

        def identity(root, output_dir, revision, build, runtime, cap, every):
            self.identity = closeout.seal({"schema_version": 1, "identity_digest": "",
                "runner_version": closeout.RUNNER_VERSION, "score_contract": wg.SCORE_CONTRACT,
                "source_revision": revision, "cli": build["cli"], "oracle": runtime,
                "settings": {"sample": "efficiency8", "max_rss_kib_per_process": cap,
                             "progress_every": every}, "output_directory": str(output_dir)},
                "identity_digest")
            return self.identity

        def measure(args, _manifest_digest, condition, _checkpoints, **kwargs):
            self.events.append("measure")
            self.assertEqual(condition, "efficiency8")
            report = self.make_report(args)
            report["identity"] = wg.measurement_identity(args)
            report["report_digest"] = hashlib.sha256(wg.canonical(
                {key: value for key, value in report.items() if key != "report_digest"})).hexdigest()
            wg.atomic_write(args.output, report)
            callback = kwargs.get("game_progress")
            if callback:
                for done in range(1, 9):
                    callback(f"opening-{(done-1)//2+1}-seat{(done-1)%2}", done, 8,
                             100 + done, done)
            return report

        stack.enter_context(patch.object(closeout, "source_revision", return_value="a" * 40))
        stack.enter_context(patch.object(closeout, "require_clean_checkout"))
        stack.enter_context(patch.object(closeout, "build_release", side_effect=build))
        stack.enter_context(patch.object(closeout, "run_identity", side_effect=identity))
        stack.enter_context(patch.object(closeout, "probe_cli",
            side_effect=lambda *_args: self.events.append("cli-preflight")))
        stack.enter_context(patch.object(wg, "measurement_identity", side_effect=lambda args: {
            "source_revision": args.source_revision, "settings": {"max_rss_kib": args.max_rss_kib}}))
        stack.enter_context(patch.object(wg, "measure_resumable", side_effect=measure))
        stack.enter_context(patch.object(wg, "verify"))
        stack.enter_context(patch.object(wg, "oracle_evidence", side_effect=self.make_evidence))
        stack.enter_context(patch.object(wg, "verify_oracle_evidence"))
        stack.enter_context(patch.object(wg, "verify_oracle_checkpoints"))

    def test_runs_stages_in_order_and_publishes_digest_pinned_summary(self):
        with contextlib.ExitStack() as stack:
            self.setup_patches(stack)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                summary = closeout.run_closeout(self.args(), root=self.root)
        self.assertEqual(self.events, ["build", "cli-preflight", "measure", "oracle"])
        self.assertTrue((self.output / "summary.json").is_file())
        self.assertEqual(summary["performance"]["mean_seconds"], 103.5)
        self.assertEqual(summary["performance"]["nearest_rank_p95_seconds"], 107)
        self.assertEqual(summary["oracle_aggregate"]["queries"], 1)
        self.assertEqual(summary["oracle_aggregate"]["nodes"], 300)
        self.assertEqual(summary["summary_digest"], closeout.seal(summary, "summary_digest")["summary_digest"])
        output = stderr.getvalue()
        stages = [output.index(f"stage={stage} status=started") for stage in
                  ("build", "cli-preflight", "self-play", "report-verification", "oracle-check",
                   "oracle-verification")]
        self.assertEqual(stages, sorted(stages))
        self.assertIn("progress efficiency8 stage=self-play game=opening-4-seat1 done=8 total=8", output)
        self.assertIn("progress efficiency8 stage=complete games=8", output)

    def test_completed_summary_is_verified_and_reused_without_long_stages(self):
        with contextlib.ExitStack() as stack:
            self.setup_patches(stack)
            with contextlib.redirect_stderr(io.StringIO()):
                first = closeout.run_closeout(self.args(), root=self.root)
            self.events.clear()
            with contextlib.redirect_stderr(io.StringIO()):
                second = closeout.run_closeout(self.args(), root=self.root)
        self.assertEqual(first, second)
        self.assertEqual(self.events, ["build"])

    def test_preflight_rejects_invalid_rss_before_build(self):
        with patch.object(closeout, "source_revision", return_value="a" * 40), \
             patch.object(closeout, "require_clean_checkout"), \
             patch.object(closeout, "build_release") as build:
            with self.assertRaisesRegex(wg.BenchmarkError, "positive integer"):
                closeout.run_closeout(self.args(max_rss_kib=0), root=self.root)
        build.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_failed_oracle_stage_does_not_publish_success_summary(self):
        with contextlib.ExitStack() as stack:
            self.setup_patches(stack)
            stack.enter_context(patch.object(wg, "oracle_evidence",
                side_effect=wg.BenchmarkError("Oracle fixture failed")))
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(wg.BenchmarkError,
                    "Oracle fixture failed"):
                closeout.run_closeout(self.args(), root=self.root)
        self.assertTrue((self.output / "whole-game-report.json").is_file())
        self.assertFalse((self.output / "summary.json").exists())
        state = closeout.read_object(self.output / "stage-state.json")
        self.assertEqual(state["stages"]["oracle-check"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
