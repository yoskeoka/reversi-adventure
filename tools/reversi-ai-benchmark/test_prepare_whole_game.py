"""Manifest/script tests use fake binaries and never perform production measurements."""

import argparse
import copy
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import whole_game
from test_whole_game import redigest, synthetic_report

SPEC = importlib.util.spec_from_file_location("prepare_whole_game", Path(__file__).with_name("prepare-whole-game-measurement.py"))
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cli = self.root / "fake cli'quoted"
        self.cli.write_text("#!/bin/sh\nexit 99\n")
        self.cli.chmod(0o755)
        self.oracle = self.root / "oracle"
        self.oracle.write_text("#!/bin/sh\nexit 98\n")
        self.oracle.chmod(0o755)
        self.artifact = self.root / "artifact.json"
        self.artifact.write_text("{}\n")
        self.args = argparse.Namespace(cli_binary=self.cli, oracle_binary=self.oracle,
                                      artifact=self.artifact, output_dir=self.root / "new measurements",
                                      source_revision=prepare.revision(), harness_revision=prepare.revision(),
                                      legacy_dir=None, legacy_binary=None, legacy_candidate_binary=None,
                                      oracle_cwd=None, timeout_seconds=310, max_rss_kib=1000)

    def generate(self):
        with mock.patch.object(whole_game, "measure_resumable") as measure, mock.patch.object(prepare, "probe_reset"):
            path = prepare.prepare(self.args)
            measure.assert_not_called()
        return path

    def test_prepare_pins_inputs_order_and_safe_runnable_script(self):
        path = self.generate()
        manifest = prepare.verify_manifest(path)
        self.assertEqual([c["id"] for c in manifest["conditions"]],
                         [f"{name}-{depth}" for depth in (12, 8) for name in ("turn", "game", "persistent")])
        self.assertEqual(len(manifest["assignments"]), 8)
        self.assertEqual(manifest["inputs"]["cli"], prepare.pin(self.cli))
        script = self.args.output_dir / "run-whole-game.sh"
        subprocess.run(["rtk", "bash", "-n", str(script)], check=True)
        self.assertIn("rtk python3", script.read_text())
        with self.assertRaises(whole_game.BenchmarkError):
            prepare.prepare(self.args)

    def test_prepare_rejects_binary_without_reset_ack_before_creating_output(self):
        with mock.patch.object(whole_game, "measure_resumable") as measure:
            with self.assertRaises(whole_game.BenchmarkError):
                prepare.prepare(self.args)
            measure.assert_not_called()
        self.assertFalse(self.args.output_dir.exists())

    def test_changed_input_manifest_host_harness_and_order_fail_closed(self):
        path = self.generate()
        original = prepare.load(path)
        self.cli.write_text("changed binary")
        with self.assertRaisesRegex(whole_game.BenchmarkError, "digest mismatch"):
            prepare.verify_manifest(path)
        self.cli.write_text("#!/bin/sh\nexit 99\n")
        for mutate in (lambda m: m["host"].update(host="another host"),
                       lambda m: m.update(harness_revision="b" * 40),
                       lambda m: m["harness_files"].pop(),
                       lambda m: m["conditions"].reverse()):
            changed = copy.deepcopy(original)
            mutate(changed)
            changed = prepare.signed({k: v for k, v in changed.items() if k != "manifest_digest"})
            path.write_bytes(whole_game.canonical(changed))
            with self.assertRaises(whole_game.BenchmarkError):
                prepare.verify_manifest(path)
        path.write_bytes(whole_game.canonical(original).replace(b'"schema_version":1', b'"schema_version":2'))
        with self.assertRaisesRegex(whole_game.BenchmarkError, "manifest digest"):
            prepare.verify_manifest(path)

    def test_explicit_fourteen_legacy_results_verify_without_process_launch(self):
        directory = self.root / "legacy"
        directory.mkdir()
        for depth in (12, 8):
            reports = {}
            for name in ("oracle", "legacy", "turn", "game", "persistent"):
                report = synthetic_report(depth)
                report["binary"] = prepare.pin(self.oracle if name == "oracle" else self.cli)
                report["artifact"] = None if name == "oracle" else prepare.pin(self.artifact)
                report["kind"] = {"oracle": "oracle", "legacy": "cli-legacy", "persistent": "cli-persistent"}.get(name, "cli")
                report["settings"]["exact_cache_scope"] = "turn" if name == "turn" else "game"
                if name in ("oracle", "legacy"):
                    report["oracle_profile"] = (whole_game.oracle.profile_metadata(whole_game.profile(depth))
                                                if name == "oracle" else None)
                    for game in report["games"]:
                        for step in game["steps"]:
                            step.pop("search")
                        game["cache"] = None
                        game["search_count"] = sum(step["move"] != "pass" for step in game["steps"])
                    report["aggregate"] = whole_game.totals(report["games"])
                if name == "persistent":
                    report["settings"]["process_lifetime"] = "all-games-per-seat"
                    report["process_totals"] = {side: {"startup_ns": 1, "shutdown_ns": 1,
                                                      "peak_rss_kib": 100, "user_cpu_ns": 8,
                                                      "system_cpu_ns": 0} for side in ("B", "W")}
                redigest(report)
                whole_game.verify(report)
                reports[name] = report
                (directory / f"{name}-{depth}.json").write_bytes(whole_game.canonical(report))
            (directory / f"comparison-{depth}.json").write_bytes(whole_game.canonical(
                whole_game.comparison(reports["turn"], reports["game"])))
            game = reports["game"]
            evidence = {"schema_version": 1, "runner_version": whole_game.VERSION,
                        "cli_report_digest": game["report_digest"],
                        "oracle_binary_sha256": whole_game.digest(self.oracle),
                        "oracle_profile": whole_game.oracle.profile_metadata(whole_game.profile(depth)),
                        "positions": [{"id": step["id"], "board": step["board"], "side": step["side"],
                                       "move": step["move"], "cli_score": step["search"]["score"],
                                       "oracle_score": step["search"]["score"], "selected_score": step["search"]["score"]}
                                      for g in game["games"] for step in g["steps"] if step["search"]["exact"]]}
            redigest(evidence)
            (directory / f"exact-check-{depth}.json").write_bytes(whole_game.canonical(evidence))
        self.args.legacy_dir = directory
        self.args.legacy_binary = self.cli
        self.args.legacy_candidate_binary = self.cli
        with mock.patch.object(whole_game, "Seat", side_effect=AssertionError("seat started")):
            # Git identity is the only allowed subprocess; override it while verifying registry.
            with mock.patch.object(prepare, "revision", return_value=self.args.harness_revision):
                path = self.generate()
                manifest = prepare.verify_manifest(path)
        self.assertEqual(len(manifest["legacy"]), 14)
        (directory / "exact-check-8.json").write_text("{}\n")
        with self.assertRaisesRegex(whole_game.BenchmarkError, "digest mismatch"):
            prepare.verify_manifest(path)

    def test_corrupt_existing_result_stops_before_measurement(self):
        path = self.generate()
        (self.args.output_dir / "persistent-8.json").write_text("{}\n")
        with mock.patch.object(whole_game, "measure_resumable") as measure:
            with self.assertRaises(whole_game.BenchmarkError):
                prepare.execute(path, False, 1)
            measure.assert_not_called()

    def test_report_cannot_claim_manifest_with_different_measurement_settings(self):
        manifest = prepare.verify_manifest(self.generate())
        condition = manifest["conditions"][0]
        args = prepare.args_for_condition(manifest, condition, 1)
        report = {"manifest_digest": manifest["manifest_digest"], "condition_id": condition["id"],
                  "identity": whole_game.measurement_identity(args)}
        report["identity"]["settings"]["timeout_seconds"] += 1
        with mock.patch.object(whole_game, "verify"):
            with self.assertRaisesRegex(whole_game.BenchmarkError, "manifest identity"):
                prepare.verify_condition(manifest, condition, report, 1)


if __name__ == "__main__":
    unittest.main()
