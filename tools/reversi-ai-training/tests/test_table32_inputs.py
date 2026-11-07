"""Bounded synthetic input fixtures; no candidate or Oracle process is used."""
import copy
import random
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reinforcement as rf
import table32_inputs as inputs
import training


def fixture_choose(identifier, board, side, settings):
    legal = sorted(rf.legal_moves(board, side))
    empty = board.count(".")
    return {"move": legal[0] if legal else "pass", "score": 0,
            "completed_depth": empty if empty <= 25 else settings["opening_depth"],
            "exact": empty <= 25, "nodes": 1, "elapsed_ms": 1}


def saved_game(seed):
    rng = random.Random(seed)
    board, side, turns = rf.INITIAL, "B", []
    while rf.legal_moves(board, side) or rf.legal_moves(board, rf.other(side)):
        legal = sorted(rf.legal_moves(board, side))
        move = legal[rng.randrange(len(legal))] if legal else "pass"
        turns.append({"board": board, "side": side, "move": move})
        board, side = inputs.advance(board, side, move)
    return {"score_contract": training.SCORE_CONTRACT, "turns": turns, "terminal_board": board}


class Table32InputTests(unittest.TestCase):
    def test_frozen_plan_counts_domains_and_repeatability(self):
        plan = inputs.generation_plan()
        self.assertEqual(len(plan), 128)
        self.assertEqual(Counter(item["split"] for item in plan), {"train": 96, "validation": 16, "test": 16})
        for length in inputs.PREFIX_LENGTHS:
            self.assertEqual(Counter(item["split"] for item in plan if item["prefix_length"] == length), inputs.SPLIT_COUNTS)
        self.assertEqual(len({item["stream_seed"] for item in plan}), 128)
        self.assertEqual(plan, inputs.generation_plan())
        self.assertNotEqual(plan[0]["stream_seed"], inputs.generation_plan(inputs.SEED + 1)[0]["stream_seed"])
        self.assertEqual(inputs.random_prefix(plan[0]), inputs.random_prefix(plan[0]))

    def test_prefix_counts_placements_and_stays_legal(self):
        for spec in inputs.generation_plan()[::16]:
            opening = inputs.random_prefix(spec)
            self.assertEqual(64 - opening["board"].count(".") - 4, spec["prefix_length"])
            board, side = rf.INITIAL, "B"
            for turn in opening["turns"]:
                self.assertEqual((turn["board"], turn["side"]), (board, side))
                board, side = inputs.advance(board, side, turn["move"])
            self.assertEqual((opening["board"], opening["side"]), (board, side))

    def test_explicit_scale_changes_plan_and_derived_caps(self):
        plan = inputs.generation_plan(train_per_prefix=24, validation_per_prefix=4, test_per_prefix=4)
        self.assertEqual(len(plan), 256)
        self.assertEqual(Counter(item["split"] for item in plan), {"train": 192, "validation": 32, "test": 32})
        with mock.patch.object(inputs, "replay_game", return_value=[]):
            result = inputs.extract([{"spec": plan[0]}], [], planned_specs=plan,
                                    early_limit=512, require_complete=False)
        self.assertEqual(result["coverage"]["accepted_rows"], 0)
        # Larger operator limits remain usable through the same API; fixture
        # candidate collection is deliberately tiny and invokes no teacher.
        pool = inputs.early_pool(max_sequences=1, total_limit=512, candidate_limit=64)
        self.assertEqual(pool["limits"], {"sequences": 1, "total": 512, "per_phase": 64})
        with self.assertRaises(training.TrainingError):
            inputs.generation_plan(train_per_prefix=0)
        with self.assertRaises(training.TrainingError):
            inputs.early_pool(max_sequences=True)

    def test_generation_replays_terminal_teachers_only_after_prefix(self):
        spec = inputs.generation_plan()[0]
        game = inputs.generate_game(spec, fixture_choose)
        rows = inputs.replay_game(game)
        self.assertTrue(rows)
        self.assertEqual(len(rows), len(game["decisions"]))
        self.assertEqual(rows[0]["board"], game["opening"]["board"])
        for row in rows:
            expected = training.terminal_score(game["terminal_board"], row["side"])
            self.assertEqual(row["target"], expected)
            self.assertEqual(row["source_kind"], "project-owned-s0-terminal")
        tampered = copy.deepcopy(game)
        tampered["decisions"][0]["move"] = "a1"
        tampered["game_digest"] = training.digest({k: v for k, v in tampered.items() if k != "game_digest"})
        with self.assertRaises(training.TrainingError):
            inputs.replay_game(tampered)

    def test_no_shallow_exact_or_resource_fallback(self):
        opening = inputs.random_prefix(inputs.generation_plan()[0])
        board, side = opening["board"], opening["side"]
        result = fixture_choose("x", board, side, inputs.TEACHER_SETTINGS)
        for field, value in (("completed_depth", 10), ("nodes", 10000001), ("elapsed_ms", 300001), ("score", True)):
            with self.subTest(field=field), self.assertRaises(training.TrainingError):
                inputs.validate_decision(board, side, {**result, field: value}, inputs.TEACHER_SETTINGS)
        late = inputs.random_prefix(inputs.generation_plan()[-1])
        result = fixture_choose("x", late["board"], late["side"], inputs.TEACHER_SETTINGS)
        with self.assertRaises(training.TrainingError):
            inputs.validate_decision(late["board"], late["side"], {**result, "exact": False}, inputs.TEACHER_SETTINGS)

    def test_pass_preserves_phase_and_terminal_winner_empty(self):
        board = "WB." + "W" * 61
        after, side = inputs.advance(board, "B", "pass")
        self.assertEqual(after, board)
        self.assertEqual(side, "W")
        self.assertEqual(inputs.phase(after), inputs.phase(board))
        terminal, side = inputs.advance(after, side, "c1")
        self.assertEqual(training.terminal_score(terminal, "W"), 64)
        with self.assertRaises(training.TrainingError):
            inputs.advance(rf.INITIAL, "B", "pass")

    def test_early_pool_covers_each_length_and_label_reuse(self):
        pool = inputs.early_pool(max_sequences=4, total_limit=24, candidate_limit=3)
        self.assertEqual(pool, inputs.early_pool(max_sequences=4, total_limit=24, candidate_limit=3))
        self.assertLessEqual(len(pool["roots"]), 24)
        self.assertEqual([root["placements"] for root in pool["roots"][:12]], list(range(12)))
        self.assertEqual(len({root["canonical_key"] for root in pool["roots"]}), len(pool["roots"]))
        choose = mock.Mock(side_effect=fixture_choose)
        completed = {root["id"]: inputs.label_early(root, choose) for root in pool["roots"][:2]}
        labels = [completed[root["id"]] if root["id"] in completed else inputs.label_early(root, choose)
                  for root in pool["roots"]]
        self.assertEqual(choose.call_count, len(pool["roots"]))
        self.assertEqual([label["root"]["id"] for label in labels[:2]], [root["id"] for root in pool["roots"][:2]])
        self.assertTrue(all(inputs.early_row(label)["split"] == "train" for label in labels))
        bad = copy.deepcopy(labels[0])
        bad["source_kind"] = "egaroucid"
        with self.assertRaises(training.TrainingError):
            inputs.early_row(bad)

    def test_early_pool_skips_terminal_and_forced_pass_positions(self):
        # The original production generation seed has a genuine terminal after ten
        # placements. Seed 364 reaches a legal forced pass within eleven.
        terminal_spec = next(spec for spec in inputs.generation_plan(seed=2026110101)
                             if spec["game_id"] == "p24-validation-00")
        terminal_stream = terminal_spec["stream_seed"]
        with self.assertRaisesRegex(training.TrainingError, "random prefix reached terminal"):
            inputs.random_prefix({"prefix_length": 11, "stream_seed": terminal_stream})

        with mock.patch.object(inputs, "seed_stream", side_effect=[terminal_stream, 364, 0]):
            pool = inputs.early_pool(max_sequences=3, total_limit=64, candidate_limit=32)

        self.assertEqual(pool["exclusions"]["terminal"], 1)
        self.assertEqual(pool["exclusions"]["forced-pass"], 1)
        self.assertEqual(len(pool["sequences"][0]["moves"]), 10)
        self.assertIn("pass", pool["sequences"][1]["moves"])
        self.assertEqual([root["placements"] for root in pool["roots"][:12]], list(range(12)))
        for root in pool["candidates"]:
            self.assertTrue(rf.legal_moves(root["board"], root["side"]))
        # The post-pass position is still eligible: do not discard the whole sequence.
        self.assertTrue(any("pass" in root["prefix"] for root in pool["candidates"]))

    def test_cross_split_duplicates_removed_from_every_split(self):
        key = inputs.position_key(rf.INITIAL, "B")
        raw = [{"id": "a", "split": "train", "canonical_key": key, "phase": 0, "prefix_length": 12},
               {"id": "b", "split": "test", "canonical_key": key, "phase": 0, "prefix_length": 12},
               {"id": "c", "split": "train", "canonical_key": "independent", "phase": 1, "prefix_length": 12}]
        spec = inputs.generation_plan()[0]
        with mock.patch.object(inputs, "replay_game", return_value=raw):
            result = inputs.extract([{"spec": spec}], [], require_complete=False)
        self.assertEqual([row["id"] for row in result["rows"]], ["c"])
        self.assertEqual([row["id"] for row in result["exclusions"]], ["a", "b"])
        self.assertIn(0, result["coverage"]["training_unavailable"])
        self.assertIn(0, result["coverage"]["validation_unavailable"])
        self.assertEqual(result["exposure_keys"], sorted({key, "independent"}))

    def test_generation_prefix_and_empty_training_rejected(self):
        with self.assertRaises(training.TrainingError):
            inputs.extract([], [])
        with self.assertRaises(training.TrainingError):
            inputs.extract([{"spec": inputs.generation_plan()[1]}], [], require_complete=False)

    def test_historical_roots_replay_without_color_inversion(self):
        games = [saved_game(seed) for seed in range(4)]
        roots = inputs.preflight_roots(games)
        self.assertEqual(len(roots), 12)
        self.assertEqual(Counter(root["empty"] for root in roots), {20: 3, 22: 3, 24: 3, 25: 3})
        for root in roots:
            original = games[root["source_game"]]["turns"][root["source_turn"]]
            self.assertEqual((root["board"], root["side"]), (original["board"], original["side"]))
        raw = games[0]
        rf_game = {"score_contract": training.SCORE_CONTRACT,
                   "opening": [turn["move"] for turn in raw["turns"][:8]],
                   "start_board": raw["turns"][8]["board"], "start_side": raw["turns"][8]["side"],
                   "decisions": raw["turns"][8:], "terminal_board": raw["terminal_board"]}
        self.assertEqual(inputs.historical_states(rf_game), inputs.historical_states(raw))
        with self.assertRaises(training.TrainingError):
            inputs.preflight_roots([])

    def test_exact_preflight_root_and_child_sign_and_profile(self):
        roots = inputs.preflight_roots([saved_game(seed) for seed in range(4)])
        decisions = [fixture_choose(root["id"], root["board"], root["side"], inputs.TEACHER_SETTINGS) for root in roots]
        queries = [{"query": query, "result": {"score": 0, "exact": True, "completed_depth": query["depth"]}}
                   for root, decision in zip(roots, decisions)
                   for query in (inputs.oracle_query(root), inputs.oracle_query(root, child_move=decision["move"]))]
        pool = inputs.early_pool(max_sequences=1, total_limit=12, candidate_limit=1)
        labels = [inputs.label_early(root, fixture_choose) for root in pool["roots"][:2]]
        result = inputs.validate_preflight(roots, decisions, queries, labels)
        self.assertEqual(result["status"], "feasible")
        bad = copy.deepcopy(queries)
        bad[1]["result"]["score"] = 1
        with self.assertRaises(training.TrainingError):
            inputs.validate_preflight(roots, decisions, bad, labels)
        bad = copy.deepcopy(queries)
        bad[0]["query"]["settings"]["profile"] = "oracle-0018-acceptance-v1"
        with self.assertRaises(training.TrainingError):
            inputs.validate_preflight(roots, decisions, bad, labels)


if __name__ == "__main__":
    unittest.main()
