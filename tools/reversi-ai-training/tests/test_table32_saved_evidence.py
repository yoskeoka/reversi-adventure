"""Saved historical evidence must not be replayed when a run is reopened."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import table32
import table32_inputs as inputs
import table32_store as st
import optimizer_compare
import optimizer_compare_evaluation
import optimizer_compare_inputs
import test_table32_cli


class SavedEvidenceTests(unittest.TestCase):
    def make_history(self, folder):
        source, comparison, evaluation = (folder / name for name in ("source", "comparison", "evaluation"))
        attempt = source / "phases/self-play/attempt-0001"
        for path in (attempt, comparison, evaluation):
            path.mkdir(parents=True)
        corpus, golden = source / "corpus.jsonl", source / "golden.jsonl"
        corpus.write_bytes(st.blob({"saved": "corpus"}))
        golden.write_bytes(st.blob({"saved": "golden"}))
        manifest = {"inputs": {"corpus": {"path": str(corpus)}, "golden": {"path": str(golden)}},
                    "verified_bundle": {"exposure_keys": {}, "acceptance_reservation": {"keys": []}}}
        st.atomic(source / "manifest.json", manifest)
        st.atomic(source / "report.json", {"run_status": "complete", "selected_artifact": "candidate",
                  "exposure_keys": {}, "phase_receipts": {"self-play": "saved-receipt"}})
        st.atomic(attempt / "receipt.json", {"phase": "self-play", "status": "complete",
                                              "receipt_digest": "saved-receipt"})
        games = []
        for seed in range(8):
            prefix = inputs.random_prefix({"prefix_length": 44, "stream_seed": seed})
            games.append({"decisions": prefix["turns"]})
        (attempt / "games.jsonl").write_bytes(b"".join(st.blob(game) for game in games))
        for root in (comparison, evaluation):
            st.atomic(root / "manifest.json", {"matches": {"openings": {}}})
            st.atomic(root / "report.json", {"status": "complete"})
            st.atomic(root / "offline-verification.receipt.json", {"status": "complete"})
        (evaluation / "matches").mkdir()
        match = {"start_board": inputs.rf.INITIAL, "start_side": "B",
                 "decisions": [{"board": "B" * 63 + ".", "side": "W"}],
                 "terminal_board": "B" * 64}
        (evaluation / "matches/games.jsonl").write_bytes(st.blob(match))
        st.atomic(comparison / "prepare.receipt.json", {"status": "complete"})
        for name in ("validation", "held_out", "teachers"):
            st.atomic(comparison / f"{name}.json", [{"saved": name, "board": inputs.rf.INITIAL, "side": "B"}])
        return source, comparison, evaluation

    def test_historical_reads_completed_saved_data_without_semantic_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, comparison, evaluation = self.make_history(Path(temporary))
            with mock.patch.object(table32.oracle_compat, "verify_source_identity", return_value={"runtime": {}}), \
                 mock.patch.object(optimizer_compare_inputs, "load_source", side_effect=AssertionError("source replay")), \
                 mock.patch.object(optimizer_compare, "verify", side_effect=AssertionError("comparison replay")), \
                 mock.patch.object(optimizer_compare_evaluation, "verify", side_effect=AssertionError("evaluation replay")), \
                 mock.patch.object(inputs, "historical_states", side_effect=AssertionError("games replayed")), \
                 mock.patch.object(table32.subprocess, "Popen", side_effect=AssertionError("process started")):
                originals, snapshot = table32.historical(source / "manifest.json", comparison, evaluation,
                                                          runtime_receipt=source / "runtime.json")
            self.assertEqual(originals["policy"], "saved-completed-v1")
            self.assertEqual(snapshot["validation"][0]["saved"], "validation")
            self.assertEqual(snapshot["held_out"][0]["saved"], "held_out")
            self.assertEqual(snapshot["corpus"], [{"saved": "corpus"}])
            self.assertEqual(snapshot["golden"], [{"saved": "golden"}])
            self.assertEqual(len(snapshot["preflight_roots"]), 12)
            for board, side in ((inputs.rf.INITIAL, "B"), ("B" * 63 + ".", "W"),
                                ("B" * 64, "B"), ("B" * 64, "W")):
                self.assertIn(inputs.position_key(board, side), snapshot["excluded_keys"])

    def test_incomplete_saved_reports_are_rejected(self):
        for name, field in (("source", "run_status"), ("comparison", "status"), ("evaluation", "status")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                source, comparison, evaluation = self.make_history(Path(temporary))
                path = {"source": source, "comparison": comparison, "evaluation": evaluation}[name] / "report.json"
                report = st.read(path)
                report[field] = "incomplete"
                st.atomic(path, report)
                with mock.patch.object(table32.oracle_compat, "verify_source_identity", return_value={"runtime": {}}):
                    with self.assertRaisesRegex(Exception, "incomplete"):
                        table32.historical(source / "manifest.json", comparison, evaluation,
                                           runtime_receipt=source / "runtime.json")

    def test_load_uses_frozen_snapshot_without_reconstructing_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            manifest, _ = test_table32_cli.Table32CliTests().prepare_fixture(folder, [])
            root = folder / "run"
            # This fixture stands for already completed evidence. No historical
            # game, verifier, trainer, or Oracle process is needed to reopen it.
            original = manifest["historical"]
            original.update(policy="saved-completed-v1", files=[])
            st.atomic(root / "manifest.json", manifest)
            st.atomic(root / "prepare.receipt.json", st.seal({
                "manifest_digest": st.digest(manifest),
                "snapshot_digest": manifest["snapshot_digest"],
            }))
            with mock.patch.object(table32, "historical", side_effect=AssertionError("history replayed")), \
                 mock.patch.object(table32.oracle_compat, "verify_source_identity",
                                   return_value=manifest["oracle_source_identity"]), \
                 mock.patch.object(table32.subprocess, "Popen", side_effect=AssertionError("process started")):
                loaded, snapshot = table32.load(root)
            self.assertEqual(loaded, manifest)
            self.assertEqual(snapshot, {"fixture": True})


if __name__ == "__main__":
    unittest.main()
