"""Independent terminal labels and explicit historical evidence boundaries."""
import copy
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
import training
import reinforcement
import random_inputs
from legacy import producer
import test_reinforcement

class WinnerEmptyTests(unittest.TestCase):
    def test_non_object_manifests_fail_with_controlled_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            for value in ([], None, "invalid", 1):
                path.write_bytes(training.canonical_json(value))
                for legacy in (False, True):
                    with self.subTest(value=value, legacy=legacy):
                        with self.assertRaisesRegex(training.TrainingError, "manifest must be an object"):
                            training.validate_input_manifest(path, legacy_offline=legacy)
                        with self.assertRaisesRegex(training.TrainingError, "manifest"):
                            random_inputs.verify(path, Path(temporary), legacy_offline=legacy)

    def test_independent_terminal_formula_and_sign(self):
        for board, expected in (("B" * 64, 64), ("W" * 64, -64),
                                ("B" * 32 + "W" * 32, 0), ("." * 64, 0),
                                ("B" * 3 + "." * 61, 64),
                                ("B" * 3 + "W" + "." * 60, 62),
                                ("B" * 2 + "W" * 2 + "." * 60, 0)):
            self.assertEqual(training.terminal_score(board, "B"), expected)
            self.assertEqual(training.terminal_score(board, "W"), -expected)

    def test_new_fixture_labels_are_legally_replayed(self):
        games = training.read_jsonl(TOOL / "fixtures/tiny-winner-empty-games.jsonl")
        for row in training.read_jsonl(TOOL / "fixtures/tiny-winner-empty.jsonl"):
            game = games[row["game_id"]]
            random_inputs.verify_game(game, {"max_turns": 128})
            board, side = reinforcement.INITIAL, "B"
            for index, turn in enumerate(game["turns"]):
                if index == row["turn_index"]:
                    self.assertEqual((board, side), (row["board"], row["side"]))
                if turn["move"] != "pass":
                    board = reinforcement.apply_move(board, side, turn["move"])
                side = reinforcement.other(side)
            difference = board.count(row["side"]) - board.count(reinforcement.other(row["side"]))
            expected = difference + (1 if difference > 0 else -1 if difference < 0 else 0) * board.count(".")
            self.assertEqual(row["target"]["value"], expected)

    def test_old_artifact_requires_explicit_offline_and_new_producer_pairing(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
            root = Path(temporary)
            with producer("training") as frozen:
                frozen.run(TOOL / "fixtures/tiny-manifest.json", root / "old.json", root / "report.json")
            old = training.read_json(root / "old.json")
            with self.assertRaises(training.TrainingError):
                training.validate_artifact(old)
            training.validate_artifact(old, legacy_offline=True)
            new = training.read_json(TOOL / "fixtures/tiny-winner-empty-artifact.json")
            for field, value in (("score_contract", "old"),):
                bad = copy.deepcopy(new)
                bad[field] = value
                bad["artifact_digest"] = training.digest({k: v for k, v in bad.items() if k != "artifact_digest"})
                with self.assertRaises(training.TrainingError):
                    training.validate_artifact(bad)
            new["provenance"]["trainer_version"] = "reversi-ai-pattern-training-v1"
            new["artifact_digest"] = training.digest({k: v for k, v in new.items() if k != "artifact_digest"})
            with self.assertRaises(training.TrainingError):
                training.validate_artifact(new)

    def test_complete_historical_reports_keep_raw_teachers_and_original_shapes(self):
        helper = test_reinforcement.ReinforcementTests()
        for version in (3, 4, 5):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
                root = Path(temporary)
                path = helper.prepare_fixture(root)
                manifest = training.read_json(path)
                with producer("training") as frozen:
                    frozen.run(TOOL / "fixtures/tiny-manifest.json", root / "baseline.json", root / "old-report.json")
                old = training.read_json(root / "baseline.json")
                manifest.pop("score_contract")
                manifest.update(schema_version=version, producer_version="reversi-ai-pattern-reinforcement-v3")
                manifest["baseline_artifact"].update(sha256=training.sha256_file(root / "baseline.json"), artifact_digest=old["artifact_digest"])
                manifest["validation"].update(path=str(TOOL / "fixtures/reinforcement-validation-v1.jsonl"), sha256=training.sha256_file(TOOL / "fixtures/reinforcement-validation-v1.jsonl"), source="project-owned-reinforcement-fixture-v1")
                if version == 3:
                    manifest.pop("exact_cache_policy")
                path.write_bytes(training.canonical_json(manifest) + b"\n")
                with producer("reinforcement") as frozen:
                    original = frozen.validate_manifest
                    with mock.patch.object(frozen, "validate_manifest", side_effect=lambda path, **kwargs: original(path)):
                        frozen.run(path, root / "output", 1000)
                before = {p.name: p.read_bytes() for p in (root / "output").iterdir()}
                with mock.patch.object(reinforcement.subprocess, "Popen", side_effect=AssertionError("offline launched process")):
                    reinforcement.verify(path, root / "output", legacy_offline=True)
                self.assertEqual(before, {p.name: p.read_bytes() for p in (root / "output").iterdir()})
                report = training.read_json(root / "output/report.json")
                self.assertEqual(report["schema_version"], 3)
                self.assertNotIn("score_contract", report)
                self.assertEqual("exact_cache_policy" in report, version == 5)
                for game in training.read_jsonl(root / "output/games.jsonl"):
                    self.assertEqual(game["final_score_black"], game["terminal_board"].count("B") - game["terminal_board"].count("W"))
                if version == 5:
                    for name, seal in (("report.json", "report_digest"), ("checkpoint.json", "checkpoint_digest"), ("candidate-artifact.json", "artifact_digest"), ("selected-artifact.json", "artifact_digest")):
                        file = root / "output" / name
                        original = file.read_bytes()
                        modified = training.read_json(file)
                        modified["migration_identity"] = {"score_contract": training.SCORE_CONTRACT}
                        modified[seal] = training.digest({k: v for k, v in modified.items() if k != seal})
                        file.write_bytes(training.canonical_json(modified) + b"\n")
                        with self.assertRaisesRegex(training.TrainingError, "original score identity"):
                            reinforcement.verify(path, root / "output", legacy_offline=True)
                        file.write_bytes(original)
                    file = root / "output/games.jsonl"
                    original = file.read_bytes()
                    for changed in ({"schema_version": 4}, {"score_contract": training.SCORE_CONTRACT}, {"metadata": {"score_contract": training.SCORE_CONTRACT}}):
                        modified = training.read_jsonl(file)
                        modified[0].update(changed)
                        modified[0]["game_digest"] = training.digest({k: v for k, v in modified[0].items() if k != "game_digest"})
                        file.write_bytes(b"".join(training.canonical_json(game) + b"\n" for game in modified))
                        with self.assertRaisesRegex(training.TrainingError, "original score identity"):
                            reinforcement.verify(path, root / "output", legacy_offline=True)
                        file.write_bytes(original)
                with self.assertRaises(training.TrainingError):
                    reinforcement.verify(path, root / "output")

    def test_resealed_raw_score_and_wrong_game_identity_are_rejected(self):
        board = "BB......" + "." * 48 + ".......W"
        self.assertFalse(reinforcement.legal_moves(board, "B"))
        self.assertFalse(reinforcement.legal_moves(board, "W"))
        game = reinforcement.play("self-play", 0, 0, board, "B", [], 0,
                                  {"baseline": mock.Mock()}, {"B": "baseline", "W": "baseline"}, [1])
        self.assertEqual(game, training.read_json(TOOL / "fixtures/winner-empty-reinforcement-game-v4.json"))
        self.assertEqual(game["disc_counts"], {"B": 2, "W": 1})
        self.assertEqual(game["final_score_black"], 62)
        reinforcement.replay(game)
        for field, value in (("final_score_black", 1), ("score_contract", "raw"), ("schema_version", 3)):
            bad = copy.deepcopy(game)
            bad[field] = value
            bad["game_digest"] = training.digest({k: v for k, v in bad.items() if k != "game_digest"})
            with self.assertRaises(training.TrainingError):
                reinforcement.replay(bad)
        old = copy.deepcopy(game)
        old.pop("schema_version")
        old.pop("score_contract")
        old["final_score_black"] = 1
        old["game_digest"] = training.digest({k: v for k, v in old.items() if k != "game_digest"})
        with producer("reinforcement") as frozen:
            frozen.replay(old)

    def test_frozen_digest_mismatch_without_imported_training_fails_clearly(self):
        original = Path.read_bytes
        def changed(path):
            data = original(path)
            return data + b"# tamper" if path.parent.name == "legacy_offline" and path.name == "training.py" else data
        with mock.patch.dict(sys.modules):
            sys.modules.pop("training", None)
            with mock.patch.object(Path, "read_bytes", changed):
                with self.assertRaisesRegex(ValueError, "frozen legacy source digest mismatch"):
                    with producer("training"):
                        self.fail("corrupted source loaded")

    def test_saved_artifact_and_report_are_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
            root = Path(temporary)
            training.run(TOOL / "fixtures/tiny-winner-empty-manifest.json", root / "artifact", root / "report")
            self.assertEqual((root / "artifact").read_bytes(), (TOOL / "fixtures/tiny-winner-empty-artifact.json").read_bytes())
            self.assertEqual((root / "report").read_bytes(), (TOOL / "fixtures/tiny-winner-empty-report.json").read_bytes())

    def test_random_legacy_source_pins_and_raw_outputs_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
            root = Path(temporary)
            manifest_path = root / "old-manifest.json"
            with producer("random_inputs") as frozen:
                frozen.prepare(manifest_path, 20260926, {"train": 4, "validation": 2, "held_out": 2}, 8, 128, require_clean=False)
                frozen.generate(manifest_path, root / "output", 1000)
            before = {p.name: p.read_bytes() for p in (root / "output").iterdir()}
            random_inputs.verify(manifest_path, root / "output", 1000, legacy_offline=True)
            random_inputs.verify(manifest_path, root / "output", 1000, legacy_offline=True, legacy_source_dir=TOOL / "legacy_offline")
            with self.assertRaisesRegex(training.TrainingError, "requires --legacy-offline"):
                random_inputs.verify(manifest_path, root / "output", legacy_source_dir=TOOL / "legacy_offline")
            with self.assertRaisesRegex(training.TrainingError, "source digest mismatch"):
                random_inputs.verify(manifest_path, root / "output", legacy_offline=True, legacy_source_dir=TOOL)
            self.assertEqual(before, {p.name: p.read_bytes() for p in (root / "output").iterdir()})
            training.validate_input_manifest(root / "output/trainer-manifest.json", legacy_offline=True)
            with self.assertRaises(training.TrainingError):
                training.validate_input_manifest(root / "output/trainer-manifest.json")
            with self.assertRaises(training.TrainingError):
                random_inputs.generate(manifest_path, root / "new")
            report_path = root / "output/report.json"
            original = report_path.read_bytes()
            report = training.read_json(report_path)
            report["metadata"] = {"score_contract": training.SCORE_CONTRACT}
            report_path.write_bytes(training.canonical_json(report) + b"\n")
            with self.assertRaisesRegex(training.TrainingError, "original score identity"):
                random_inputs.verify(manifest_path, root / "output", legacy_offline=True)
            report_path.write_bytes(original)
            games_path = root / "output/games.jsonl"
            original = games_path.read_bytes()
            games = training.read_jsonl(games_path)
            games[0]["schema_version"] = 2
            games[0]["game_digest"] = training.digest({k: v for k, v in games[0].items() if k != "game_digest"})
            games_path.write_bytes(b"".join(training.canonical_json(game) + b"\n" for game in games))
            with self.assertRaisesRegex(training.TrainingError, "original schema"):
                random_inputs.verify(manifest_path, root / "output", legacy_offline=True)
            games_path.write_bytes(original)
            manifest = training.read_json(manifest_path)
            manifest["generator_sha256"] = training.sha256_file(Path(random_inputs.__file__))
            manifest_path.write_bytes(training.canonical_json(manifest) + b"\n")
            with self.assertRaisesRegex(training.TrainingError, "generator source digest mismatch"):
                random_inputs.verify(manifest_path, root / "output", 1000, legacy_offline=True)

    def test_resealed_legacy_record_and_nested_artifact_contract_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
            root = Path(temporary)
            with producer("training") as frozen:
                frozen.run(TOOL / "fixtures/tiny-manifest.json", root / "artifact.json", root / "report.json")
            artifact = training.read_json(root / "artifact.json")
            artifact["provenance"]["score_contract"] = training.SCORE_CONTRACT
            artifact["artifact_digest"] = training.digest({k: v for k, v in artifact.items() if k != "artifact_digest"})
            with self.assertRaisesRegex(training.TrainingError, "original score identity"):
                training.validate_artifact(artifact, legacy_offline=True)
            manifest = training.read_json(TOOL / "fixtures/tiny-manifest.json")
            rows = training.read_jsonl(TOOL / "fixtures/tiny.jsonl")
            rows[0]["score_contract"] = training.SCORE_CONTRACT
            (root / "tiny.jsonl").write_bytes(b"".join(training.canonical_json(row) + b"\n" for row in rows))
            manifest["inputs"][0]["sha256"] = training.sha256_file(root / "tiny.jsonl")
            (root / "manifest.json").write_bytes(training.canonical_json(manifest) + b"\n")
            with self.assertRaisesRegex(training.TrainingError, "original score identity"):
                training.validate_input_manifest(root / "manifest.json", legacy_offline=True)
