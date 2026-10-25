"""Offline checks for global numbering and complete reports across match retries."""

import copy
from contextlib import redirect_stderr
import importlib.util
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("resume_oracle", Path(__file__).resolve().parents[1] / "oracle.py")
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


class MatchResumeTests(unittest.TestCase):
    def setUp(self):
        # One legal black move ends this game. Both candidate and Oracle paths
        # execute across a color-swapped pair, without launching any process.
        opening = {"board": "BW." + "B" * 61, "side": "B", "moves": [], "rotation": 0}
        self.pairs = [(copy.deepcopy(opening), copy.deepcopy(opening)) for _ in range(10)]
        self.config = {"opening_depth": 12, "midgame_depth": 12,
                       "endgame_depth": 12, "exact_solver_empty_squares": 16}
        self.candidate = Mock()
        self.candidate.choose_with_diagnostic.return_value = ("c1", {
            "completed_depth": 1, "exact": True, "elapsed_us": 1,
            "nodes": 1, "outcome": "move"})

    def match(self, *, initial_games=None, on_game=None, timeout=5):
        with redirect_stderr(StringIO()), patch.object(oracle, "run_solve", return_value=[{
                "move": "c1", "completed_depth": 1, "exact": True}]) as solve:
            report = oracle.run_profiled_match(
                Path("/unused/fake-oracle"), Path("/unused"), self.candidate,
                self.pairs, oracle.ORACLE_0018_ACCEPTANCE_V1, self.config,
                timeout, on_game=on_game, initial_games=initial_games)
        return report, solve

    def test_seven_game_prefix_plays_only_remaining_thirteen(self):
        original, _ = self.match()
        prefix = copy.deepcopy(original["results"][:7])
        saved = copy.deepcopy(prefix)
        self.candidate.reset_mock()
        emitted = []
        report, solve = self.match(initial_games=prefix, on_game=emitted.append, timeout=17)
        self.assertEqual(prefix, saved)
        self.assertEqual(report, original)
        self.assertEqual([game["game"] for game in emitted], list(range(8, 21)))
        self.assertEqual(self.candidate.new_game.call_count, 13)
        self.assertEqual(self.candidate.new_game.call_args_list[0].args, ("oracle-match-p3-m1",))
        self.assertEqual(solve.call_count, 7)
        self.assertTrue(all(call.args[4] == 17 for call in solve.call_args_list))

    def test_second_failure_keeps_global_prefix_for_next_retry(self):
        original, _ = self.match()
        completed = copy.deepcopy(original["results"][:7])
        def fail_tenth(identifier):
            if identifier == "oracle-match-p4-m1":
                raise TimeoutError("fixture timeout")
        self.candidate.new_game.side_effect = fail_tenth
        with self.assertRaisesRegex(TimeoutError, "fixture timeout"):
            self.match(initial_games=completed, on_game=completed.append)
        self.assertEqual([game["game"] for game in completed], list(range(1, 10)))
        self.candidate.new_game.side_effect = None
        self.candidate.reset_mock()
        report, _ = self.match(initial_games=completed, timeout=19)
        self.assertEqual(report, original)
        self.assertEqual(self.candidate.new_game.call_count, 11)
        self.assertEqual(self.candidate.new_game.call_args_list[0].args, ("oracle-match-p4-m1",))

    def test_invalid_prefix_is_rejected_before_play(self):
        original, _ = self.match()
        prefix = original["results"][:7]
        for broken in (prefix[1:], prefix[:2] + prefix[1:2],
                       prefix[:2] + [dict(prefix[2], game_digest="0" * 64)],
                       prefix[:2] + [dict(prefix[2], start_side="W")],
                       original["results"] + original["results"][:1]):
            with self.subTest(prefix_length=len(broken)):
                self.candidate.reset_mock()
                with self.assertRaises(oracle.OracleError):
                    self.match(initial_games=broken)
                self.candidate.new_game.assert_not_called()


if __name__ == "__main__":
    unittest.main()
