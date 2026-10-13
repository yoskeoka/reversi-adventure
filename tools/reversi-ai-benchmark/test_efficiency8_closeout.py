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
                  "binary": self.identity["cli"],
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
                    "peak_rss_kib": 500}},
                "execution_host": wg.execution_host_identity()}]}]}
        return self.evidence

    def setup_patches(self, stack):
        def build(root, output_dir, revision, **_kwargs):
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
                "host": wg.execution_host_identity(),
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
        stack.enter_context(patch.object(closeout, "validate_saved_identity", return_value="a" * 40))
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

    def legacy_identity(self, *, host=None, settings=None):
        harness_paths = {
            "run-efficiency8-closeout.py": "tools/reversi-ai-benchmark/run-efficiency8-closeout.py",
            "whole_game.py": "tools/reversi-ai-benchmark/whole_game.py",
            "exact_threshold.py": "tools/reversi-ai-benchmark/exact_threshold.py",
            "prepare-whole-game-measurement.py": "tools/reversi-ai-benchmark/prepare-whole-game-measurement.py",
            "oracle.py": "tools/reversi-ai-oracle/oracle.py"}
        harness = {name: {"path": str((self.root / relative).resolve()),
                          "sha256": hashlib.sha256(relative.encode()).hexdigest()}
                   for name, relative in harness_paths.items()}
        runtime = {"binary": {"path": str(self.oracle_binary.resolve()), "sha256": wg.digest(self.oracle_binary)},
                   "working_directory": str(self.oracle_cwd.resolve()), "resources_digest": "r" * 64}
        identity = {"schema_version": 1, "runner_version": closeout.LEGACY_RUNNER_VERSION,
            "score_contract": wg.SCORE_CONTRACT, "source_revision": closeout.LEGACY_SOURCE_REVISION,
            "cli": {"path": str((self.output / "build/target/release/reversi-ai-cli").resolve()),
                    "sha256": "c" * 64},
            "oracle": runtime,
            "settings": settings or {"sample": "efficiency8", "games": 8, "evaluator": "strategic",
                "opening_depth": 8, "midgame_depth": 8, "endgame_depth": 8, "exact_empty": 16,
                "cache_scope": "turn", "search_time_limit_ms": None, "node_limit": None,
                "game_timeout_seconds": 600, "oracle_timeout_seconds": 600,
                "max_rss_kib_per_process": 1000, "progress_every": 2},
            "host": host or {"node": "xps", "system": "Linux-6.18.40.1-microsoft-standard-WSL2-x86_64-with-glibc2.35",
                             "machine": "x86_64"},
            "openings_sha256": wg.digest(Path(closeout.__file__).with_name("whole-game-openings-v1.json")),
            "harness": harness, "output_directory": str(self.output.resolve())}
        return closeout.seal(identity, "identity_digest"), runtime, harness_paths

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
        self.assertEqual(summary["oracle_queries"][0]["execution_host"], wg.execution_host_identity())
        self.assertEqual(len(summary["host_invocations"]), 1)
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

    def test_kernel_release_is_the_only_host_difference_allowed(self):
        saved = {"node": "xps", "machine": "x86_64",
                 "system": "Linux-6.18.40.1-microsoft-standard-WSL2-x86_64-with-glibc2.35"}
        current = {"node": "xps", "machine": "x86_64",
                   "system": "Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.35"}
        self.assertTrue(closeout.same_linux_host_except_kernel(saved, current))
        for key, value in (("node", "other"), ("machine", "aarch64"),
                           ("system", "Linux-6.18.54.1-other-distro")):
            changed = dict(current, **{key: value})
            self.assertFalse(closeout.same_linux_host_except_kernel(saved, changed))

    def test_legacy_identity_is_pinned_to_approved_lineage_and_inputs(self):
        identity, runtime, harness_paths = self.legacy_identity()
        current_host = {"node": "xps", "machine": "x86_64",
                        "system": "Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.35"}
        blob_hashes = {relative: item["sha256"] for name, relative in harness_paths.items()
                       for item in [identity["harness"][name]]}
        openings_path = "tools/reversi-ai-benchmark/whole-game-openings-v1.json"
        with patch.object(wg, "execution_host_identity", return_value=current_host), \
             patch.object(closeout, "git_blob_sha256", side_effect=lambda _root, _revision, path:
                          identity["openings_sha256"] if path == openings_path else blob_hashes[path]), \
             patch.object(closeout.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            self.assertEqual(closeout.validate_saved_identity(identity, root=self.root,
                output_dir=self.output.resolve(), current_revision="d" * 40, runtime=runtime,
                max_rss_kib=1000, progress_every=2), closeout.LEGACY_SOURCE_REVISION)
            for key, value in (("max_rss_kib_per_process", 999),):
                changed = dict(identity)
                changed["settings"] = dict(identity["settings"], **{key: value})
                changed = closeout.seal(changed, "identity_digest")
                with self.subTest(input=key), self.assertRaises(wg.BenchmarkError):
                    closeout.validate_saved_identity(changed, root=self.root,
                        output_dir=self.output.resolve(), current_revision="d" * 40, runtime=runtime,
                        max_rss_kib=1000, progress_every=2)
            changed_host = dict(identity, host=dict(identity["host"], node="other"))
            changed_host = closeout.seal(changed_host, "identity_digest")
            with self.assertRaisesRegex(wg.BenchmarkError, "host differs"):
                closeout.validate_saved_identity(changed_host, root=self.root,
                    output_dir=self.output.resolve(), current_revision="d" * 40, runtime=runtime,
                    max_rss_kib=1000, progress_every=2)

    def test_invalid_saved_runner_is_rejected_before_build_or_cli(self):
        self.output.mkdir(parents=True)
        identity = closeout.seal({"schema_version": 1, "runner_version": "unrecognized-runner",
                                  "source_revision": closeout.LEGACY_SOURCE_REVISION},
                                 "identity_digest")
        wg.atomic_write(self.output / "run-identity.json", identity)
        with patch.object(closeout, "source_revision", return_value="d" * 40), \
             patch.object(closeout, "require_clean_checkout"), \
             patch.object(closeout, "build_release") as build, \
             patch.object(closeout, "probe_cli") as probe:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(
                    wg.BenchmarkError, "unsupported closeout runner"):
                closeout.run_closeout(self.args(), root=self.root)
        build.assert_not_called()
        probe.assert_not_called()

    def test_stage_state_v1_migrates_and_records_resume_host(self):
        self.output.mkdir(parents=True)
        original_host = {"node": "xps", "machine": "x86_64",
                         "system": "Linux-6.18.40.1-microsoft-standard-WSL2-x86_64-with-glibc2.35"}
        resumed_host = {"node": "xps", "machine": "x86_64",
                        "system": "Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.35"}
        identity = closeout.seal({"schema_version": 1, "runner_version": closeout.LEGACY_RUNNER_VERSION,
            "source_revision": closeout.LEGACY_SOURCE_REVISION, "host": original_host}, "identity_digest")
        state = closeout.seal({"schema_version": 1, "identity_digest": identity["identity_digest"],
                               "stages": {"self-play": {"elapsed_ns": 12, "attempts": 1,
                                                         "failures": 0, "status": "completed"}}},
                              "state_digest")
        wg.atomic_write(self.output / "stage-state.json", state)
        with patch.object(wg, "execution_host_identity", return_value=resumed_host):
            tracker = closeout.StageTracker(self.output, identity, 0.0, current_revision="d" * 40)
        self.assertEqual(tracker.state["schema_version"], 2)
        self.assertEqual(tracker.state["stages"]["self-play"]["elapsed_ns"], 12)
        self.assertEqual([item["host"] for item in tracker.state["invocations"]],
                         [original_host, resumed_host])

    def test_report_rejects_cli_binary_different_from_pinned_identity(self):
        self.cli.parent.mkdir(parents=True, exist_ok=True)
        self.cli.write_bytes(b"fixture cli")
        cli_identity = {"path": str(self.cli.resolve()), "sha256": "a" * 64}
        report = {"binary": {"path": str(self.cli.resolve()), "sha256": "b" * 64}}
        identity = {"cli": cli_identity}
        with patch.object(wg, "verify"), \
             self.assertRaisesRegex(wg.BenchmarkError, "differs from the pinned release CLI"):
            closeout.validate_measurement_report(report, self.output / "report.json", identity,
                                                 self.cli, self.args(), self.output)

    def test_oracle_runtime_change_after_preflight_is_rejected(self):
        pinned = {"binary": {"path": str(self.oracle_binary)},
                  "working_directory": str(self.oracle_cwd), "resources_digest": "a" * 64}
        with patch.object(wg, "oracle_runtime_identity", return_value={"resources_digest": "b" * 64}), \
             self.assertRaisesRegex(wg.BenchmarkError, "Oracle runtime changed after closeout preflight"):
            closeout.require_pinned_oracle_runtime(pinned)

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
