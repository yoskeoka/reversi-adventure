"""Process-free fixtures for the 0058 training and independent evaluation paths."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_table32_cycle as fixture
import test_table32_labels as label_fixture
import start_table32
import table32
import table32_combine as combine
import table32_data as data
import table32_extract as extract
import table32_inputs as inputs
import table32_model as model
import table32_players as players
import table32_store as st
import table32_verify as verify
import training


class DataPolicyTests(unittest.TestCase):
    def test_split_defaults_and_independent_overrides(self):
        def settings_for(*extra):
            args = ["prepare", "--run-root", "/tmp/fixture", "--candidate-executable",
                    "/tmp/cli", "--candidate-source-commit", "d" * 40, *extra]
            with mock.patch.object(table32, "prepare", side_effect=table32.settings) as prepare, \
                 contextlib.redirect_stdout(io.StringIO()):
                table32.main(args)
            return table32.settings(prepare.call_args.args[0])

        legacy = settings_for()
        self.assertEqual([legacy[f"{s}_per_prefix"] for s in data.SPLITS], [12, 2, 2])
        strict = settings_for("--data-0058", "--phase-start", "10", "--phase-end", "19",
                              "--generation-prefix", "10", "--train-per-prefix", "16",
                              "--test-per-prefix", "48", "--minimum-test-rows", "33")
        self.assertEqual([strict[f"{s}_per_prefix"] for s in data.SPLITS], [16, 32, 48])
        self.assertEqual(strict["data_0058"]["minimum_rows"],
                         {"train": 16, "validation": 32, "test": 33})
        with self.assertRaisesRegex(training.TrainingError, "require both fixed corpus and label"):
            settings_for("--data-0058", "--phase-start", "0", "--phase-end", "0")

    def test_phase_zero_learns_fixed_score_and_replays(self):
        fixture_case = fixture.Table32CycleTests()
        fixture_case.setUpClass()
        manifest, snapshot = fixture_case.fixture()
        manifest.update(generation_plan=[], fixed_openings={"fixture": True})
        manifest["settings"].update(target_phases=[0], training_only=True,
            data_0058={"minimum_rows": dict.fromkeys(data.SPLITS, 1)})
        start = fixture.rf.INITIAL
        record = {name: f"{sum(1 << i for i, square in enumerate(start) if square == side):016x}"
                  for name, side in (("black", "B"), ("white", "W"))}
        row = data.labeled_row({**record, "id": "p00-000000", "phase": 0, "turn": "black", "score": 8})
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()), \
             mock.patch.object(data, "fixed_rows", side_effect=lambda _: iter([row])), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("unexpected engine")):
            root = Path(temporary)
            providers = fixture.Providers()
            report = fixture_case.execute_fixture(root, manifest, snapshot, providers)
            self.assertEqual(report["outcome"], "training-complete")
            self.assertEqual(report["coverage"]["validation_unavailable"], [0])
            self.assertEqual(report["coverage"]["test_unavailable"], [0])
            self.assertEqual(report["test_once_after_candidate_freeze"]["0"]["mse"], None)
            self.assertEqual(providers.calls, [])
            self.assertEqual(providers.queries, [])
            artifact = st.read(root / "candidate-artifact.json")
            self.assertEqual(artifact["provenance"]["source_kind"], data.FIXED_SOURCE)
            self.assertTrue(artifact["weights"]["0"])
            self.assertEqual(report["phases"][0]["integer_train"]["mse"],
                             (8 - model.predict_partial(artifact, start, "B", lambda *_: 0)) ** 2)
            self.assertEqual(verify.verify(root, manifest=manifest, snapshot=snapshot), report)
        with tempfile.TemporaryDirectory() as temporary:
            result = extract.build([], [], [], temporary, early_limit=0, target_phases=[0],
                                   fixed_rows=[row], coverage_minima=dict.fromkeys(data.SPLITS, 1),
                                   reserved_keys=[row["canonical_key"]])
            self.assertEqual(result["status"], "training-phase-unavailable")
            self.assertEqual(result["reserved_phase_rows"]["train"]["0"], 1)

    def test_cli_prepares_and_runs_phase_zero_from_validated_batches(self):
        labels = label_fixture.LabelTests()
        labels.setUp()
        self.addCleanup(labels.doCleanups)
        labels.prepare()
        labels.cli("run", "--phase-end", "0")
        candidate = labels.root / "candidate"
        candidate.write_text("#!/bin/sh\n[ \"$1\" = --help ] || exit 2\n"
                             "echo 'trained-table32-partial --fallback-artifact'\n")
        candidate.chmod(0o755)
        run_root = labels.root / "training"
        common = ["--run-root", str(run_root)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
             mock.patch.object(table32, "clean_commit", return_value="d" * 40):
            self.assertEqual(start_table32.main(["prepare", *common, "--data-0058",
                "--candidate-executable", str(candidate), "--candidate-source-commit", "e" * 40,
                "--phase-start", "0", "--phase-end", "0", "--fixed-opening-corpus", str(labels.corpus_root),
                "--fixed-opening-labels", str(labels.label_root), "--max-steps", "1", "--max-proposals", "1"]), 0)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
             mock.patch.object(table32, "clean_commit", side_effect=AssertionError("HEAD checked on resume")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("unexpected engine search")):
            self.assertEqual(start_table32.main(["resume", *common, "--attempt-wall-seconds", "30"]), 0)
            self.assertEqual(start_table32.main(["verify", *common]), 0)
        rows = extract.phase_rows(run_root / "extracted", "train", 0)
        self.assertEqual([(row["side"], row["target"], row["source_kind"]) for row in rows],
                         [("B", 3, data.FIXED_SOURCE)])
        self.assertTrue(st.read(run_root / "candidate-artifact.json")["weights"]["0"])

    def test_later_phase_shortage_after_game_and_position_exclusion(self):
        specs = inputs.generation_plan(train_per_prefix=2, validation_per_prefix=1,
                                       test_per_prefix=1, prefix_lengths=(10,))
        boards = [inputs.generation_opening(spec) for spec in specs[:2]]
        self.assertNotEqual(*(inputs.position_key(row["board"], row["side"]) for row in boards))
        # One different train row remains after removing the symmetric
        # train/validation collision and the duplicate test exposure.
        games = [{"spec": spec, "decisions": [boards[index]], "final_score_black": 4}
                 for spec, index in zip(specs, (0, 1, 0, 0))]
        with tempfile.TemporaryDirectory() as temporary:
            result = extract.build(games, [], specs, temporary, early_limit=0, target_phases=[10],
                                   trusted_import_count=len(games),
                                   coverage_minima=dict.fromkeys(data.SPLITS, 1))
        self.assertEqual(result["status"], "input-coverage-unavailable")
        self.assertEqual(result["reached_games"]["train"]["10"], 2)
        self.assertEqual(result["unique_phase_rows"]["train"]["10"], 2)
        self.assertEqual(result["phase_rows"]["train"]["10"], 1)
        self.assertEqual([entry["split"] for entry in result["coverage_shortages"]], ["validation", "test"])

    def test_reserved_prefix_turn_retries_with_same_seed(self):
        spec = inputs.generation_plan(prefix_lengths=(10,))[0]
        first = inputs.generation_opening(spec)
        turn = first["turns"][4]
        reserved = {inputs.position_key(turn["board"], turn["side"])}
        replacement = inputs.generation_opening(spec, reserved=reserved)
        self.assertGreater(replacement["candidate_index"], 0)
        self.assertEqual(replacement["rejected_candidates"][0]["reason"], "reserved-opening")
        self.assertFalse(inputs.intersects_reservation(replacement, reserved))
        self.assertEqual(inputs.generation_opening(spec, reserved=reserved), replacement)
        limits = {**inputs.TEACHER_SETTINGS, "data_0058": {"reserved_keys": sorted(reserved)}}
        provider = fixture.Providers()
        game = inputs.generate_game(spec, lambda *args: provider.choose("teacher", *args), limits=limits)
        self.assertEqual(game["opening"], replacement)
        self.assertTrue(inputs.replay_game(game, limits=limits))

    def test_all_three_opponents_replay_with_distinct_policies(self):
        provider = fixture.Providers()
        for opponent in ("s0", "strategic", "random"):
            with self.subTest(opponent=opponent), tempfile.TemporaryDirectory() as temporary, \
                 contextlib.redirect_stderr(io.StringIO()):
                root = Path(temporary)
                manifest = {"version": combine.VERSION, "producer_commit": "a" * 40, "seed": 9,
                            "coverage": "partial", "phases": [40], "input_kind": "fixture",
                            "settings": {"time_limit_ms": None, "node_limit": None,
                                         "decision_timeout_seconds": None},
                            "limits": st.LIMITS, "exposure_digest": st.digest([]), "source_runs": [],
                            "comparison": {"opponent": opponent, "pairs": 1, "depth": 3,
                                           "exact_empty": 0, "reserved_keys": []}}
                artifact = combine.candidate(manifest, {40: {}})
                st.atomic(root / "candidate-artifact.json", artifact)
                provider.calls.clear()
                driver = table32.Driver(root, manifest, execute=True, providers=(provider.choose, provider.solve))
                report = combine.evaluate(driver, artifact, set())
                driver.finish()
                self.assertEqual((report["outcome"], report["games"]), ("comparison-complete", 2))
                self.assertEqual(report["match_profile"]["opponent"], opponent)
                self.assertEqual(report["match_profile"]["opening_depth"], 3)
                expected_calls = {"s0": {"candidate", "baseline"}, "strategic": {"candidate", "strategic"},
                                  "random": {"candidate"}}
                self.assertEqual({kind for kind, _ in provider.calls}, expected_calls[opponent])
                replay = table32.Driver(root, manifest, execute=False)
                self.assertEqual(combine.evaluate(replay, artifact, set()), report)
                replay.finish()
        argv = players.player_argv("/fixture/cli", None, inputs.TEACHER_SETTINGS, "strategic")
        self.assertEqual(argv[:3], ["/fixture/cli", "--evaluator", "strategic"])
        self.assertNotIn("--trained-artifact", argv)


if __name__ == "__main__":
    unittest.main()
