import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stderr

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
                "--opening-depth", "12", "--midgame-depth", "12", "--endgame-depth", "12",
                "--exact-solver-empty-squares", "16", "--time-limit-ms", "1000",
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
            self.assertEqual(report["validation_position_keys"],
                             [training.canonical_position_key(reinforcement.INITIAL, "B")])
            selected = json.loads(outputs[0]["selected-artifact.json"])
            training.validate_artifact(selected)
            command = reinforcement.regret_command(manifest, root / "first")
            self.assertIn("--trained-artifact", command)
            self.assertIn("--exact-solver-empty-squares 16", command)
            self.assertEqual(reinforcement.regret_timeout(manifest, root / "first"), 5)

    def test_progress_interval_stages_and_output_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_fixture(root)
            default_log, limited_log = io.StringIO(), io.StringIO()
            with redirect_stderr(default_log):
                reinforcement.run(manifest, root / "default")
            with redirect_stderr(limited_log):
                reinforcement.run(manifest, root / "limited", progress_every=2)
            default_lines = [line for line in default_log.getvalue().splitlines() if line.startswith("progress self-play")]
            limited_lines = [line for line in limited_log.getvalue().splitlines() if line.startswith("progress self-play")]
            self.assertEqual(["1/2" in line for line in default_lines], [True, False])
            self.assertEqual(len(limited_lines), 1)
            self.assertIn("2/2", limited_lines[0])
            for stage in ("self-play", "replay-tuning-extraction", "validation", "artifact-update", "metrics-selection", "report-serialization", "atomic-output-publication"):
                self.assertIn(f"stage {stage} start", default_log.getvalue())
                self.assertIn(f"stage {stage} done", default_log.getvalue())
            self.assertEqual({name: (root / "default" / name).read_bytes() for name in reinforcement.OUTPUTS},
                             {name: (root / "limited" / name).read_bytes() for name in reinforcement.OUTPUTS})

    def test_progress_interval_rejects_zero_and_failure_does_not_publish(self):
        with self.assertRaises(SystemExit):
            reinforcement.main(["run", "--manifest", "x", "--output-dir", "y", "--progress-every", "0"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare_fixture(root)
            with mock.patch.object(reinforcement, "updated_artifact", side_effect=training.TrainingError("stop")):
                with self.assertRaisesRegex(training.TrainingError, "stop"):
                    reinforcement.run(manifest, root / "failed")
            self.assertFalse((root / "failed" / "report.json").exists())

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

    def test_profile_and_timeout_are_frozen_and_consistent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.prepare_fixture(root)
            original = training.read_json(manifest_path)
            for change, error in ((lambda data: data["candidate"].update(opening_depth=11), "12/12/12"),
                                  (lambda data: data["candidate"].update(exact_solver_empty_squares=12), "threshold 16"),
                                  (lambda data: data.update(decision_timeout_seconds=1), "must exceed")):
                data = json.loads(json.dumps(original))
                change(data)
                manifest_path.write_bytes(training.canonical_json(data) + b"\n")
                with self.assertRaisesRegex(training.TrainingError, error):
                    reinforcement.validate_manifest(manifest_path)

    def test_validation_keys_are_verified_independently_of_source_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.prepare_fixture(root)
            manifest = training.read_json(manifest_path)
            manifest["validation"]["source"] = "0018-label-is-not-a-proof"
            validation = root / "validation.jsonl"
            record = training.read_jsonl(ROOT / "fixtures" / "reinforcement-validation-v1.jsonl")[0]
            record["source"] = manifest["validation"]["source"]
            validation.write_bytes(training.canonical_json(record) + b"\n")
            manifest["validation"]["path"] = str(validation)
            manifest["validation"]["sha256"] = reinforcement.sha(validation)
            manifest_path.write_bytes(training.canonical_json(manifest) + b"\n")
            directory = root / "out"
            reinforcement.run(manifest_path, directory)
            report_path = directory / "report.json"
            report = training.read_json(report_path)
            report["validation_position_keys"] = []
            report["report_digest"] = training.digest({key: value for key, value in report.items() if key != "report_digest"})
            report_path.write_bytes(training.canonical_json(report) + b"\n")
            with self.assertRaisesRegex(training.TrainingError, "report metadata"):
                reinforcement.verify(manifest_path, directory)

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
