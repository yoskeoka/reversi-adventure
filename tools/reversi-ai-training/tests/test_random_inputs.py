"""Complete random-game inputs and fail-closed output verification."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
import random_inputs as ri  # noqa: E402
import reinforcement  # noqa: E402
import training  # noqa: E402


class RandomInputsTests(unittest.TestCase):
    def fixture(self):
        return json.loads((TOOL / "fixtures/random-inputs-v1.json").read_text())

    def test_distinct_game_streams_and_split(self):
        config = self.fixture()
        seeds = [ri.seed_for(config["seed"], i) for i in range(8)]
        self.assertEqual(len(set(seeds)), 8)
        self.assertEqual(ri.assignment(config["seed"], config["counts"]),
                         ri.assignment(config["seed"], config["counts"]))
        self.assertEqual(sorted(sum(ri.assignment(config["seed"], config["counts"]).values(), [])), list(range(8)))
        self.assertNotEqual([ri.Stream(seeds[0]).next()], [ri.Stream(seeds[1]).next()])

    def test_bounded_index_covers_each_sorted_legal_move(self):
        moves = sorted(reinforcement.legal_moves(reinforcement.INITIAL, "B"))
        self.assertEqual(len(moves), 4)
        stream = ri.Stream(7)
        self.assertEqual(set(moves[stream.index(len(moves))] for _ in range(100)), set(moves))

    def test_terminal_move_on_last_allowed_turn(self):
        manifest = {"seed": 20260926, "record_start_placements": 8,
                    "max_turns": 60, "generator_sha256": "fixture"}
        game, _, _ = ri.play(0, "train", manifest)
        self.assertEqual(len(game["turns"]), 60)
        ri.verify_game(game, manifest)

    def test_complete_replay_targets_and_duplicate_filter(self):
        config = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest_path = root / "manifest.json"
            ri.prepare(manifest_path, config["seed"], config["counts"],
                       config["record_start_placements"], config["max_turns"],
                       require_clean=False)
            manifest = ri.check_manifest(manifest_path)
            bad_manifest = dict(manifest)
            bad_manifest["producer_sources"] = dict(manifest["producer_sources"])
            bad_manifest["producer_sources"]["training.py"] = "0" * 64
            bad_path = root / "bad-manifest.json"
            bad_path.write_bytes(ri.canonical(bad_manifest))
            with self.assertRaises(training.TrainingError):
                ri.check_manifest(bad_path)
            ri.generate(manifest_path, root / "one")
            ri.generate(manifest_path, root / "two")
            report = ri.verify(manifest_path, root / "one")
            self.assertEqual({p.name: p.read_bytes() for p in (root / "one").iterdir()},
                             {p.name: p.read_bytes() for p in (root / "two").iterdir()})
            games = training.read_jsonl(root / "one/games.jsonl")
            self.assertEqual(len(games), 8)
            self.assertGreater(sum(turn["move"] == "pass" for game in games for turn in game["turns"]), 0)
            keys = set()
            for game in games:
                ri.verify_game(game, manifest)
                self.assertFalse(reinforcement.legal_moves(game["terminal_board"], "B"))
                self.assertFalse(reinforcement.legal_moves(game["terminal_board"], "W"))
                self.assertEqual(game["black"] + game["white"], game["terminal_board"].count("B") + game["terminal_board"].count("W"))
            for split in ri.SPLITS:
                rows = training.read_jsonl(root / "one" / f"{split}.jsonl")
                self.assertEqual(report["splits"][split]["records"], len(rows))
                self.assertEqual(set(report["splits"][split]["phases"]), {"opening", "midgame", "endgame"})
                for row in rows:
                    game = games[row["game_id"]]
                    expected = game["black"] - game["white"]
                    self.assertEqual(row["target"]["value"], expected if row["side"] == "B" else -expected)
                    key = training.canonical_position_key(row["board"], row["side"])
                    self.assertNotIn(key, keys)
                    keys.add(key)

    def test_partial_and_tampered_outputs_fail(self):
        config = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / "manifest.json"
            output = root / "output"
            ri.prepare(manifest, config["seed"], config["counts"], 8, 128, require_clean=False)
            ri.generate(manifest, output)
            report = output / "report.json"
            original = report.read_bytes()
            report.unlink()
            with self.assertRaises(training.TrainingError):
                ri.verify(manifest, output)
            report.write_bytes(original)
            games_path = output / "games.jsonl"
            original = games_path.read_bytes()
            games_path.write_bytes(original[:-2])
            with self.assertRaises((training.TrainingError, json.JSONDecodeError)):
                ri.verify(manifest, output)
            games_path.write_bytes(original)
            validation_path = output / "validation.jsonl"
            validation_bytes = validation_path.read_bytes()
            validation_path.write_bytes(validation_bytes + b"{}\n")
            with self.assertRaises(training.TrainingError):
                ri.verify(manifest, output)
            validation_path.write_bytes(validation_bytes)
            ri.verify(manifest, output)


if __name__ == "__main__":
    unittest.main()
