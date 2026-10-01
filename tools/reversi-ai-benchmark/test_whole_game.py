"""Offline contract checks; never launches an eight-game measurement."""

import copy
import hashlib
import importlib.util
import unittest
import tempfile
from unittest.mock import patch
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


class FakeSeat:
    def __init__(self, kind, binary, artifact, depth, timeout, side, *args):
        self.depth, self.side = depth, side
        self.process = SimpleNamespace(pid=1)
        self.diagnostics = {}
        self.startup_ns = 1
        self.started_at_ns = 1

    def new_game(self, identifier):
        return {"game_id": identifier, "acknowledged": True, "elapsed_ns": 1, "protocol": "new_game-v1"}

    def close(self):
        return {"startup_ns": 1, "shutdown_ns": 1, "user_cpu_ns": 100, "system_cpu_ns": 0,
                "peak_rss_kib": 100, "started_at_ns": 1, "ended_at_ns": 2}

    def collect_diagnostics(self):
        pass

    def abort(self):
        return self.close()


class ResumableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.binary = self.root / "cli"
        self.artifact = self.root / "artifact"
        self.binary.write_bytes(b"cli")
        self.artifact.write_bytes(b"artifact")
        self.args = SimpleNamespace(kind="cli", binary=self.binary, artifact=self.artifact,
            midgame_depth=8, cache_scope="game", timeout_seconds=2, max_rss_kib=1000,
            max_decisions=120, oracle_cwd=None, output=self.root / "report.json", progress_every=1,
            source_revision="abc")
        self.checkpoints = self.root / "checkpoints"
        self.calls = []
        self.interrupt_after = None

    def tearDown(self):
        self.tmp.cleanup()

    def fixture_game(self, row, assignment, seats, kind, timeout, max_decisions):
        if self.interrupt_after is not None and len(self.calls) == self.interrupt_after:
            raise KeyboardInterrupt
        self.calls.append((row["id"], assignment))
        record = synthetic_game(row, assignment, 8)
        for step in record["steps"]:
            seats[step["seat"]].diagnostics[step["id"]] = step["search"]
        return record

    def measure(self):
        with patch.object(whole_game, "Seat", FakeSeat), patch.object(whole_game, "game", self.fixture_game), \
             patch.object(whole_game, "proc_usage", return_value={"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 100}):
            return whole_game.measure_resumable(self.args, "a" * 64, "fixture", self.checkpoints)

    def test_two_saved_games_resume_only_six_and_skip_complete(self):
        self.interrupt_after = 2
        with self.assertRaises(KeyboardInterrupt):
            self.measure()
        self.assertEqual(len(list(self.checkpoints.glob("game-*.json"))), 2)
        self.interrupt_after = None
        report = self.measure()
        self.assertEqual(len(self.calls), 8)
        whole_game.verify(report)
        self.assertEqual(len({item["session_id"] for item in report["games"]}), 2)
        self.measure()
        self.assertEqual(len(self.calls), 8)

    def test_resumed_semantics_equal_continuous_and_missing_game_rejected(self):
        continuous = self.measure()
        self.checkpoints = self.root / "resumed"
        self.args.output = self.root / "resumed.json"
        self.calls = []
        self.interrupt_after = 2
        with self.assertRaises(KeyboardInterrupt):
            self.measure()
        self.interrupt_after = None
        resumed = self.measure()
        self.assertEqual(continuous["aggregate"], resumed["aggregate"])
        for old, new in zip(continuous["games"], resumed["games"]):
            self.assertEqual(old["steps"], new["steps"])
            self.assertEqual(old["terminal_board"], new["terminal_board"])
            self.assertEqual(old["cache"], new["cache"])
        changed = copy.deepcopy(resumed)
        changed["games"].pop()
        changed = whole_game.sealed(changed)
        with self.assertRaisesRegex(whole_game.BenchmarkError, "incomplete eight-game"):
            whole_game.verify(changed)

    def test_corrupt_checkpoint_and_changed_identity_fail_before_launch(self):
        self.interrupt_after = 1
        with self.assertRaises(KeyboardInterrupt):
            self.measure()
        path = next(self.checkpoints.glob("game-*.json"))
        original = path.read_bytes()
        path.write_bytes(b"{}\n")
        self.interrupt_after = None
        with self.assertRaises(whole_game.BenchmarkError):
            self.measure()
        self.assertEqual(len(self.calls), 1)
        path.write_bytes(original)
        self.binary.write_bytes(b"changed")
        with self.assertRaisesRegex(whole_game.BenchmarkError, "identity"):
            self.measure()
        self.assertEqual(len(self.calls), 1)

    def test_atomic_save_crash_before_and_after_commit(self):
        original = whole_game.atomic_write
        for after in (False, True):
            with self.subTest(after=after):
                self.calls = []
                self.checkpoints = self.root / str(after)
                self.args.output = self.root / f"{after}.json"
                def crashing(path, value):
                    if after:
                        original(path, value)
                    raise KeyboardInterrupt
                with patch.object(whole_game, "atomic_write", crashing):
                    with self.assertRaises(KeyboardInterrupt):
                        self.measure()
                self.assertEqual(len(list(self.checkpoints.glob("game-*.json"))), int(after))
                self.measure()
                self.assertEqual(len(self.calls), 9-int(after))

    def test_lock_duplicate_unknown_and_unfinished_temp(self):
        with whole_game.exclusive_lock(self.checkpoints):
            with self.assertRaisesRegex(whole_game.BenchmarkError, "locked"):
                self.measure()
        (self.checkpoints / ".unfinished-fixture").write_bytes(b"partial")
        self.interrupt_after = 1
        with self.assertRaises(KeyboardInterrupt):
            self.measure()
        saved = next(self.checkpoints.glob("game-*.json"))
        (self.checkpoints / "game-duplicate.json").write_bytes(saved.read_bytes())
        with self.assertRaisesRegex(whole_game.BenchmarkError, "duplicate/unknown"):
            self.measure()
        self.assertEqual(len(self.calls), 1)

    def test_real_seat_protocol_ack_and_missing_ack(self):
        self.binary.write_text("#!/usr/bin/env python3\nimport sys\nfor line in sys.stdin:\n parts=line.strip().split('\\t')\n print('new_game\\t'+parts[1]+'\\tready', flush=True)\n")
        self.binary.chmod(0o755)
        seat = whole_game.Seat("cli", self.binary, self.artifact, 8, 2, "B")
        try:
            self.assertTrue(seat.new_game("game-1")["acknowledged"])
            seat.close()
        finally:
            seat.abort()
        self.binary.write_text("#!/usr/bin/env python3\nimport sys\nsys.stdin.readline()\nprint('bad',flush=True)\n")
        seat = whole_game.Seat("cli", self.binary, self.artifact, 8, 2, "B")
        try:
            with self.assertRaisesRegex(whole_game.BenchmarkError, "acknowledgement"):
                seat.new_game("game-2")
        finally:
            seat.abort()

    def test_reset_ack_rejected(self):
        with patch.object(FakeSeat, "new_game", return_value={"game_id": "bad", "acknowledged": False}):
            with self.assertRaisesRegex(whole_game.BenchmarkError, "acknowledgement"):
                self.measure()
        self.assertFalse(self.args.output.exists())

    def test_first_seat_aborted_when_second_constructor_fails(self):
        original = FakeSeat.__init__
        started = []
        aborted = []
        def construct(seat, kind, binary, artifact, depth, timeout, side, *args):
            if side == "W":
                raise whole_game.BenchmarkError("second seat failed")
            original(seat, kind, binary, artifact, depth, timeout, side, *args)
            started.append(side)
        def abort(seat):
            aborted.append(seat.side)
            return seat.close()
        with patch.object(FakeSeat, "__init__", construct), patch.object(FakeSeat, "abort", abort):
            with self.assertRaisesRegex(whole_game.BenchmarkError, "second seat failed"):
                self.measure()
        self.assertEqual(started, ["B"])
        self.assertEqual(aborted, ["B"])
        self.assertFalse(self.args.output.exists())

    def test_terminal_segment_peak_above_cap_rejects_before_report(self):
        self.args.kind = "cli-persistent"
        original = FakeSeat.close
        def final_usage(seat):
            usage = original(seat)
            usage["peak_rss_kib"] = self.args.max_rss_kib + 1
            return usage
        with patch.object(FakeSeat, "close", final_usage):
            with self.assertRaisesRegex(whole_game.BenchmarkError, "segment resources invalid"):
                self.measure()
        self.assertFalse(self.args.output.exists())

    def test_terminal_segment_resources_visible_and_independently_verified(self):
        self.args.kind = "cli-persistent"
        original = FakeSeat.close
        def final_usage(seat):
            usage = original(seat)
            usage["peak_rss_kib"] = 200
            usage["user_cpu_ns"] = 123
            return usage
        with patch.object(FakeSeat, "close", final_usage):
            report = self.measure()
        self.assertEqual(report["aggregate"]["peak_rss_kib"], 100)
        self.assertEqual(report["segment_aggregate"]["peak_rss_kib"], 200)
        self.assertEqual(report["segment_aggregate"]["user_cpu_ns"], 246)
        self.assertTrue(report["segment_aggregate"]["complete_process_observations"])
        self.assertEqual(report["resource_scopes"]["aggregate"], "completed-game-checkpoints")
        incorrect_lifetime = copy.deepcopy(report)
        incorrect_lifetime["settings"]["process_lifetime"] = "all-games-per-seat"
        incorrect_lifetime["identity"]["settings"]["process_lifetime"] = "all-games-per-seat"
        incorrect_lifetime["condition_digest"] = hashlib.sha256(
            whole_game.canonical(incorrect_lifetime["identity"])).hexdigest()
        with self.assertRaisesRegex(whole_game.BenchmarkError, "process lifetime mismatch"):
            whole_game.verify(whole_game.sealed(incorrect_lifetime))
        changed = copy.deepcopy(report)
        changed["segment_aggregate"]["peak_rss_kib"] = 100
        with self.assertRaisesRegex(whole_game.BenchmarkError, "segment aggregate mismatch"):
            whole_game.verify(whole_game.sealed(changed))

    def test_persistent_saved_diagnostics_and_lost_segment_scope(self):
        self.args.kind = "cli-persistent"
        self.interrupt_after = 2
        with self.assertRaises(KeyboardInterrupt):
            self.measure()
        saved = whole_game.read_canonical(next(self.checkpoints.glob("game-*.json")))
        self.assertIn("search", saved["game"]["steps"][0])
        receipt_path = next(self.checkpoints.glob("segment-*.json"))
        receipt = whole_game.read_canonical(receipt_path)
        self.assertEqual(receipt["resource_observation"], "wait4")
        # Simulate loss of the parent before it could record wait4.
        receipt["status"] = "live"
        receipt["resource_observation"] = "proc-checkpoint"
        for usage in receipt["process_totals"].values():
            usage["shutdown_ns"] = 0
            usage["ended_at_ns"] = None
        whole_game.atomic_write(receipt_path, whole_game.sealed(receipt))
        self.interrupt_after = None
        report = self.measure()
        self.assertEqual(report["settings"]["process_lifetime"], "segments-per-seat")
        self.assertEqual({item["status"] for item in report["segments"]}, {"closed", "process-lost"})
        lost = next(item for item in report["segments"] if item["status"] == "process-lost")
        self.assertEqual(lost["resource_observation"], "proc-checkpoint")
        self.assertEqual(lost["process_totals"]["B"]["shutdown_ns"], 0)
        whole_game.verify(report)


if __name__ == "__main__":
    unittest.main()
