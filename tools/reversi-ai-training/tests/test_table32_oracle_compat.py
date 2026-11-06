"""0054-only replay of a rebuilt Oracle from the source-pinned release."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optimizer_compare_inputs
import optimizer_compare_matches
import input_bundle
import production_cycle
import table32_oracle_compat as oracle_compat
import table32_players
import training


class Table32OracleCompatTests(unittest.TestCase):
    def fixture(self, root: Path) -> dict:
        oracle_path = root / "Egaroucid_for_Console.out"
        oracle_path.write_bytes(b"rebuilt same-version Oracle")
        archive_path = root / "egaroucid-v7.8.1.tar.gz"
        archive_path.write_bytes(b"source archive fixture")
        receipt_path = root / "runtime.json"
        receipt_path.write_text("{}\n", encoding="utf-8")
        candidate_path = root / "candidate-cli"
        candidate_path.write_bytes(b"candidate fixture")
        candidate_path.chmod(0o755)

        source_root = root / "0019"
        source_root.mkdir()
        old_oracle_pin = {"path": str(oracle_path.resolve()), "sha256": "0" * 64}
        profile = production_cycle.oracle_module.profile_metadata(production_cycle.ORACLE_PROFILE)
        manifest = {
            "schema_version": 2,
            "producer_version": production_cycle.VERSION,
            "score_contract": training.SCORE_CONTRACT,
            "execution_commit": "a" * 40,
            "oracle_profile_id": production_cycle.ORACLE_PROFILE.name,
            "oracle_profile": profile,
            "oracle_exact_solver_empty_squares": production_cycle.oracle_module.profile_exact_threshold(
                production_cycle.ORACLE_PROFILE),
            "oracle_version": table32_players.oracle.ORACLE_VERSION,
            "oracle_source_sha256": table32_players.oracle.SOURCE_SHA256,
            "oracle_binary": old_oracle_pin,
        }
        source_manifest = source_root / "manifest.json"
        source_manifest.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        (source_root / "report.json").write_text("{}\n", encoding="utf-8")
        self_play = source_root / "phases" / "self-play" / "attempt-0001"
        self_play.mkdir(parents=True)
        (self_play / "games.jsonl").write_text("", encoding="utf-8")

        comparison_root, evaluation_root = root / "0052", root / "0053"
        comparison_root.mkdir()
        evaluation_root.mkdir()
        for run_root in (comparison_root, evaluation_root):
            (run_root / "manifest.json").write_text(
                json.dumps({"matches": {"openings": {}}}) + "\n", encoding="utf-8")
            (run_root / "report.json").write_text("{}\n", encoding="utf-8")

        runtime = {"binary": {"path": str(oracle_path.resolve()),
                               "sha256": training.sha256_file(oracle_path)},
                   "working_directory": str(root.resolve()), "resources": []}
        receipt = {"version": table32_players.oracle.RUNTIME_RECEIPT_VERSION,
                   "status": "complete", "oracle_version": manifest["oracle_version"],
                   "source_archive": {"path": str(archive_path.resolve()),
                                      "sha256": manifest["oracle_source_sha256"]},
                   "runtime": runtime}

        source_pins = {"schema_version": 1, "fixture": False,
                       "source_manifest": production_cycle.file_entry(source_manifest),
                       "files": [old_oracle_pin]}
        context = {"pins": source_pins,
                   "source_predecessors": {"self-play": self_play},
                   "source_context": {"manifest": manifest},
                   "exposure_keys": [], "validation": [], "held_out": [],
                   "corpus": [], "golden": [], "reserved": set()}
        return locals()

    def test_source_identity_adapter_is_scoped_and_used_by_pinned_readers(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(Path(temporary))
            actual_sha = training.sha256_file(fixture["oracle_path"])
            self.assertNotEqual(actual_sha, fixture["manifest"]["oracle_binary"]["sha256"])
            with mock.patch.object(table32_players.oracle, "verify_runtime_receipt",
                                   return_value=fixture["receipt"]), \
                 mock.patch.object(table32_players.oracle, "runtime_identity",
                                   return_value=fixture["runtime"]):
                with self.assertRaisesRegex(training.TrainingError, "comparison pinned input changed"):
                    optimizer_compare_inputs.load_pinned(fixture["source_pins"])

                with oracle_compat.historical_replay(fixture["source_manifest"], fixture["receipt_path"]):
                    self.assertEqual(production_cycle.file_entry(fixture["oracle_path"]),
                                     fixture["manifest"]["oracle_binary"])
                    with mock.patch.object(optimizer_compare_inputs, "load_source",
                                           return_value=fixture["context"]):
                        self.assertEqual(optimizer_compare_inputs.load_pinned(
                            fixture["source_pins"])["pins"], fixture["source_pins"])

                    with mock.patch.object(optimizer_compare_matches, "_forbidden", return_value=set()), \
                         mock.patch.object(optimizer_compare_matches.pilot, "opening_pool",
                                           return_value=[{"board": "." * 62 + "WB", "side": "B"}]), \
                         mock.patch.object(optimizer_compare_matches.cycle, "transform_opening",
                                           side_effect=lambda opening, rotation: {**opening,
                                                                                  "rotation": rotation}):
                        settings = optimizer_compare_matches.prepare_match_led(
                            fixture["context"], 7, fixture["candidate_path"], fixture["oracle_path"], 310)
                        optimizer_compare_matches.validate_settings(fixture["context"], settings)

            self.assertEqual(training.sha256_file(fixture["oracle_path"]), actual_sha)
            self.assertNotEqual(production_cycle.file_entry(fixture["oracle_path"])["sha256"],
                                fixture["manifest"]["oracle_binary"]["sha256"])

    def test_source_identity_rejects_a_receipt_for_another_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(Path(temporary))
            wrong_receipt = dict(fixture["receipt"])
            wrong_receipt["source_archive"] = dict(wrong_receipt["source_archive"], sha256="f" * 64)
            with mock.patch.object(table32_players.oracle, "verify_runtime_receipt",
                                   return_value=wrong_receipt), \
                 mock.patch.object(table32_players.oracle, "runtime_identity",
                                   return_value=fixture["runtime"]):
                with self.assertRaisesRegex(training.TrainingError, "runtime receipt does not match"):
                    oracle_compat.verify_source_identity(fixture["source_manifest"], fixture["receipt_path"])

    def test_replay_uses_historical_executable_entries_without_old_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(Path(temporary))
            historical_oracle = Path(temporary) / "removed-oracle"
            historical_candidate = Path(temporary) / "removed-candidate"
            oracle_pin = {"path": str(historical_oracle), "sha256": "1" * 64}
            candidate_pin = {"path": str(historical_candidate), "sha256": "2" * 64}
            manifest = dict(fixture["manifest"], oracle_binary=oracle_pin,
                            candidate_executable=candidate_pin)
            fixture["source_manifest"].write_text(json.dumps(manifest), encoding="utf-8")
            for root in (fixture["comparison_root"], fixture["evaluation_root"]):
                (root / "manifest.json").write_text(json.dumps({"matches": {
                    "candidate_executable": candidate_pin, "oracle_binary": oracle_pin}}), encoding="utf-8")
            other = Path(temporary) / "other-input"
            other.write_bytes(b"actual")
            with mock.patch.object(table32_players.oracle, "verify_runtime_receipt",
                                   return_value=fixture["receipt"]), \
                 mock.patch.object(table32_players.oracle, "runtime_identity",
                                   return_value=fixture["runtime"]):
                with oracle_compat.historical_replay(
                        fixture["source_manifest"], fixture["receipt_path"],
                        comparison_root=fixture["comparison_root"],
                        evaluation_root=fixture["evaluation_root"]):
                    self.assertEqual(production_cycle.file_entry(historical_candidate), candidate_pin)
                    self.assertEqual(training.sha256_file(historical_oracle), oracle_pin["sha256"])
                    self.assertEqual(input_bundle.checked_pin(candidate_pin, Path(temporary)), historical_candidate)
                    self.assertEqual(production_cycle.file_entry(other)["sha256"], training.sha256_file(other))
                    with self.assertRaisesRegex(training.TrainingError, "file identity mismatch"):
                        input_bundle.checked_pin({"path": str(other), "sha256": "0" * 64}, Path(temporary))
            with self.assertRaisesRegex(training.TrainingError, "required file does not exist"):
                production_cycle.file_entry(historical_candidate)

    def test_same_path_with_different_source_and_comparison_binary_digests(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(Path(temporary))
            candidate = fixture["candidate_path"]
            source_pin = {"path": str(candidate), "sha256": "1" * 64}
            comparison_pin = {"path": str(candidate), "sha256": "2" * 64}
            oracle_pin = fixture["manifest"]["oracle_binary"]
            fixture["manifest"]["candidate_executable"] = source_pin
            fixture["source_manifest"].write_text(json.dumps(fixture["manifest"]), encoding="utf-8")
            old_file_entry = production_cycle.file_entry

            def historical_entry(path):
                if Path(path) == candidate:
                    return comparison_pin
                if Path(path) == fixture["oracle_path"]:
                    return oracle_pin
                return old_file_entry(path)

            with mock.patch.object(optimizer_compare_matches, "_forbidden", return_value=set()), \
                 mock.patch.object(optimizer_compare_matches.pilot, "opening_pool",
                                   return_value=[{"board": "." * 62 + "WB", "side": "B"}]), \
                 mock.patch.object(optimizer_compare_matches.cycle, "transform_opening",
                                   side_effect=lambda opening, rotation: {**opening, "rotation": rotation}):
                with mock.patch.object(production_cycle, "file_entry", side_effect=historical_entry):
                    settings = optimizer_compare_matches.prepare_match_led(
                        fixture["context"], 7, candidate, fixture["oracle_path"], 310)
                for root in (fixture["comparison_root"], fixture["evaluation_root"]):
                    (root / "manifest.json").write_text(json.dumps({"matches": settings}), encoding="utf-8")
                with mock.patch.object(table32_players.oracle, "verify_runtime_receipt",
                                       return_value=fixture["receipt"]), \
                     mock.patch.object(table32_players.oracle, "runtime_identity",
                                       return_value=fixture["runtime"]):
                    with oracle_compat.historical_replay(
                            fixture["source_manifest"], fixture["receipt_path"],
                            comparison_root=fixture["comparison_root"],
                            evaluation_root=fixture["evaluation_root"]):
                        self.assertEqual(production_cycle.file_entry(candidate), source_pin)
                        optimizer_compare_matches.validate_settings(fixture["context"], settings)
                        changed = dict(settings, requested_games=1)
                        with self.assertRaisesRegex(training.TrainingError, "comparison settings"):
                            optimizer_compare_matches.validate_settings(fixture["context"], changed)
                with self.assertRaisesRegex(training.TrainingError, "comparison Oracle differs"):
                    optimizer_compare_matches.validate_settings(fixture["context"], settings)

    def test_missing_historical_cli_in_real_stage_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self.fixture(root)
            cli = root / "old-cli"
            cli_pin = {"path": str(cli), "sha256": "a" * 64}
            fixture["manifest"]["candidate_executable"] = cli_pin
            old_oracle = root / "old-oracle"
            fixture["manifest"]["oracle_binary"] = {"path": str(old_oracle), "sha256": "b" * 64}
            fixture["source_manifest"].write_text(json.dumps(fixture["manifest"]), encoding="utf-8")
            corpus = root / "corpus"
            corpus.mkdir()
            (root / "resources").mkdir()
            stage = root / "stage"
            stage.mkdir()
            bundle, output = root / "bundle.json", root / "output.json"
            bundle.write_text("{}", encoding="utf-8")
            output.write_text("{}", encoding="utf-8")
            for name in ("stdout", "stderr"):
                (stage / name).write_bytes(b"")
            name = "bundle-verify"
            wall, rss = input_bundle.BOUNDS[name]
            request = {"bundle_manifest": str(bundle), "cli": str(cli), "report": str(output)}
            manifest = {"version": input_bundle.VERSION, "stage": name,
                        "total_wall_budget_seconds": input_bundle.TOTAL_WALL_SECONDS,
                        "bounds": {"wall_seconds": wall, "rss_bytes": rss, "sample_seconds": 1},
                        "request": request, "inputs": [input_bundle.pin(bundle), cli_pin]}
            manifest_path = stage / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = {"stage": name, "manifest_sha256": training.sha256_file(manifest_path),
                      "outputs": {"bundle_manifest": input_bundle.pin(bundle),
                                  "report": input_bundle.pin(output)}}
            result_path = stage / "result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            report = {"version": input_bundle.VERSION, "stage": name, "status": "completed",
                      "exit_code": 0, "manifest_sha256": training.sha256_file(manifest_path),
                      "sample_seconds": 1, "wall_seconds": 1, "peak_observed_rss_bytes": 1,
                      "cpu_seconds": 1, "stdout_sha256": training.sha256_file(stage / "stdout"),
                      "stderr_sha256": training.sha256_file(stage / "stderr"),
                      "result": input_bundle.pin(result_path)}
            report_path = stage / "report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            predecessors = dict(input_bundle.PREDECESSORS, **{name: set()})
            with mock.patch.object(input_bundle, "PREDECESSORS", predecessors), \
                 mock.patch.object(table32_players.oracle, "verify_runtime_receipt",
                                   return_value=fixture["receipt"]), \
                 mock.patch.object(table32_players.oracle, "runtime_identity",
                                   return_value=fixture["runtime"]):
                with self.assertRaisesRegex(training.TrainingError, "file identity mismatch"):
                    input_bundle.verify_stage(report_path)
                with oracle_compat.historical_replay(fixture["source_manifest"], fixture["receipt_path"]):
                    self.assertEqual(input_bundle.verify_stage(report_path)["stage"], name)
                    oracle_request = {"corpus_dir": str(corpus), "binary": str(old_oracle),
                                      "oracle_cwd": str(root), "output_dir": str(root / "golden"),
                                      "progress_every": 1}
                    self.assertIn(old_oracle, input_bundle.request_inputs("oracle", oracle_request))
                    with self.assertRaisesRegex(training.TrainingError, "missing frozen stage input"):
                        input_bundle.request_inputs(name, dict(request, bundle_manifest=str(root / "missing.json")))
                with self.assertRaisesRegex(training.TrainingError, "file identity mismatch"):
                    input_bundle.verify_stage(report_path)

if __name__ == "__main__":
    unittest.main()
