"""Offline contract checks; never launches an eight-game measurement."""

import copy
import hashlib
import importlib.util
import unittest
from pathlib import Path


MODULE = Path(__file__).with_name("whole_game.py")
SPEC = importlib.util.spec_from_file_location("whole_game", MODULE)
assert SPEC and SPEC.loader
whole_game = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(whole_game)


def synthetic_game(row: dict, assignment: int) -> dict:
    oracle = whole_game.oracle
    board, side = row["board"], row["side"]
    steps = []
    for turn in range(120):
        legal = oracle.legal_moves(board, side)
        if not legal and not oracle.legal_moves(board, oracle.other(side)):
            break
        move = legal[0] if legal else "pass"
        occupied = 64 - board.count(".")
        exact = occupied >= 48
        depth = 64 - occupied if exact else 12
        steps.append({"id": f"{row['id']}-seat{assignment}-turn{turn}",
                      "board": board, "side": side,
                      "seat": side if assignment == 0 else oracle.other(side),
                      "move": move, "decision_elapsed_ns": 1,
                      "search": {"elapsed_us": 1, "nodes": 1, "exact": exact,
                                 "score": 0, "completed_depth": depth,
                                 "outcome": "pass" if move == "pass" else "move",
                                 "cache_probes": 0, "cache_hits": 0, "cache_stores": 0}})
        if legal:
            board = oracle.apply_move(board, side, move)
        side = oracle.other(side)
    processes = {seat: {"startup_ns": 1, "shutdown_ns": 1, "user_cpu_ns": 1,
                        "system_cpu_ns": 0, "peak_rss_kib": 100}
                 for seat in ("B", "W")}
    return {"opening_id": row["id"], "assignment": assignment, "opening": row["moves"],
            "start_board": row["board"], "start_side": row["side"], "steps": steps,
            "wall_ns": 100, "terminal_board": board,
            "score_black": board.count("B") - board.count("W"), "completed": True,
            "resources": {"user_cpu_ns": 2, "system_cpu_ns": 0, "peak_rss_kib": 100},
            "seat_processes": processes, "cache": {"probes": 0, "hits": 0, "stores": 0},
            "search_count": len(steps)}


def synthetic_report() -> dict:
    games = [synthetic_game(row, assignment) for row in whole_game.opening_rows()
             for assignment in (0, 1)]
    report = {"schema_version": 1, "runner_version": whole_game.VERSION, "kind": "cli",
              "openings_sha256": whole_game.digest(whole_game.OPENINGS),
              "binary": {"path": "/synthetic/cli", "sha256": "0" * 64},
              "artifact": {"path": "/synthetic/artifact", "sha256": "1" * 64},
              "oracle_profile": None,
              "settings": {"opening_depth": 12, "midgame_depth": 12, "endgame_depth": 12,
                           "exact_empty": 16, "timeout_seconds": 310,
                           "exact_cache_scope": "game",
                           "max_decisions": 120, "max_rss_kib": 1000,
                           "process_lifetime": "one-game-per-seat"},
              "environment": {"measurement": "linux-wait4"},
              "games": games, "aggregate": whole_game.totals(games), "process_totals": None}
    report["report_digest"] = hashlib.sha256(whole_game.canonical(report)).hexdigest()
    return report


class WholeGameTests(unittest.TestCase):
    def test_openings_and_phase_boundaries(self):
        self.assertEqual(len(whole_game.opening_rows()), 4)
        oracle = whole_game.oracle
        for occupied, depth in ((20, 12), (21, 8), (44, 8), (45, 12), (47, 12), (48, 16)):
            self.assertEqual(oracle.profile_depth_at(whole_game.profile(8), occupied), depth)

    def test_independent_replay_and_resource_verification(self):
        report = synthetic_report()
        whole_game.verify(report)
        changed = copy.deepcopy(report)
        changed["games"][0]["steps"][0]["move"] = "a1"
        changed["report_digest"] = hashlib.sha256(
            whole_game.canonical({key: value for key, value in changed.items()
                                  if key != "report_digest"})).hexdigest()
        with self.assertRaisesRegex(whole_game.BenchmarkError, "illegal move"):
            whole_game.verify(changed)
        changed = copy.deepcopy(report)
        del changed["games"][0]["seat_processes"]["B"]["peak_rss_kib"]
        changed["report_digest"] = hashlib.sha256(
            whole_game.canonical({key: value for key, value in changed.items()
                                  if key != "report_digest"})).hexdigest()
        with self.assertRaises(whole_game.BenchmarkError):
            whole_game.verify(changed)

    def test_comparison_checks_same_position_score(self):
        turn = synthetic_report()
        turn["settings"]["exact_cache_scope"] = "turn"
        turn["report_digest"] = hashlib.sha256(whole_game.canonical(
            {key: value for key, value in turn.items() if key != "report_digest"})).hexdigest()
        game = synthetic_report()
        comparison = whole_game.comparison(turn, game)
        self.assertGreater(comparison["semantic_positions"], 400)
        self.assertEqual(comparison["wall_ratio"], 1)
        game["games"][0]["steps"][0]["search"]["score"] = 1
        game["report_digest"] = hashlib.sha256(whole_game.canonical(
            {key: value for key, value in game.items() if key != "report_digest"})).hexdigest()
        with self.assertRaisesRegex(whole_game.BenchmarkError, "semantic score mismatch"):
            whole_game.comparison(turn, game)

    def test_oracle_evidence_requires_every_exact_position(self):
        report = synthetic_report()
        rows = [{"id": step["id"], "board": step["board"], "side": step["side"],
                 "move": step["move"], "cli_score": step["search"]["score"],
                 "oracle_score": step["search"]["score"],
                 "selected_score": step["search"]["score"]}
                for game in report["games"] for step in game["steps"] if step["search"]["exact"]]
        evidence = {"schema_version": 1, "runner_version": whole_game.VERSION,
                    "cli_report_digest": report["report_digest"],
                    "oracle_binary_sha256": "2" * 64,
                    "oracle_profile": whole_game.oracle.profile_metadata(whole_game.profile(12)),
                    "positions": rows}
        evidence["report_digest"] = hashlib.sha256(whole_game.canonical(evidence)).hexdigest()
        whole_game.verify_oracle_evidence(report, evidence)
        broken = copy.deepcopy(evidence)
        broken["positions"].pop()
        broken["report_digest"] = hashlib.sha256(whole_game.canonical(
            {key: value for key, value in broken.items() if key != "report_digest"})).hexdigest()
        with self.assertRaisesRegex(whole_game.BenchmarkError, "position count mismatch"):
            whole_game.verify_oracle_evidence(report, broken)


if __name__ == "__main__":
    unittest.main()
