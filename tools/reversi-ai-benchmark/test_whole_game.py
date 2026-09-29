"""Offline contract checks; never launches an eight-game measurement."""

import copy
import hashlib
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE = Path(__file__).with_name("whole_game.py")
SPEC = importlib.util.spec_from_file_location("whole_game", MODULE)
assert SPEC and SPEC.loader
whole_game = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(whole_game)

TARGET_MOVES = "e6f6d3g4h4d2e2c2c1g2f2h3h1d1f1h2e1g3e3b1a1b4g1h5h6b2g5"
TARGET_BOARD = "BBBBBBBB.WWBBBBB..WWBWBB.WWWWBBB...WWWBB...WWW.B................"


def synthetic_game(row: dict, assignment: int, midgame_depth: int = 12,
                   target_prefix: bool = False) -> dict:
    oracle = whole_game.oracle
    board, side = row["board"], row["side"]
    steps = []
    for turn in range(120):
        legal = oracle.legal_moves(board, side)
        if not legal and not oracle.legal_moves(board, oracle.other(side)):
            break
        move = (TARGET_MOVES[turn * 2:turn * 2 + 2] if target_prefix and turn < 27
                else legal[0] if legal else "pass")
        assert move in legal if legal else move == "pass"
        occupied = 64 - board.count(".")
        exact = occupied >= 48
        depth = 64 - occupied if exact else (0 if move == "pass" else
                                           12 if occupied <= 20 or occupied >= 45 else midgame_depth)
        steps.append({"id": f"{row['id']}-seat{assignment}-turn{turn}",
                      "board": board, "side": side,
                      "seat": side if assignment == 0 else oracle.other(side),
                      "move": move, "decision_elapsed_ns": 1,
                      "search": {"elapsed_us": 1, "nodes": 0 if move == "pass" and not exact else 1,
                                 "exact": exact, "score": None if move == "pass" and not exact else 0,
                                 "completed_depth": depth,
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


def synthetic_report(midgame_depth: int = 12, target_prefix: bool = False) -> dict:
    games = [synthetic_game(row, assignment, midgame_depth,
                            target_prefix and row["id"] == "opening-4" and assignment == 0)
             for row in whole_game.opening_rows()
             for assignment in (0, 1)]
    report = {"schema_version": 1, "runner_version": whole_game.VERSION, "kind": "cli",
              "openings_sha256": whole_game.digest(whole_game.OPENINGS),
              "binary": {"path": "/synthetic/cli", "sha256": "0" * 64},
              "artifact": {"path": "/synthetic/artifact", "sha256": "1" * 64},
              "oracle_profile": None,
              "settings": {"opening_depth": 12, "midgame_depth": midgame_depth, "endgame_depth": 12,
                           "exact_empty": 16, "timeout_seconds": 310,
                           "exact_cache_scope": "game",
                           "max_decisions": 120, "max_rss_kib": 1000,
                           "process_lifetime": "one-game-per-seat"},
              "environment": {"measurement": "linux-wait4"},
              "games": games, "aggregate": whole_game.totals(games), "process_totals": None}
    report["report_digest"] = hashlib.sha256(whole_game.canonical(report)).hexdigest()
    return report


def redigest(report: dict) -> None:
    report["report_digest"] = hashlib.sha256(whole_game.canonical(
        {key: value for key, value in report.items() if key != "report_digest"})).hexdigest()


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

    def test_observed_heuristic_pass_is_attached_verified_and_compared(self):
        report = synthetic_report(8, target_prefix=True)
        record = report["games"][6]
        step = record["steps"][27]
        self.assertEqual((step["id"], step["board"], step["side"], step["move"]),
                         ("opening-4-seat0-turn27", TARGET_BOARD, "W", "pass"))
        self.assertEqual((step["search"]["score"], step["search"]["completed_depth"],
                          step["search"]["exact"], step["search"]["nodes"]), (None, 0, False, 0))
        diagnostic = copy.deepcopy(step["search"])
        record["cache"] = None
        record["search_count"] = 0
        seats = {side: SimpleNamespace(depth=8, diagnostics={
            item["id"]: copy.deepcopy(item["search"]) for item in record["steps"]
            if item["seat"] == side}) for side in ("B", "W")}
        for item in record["steps"]:
            item.pop("search", None)
        whole_game.attach_diagnostics(record, seats, "cli")
        self.assertEqual(step["search"], diagnostic)
        redigest(report)
        whole_game.verify(report)
        turn = copy.deepcopy(report)
        turn["settings"]["exact_cache_scope"] = "turn"
        redigest(turn)
        self.assertGreater(whole_game.comparison(turn, report)["semantic_positions"], 400)

    def test_pass_and_legal_move_diagnostics_reject_inconsistency(self):
        report = synthetic_report(8, target_prefix=True)
        whole_game.verify(report)
        steps = report["games"][6]["steps"]
        heuristic_pass = steps[27]
        exact_pass = next(step for game in report["games"] for step in game["steps"]
                          if step["move"] == "pass" and step["search"]["exact"])
        legal_move = steps[0]
        cases = ((heuristic_pass, "score", 0), (heuristic_pass, "completed_depth", 8),
                 (heuristic_pass, "exact", True), (heuristic_pass, "outcome", "move"),
                 (heuristic_pass, "cache_hits", -1), (exact_pass, "score", None),
                 (exact_pass, "completed_depth", 0), (exact_pass, "exact", False),
                 (legal_move, "score", None), (legal_move, "completed_depth", 0),
                 (legal_move, "outcome", "pass"))
        for step, field, value in cases:
            with self.subTest(step=step["id"], field=field):
                changed = copy.deepcopy(report)
                changed_step = next(item for game in changed["games"] for item in game["steps"]
                                    if item["id"] == step["id"])
                changed_step["search"][field] = value
                redigest(changed)
                with self.assertRaises(whole_game.BenchmarkError):
                    whole_game.verify(changed)
                seat = SimpleNamespace(depth=8, diagnostics={step["id"]: changed_step["search"]})
                with self.assertRaises(whole_game.BenchmarkError):
                    whole_game.attach_diagnostics({"steps": [dict(changed_step)]},
                                                  {step["seat"]: seat}, "cli")

        illegal = copy.deepcopy(report)
        illegal["games"][0]["steps"][0]["move"] = "pass"
        redigest(illegal)
        with self.assertRaisesRegex(whole_game.BenchmarkError, "illegal move or pass"):
            whole_game.verify(illegal)

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
