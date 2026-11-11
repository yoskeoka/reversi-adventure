import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reinforcement as rf
import table32_import as imported
import table32_inputs as inputs
import table32_store as st
import training


def game(name="p12-train-00", split="train", board=rf.INITIAL):
    return {"schema_version": 1, "version": inputs.VERSION,
            "score_contract": training.SCORE_CONTRACT,
            "source_kind": "project-owned-s0-continuation",
            "teacher_settings": dict(inputs.TEACHER_SETTINGS),
            "spec": {"game_id": name, "split": split},
            "decisions": [{"board": board, "side": "B", "move": "d3"}],
            "terminal_board": "B" * 64, "terminal_side": "W",
            "final_score_black": training.terminal_score("B" * 64, "B")}


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.baseline = {"path": "/saved/baseline", "sha256": "fixture"}
        st.atomic(self.root / "manifest.json", {"version": st.VERSION,
                  "score_contract": training.SCORE_CONTRACT, "baseline": self.baseline})
        st.atomic(self.root / "units/0000000.json", {"index": 0, "phase": "input-verification"})
        st.atomic(self.root / "units/0000001.json", {"index": 1, "phase": "generation",
                  "unit": "p12-train-00", "value": game(), "digest": "saved"})

    def load(self, **kwargs):
        return imported.completed_games(self.root, teacher_settings=inputs.TEACHER_SETTINGS,
                                        baseline=self.baseline, **kwargs)

    def test_imports_only_completed_game_and_does_not_mutate_source(self):
        st.atomic(self.root / "attempts/0000/partial.json", {"unfinished": True})
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = self.load()
        self.assertEqual([g["spec"]["game_id"] for g in result["games"]], ["p12-train-00"])
        self.assertEqual(result["receipts"][0]["index"], 1)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes()
                                  for p in self.root.rglob("*") if p.is_file()})

    def test_rejects_teacher_or_baseline_mismatch(self):
        with self.assertRaisesRegex(Exception, "baseline differs"):
            imported.completed_games(self.root, teacher_settings=inputs.TEACHER_SETTINGS,
                                     baseline={"sha256": "different"})
        with self.assertRaisesRegex(Exception, "settings or format differ"):
            imported.completed_games(self.root, teacher_settings={}, baseline=self.baseline)

    def test_older_exact25_games_work_for_exact20_at_target_40_and_later(self):
        desired = {**inputs.TEACHER_SETTINGS, "exact_solver_empty_squares": 20}
        result = imported.completed_games(self.root, teacher_settings=desired,
                    baseline=self.baseline, target_phases=range(40, 50))
        self.assertEqual(len(result["games"]), 1)
        for phases in (range(39, 50), None):
            with self.assertRaisesRegex(Exception, "settings or format differ"):
                imported.completed_games(self.root, teacher_settings=desired,
                        baseline=self.baseline, target_phases=phases)
        with self.assertRaisesRegex(Exception, "settings or format differ"):
            imported.completed_games(self.root,
                    teacher_settings={**desired, "opening_depth": 10},
                    baseline=self.baseline, target_phases=range(40, 50))
        with self.assertRaisesRegex(Exception, "settings or format differ"):
            imported.completed_games(self.root,
                    teacher_settings={**desired, "exact_solver_empty_squares": 21},
                    baseline=self.baseline, target_phases=range(40, 50))

    def test_rejects_cross_split_position_collision_and_duplicate_id(self):
        with self.assertRaisesRegex(Exception, "cross-split"):
            self.load(other_games=[game("other-validation", "validation")])
        with self.assertRaisesRegex(Exception, "duplicate"):
            self.load(other_games=[game()])

    def test_rejects_incomplete_or_noncontiguous_units(self):
        bad = game()
        bad["terminal_board"] = rf.INITIAL
        st.atomic(self.root / "units/0000001.json", {"index": 1, "phase": "generation",
                  "unit": "p12-train-00", "value": bad})
        with self.assertRaisesRegex(Exception, "not completed"):
            self.load()
        (self.root / "units/0000001.json").unlink()
        st.atomic(self.root / "units/0000002.json", {"index": 2, "phase": "generation"})
        with self.assertRaisesRegex(Exception, "not contiguous"):
            self.load()


if __name__ == "__main__":
    unittest.main()
