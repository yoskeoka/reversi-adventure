import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reinforcement as rf
import table32_game_checkpoint as checkpoint
import table32_inputs as inputs
import table32_store as st
import training


def choose(identifier, board, side, settings):
    legal = sorted(rf.legal_moves(board, side))
    if not legal:
        return {"move": "pass", "score": 0, "completed_depth": 0,
                "exact": False, "nodes": 0, "elapsed_ms": 0, "forced_pass": True}
    empty = board.count(".")
    return {"move": legal[0], "score": 0, "completed_depth": max(empty, 11),
            "exact": empty <= 25, "nodes": 1, "elapsed_ms": 1}


class GameCheckpointTests(unittest.TestCase):
    def test_interrupted_game_reuses_completed_decisions(self):
        spec = inputs.generation_plan()[0]
        manifest = {"run": "fixture"}
        calls = []
        def interrupt(identifier, board, side, settings):
            if len(calls) == 2:
                raise RuntimeError("interrupted")
            calls.append(identifier)
            return choose(identifier, board, side, settings)
        with tempfile.TemporaryDirectory() as root:
            save = checkpoint.GameDecisions(root, manifest, spec, interrupt, lambda *args: None)
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                inputs.generate_game(spec, save)
            resumed_calls = []
            def resumed(identifier, board, side, settings):
                resumed_calls.append(identifier)
                return choose(identifier, board, side, settings)
            game = inputs.generate_game(spec, checkpoint.GameDecisions(
                root, manifest, spec, resumed, lambda *args: None))
            self.assertEqual(game, inputs.generate_game(spec, choose))
            self.assertFalse(set(calls) & set(resumed_calls))
            inputs.replay_game(game)

    def test_wrong_identity_or_tampering_does_not_resume(self):
        spec = inputs.generation_plan()[0]
        opening = inputs.generation_opening(spec)
        settings = inputs.search_settings(inputs.TEACHER_SETTINGS)
        identifier = spec["game_id"] + "-000"
        with tempfile.TemporaryDirectory() as root:
            save = checkpoint.GameDecisions(root, {"run": 1}, spec, choose, lambda *args: None)
            save(identifier, opening["board"], opening["side"], settings)
            wrong = checkpoint.GameDecisions(root, {"run": 2}, spec, choose, lambda *args: None)
            with self.assertRaises(training.TrainingError):
                wrong(identifier, opening["board"], opening["side"], settings)
            path = save.folder / "000.json"
            value = st.read(path)
            value["decision"]["move"] = "a1"
            st.atomic(path, value)
            again = checkpoint.GameDecisions(root, {"run": 1}, spec, choose, lambda *args: None)
            with self.assertRaises(training.TrainingError):
                again(identifier, opening["board"], opening["side"], settings)


if __name__ == "__main__":
    unittest.main()
