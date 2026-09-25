import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("reinforcement", ROOT / "reinforcement.py")
assert SPEC and SPEC.loader
import sys
sys.path.insert(0, str(ROOT))
reinforcement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reinforcement)
import training


class ReinforcementTests(unittest.TestCase):
    def setUp(self):
        original_run = reinforcement.subprocess.run
        def clean_status(command, **kwargs):
            if command == ["git", "status", "--porcelain"]:
                return mock.Mock(stdout="")
            return original_run(command, **kwargs)
        patcher = mock.patch.object(reinforcement.subprocess, "run", side_effect=clean_status)
        patcher.start()
        self.addCleanup(patcher.stop)

    def prepare_fixture(self, root: Path, seed: int = 7) -> Path:
        baseline = root / "baseline.json"
        training.run(ROOT / "fixtures" / "tiny-manifest.json", baseline, root / "baseline-report.json")
        executable = root / "candidate"
        fixture = ROOT / "fixtures" / "fake-self-play-v1.py"
        executable.write_text(f"#!/usr/bin/env python3\nimport runpy\nrunpy.run_path({str(fixture)!r}, run_name='__main__')\n")
        executable.chmod(0o755)
        manifest = root / "manifest.json"
        argv = ["prepare", "--manifest", str(manifest), "--baseline-artifact", str(baseline),
                "--candidate-executable", str(executable), "--validation-input",
                str(ROOT / "fixtures" / "reinforcement-validation-v1.jsonl"),
                "--validation-source", "project-owned-reinforcement-fixture-v1",
                "--seed", str(seed), "--game-count", "2", "--opening-plies", "2",
                "--opening-depth", "1", "--midgame-depth", "1", "--endgame-depth", "1",
                "--exact-solver-empty-squares", "12", "--time-limit-ms", "1000",
                "--node-limit", "1000", "--decision-timeout-seconds", "5", "--max-decisions", "120"]
        self.assertEqual(reinforcement.main(argv), 0)
        return manifest

    def test_fixture_is_reproducible_and_replays(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_fixture(root)
            outputs = []
            for name in ("first", "second"):
                directory = root / name
                reinforcement.run(manifest, directory)
                reinforcement.verify(manifest, directory)
                outputs.append({item: (directory / item).read_bytes() for item in reinforcement.OUTPUTS})
            self.assertEqual(outputs[0], outputs[1])
            report = json.loads(outputs[0]["report.json"])
            self.assertEqual(report["game_count"], 2)
            self.assertEqual(report["pair_count"], 1)
            self.assertGreater(report["decisions"], 0)
            selected = json.loads(outputs[0]["selected-artifact.json"])
            training.validate_artifact(selected)
            command = reinforcement.regret_command(manifest, root / "first")
            self.assertIn("--trained-artifact", command)
            self.assertIn("--exact-solver-empty-squares 12", command)

    def test_seed_and_pair_generation(self):
        self.assertEqual(reinforcement.openings(11, 4, 3), reinforcement.openings(11, 4, 3))
        self.assertNotEqual(reinforcement.openings(11, 4, 3), reinforcement.openings(12, 4, 3))
        board, side, _, rotation = reinforcement.openings(11, 2, 3)[0]
        paired, paired_side = reinforcement.rotated_pair(board, side, rotation)
        self.assertEqual(paired_side, reinforcement.other(side))
        self.assertEqual(paired.count("B"), board.count("W"))
        self.assertEqual(paired.count("W"), board.count("B"))

    def test_update_bounds_and_tie_selects_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.prepare_fixture(root)
            manifest = training.read_json(manifest_path)
            baseline = training.read_json(root / "baseline.json")
            board = reinforcement.INITIAL
            tuning = [{"board": board, "side": "B", "target": 64}] * 100
            artifact = reinforcement.updated_artifact(baseline, tuning, manifest)
            training.validate_artifact(artifact)
            self.assertTrue(all(abs(value) <= 1 for tables in artifact["weights"].values() for table in tables for value in table.values()))
            self.assertEqual(reinforcement.mse(baseline, [{"board": board, "side": "B", "target": 0}])["sum_squared_error"], 0)
            self.assertIs(reinforcement.select_artifact(baseline, artifact,
                          {"sum_squared_error": 5}, {"sum_squared_error": 5}), baseline)
            self.assertIs(reinforcement.select_artifact(baseline, artifact,
                          {"sum_squared_error": 5}, {"sum_squared_error": 4}), artifact)

    def test_partial_and_corrupt_output_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_fixture(root)
            directory = root / "output"
            directory.mkdir()
            with self.assertRaises(training.TrainingError):
                reinforcement.verify(manifest, directory)
            reinforcement.run(manifest, directory)
            games = directory / "games.jsonl"
            games.write_bytes(games.read_bytes()[:-2])
            with self.assertRaises(training.TrainingError):
                reinforcement.verify(manifest, directory)

    def test_changed_producer_digest_fails_before_cycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.prepare_fixture(root)
            manifest = training.read_json(manifest_path)
            manifest["producer_sources"]["reinforcement.py"] = "0" * 64
            manifest_path.write_bytes(training.canonical_json(manifest) + b"\n")
            with self.assertRaisesRegex(training.TrainingError, "producer source digest mismatch"):
                reinforcement.cycle(manifest_path)

    def test_validation_split_leakage_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_fixture(root)
            board, side, _, _ = reinforcement.openings(7, 2, 2)[0]
            record = {"schema_version": 1, "record_id": "leak", "split": "validation", "board": board,
                      "source": "test-v1", "license": "CC0-1.0", "source_digest": "test-v1",
                      "side": side, "target": {"semantics": training.TARGET_SEMANTICS, "value": 0}}
            validation = root / "leak.jsonl"
            validation.write_bytes(training.canonical_json(record) + b"\n")
            data = training.read_json(manifest)
            data["validation"] = {"path": str(validation), "sha256": reinforcement.sha(validation), "source": "test-v1"}
            manifest.write_bytes(training.canonical_json(data) + b"\n")
            with self.assertRaises(training.TrainingError):
                reinforcement.cycle(manifest)

    def test_partial_candidate_line_obeys_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "partial"
            executable.write_text("#!/usr/bin/env python3\nimport sys,time\n"
                                  "for line in sys.stdin:\n sys.stdout.write('id\\t')\n sys.stdout.flush()\n time.sleep(30)\n")
            executable.chmod(0o755)
            candidate = reinforcement.Candidate(executable, root / "unused.json",
                      {"opening_depth": 1, "midgame_depth": 1, "endgame_depth": 1,
                       "exact_solver_empty_squares": 12, "time_limit_ms": 1000, "node_limit": 1}, 1)
            try:
                with self.assertRaisesRegex(training.TrainingError, "timed out"):
                    candidate.choose("id", reinforcement.INITIAL, "B")
            finally:
                candidate.close()


if __name__ == "__main__":
    unittest.main()
