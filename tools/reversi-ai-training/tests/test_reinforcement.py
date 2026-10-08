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

    def prepare_fixture(self, root: Path, seed: int = 7, self_play_args: list[str] | None = None) -> Path:
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
                "--node-limit", "1000", "--decision-timeout-seconds", "5", "--max-decisions", "10000"]
        self.assertEqual(reinforcement.main(argv + (self_play_args or [])), 0)
        return manifest

    def test_manifest_freezes_turn_policy_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.prepare_fixture(root)
            manifest = training.read_json(path)
            self.assertEqual(manifest["schema_version"], 5)
            self.assertEqual(manifest["exact_cache_policy"], {
                "policy": reinforcement.EXACT_CACHE_POLICY, "effective_scope": "turn",
                "binary_sha256": reinforcement.sha(root / "candidate")})
            with mock.patch.object(reinforcement.subprocess, "Popen") as popen:
                reinforcement.Candidate(root / "candidate", root / "baseline.json",
                                        manifest["self_play_search"], 5)
            argv = popen.call_args.args[0]
            self.assertEqual(argv[argv.index("--exact-cache-scope") + 1], "turn")
            manifest["exact_cache_policy"]["effective_scope"] = "game"
            path.write_bytes(training.canonical_json(manifest) + b"\n")
            with self.assertRaisesRegex(training.TrainingError, "safety policy"):
                reinforcement.validate_manifest(path, for_execution=True)

    def test_historical_manifest_only_allows_offline_completed_verification(self):
        for version in (3, 4):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = self.prepare_fixture(root)
                manifest = training.read_json(path)
                manifest["schema_version"] = version
                if version == 3:
                    manifest.pop("exact_cache_policy")
                path.write_bytes(training.canonical_json(manifest) + b"\n")
                with mock.patch.object(reinforcement, "Candidate") as candidate:
                    for operation in (lambda: reinforcement.run(path, root / "rejected"),
                                      lambda: reinforcement.regret_command(path, root / "historical"),
                                      lambda: reinforcement.regret_timeout(path, root / "historical")):
                        with self.assertRaisesRegex(training.TrainingError, "historical reinforcement manifest"):
                            operation()
                    candidate.assert_not_called()
                # Recreate completed output with the historical producer contract.
                validate = reinforcement.validate_manifest
                with mock.patch.object(reinforcement, "validate_manifest",
                                       side_effect=lambda path, **kwargs: validate(path)):
                    reinforcement.run(path, root / "historical")
                with mock.patch.object(reinforcement, "Candidate", side_effect=AssertionError("offline started CLI")):
                    reinforcement.verify(path, root / "historical")
                report = training.read_json(root / "historical" / "report.json")
                self.assertEqual(report["schema_version"], 3)
                self.assertNotIn("exact_cache_policy", report)
                manifest["self_play_search"]["midgame_depth"] = 7
                path.write_bytes(training.canonical_json(manifest) + b"\n")
                with self.assertRaisesRegex(training.TrainingError, "12/8/12 or 12/12/12"):
                    reinforcement.validate_manifest(path)

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
            self.assertEqual(report["self_play_game_count"], 2)
            self.assertEqual(report["self_play_search"]["midgame_depth"], 12)
            self.assertEqual(report["candidate_executable_sha256"],
                             reinforcement.sha(root / "candidate"))
            self.assertEqual(report["match"]["games"], 50)
            self.assertFalse(report["continued"])
            self.assertGreater(report["decisions"], 0)
            self.assertEqual(report["validation_position_keys"],
                             [training.canonical_position_key(reinforcement.INITIAL, "B")])
            selected = json.loads(outputs[0]["selected-artifact.json"])
            training.validate_artifact(selected)
            command = reinforcement.regret_command(manifest, root / "first")
            self.assertIn("--trained-artifact", command)
            self.assertIn("--exact-solver-empty-squares 16", command)
            self.assertIn("--exact-cache-scope turn", command)
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
            for stage in ("self-play", "replay-tuning-extraction", "validation", "artifact-update", "metrics", "candidate-match", "report-serialization", "atomic-output-publication"):
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

    def test_update_bounds_and_match_threshold_selects(self):
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
            self.assertEqual(reinforcement.selected_from_match({"match_points": 100}, True), "baseline")
            self.assertEqual(reinforcement.selected_from_match({"match_points": 100.5}, True), "candidate")

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

    def test_version_one_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.prepare_fixture(root)
            manifest = training.read_json(manifest_path)
            manifest["schema_version"] = 1
            manifest_path.write_bytes(training.canonical_json(manifest) + b"\n")
            with self.assertRaisesRegex(training.TrainingError, "unsupported reinforcement manifest"):
                reinforcement.validate_manifest(manifest_path)

    def test_old_version_two_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.prepare_fixture(root)
            manifest = training.read_json(manifest_path)
            manifest.pop("self_play_search")
            manifest["producer_version"] = "reversi-ai-pattern-reinforcement-v2"
            manifest_path.write_bytes(training.canonical_json(manifest) + b"\n")
            with self.assertRaises(training.TrainingError):
                reinforcement.validate_manifest(manifest_path)

    def test_self_play_midgame_depth_is_frozen_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.prepare_fixture(root)
            manifest = training.read_json(manifest_path)
            manifest["self_play_search"]["midgame_depth"] = 8
            manifest_path.write_bytes(training.canonical_json(manifest) + b"\n")
            reinforcement.validate_manifest(manifest_path)
            self.assertEqual(manifest["candidate"]["midgame_depth"], 12)
            output = root / "depth-eight-output"
            reinforcement.run(manifest_path, output, progress_every=1000)
            reinforcement.verify(manifest_path, output)
            self.assertEqual(training.read_json(output / "report.json")["self_play_search"]["midgame_depth"], 8)

    def test_independent_self_play_arguments_and_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.prepare_fixture(root, self_play_args=[
                "--self-play-opening-depth", "18", "--self-play-midgame-depth", "22",
                "--self-play-endgame-depth", "24", "--self-play-exact-solver-empty-squares", "24"])
            manifest = training.read_json(path)
            config = manifest["self_play_search"]
            self.assertEqual([config[key] for key in ("opening_depth", "midgame_depth", "endgame_depth", "exact_solver_empty_squares")], [18, 22, 24, 24])
            self.assertEqual([manifest["candidate"][key] for key in ("opening_depth", "midgame_depth", "endgame_depth", "exact_solver_empty_squares")], [12, 12, 12, 16])
            with mock.patch.object(reinforcement.subprocess, "Popen") as popen:
                reinforcement.Candidate(root / "candidate", root / "baseline.json", config, 5)
            argv = popen.call_args.args[0]
            for option, value in (("opening-depth", 18), ("midgame-depth", 22), ("endgame-depth", 24), ("exact-solver-empty-squares", 24)):
                self.assertEqual(argv[argv.index("--" + option) + 1], str(value))
            output = root / "flexible"
            reinforcement.run(path, output, progress_every=1000)
            reinforcement.verify(path, output)
            report = training.read_json(output / "report.json")
            self.assertEqual(report["self_play_search"], config)
            self.assertEqual(report["exact_cache_policy"], manifest["exact_cache_policy"])
            report_path = output / "report.json"
            original_report = report_path.read_bytes()
            report["exact_cache_policy"]["effective_scope"] = "game"
            report["report_digest"] = training.digest({key: value for key, value in report.items() if key != "report_digest"})
            report_path.write_bytes(training.canonical_json(report) + b"\n")
            with self.assertRaisesRegex(training.TrainingError, "report metadata"):
                reinforcement.verify(path, output)
            report_path.write_bytes(original_report)
            command = reinforcement.regret_command(path, output)
            self.assertIn("--opening-depth 12", command)
            self.assertIn("--exact-solver-empty-squares 16", command)
            manifest["self_play_search"]["exact_solver_empty_squares"] = 22
            path.write_bytes(training.canonical_json(manifest) + b"\n")
            with self.assertRaises(training.TrainingError):
                reinforcement.verify(path, output)

    def test_schema_five_self_play_ranges(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.prepare_fixture(root)
            original = training.read_json(path)
            for key in ("opening_depth", "midgame_depth", "endgame_depth", "exact_solver_empty_squares"):
                incomplete = json.loads(json.dumps(original))
                incomplete["self_play_search"].pop(key)
                path.write_bytes(training.canonical_json(incomplete) + b"\n")
                with self.assertRaisesRegex(training.TrainingError, "self_play_search must contain exactly"):
                    reinforcement.validate_manifest(path)
                accepted = (0, 16, 18, 20, 22, 24, 30) if key == "exact_solver_empty_squares" else (1, 8, 18, 22, 24, 64)
                rejected = (-1, 31, 2**32, True) if key == "exact_solver_empty_squares" else (-1, 0, 65, 256, True)
                for value in accepted + rejected:
                    with self.subTest(key=key, value=value):
                        manifest = json.loads(json.dumps(original))
                        manifest["self_play_search"][key] = value
                        path.write_bytes(training.canonical_json(manifest) + b"\n")
                        if value in accepted and type(value) is int:
                            reinforcement.validate_manifest(path)
                        else:
                            with self.assertRaises(training.TrainingError):
                                reinforcement.validate_manifest(path)

    def test_failed_self_play_decision_does_not_publish_teacher_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.prepare_fixture(root, self_play_args=["--self-play-exact-solver-empty-squares", "24"])
            output = root / "failed-decision"
            with mock.patch.object(reinforcement.Candidate, "choose", side_effect=training.TrainingError("candidate timed out at fixture")):
                with self.assertRaisesRegex(training.TrainingError, "timed out"):
                    reinforcement.run(path, output)
            self.assertFalse((output / "games.jsonl").exists())
            self.assertFalse((output / "candidate-artifact.json").exists())
            self.assertFalse((output / "report.json").exists())

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

    def test_validation_overlap_is_excluded_from_mse(self):
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
            output = root / "out"
            reinforcement.run(manifest, output)
            report = training.read_json(output / "report.json")
            self.assertEqual(report["validation"]["remaining_records"], 0)
            self.assertEqual(report["validation"]["baseline"]["status"], "unavailable")

    def test_artifact_provenance_accepts_legacy_and_game_reset_producers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare_fixture(root)
            original = training.read_json(root / "baseline.json")
            for version in (training.REINFORCEMENT_V1_VERSION, training.REINFORCEMENT_VERSION,
                            reinforcement.VERSION):
                artifact = json.loads(json.dumps(original))
                artifact["provenance"]["trainer_version"] = version
                artifact["provenance"]["optimizer"]["name"] = "bounded_td_v1"
                artifact.pop("artifact_digest")
                artifact["artifact_digest"] = training.digest(artifact)
                training.validate_artifact(artifact)

    def test_reset_contract_binary_and_old_manifest_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.prepare_fixture(root)
            original = training.read_json(manifest_path)
            for contract in (None, {"protocol": "new_game-v1", "cache_lifetime": "process", "binary_sha256": original["candidate"]["sha256"]},
                             {"protocol": "new_game-v1", "cache_lifetime": "one-game", "binary_sha256": "0" * 64}):
                manifest = json.loads(json.dumps(original))
                if contract is None:
                    manifest.pop("reset_contract")
                else:
                    manifest["reset_contract"] = contract
                manifest_path.write_bytes(training.canonical_json(manifest) + b"\n")
                with self.assertRaises(training.TrainingError):
                    reinforcement.validate_manifest(manifest_path)

    def test_play_resets_both_players_before_any_decision(self):
        events = []
        class Player:
            def __init__(self, name):
                self.name = name
            def new_game(self, identifier):
                events.append(("reset", self.name, identifier))
            def choose(self, identifier, board, side):
                self.assert_resets()
                return reinforcement.legal_moves(board, side)[0]
            def assert_resets(self):
                if {event[1] for event in events} != {"baseline", "candidate"}:
                    raise AssertionError("move precedes both acknowledgements")
        game = reinforcement.play("candidate-match", 0, 0, reinforcement.INITIAL, "B", [], 0,
                                  {name: Player(name) for name in ("baseline", "candidate")},
                                  {"B": "baseline", "W": "candidate"}, [120])
        self.assertEqual(len(events), 2)
        reinforcement.replay(game)
        game["reset_events"].pop()
        game["game_digest"] = training.digest({key: value for key, value in game.items() if key != "game_digest"})
        with self.assertRaisesRegex(training.TrainingError, "reset evidence"):
            reinforcement.replay(game)

    def test_interrupted_prepare_closes_candidate_removes_manifest_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            close_candidate = reinforcement.Candidate.close
            with mock.patch.object(reinforcement.Candidate, "new_game", side_effect=KeyboardInterrupt), \
                 mock.patch.object(reinforcement.Candidate, "close", autospec=True,
                                   side_effect=close_candidate) as close:
                with self.assertRaises(KeyboardInterrupt):
                    self.prepare_fixture(root)
            close.assert_called_once()
            self.assertIsNotNone(close.call_args.args[0].process.returncode)
            self.assertFalse((root / "manifest.json").exists())
            manifest = self.prepare_fixture(root)
            reinforcement.validate_manifest(manifest)

    def test_candidate_rejects_missing_reset_acknowledgement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "old-cli"
            executable.write_text("#!/usr/bin/env python3\nimport sys\nfor line in sys.stdin:\n print('new_game\\twrong\\tready', flush=True)\n")
            executable.chmod(0o755)
            candidate = reinforcement.Candidate(executable, root / "unused", {
                "opening_depth": 1, "midgame_depth": 1, "endgame_depth": 1,
                "exact_solver_empty_squares": 0, "time_limit_ms": 1, "node_limit": 100}, 1)
            try:
                with self.assertRaisesRegex(training.TrainingError, "reset acknowledgement"):
                    candidate.new_game("game")
            finally:
                candidate.close()

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
