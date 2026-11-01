"""Synthetic cycle integration: no training run or external engine is started."""
import contextlib
import io
import random
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reinforcement as rf
import table32 as cycle
import table32_extract as extraction
import table32_inputs as inputs
import table32_players as players
import table32_store as st
import table32_verify as verifier
import training


def historical_game(seed):
    board, side, turns, rng = rf.INITIAL, "B", [], random.Random(seed)
    while rf.legal_moves(board, side) or rf.legal_moves(board, rf.other(side)):
        legal = sorted(rf.legal_moves(board, side))
        move = legal[rng.randrange(len(legal))] if legal else "pass"
        turns.append({"board": board, "side": side, "move": move})
        board, side = inputs.advance(board, side, move)
    return {"turns": turns, "terminal_board": board, "score_contract": training.SCORE_CONTRACT}


class Providers:
    def __init__(self, interrupt=False):
        self.calls, self.queries, self.interrupt = [], [], interrupt

    def choose(self, kind, identifier, board, side, config):
        self.calls.append((kind, identifier))
        if self.interrupt and identifier.startswith("p12-train-00"):
            self.interrupt = False
            raise RuntimeError("fixture interrupted before completing a game")
        legal = sorted(rf.legal_moves(board, side))
        if not legal:
            player = players.Player.__new__(players.Player)
            player.config, player.log = config, None
            return player.decision(identifier, board, side)
        move, empty = legal[0], board.count(".")
        exact = empty <= config["exact_solver_empty_squares"]
        depth = empty if exact else config["opening_depth"]
        return {"move": move, "score": 0, "completed_depth": depth, "exact": exact,
                "nodes": 1, "elapsed_ms": 1,
                "raw": {"request": f"{identifier}\t{board}\t{side}", "stdout": f"{identifier}\t{move}\n",
                        "reset": {"request": f"new_game\t{identifier}", "stdout": f"new_game\t{identifier}\tready\n"},
                        "argv": ["/fixture/never-executed-cli"],
                        "stderr": f"search_diagnostic_v1\tposition_id={identifier}\toutcome=move\tscore=0\tcompleted_depth={depth}\texact={str(exact).lower()}\tnodes=1\telapsed_us=1000"}}

    def solve(self, query):
        self.queries.append(query["id"])
        board, side = query["board"], query["side"]
        effective, sign = players.oracle.effective_query(board, side)
        move = sorted(rf.legal_moves(board, effective))[0]
        problem_path = Path("/fixture") / (query["id"] + ".problem.txt")
        stdout = "\n".join(["| Level | Depth | Move | Score | Time | Nodes | NPS |",
                             f"| custom | {board.count('.')}@100% | {move} | +0 | 000:00:00.001 | 1 | 1000 |",
                             "total 1 nodes in 0.001s NPS 1000"])
        return {"query": query, "result": {"score": sign * 0, "exact": True, "completed_depth": board.count(".")},
                "raw": {"runtime": runtime(), "timeout": 310, "returncode": 0,
                        "runtime_before":runtime(),"runtime_after":runtime(),
                        "problem": players.oracle.to_egaroucid_problem(board, effective) + "\n",
                        "problem_path": str(problem_path),
                        "argv": players.oracle.oracle_argv(Path(runtime()["binary"]["path"]), players.full_solve_profile(), solve_path=problem_path),
                        "stdout": stdout, "stderr": ""}}


def runtime():
    return {"binary": {"path": "/fixture/never-executed-oracle"}, "working_directory": "/fixture"}


