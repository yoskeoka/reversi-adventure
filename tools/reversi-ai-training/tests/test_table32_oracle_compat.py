"""0054-only replay of a rebuilt Oracle from the source-pinned release."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optimizer_compare
import optimizer_compare_evaluation
import optimizer_compare_inputs
import optimizer_compare_matches
import production_cycle
import table32
import table32_inputs
import table32_model
import table32_oracle_compat as oracle_compat
import table32_players
import table32_store as st
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

    def patched_verifiers(self, fixture):
        stack = ExitStack()
        stack.enter_context(mock.patch.object(table32_players.oracle, "verify_runtime_receipt",
                                              return_value=fixture["receipt"]))
        stack.enter_context(mock.patch.object(table32_players.oracle, "runtime_identity",
                                              return_value=fixture["runtime"]))
        stack.enter_context(mock.patch.object(optimizer_compare_inputs, "load_source",
                                              return_value=fixture["context"]))
        stack.enter_context(mock.patch.object(optimizer_compare, "verify",
                                              return_value={"status": "complete"}))
        stack.enter_context(mock.patch.object(optimizer_compare_evaluation, "verify",
                                              return_value={"status": "complete"}))
        stack.enter_context(mock.patch.object(table32_inputs, "preflight_roots",
                                              return_value=[{"id": "fixture"}]))
        stack.enter_context(mock.patch.object(table32, "verified_match_exposure_keys",
                                              return_value=set()))
        return stack

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

    def test_historical_and_table32_reload_reconstruct_without_rewriting_source_pins(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(Path(temporary))
            baseline = Path(__file__).resolve().parents[3] / "models/trained/0019-20261020-02.json"
            with self.patched_verifiers(fixture):
                originals, snapshot = table32.historical(
                    fixture["source_manifest"], fixture["comparison_root"], fixture["evaluation_root"],
                    runtime_receipt=fixture["receipt_path"], seed=7)
                self.assertEqual(originals["oracle_source_identity"]["historical_binary"],
                                 fixture["manifest"]["oracle_binary"])

                root = Path(temporary) / "table32-run"
                root.mkdir()
                manifest = {"version": st.VERSION, "score_contract": training.SCORE_CONTRACT,
                            "producer_commit": "b" * 40, "sources": table32.source_hashes(), "seed": 7,
                            "catalog_digest": table32_model.CATALOG_DIGEST, "baseline": st.pin(baseline),
                            "candidate_executable": st.pin(fixture["candidate_path"]),
                            "oracle_runtime_receipt": st.pin(fixture["receipt_path"]),
                            "oracle_runtime": fixture["runtime"],
                            "oracle_source_identity": originals["oracle_source_identity"],
                            "historical": originals, "snapshot_digest": st.digest(snapshot)}
                st.atomic(root / "snapshot.json", snapshot, once=True)
                st.atomic(root / "manifest.json", manifest, once=True)
                st.atomic(root / "prepare.receipt.json", st.seal({"manifest_digest": st.digest(manifest),
                           "snapshot_digest": st.digest(snapshot)}), once=True)
                loaded, reconstructed = table32.load(root)
                self.assertEqual(loaded, manifest)
                self.assertEqual(reconstructed, snapshot)


if __name__ == "__main__":
    unittest.main()
