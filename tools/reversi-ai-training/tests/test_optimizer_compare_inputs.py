"""Offline input reconstruction, independence, and immutable pin checks."""

import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optimizer_compare_inputs as inputs
import pilot
import production_cycle as cycle
import reinforcement as rf
import training


class ComparisonInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest_path = self.root / "manifest.json"
        self.write(self.manifest_path, {"seed": 1})

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pilot.blob(value))

    def rows(self, count=5):
        result, board, side = [], rf.INITIAL, "B"
        for index in range(count):
            result.append({"id": f"source-p0-m0-t{index}", "board": board, "side": side, "target": 0})
            board = rf.apply_move(board, side, rf.legal_moves(board, side)[0])
            side = rf.other(side)
        return result

    def fixture(self):
        rows = self.rows()
        adopted = {"weights": {}, "weight_digest": training.digest({})}
        manifest = {"seed": 1}
        report = {"selected_artifact": "candidate", "exposure_keys": {"decision": [pilot.key(rows[0]["board"], rows[0]["side"])]}}
        context = {"manifest": manifest, "baseline": adopted, "baseline_keys": set(),
                   "reserved": set(), "corpus_keys": set(), "validation": rows[:2],
                   "held_out": rows[:3] + [rows[2]], "corpus": [], "golden": []}
        predecessors = {}
        for phase in cycle.PHASES:
            path = self.root / "phases" / phase / "attempt-0001"
            path.mkdir(parents=True)
            self.write(path / "receipt.json", {"phase": phase})
            predecessors[phase] = path
        self.write(predecessors["self-play"] / "games.jsonl", {"kind": "fixture"})
        self.write(predecessors["candidate-update"] / "candidate-artifact.json", adopted)
        self.write(predecessors["candidate-selection"] / "selection.json", {
            "validation_position_keys": [pilot.key(rows[1]["board"], rows[1]["side"])]})
        self.write(predecessors["offline-verification"] / "report.json", report)
        self.write(self.root / "report.json", report)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name, value in (("load_context", context), ("check_dependencies", None),
                            ("verify_failed_attempts", None), ("semantic_phase_check", None),
                            ("build_final_report", report), ("tuning_rows", [rows[0]]),
                            ("all_game_records", []), ("played_keys", {pilot.key(rows[0]["board"], rows[0]["side"])})):
            stack.enter_context(mock.patch.object(cycle, name, return_value=value))
        stack.enter_context(mock.patch.object(cycle, "latest_success", side_effect=lambda root, phase, digest: (predecessors[phase], {})))
        stack.enter_context(mock.patch.object(rf, "updated_artifact", return_value=adopted))
        stack.enter_context(mock.patch.object(rf, "Candidate", side_effect=AssertionError("offline candidate")))
        stack.enter_context(mock.patch.object(pilot.oracle, "run_solve", side_effect=AssertionError("offline Oracle")))
        return context, rows, predecessors

    def test_source_reconstructs_disjoint_splits_and_checks_every_phase(self):
        _, rows, _ = self.fixture()
        result = inputs.load_source(self.manifest_path, fixture=True)
        self.assertEqual(result["validation"], [rows[1]])
        self.assertEqual(result["held_out"], [rows[2]])
        self.assertEqual(result["teachers"][0]["game_id"], "source-p0-m0")
        self.assertEqual(result["teachers"][0]["score_view"], "side-to-move-winner-empty-v1")
        self.assertEqual(result["split_audit"]["held_out"]["excluded_ids"], [rows[0]["id"], rows[1]["id"], rows[2]["id"]])
        self.assertEqual(cycle.semantic_phase_check.call_count, len(cycle.PHASES))
        self.assertEqual(inputs.load_pinned(result["pins"], fixture=True)["pins"], result["pins"])

    def test_fixture_requires_explicit_opt_in(self):
        self.fixture()
        with self.assertRaisesRegex(training.TrainingError, "production identities"):
            inputs.load_source(self.manifest_path)
        pins = inputs.pin_inputs(self.manifest_path, fixture=True)
        with self.assertRaisesRegex(training.TrainingError, "fixture eligibility"):
            inputs.load_pinned(pins)

    def test_held_out_excludes_d4_equivalent_teacher_and_validation_rows(self):
        context, rows, _ = self.fixture()
        rotated = [{**row, "id": row["id"] + "-rotated",
                    "board": cycle.transform_board(row["board"], 2)} for row in rows[:3]]
        context["held_out"] = rotated
        result = inputs.load_source(self.manifest_path, fixture=True)
        self.assertEqual(result["held_out"], [rotated[2]])
        self.assertEqual(result["split_audit"]["held_out"]["excluded_ids"],
                         [rotated[0]["id"], rotated[1]["id"]])

    def test_empty_split_and_wrong_control_fail_closed(self):
        context, _, _ = self.fixture()
        context["held_out"] = context["validation"]
        with self.assertRaisesRegex(training.TrainingError, "nonempty independent"):
            inputs.load_source(self.manifest_path, fixture=True)
        context["held_out"] = self.rows()[2:]
        rf.updated_artifact.return_value = {"weights": {"bad": 1}, "weight_digest": "wrong"}
        with self.assertRaisesRegex(training.TrainingError, "control A"):
            inputs.load_source(self.manifest_path, fixture=True)

    def test_referenced_input_and_extra_source_file_tampering_are_rejected(self):
        self.fixture()
        child = self.root / "child.jsonl"
        child.write_text("teacher evidence\n")
        self.write(self.manifest_path, {"input": {"path": child.name, "sha256": training.sha256_file(child)}})
        pins = inputs.pin_inputs(self.manifest_path, fixture=True)
        self.assertIn(str(child), [entry["path"] for entry in pins["files"]])
        child.write_text("tampered\n")
        with self.assertRaisesRegex(training.TrainingError, "pinned input changed"):
            inputs.load_pinned(pins, fixture=True)
        child.write_text("teacher evidence\n")
        self.write(self.root / "phases" / "self-play" / "attempt-0001" / "extra.json", {})
        with self.assertRaisesRegex(training.TrainingError, "inventory changed"):
            inputs.load_pinned(pins, fixture=True)

    def test_source_receipt_failure_propagates(self):
        self.fixture()
        cycle.semantic_phase_check.side_effect = training.TrainingError("tampered source receipt")
        with self.assertRaisesRegex(training.TrainingError, "tampered source receipt"):
            inputs.load_source(self.manifest_path, fixture=True)

    def test_oracle_resource_pin_uses_resolved_path(self):
        self.fixture()
        resource = self.root / "actual-runtime" / "resources" / "eval.dat"
        resource.parent.mkdir(parents=True)
        resource.write_bytes(b"saved runtime resource")
        self.write(self.manifest_path, {"resource": {"path": "resources/eval.dat",
                   "resolved_path": str(resource), "sha256": training.sha256_file(resource)}})
        pins = inputs.pin_inputs(self.manifest_path, fixture=True)
        self.assertIn(str(resource), [entry["path"] for entry in pins["files"]])


if __name__ == "__main__":
    unittest.main()
