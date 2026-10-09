"""Offline contract checks; never launches an eight-game measurement."""

import copy
import hashlib
import importlib.util
import unittest
import tempfile
import contextlib
import io
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
                      "search": {"score_contract": whole_game.SCORE_CONTRACT, "search_semantics_version": 2,
                                 "score_identity_raw": f"score_contract_v1\tposition_id={row['id']}-seat{assignment}-turn{turn}\tscore_contract=winner-empty-v1\tsearch_semantics_version=2",
                                 "elapsed_us": 1, "nodes": 0 if move == "pass" and not exact else 1,
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
    report = {"schema_version": 3, "score_contract": whole_game.SCORE_CONTRACT, "runner_version": whole_game.VERSION, "kind": "cli",
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

    def test_experimental_thresholds_preserve_strict_legacy_reports(self):
        for threshold in (20, 24):
            report = synthetic_report(8)
            report["settings"]["exact_empty"] = threshold
            for record in report["games"]:
                for step in record["steps"]:
                    occupied = 64 - step["board"].count(".")
                    exact = 64 - occupied <= threshold
                    step["search"]["exact"] = exact
                    step["search"]["completed_depth"] = (64 - occupied if exact else
                        0 if step["move"] == "pass" else 12 if occupied <= 20 or occupied >= 45 else 8)
                    step["search"]["score"] = 0 if exact or step["move"] != "pass" else None
                    whole_game.validate_cli_diagnostic(step, step["search"], 8, threshold)
            redigest(report)
            with self.assertRaisesRegex(whole_game.BenchmarkError, "search settings mismatch"):
                whole_game.verify(report)
            boundary = next(step for record in report["games"] for step in record["steps"]
                            if step["board"].count(".") == threshold)
            with self.assertRaisesRegex(whole_game.BenchmarkError, "incomplete or inconsistent"):
                whole_game.validate_cli_diagnostic(boundary, boundary["search"], 8, 16)

    def test_decision_phase_legal_count_and_resource_evidence(self):
        report = synthetic_report(8)
        step = report["games"][0]["steps"][0]
        step.update(legal_move_count=len(whole_game.oracle.legal_moves(step["board"], step["side"])),
                    phase=whole_game.decision_phase(step["board"]),
                    resources={"user_cpu_ns": 1, "system_cpu_ns": 0, "peak_rss_kib": 100})
        step["resource_observations"] = {
            "before": {"user_cpu_ns": 2, "system_cpu_ns": 0, "peak_rss_kib": 99},
            "after": {"user_cpu_ns": 3, "system_cpu_ns": 0, "peak_rss_kib": 100}}
        redigest(report)
        whole_game.verify(report)
        changed = copy.deepcopy(report)
        changed["games"][0]["steps"][0]["resource_observations"]["after"]["user_cpu_ns"] += 1
        redigest(changed)
        with self.assertRaisesRegex(whole_game.BenchmarkError, "do not match observations"):
            whole_game.verify(changed)
        for field, value in (("legal_move_count", 99), ("phase", "exact"),
                             ("resources", {"user_cpu_ns": -1, "system_cpu_ns": 0, "peak_rss_kib": 100}),
                             ("resources", {"user_cpu_ns": 1, "system_cpu_ns": 0, "peak_rss_kib": 101})):
            changed = copy.deepcopy(report)
            changed["games"][0]["steps"][0][field] = value
            redigest(changed)
            with self.assertRaises(whole_game.BenchmarkError):
                whole_game.verify(changed)

    def test_independent_proc_wait4_rss_peaks_and_fluctuating_sample_reconcile(self):
        report = synthetic_report(8)
        game = report["games"][0]
        step = game["steps"][0]
        step.update(legal_move_count=len(whole_game.oracle.legal_moves(step["board"], step["side"])),
                    phase=whole_game.decision_phase(step["board"]),
                    resources={"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 200},
                    resource_observations={
                        "before": {"user_cpu_ns": 1, "system_cpu_ns": 0, "peak_rss_kib": 250},
                        "after": {"user_cpu_ns": 1, "system_cpu_ns": 0, "peak_rss_kib": 200}})
        game["resources"]["peak_rss_kib"] = 250
        report["aggregate"] = whole_game.totals(report["games"])
        redigest(report)
        whole_game.verify(report)
        self.assertEqual(game["seat_processes"][step["seat"]]["peak_rss_kib"], 100)
        self.assertEqual(step["resource_observations"]["before"]["peak_rss_kib"], 250)
        for source in ("aggregate", "before", "after", "wait4", "cpu"):
            changed = copy.deepcopy(report)
            target_game = changed["games"][0]
            target_step = target_game["steps"][0]
            if source == "aggregate":
                target_game["resources"]["peak_rss_kib"] = 200
            elif source in ("before", "after"):
                target_step["resource_observations"][source]["peak_rss_kib"] = changed["settings"]["max_rss_kib"]+1
                if source == "after":
                    target_step["resources"]["peak_rss_kib"] = changed["settings"]["max_rss_kib"]+1
                target_game["resources"]["peak_rss_kib"] = changed["settings"]["max_rss_kib"]+1
            elif source == "wait4":
                target_game["seat_processes"][target_step["seat"]]["peak_rss_kib"] = changed["settings"]["max_rss_kib"]+1
                target_game["resources"]["peak_rss_kib"] = changed["settings"]["max_rss_kib"]+1
            else:
                target_step["resource_observations"]["after"]["user_cpu_ns"] = 3
                target_step["resources"]["user_cpu_ns"] = 2
            changed["aggregate"] = whole_game.totals(changed["games"])
            redigest(changed)
            with self.subTest(source=source), self.assertRaises(whole_game.BenchmarkError):
                whole_game.verify(changed)

    def test_oracle_forced_pass_does_not_retain_previous_decision_peak(self):
        self.assertFalse(whole_game.oracle.legal_moves(TARGET_BOARD, "W"))
        self.assertTrue(whole_game.oracle.legal_moves(TARGET_BOARD, "B"))
        seats, chosen_ids = {}, []
        for label in ("B", "W"):
            seat = SimpleNamespace(exact_empty=16,
                peak_observation={"user_cpu_ns": 1, "system_cpu_ns": 0, "peak_rss_kib": 900},
                gtp_command=lambda _command: [])
            def observe(current=seat):
                raw = {"user_cpu_ns": 10, "system_cpu_ns": 0, "peak_rss_kib": 100}
                if current.peak_observation is None or raw["peak_rss_kib"] > current.peak_observation["peak_rss_kib"]:
                    current.peak_observation = dict(raw)
                return raw
            def choose(identifier, board, side):
                chosen_ids.append(identifier)
                legal = whole_game.oracle.legal_moves(board, side)
                return (legal[0] if legal else "pass"), 1
            seat.observe_resources, seat.choose = observe, choose
            seats[label] = seat
        record = whole_game.game({"id": "forced-pass", "board": TARGET_BOARD,
                                  "side": "W", "moves": ""}, 0, seats, "oracle", 2, 120)
        first = record["steps"][0]
        self.assertEqual(first["move"], "pass")
        self.assertNotIn(first["id"], chosen_ids)
        self.assertEqual(first["resource_observations"]["peak"],
                         {"user_cpu_ns": 10, "system_cpu_ns": 0, "peak_rss_kib": 100})
        self.assertEqual(first["resource_observations"]["before"], first["resource_observations"]["peak"])
        self.assertEqual(first["resource_observations"]["after"], first["resource_observations"]["peak"])

    def test_polled_peak_raw_resources_verify_and_reaggregate(self):
        report = synthetic_report(8)
        game = report["games"][0]
        step = game["steps"][0]
        raw = {"user_cpu_ns": 1, "system_cpu_ns": 0}
        step.update(legal_move_count=len(whole_game.oracle.legal_moves(step["board"], step["side"])),
                    phase=whole_game.decision_phase(step["board"]),
                    resources={"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 200},
                    resource_observations={"before": dict(raw, peak_rss_kib=100),
                                           "after": dict(raw, peak_rss_kib=200),
                                           "peak": dict(raw, peak_rss_kib=900)})
        game["resources"]["peak_rss_kib"] = 900
        report["aggregate"] = whole_game.totals(report["games"])
        redigest(report)
        whole_game.verify(report)
        self.assertEqual(whole_game.max_observed_rss(game["seat_processes"], game), 900)
        for field, value in (("user_cpu_ns", 2), ("system_cpu_ns", 1), ("peak_rss_kib", 1001)):
            changed = copy.deepcopy(report)
            changed["games"][0]["steps"][0]["resource_observations"]["peak"][field] = value
            changed["games"][0]["resources"]["peak_rss_kib"] = whole_game.max_observed_rss(
                changed["games"][0]["seat_processes"], changed["games"][0])
            changed["aggregate"] = whole_game.totals(changed["games"])
            redigest(changed)
            with self.subTest(field=field), self.assertRaises(whole_game.BenchmarkError):
                whole_game.verify(changed)

    def test_oracle_evidence_requires_every_exact_position(self):
        report = synthetic_report()
        rows = [{"id": step["id"], "board": step["board"], "side": step["side"],
                 "move": step["move"], "cli_score": step["search"]["score"],
                 "oracle_score": step["search"]["score"],
                 "selected_score": step["search"]["score"]}
                for game in report["games"] for step in game["steps"] if step["search"]["exact"]]
        evidence = {"schema_version": 2, "score_contract": whole_game.SCORE_CONTRACT, "runner_version": whole_game.VERSION,
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
        self.depth, self.side, self.kind = depth, side, kind
        self.process = SimpleNamespace(pid=1)
        self.diagnostics = {}
        self.startup_ns = 1
        self.started_at_ns = 1

    def new_game(self, identifier):
        return {"game_id": identifier, "acknowledged": True, "elapsed_ns": 1,
                "protocol": "gtp-clear-board" if self.kind == "oracle" else "new_game-v1"}

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
            midgame_depth=8, cache_scope="turn", timeout_seconds=2, max_rss_kib=1000,
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
            raw = {"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 100}
            step.update(legal_move_count=len(whole_game.oracle.legal_moves(step["board"], step["side"])),
                        phase=whole_game.decision_phase(step["board"]),
                        resources=dict(raw), resource_observations={"before": dict(raw), "after": dict(raw)})
            seats[step["seat"]].diagnostics[step["id"]] = step["search"]
            if kind == "oracle":
                step.pop("search")
        return record

    def measure(self):
        with patch.object(whole_game, "Seat", FakeSeat), patch.object(whole_game, "game", self.fixture_game), \
             patch.object(whole_game, "proc_usage", return_value={"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 100}):
            return whole_game.measure_resumable(self.args, "a" * 64, "fixture", self.checkpoints)

    def test_measure_cli_defaults_turn_and_oracle_retains_game(self):
        for kind, expected in (("cli", "turn"), ("oracle", "game")):
            with patch.object(whole_game, "measure_resumable") as measure:
                self.assertEqual(whole_game.main([
                    "measure", "--kind", kind, "--binary", str(self.binary),
                    "--midgame-depth", "8", "--max-rss-kib", "1000",
                    "--output", str(self.args.output)]), 0)
            self.assertEqual(measure.call_args.args[0].cache_scope, expected)

    def test_game_scope_rejected_before_output_or_process_creation(self):
        self.args.cache_scope = "game"
        with patch.object(whole_game, "Seat") as seat:
            with self.assertRaisesRegex(whole_game.BenchmarkError, "scope is suspended"):
                whole_game.measure_resumable(self.args, "a" * 64, "fixture", self.checkpoints)
            seat.assert_not_called()
        self.assertFalse(self.checkpoints.exists())
        self.assertFalse(self.args.output.exists())
        # Offline identity/verification retain historical game semantics.
        self.assertEqual(whole_game.measurement_identity(self.args)["settings"]["exact_cache_scope"], "game")

    def test_v2_report_requires_every_decision_resource_field(self):
        fields = ("legal_move_count", "phase", "resources", "resource_observations")
        for kind in ("cli", "cli-persistent", "oracle"):
            self.args.kind = kind
            self.args.cache_scope = "game" if kind == "oracle" else "turn"
            self.args.artifact = None if kind == "oracle" else self.artifact
            self.args.output = self.root / f"{kind}.json"
            self.checkpoints = self.root / f"{kind}-checkpoints"
            report = self.measure()
            whole_game.verify(report)
            for removed in [(field,) for field in fields] + [fields]:
                changed = copy.deepcopy(report)
                for field in removed:
                    changed["games"][0]["steps"][0].pop(field)
                with self.subTest(kind=kind, removed=removed), self.assertRaisesRegex(
                        whole_game.BenchmarkError, "complete decision resources required"):
                    whole_game.verify(whole_game.sealed(changed))

    def test_stripped_v2_checkpoint_rejected_before_process_launch(self):
        self.interrupt_after = 1
        with self.assertRaises(KeyboardInterrupt):
            self.measure()
        path = next(self.checkpoints.glob("game-*.json"))
        original = whole_game.read_canonical(path)
        fields = ("legal_move_count", "phase", "resources", "resource_observations")
        self.interrupt_after = None
        for removed in [(field,) for field in fields] + [fields]:
            changed = copy.deepcopy(original)
            for field in removed:
                changed["game"]["steps"][0].pop(field)
            whole_game.atomic_write(path, whole_game.sealed(changed))
            with self.subTest(removed=removed), patch.object(whole_game, "Seat") as seat, \
                 self.assertRaisesRegex(whole_game.BenchmarkError, "complete decision resources required"):
                whole_game.measure_resumable(self.args, "a" * 64, "fixture", self.checkpoints)
            seat.assert_not_called()
            self.assertEqual(len(self.calls), 1)

    def test_genuine_v1_reports_without_decision_resources_remain_valid(self):
        report = synthetic_report(8)
        self.assertEqual(report["schema_version"], 3)
        whole_game.verify(report)
        changed = copy.deepcopy(report)
        changed["games"][0]["steps"][0]["resource_observations"] = {
            "before": {"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 100},
            "after": {"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 100}}
        redigest(changed)
        with self.assertRaises(whole_game.BenchmarkError):
            whole_game.verify(changed)

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

    def test_seat_retains_peak_poll_and_resets_for_next_decision(self):
        seat = whole_game.Seat.__new__(whole_game.Seat)
        seat.process = SimpleNamespace(pid=123, stdin=io.BytesIO(),
                                       stdout=SimpleNamespace(fileno=lambda: 123))
        seat.gtp, seat.timeout, seat.max_rss_kib = None, 2, 1000
        seat.buffer = bytearray()
        seat.last_observation = seat.peak_observation = None
        raw = {"user_cpu_ns": 1, "system_cpu_ns": 0}
        samples = [dict(raw, peak_rss_kib=p) for p in (100, 900, 200)]
        with patch.object(whole_game, "proc_usage", side_effect=samples), \
             patch.object(whole_game.select, "select", side_effect=[([], [], []), ([seat.process.stdout], [], [])]), \
             patch.object(whole_game.os, "read", return_value=b"root\ta1\n"):
            self.assertEqual(seat.choose("root", whole_game.oracle.initial_board(), "B")[0], "a1")
        self.assertEqual(seat.peak_observation["peak_rss_kib"], 900)
        self.assertEqual(seat.last_observation["peak_rss_kib"], 200)
        with patch.object(whole_game, "proc_usage", side_effect=[dict(raw, peak_rss_kib=300), dict(raw, peak_rss_kib=250)]), \
             patch.object(whole_game.select, "select", return_value=([seat.process.stdout], [], [])), \
             patch.object(whole_game.os, "read", return_value=b"next\ta1\n"):
            seat.choose("next", whole_game.oracle.initial_board(), "B")
        self.assertEqual(seat.peak_observation["peak_rss_kib"], 300)
        self.assertEqual(seat.last_observation["peak_rss_kib"], 250)
        with patch.object(whole_game, "proc_usage", return_value=dict(raw, peak_rss_kib=1001)):
            with self.assertRaisesRegex(whole_game.BenchmarkError, "RSS cap exceeded"):
                seat.choose("failed", whole_game.oracle.initial_board(), "B")
        self.assertEqual(seat.peak_observation["peak_rss_kib"], 1001)

    def test_seat_threshold_node_flags_and_rss_failure_observation(self):
        self.binary.write_text("#!/usr/bin/env python3\nimport sys\nfor line in sys.stdin:\n parts=line.strip().split('\\t')\n print('new_game\\t'+parts[1]+'\\tready' if parts[0]=='new_game' else parts[0]+'\\ta1', flush=True)\n")
        self.binary.chmod(0o755)
        original = whole_game.subprocess.Popen
        with patch.object(whole_game.subprocess, "Popen", wraps=original) as popen:
            seat = whole_game.Seat("cli", self.binary, self.artifact, 8, 2, "B",
                                   exact_empty=24, node_limit=10_000_000, max_rss_kib=1000)
        try:
            argv = popen.call_args.args[0]
            self.assertEqual(argv[argv.index("--exact-solver-empty-squares") + 1], "24")
            self.assertEqual(argv[argv.index("--node-limit") + 1], "10000000")
            self.assertTrue(seat.new_game("reset")["acknowledged"])
            observed = {"user_cpu_ns": 123, "system_cpu_ns": 45, "peak_rss_kib": 1001}
            below_cap = {**observed, "peak_rss_kib": 999}
            with patch.object(whole_game, "proc_usage", side_effect=[below_cap, observed]), \
                 patch.object(whole_game.select, "select", return_value=([], [], [])) as select_wait:
                with self.assertRaisesRegex(whole_game.BenchmarkError, "RSS cap exceeded"):
                    seat.choose("root", whole_game.oracle.initial_board(), "B")
                self.assertEqual(select_wait.call_count, 1)
                self.assertLessEqual(select_wait.call_args.args[3], 0.05)
            self.assertEqual(seat.last_observation, observed)
        finally:
            seat.abort()

    def test_resumable_threshold_identity_and_reset_validation(self):
        report = self.measure()
        self.args.exact_empty = 20
        identity = whole_game.measurement_identity(self.args)
        self.assertEqual(identity["settings"]["exact_empty"], 20)
        with self.assertRaisesRegex(whole_game.BenchmarkError, "identity mismatch"):
            self.measure()
        self.assertEqual(len(self.calls), 8)
        changed = copy.deepcopy(report)
        changed["settings"]["exact_empty"] = 20
        changed["identity"]["settings"]["exact_empty"] = 20
        changed["condition_digest"] = hashlib.sha256(whole_game.canonical(changed["identity"])).hexdigest()
        for record in changed["games"]:
            for step in record["steps"]:
                step["phase"] = whole_game.decision_phase(step["board"], 20)
        with self.assertRaisesRegex(whole_game.BenchmarkError, "incomplete or inconsistent"):
            whole_game.verify(whole_game.sealed(changed))
        for record in changed["games"]:
            record["condition_digest"] = changed["condition_digest"]
            for step in record["steps"]:
                occupied = 64 - step["board"].count(".")
                exact = 64 - occupied <= 20
                step["search"]["exact"] = exact
                step["search"]["completed_depth"] = (64 - occupied if exact else
                    0 if step["move"] == "pass" else 12 if occupied <= 20 or occupied >= 45 else 8)
                step["search"]["score"] = 0 if exact or step["move"] != "pass" else None
        whole_game.verify(whole_game.sealed(changed))
        changed["games"][0]["reset_events"]["B"]["game_id"] = "other-game"
        with self.assertRaisesRegex(whole_game.BenchmarkError, "acknowledgement mismatch"):
            whole_game.verify(whole_game.sealed(changed))
        self.args.node_limit = 10_000_000
        with self.assertRaisesRegex(whole_game.BenchmarkError, "must not use a node cap"):
            whole_game.measurement_identity(self.args)

    def test_reset_ack_rejected(self):
        with patch.object(FakeSeat, "new_game", return_value={"game_id": "bad", "acknowledged": False}):
            with self.assertRaisesRegex(whole_game.BenchmarkError, "acknowledgement"):
                self.measure()
        self.assertFalse(self.args.output.exists())

    def test_oracle_identity_records_actual_protocol(self):
        self.args.kind = "oracle"
        self.args.cache_scope = "game"
        self.args.artifact = None
        report = self.measure()
        self.assertEqual(report["identity"]["reset_protocol"], "gtp-clear-board")
        self.assertEqual(report["settings"]["process_lifetime"], "one-game-per-seat")
        for record in report["games"]:
            self.assertEqual({event["protocol"] for event in record["reset_events"].values()}, {"gtp-clear-board"})
        whole_game.verify(report)

    def test_legacy_measure_kind_rejected_by_argument_parser(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                whole_game.main(["measure", "--kind", "cli-legacy"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())
        self.assertIn("cli-legacy", stderr.getvalue())

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

    def test_persistent_sampled_rss_above_wait4_survives_resume_and_reverifies(self):
        self.args.kind = "cli-persistent"
        original_game = self.fixture_game
        original_close = FakeSeat.close

        def sampled_game(*args):
            record = original_game(*args)
            step = record["steps"][0]
            step.update(legal_move_count=len(whole_game.oracle.legal_moves(step["board"], step["side"])),
                        phase=whole_game.decision_phase(step["board"]),
                        resources={"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 200},
                        resource_observations={
                            "before": {"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 250},
                            "after": {"user_cpu_ns": 0, "system_cpu_ns": 0, "peak_rss_kib": 200}})
            return record

        def waited(seat):
            return {**original_close(seat), "peak_rss_kib": 80}

        with patch.object(self, "fixture_game", side_effect=sampled_game), \
             patch.object(FakeSeat, "close", waited):
            self.interrupt_after = 2
            with self.assertRaises(KeyboardInterrupt):
                self.measure()
            receipt_path = next(self.checkpoints.glob("segment-*.json"))
            receipt = whole_game.read_canonical(receipt_path)
            self.assertEqual(receipt["process_totals"]["B"]["peak_rss_kib"], 80)
            self.interrupt_after = None
            report = self.measure()
            self.assertEqual(len(self.calls), 8)
            whole_game.verify(report)
            self.assertEqual(report["aggregate"]["peak_rss_kib"], 250)
            self.assertEqual(report["segment_aggregate"]["peak_rss_kib"], 80)
            for game in report["games"]:
                self.assertEqual(game["seat_processes"]["B"]["peak_rss_kib"], 100)

        changed = copy.deepcopy(report)
        changed["segments"][0]["process_totals"]["B"]["peak_rss_kib"] = self.args.max_rss_kib + 1
        changed["segments"][0] = whole_game.sealed(changed["segments"][0])
        changed["segment_aggregate"] = whole_game.segment_totals(changed["segments"])
        with self.assertRaisesRegex(whole_game.BenchmarkError, "segment resources invalid"):
            whole_game.verify(whole_game.sealed(changed))

        changed = copy.deepcopy(report)
        step = changed["games"][0]["steps"][0]
        step["resource_observations"]["before"]["peak_rss_kib"] = self.args.max_rss_kib + 1
        changed["games"][0]["resources"]["peak_rss_kib"] = self.args.max_rss_kib + 1
        changed["aggregate"] = whole_game.totals(changed["games"])
        with self.assertRaisesRegex(whole_game.BenchmarkError, "game resource totals mismatch"):
            whole_game.verify(whole_game.sealed(changed))

        changed = copy.deepcopy(report)
        step = changed["games"][0]["steps"][0]
        step["resource_observations"]["after"]["user_cpu_ns"] = 1
        step["resources"]["user_cpu_ns"] = 1
        with self.assertRaisesRegex(whole_game.BenchmarkError, "decision CPU exceeds process total"):
            whole_game.verify(whole_game.sealed(changed))

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