class Table32CycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roots = inputs.preflight_roots(historical_game(seed) for seed in range(4))

    def fixture(self):
        snapshot = {"preflight_roots": self.roots, "validation": [], "held_out": [],
                    "corpus": [], "golden": [], "excluded_keys": []}
        manifest = {"version": st.VERSION, "seed": inputs.SEED, "input_kind": "fixture",
                    "producer_commit": "a" * 40, "snapshot_digest": st.digest(snapshot),
                    "oracle_runtime": runtime(), "generation_plan": inputs.generation_plan()[:2],
                    "limits": {**st.LIMITS, "games": 2, "early_labels": 12},
                    "settings": {"pool_sequences": 1, "early_positions": 12, "early_candidates_per_phase": 1,
                                 "max_steps": 1, "max_proposals": 1, "decision_timeout_seconds": 310,
                                 "time_limit_ms": 300000, "node_limit": 10000000}}
        return manifest, snapshot

    def execute_fixture(self, root, manifest, snapshot, providers):
        driver = cycle.Driver(root, manifest, execute=True, providers=(providers.choose, providers.solve))
        report = cycle.cycle(driver, snapshot)
        driver.finish()
        st.atomic(root / "report.json", report, once=True)
        return report

    def test_cycle_preflight_reuses_first_labels_and_offline_replay_spawns_nothing(self):
        manifest, snapshot = self.fixture()
        providers = Providers()
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temporary)
            report = self.execute_fixture(root, manifest, snapshot, providers)
            self.assertEqual(report["outcome"], "input-coverage-unavailable")
            self.assertFalse(report["cycle成立"])
            self.assertTrue(report["tooling_only"])
            self.assertEqual(report["coverage"]["games"], 2)
            self.assertEqual(report["coverage"]["early_labels"], 12)
            self.assertEqual(len(providers.queries), 24)
            early = Counter(identifier for kind, identifier in providers.calls if kind == "early")
            self.assertEqual(len(early), 12)
            self.assertEqual(set(early.values()), {1})
            with mock.patch.object(cycle.subprocess, "run", side_effect=AssertionError("offline subprocess.run")), \
                 mock.patch.object(cycle.subprocess, "Popen", side_effect=AssertionError("offline subprocess.Popen")):
                self.assertEqual(verifier.verify(root, manifest=manifest, snapshot=snapshot), report)

    def test_interrupted_game_resumes_from_same_opening_and_matches_continuous_digest(self):
        manifest, snapshot = self.fixture()
        interrupted = Providers(interrupt=True)
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            root, continuous = Path(temporary) / "resumed", Path(temporary) / "continuous"
            root.mkdir()
            continuous.mkdir()
            with self.assertRaisesRegex(RuntimeError, "fixture interrupted"):
                self.execute_fixture(root, manifest, snapshot, interrupted)
            with mock.patch.object(cycle.subprocess, "run", side_effect=AssertionError("offline run")), \
                 mock.patch.object(cycle.subprocess, "Popen", side_effect=AssertionError("offline Popen")):
                prefix = verifier.verify(root, manifest=manifest, snapshot=snapshot)
            self.assertEqual(prefix["status"], "incomplete")
            self.assertEqual(prefix["resume_phase"], "generation")
            self.assertEqual(prefix["missing_unit"], manifest["generation_plan"][0]["game_id"])
            resumed = Providers()
            resumed_report = self.execute_fixture(root, manifest, snapshot, resumed)
            self.assertFalse(any(identifier.startswith("preflight-") for _, identifier in resumed.calls))
            self.assertFalse(resumed.queries)
            report = self.execute_fixture(continuous, manifest, snapshot, Providers())
            self.assertEqual(st.digest(resumed_report), st.digest(report))
            self.assertEqual(resumed_report["completed_prefix_digest"], report["completed_prefix_digest"])

    def test_match_pairs_swap_seats_keep_root_and_report_winner_empty_points(self):
        board = "WB." + "W" * 61
        opening = {"board": board, "side": "B", "turns": []}
        provider = Providers()
        first = cycle.match_game(0, opening, provider.choose)
        second = cycle.match_game(1, opening, provider.choose)
        self.assertEqual(first["opening"], second["opening"])
        self.assertEqual([row["player"] for row in first["decisions"]], ["candidate", "baseline"])
        self.assertEqual([row["player"] for row in second["decisions"]], ["baseline", "candidate"])
        self.assertEqual((first["score_candidate"], second["score_candidate"]), (-64, 64))
        self.assertEqual((first["points"], second["points"]), (0, 1))
        self.assertEqual(st.match_outcome(9.5, 20), "not-improved-at-pilot-scale")
        self.assertEqual(st.match_outcome(10, 20), "awaiting-explicit-continue")
        self.assertEqual(st.match_outcome(100, 200), "not-improved-at-pilot-scale")
        self.assertEqual(st.match_outcome(100.5, 200), "promising-at-pilot-scale")

    def test_disk_extraction_uses_scaled_plan_counts(self):
        specs = inputs.generation_plan(train_per_prefix=24, validation_per_prefix=4, test_per_prefix=4)
        def replay(game):
            spec = game["spec"]
            return [{"id": spec["game_id"], "game_id": spec["game_id"], "split": spec["split"],
                     "prefix_length": spec["prefix_length"], "phase": 0, "board": rf.INITIAL,
                     "side": "B", "target": 0, "canonical_key": "synthetic-" + spec["game_id"],
                     "source_kind": "project-owned-s0-terminal", "score_contract": training.SCORE_CONTRACT}]
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(inputs, "replay_game", side_effect=replay):
            report = extraction.build(({"spec": spec} for spec in specs), [], specs, temporary, early_limit=512)
            self.assertEqual(report["games"], 256)
            self.assertEqual({split: sum(counts.values()) for split, counts in report["raw_phase_rows"].items()},
                             {"train": 192, "validation": 32, "test": 32})
            self.assertEqual(report["prefix_missing"], [])
            self.assertEqual(report["status"], "training-phase-unavailable")


if __name__ == "__main__":
    unittest.main()
