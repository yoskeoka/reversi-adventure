"""Bounded fake-CLI tests of the pilot evidence contract, never strength runs."""

import argparse
import copy
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pilot
import random_inputs
import reinforcement as rf
import training
from types import SimpleNamespace


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        manifest = training.read_json(ROOT / "fixtures" / "tiny-winner-empty-manifest.json")
        manifest["inputs"][0]["path"] = str(ROOT / "fixtures" / "tiny-winner-empty.jsonl")
        self.baseline_manifest = self.root / "baseline-manifest.json"
        self.baseline_manifest.write_bytes(pilot.blob(manifest))
        self.baseline = self.root / "baseline.json"
        with redirect_stderr(io.StringIO()):
            training.run(self.baseline_manifest, self.baseline, self.root / "baseline-report.json")
        executable = self.root / "candidate"
        executable.write_text("#!/usr/bin/env python3\nimport runpy\n"
                              f"runpy.run_path({str(ROOT / 'fixtures' / 'fake-self-play-v1.py')!r}, run_name='__main__')\n")
        executable.chmod(0o755)
        generator = {"seed": 314, "max_turns": 128, "record_start_placements": 8,
                     "generator_sha256": "fixture-generator"}
        for game_id, split in ((1, "validation"), (2, "held_out")):
            _, rows, _ = random_inputs.play(game_id, split, generator)
            (self.root / (split + ".jsonl")).write_bytes(pilot.lines(rows))
        reserved = self.root / "reserved.json"
        reserved.write_bytes(pilot.blob({"schema_version": 1, "position_keys": [pilot.key(rf.INITIAL, "B")]}))
        oracle_root = ROOT.parent / "reversi-ai-oracle"
        self.args = argparse.Namespace(manifest=self.root / "pilot-manifest.json", baseline_artifact=self.baseline,
            baseline_manifest=self.baseline_manifest, candidate_executable=executable,
            validation_input=self.root / "validation.jsonl", held_out_input=self.root / "held_out.jsonl",
            reserved_openings=reserved, corpus=oracle_root / "winner-empty-v1-corpus.jsonl",
            golden=oracle_root / "winner-empty-v1-golden.jsonl", seed=17, opening_plies=8,
            input_kind="fixture", time_limit_ms=1, node_limit=100, decision_timeout_seconds=30)
        pilot.prepare(self.args)

    def complete(self, name="output"):
        output = self.root / name
        with redirect_stderr(io.StringIO()):
            pilot.run(self.args.manifest, output)
        return output

    def mutate_manifest(self, change):
        manifest = training.read_json(self.args.manifest)
        change(manifest)
        self.args.manifest.write_bytes(pilot.blob(manifest))

    def test_complete_run_is_deterministic_offline_and_tooling_only(self):
        first, second = self.complete("first"), self.complete("second")
        self.assertEqual({name: (first / name).read_bytes() for name in pilot.OUTPUTS},
                         {name: (second / name).read_bytes() for name in pilot.OUTPUTS})
        with mock.patch.object(rf, "Candidate", side_effect=AssertionError("verifier started CLI")), \
             mock.patch.object(pilot.oracle, "run_solve", side_effect=AssertionError("verifier started Oracle")), \
             redirect_stderr(io.StringIO()):
            report = pilot.verify(self.args.manifest, first)
        self.assertEqual(report["actual_counts"]["self_play_games"], 6)
        self.assertEqual(report["actual_counts"]["comparison_games"], 20)
        self.assertLessEqual(report["actual_counts"]["teacher_rows"], 768)
        self.assertEqual(report["match"]["match_points"], 10)
        self.assertTrue(report["tooling_only"])
        self.assertFalse(report["improvement_observed"])
        self.assertFalse(report["production_authorized"])
        training.validate_artifact(training.read_json(first / "candidate-artifact.json"))

    def test_all_games_replay_black_start_and_same_opening_seat_swaps(self):
        output = self.complete()
        games = training.read_jsonl(output / "games.jsonl")
        for game in games:
            self.assertEqual(pilot.replay_opening(game["opening"]), (game["start_board"], game["start_side"]))
            rf.replay(game)
        for pair in range(10):
            one, two = games[6 + pair * 2:8 + pair * 2]
            self.assertEqual(one["start_board"], two["start_board"])
            self.assertEqual(one["start_side"], two["start_side"])
            self.assertEqual(one["opening"], two["opening"])
            self.assertEqual(one["players"]["B"], two["players"]["W"])
            self.assertEqual(one["players"]["W"], two["players"]["B"])

    def test_relabelled_production_inputs_cannot_establish_strength(self):
        self.mutate_manifest(lambda m: m.update(input_kind="production"))
        # Even an otherwise fully checked context with strong-profile metadata
        # and renamed provenance cannot enable recognition in this release.
        context = pilot.load_manifest(self.args.manifest)
        self.assertTrue(context["tooling_only"])
        output = self.complete()
        context["tooling_only"] = False
        context["manifest"]["oracle_profile"]["name"] = "strong-engine-hcap-v1"
        for name in ("validation", "held_out"):
            context["manifest"]["inputs"][name]["provenance"]["source"] = "independent-production"
        rebuilt = pilot.reconstruct(context, training.read_jsonl(output / "games.jsonl"),
                                    training.read_jsonl(output / "corpus-decisions.jsonl"))
        import json
        report = json.loads(rebuilt["report.json"])
        self.assertTrue(report["tooling_only"])
        self.assertFalse(report["improvement_checks"]["strength_inputs"])
        self.assertFalse(report["improvement_observed"])
        self.assertFalse(report["production_authorized"])

    def bundle_stub(self, production=False):
        """Unit-test the pilot adapter; producer verification has separate tests."""
        path = self.root / "input-bundle.json"
        path.write_bytes(pilot.blob({"fixture": "adapter-only"}))
        original = training.read_json(self.args.manifest)
        verified = {"schema_version": 1, "bundle_sha256": training.sha256_file(path),
            "strength_inputs": production, "input_kind": "production" if production else "tooling",
            "tooling_only": not production,
            "inputs": {name: {field: original["inputs"][name][field] for field in ("path", "sha256")}
                       for name in ("baseline_artifact", "baseline_manifest", "validation", "held_out", "corpus", "golden")},
            "acceptance_reservation": {"state": "not-yet-selected", "artifact": None, "keys": []},
            "exposure_keys": {"train": [], "validation": [], "held_out": [], "oracle_root": [], "oracle_child": []},
            "cli": {"adapter_test": True}}
        verifier = mock.Mock(return_value=verified)
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(sys.modules, {"input_bundle": SimpleNamespace(verify_bundle=verifier)}).start()
        self.args.manifest.unlink()
        self.args.input_bundle = path
        self.args.reserved_openings = None
        pilot.prepare(self.args)
        return verified, verifier

    def test_bundle_schema_pins_verification_and_reconstructs_exposure_kinds(self):
        _, verifier = self.bundle_stub()
        output = self.complete()
        with mock.patch.object(rf, "Candidate", side_effect=AssertionError("offline CLI")), \
             mock.patch.object(pilot.oracle, "run_solve", side_effect=AssertionError("offline Oracle")), \
             redirect_stderr(io.StringIO()):
            report = pilot.verify(self.args.manifest, output)
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["acceptance_reservation"],
                         {"state": "not-yet-selected", "artifact": None, "keys": []})
        self.assertEqual(set(report["exposure_keys"]), {"opening", "decision", "terminal"})
        games = training.read_jsonl(output / "games.jsonl")
        self.assertIn(pilot.key(rf.INITIAL, "B"), report["exposure_keys"]["opening"])
        for game in games:
            self.assertIn(pilot.key(game["terminal_board"], "W"), report["exposure_keys"]["terminal"])
            for row in game["decisions"]:
                self.assertIn(pilot.key(row["board"], row["side"]), report["exposure_keys"]["decision"])
        self.assertTrue(report["tooling_only"])
        self.assertFalse(report["improvement_checks"]["strength_inputs"])
        self.assertGreaterEqual(verifier.call_count, 5)

    def test_bundle_gate_is_derived_again_not_taken_from_context(self):
        verified, verifier = self.bundle_stub(production=True)
        output = self.complete()
        context = pilot.load_manifest(self.args.manifest)
        context["tooling_only"] = True
        context["strength_inputs"] = False
        rebuilt = pilot.reconstruct(context, training.read_jsonl(output / "games.jsonl"),
                                    training.read_jsonl(output / "corpus-decisions.jsonl"))
        import json
        report = json.loads(rebuilt["report.json"])
        self.assertTrue(report["improvement_checks"]["strength_inputs"])
        self.assertFalse(report["tooling_only"])
        self.assertFalse(report["production_authorized"])
        verifier.return_value = {**verified, "strength_inputs": False, "tooling_only": True}
        context["strength_inputs"] = True
        with self.assertRaisesRegex(training.TrainingError, "verification differs"):
            pilot.reconstruct(context, training.read_jsonl(output / "games.jsonl"),
                              training.read_jsonl(output / "corpus-decisions.jsonl"))

    def test_bundle_split_and_binary_identity_are_pinned(self):
        verified, _ = self.bundle_stub()
        original = self.args.manifest.read_bytes()
        self.mutate_manifest(lambda manifest: manifest["inputs"]["validation"].update(
            path=verified["inputs"]["held_out"]["path"], sha256=verified["inputs"]["held_out"]["sha256"]))
        with self.assertRaisesRegex(training.TrainingError, "validation differs"):
            pilot.load_manifest(self.args.manifest)
        self.args.manifest.write_bytes(original)
        self.args.candidate_executable.write_text("changed binary")
        with self.assertRaisesRegex(training.TrainingError, "digest mismatch"):
            pilot.load_manifest(self.args.manifest)

    def test_real_small_bundle_integrates_and_resealed_verified_flag_is_rejected(self):
        import input_bundle
        from test_input_bundle import build_small_bundle
        directory = self.root / "real-bundle"
        directory.mkdir()
        with redirect_stderr(io.StringIO()):
            bundle_path, completion = build_small_bundle(directory)
        self.args.manifest.unlink()
        self.args.input_bundle = bundle_path
        self.args.candidate_executable = Path(completion["cli"]["binary"]["path"])
        self.args.reserved_openings = None
        with redirect_stderr(io.StringIO()):
            pilot.prepare(self.args)
            output = self.complete("real-bundle-pilot")
        original_popen = input_bundle.subprocess.Popen
        def offline_process(argv, *args, **kwargs):
            self.assertEqual(argv[0], "git", "offline verification started a runtime")
            return original_popen(argv, *args, **kwargs)
        with mock.patch.object(input_bundle.subprocess, "Popen", side_effect=offline_process), \
             mock.patch.object(rf, "Candidate", side_effect=AssertionError("offline CLI")), \
             redirect_stderr(io.StringIO()):
            report = pilot.verify(self.args.manifest, output)
        self.assertEqual(report["schema_version"], 2)
        self.assertTrue(report["tooling_only"])
        self.assertFalse(report["improvement_checks"]["strength_inputs"])
        self.assertFalse(report["production_authorized"])
        self.assertEqual(len(report["bundle_verification"]["exposure_keys"]["oracle_root"]), 12)
        forged_bundle = bundle_path.with_name("forged-bundle.json")
        input_bundle.save(forged_bundle, dict(completion, verified=True))
        self.mutate_manifest(lambda manifest: manifest["inputs"].update(input_bundle=pilot.entry(forged_bundle)))
        with self.assertRaisesRegex(training.TrainingError, "shape"), redirect_stderr(io.StringIO()):
            pilot.verify(self.args.manifest, output)

    def test_caps_source_search_and_optimizer_tampering_rejected(self):
        original = training.read_json(self.args.manifest)
        changes = [(lambda m: m["caps"].update(teacher_rows=769), "caps"),
                   (lambda m: m["caps"].update(self_play_games=6.0), "caps"),
                   (lambda m: m["denominators"].update(self_play_games=64.0), "caps"),
                   (lambda m: m["update_rule"].update(normalization_divisor=64.0), "update"),
                   (lambda m: m.update(update_count=True), "update"),
                   (lambda m: m["improvement_rule"].update(minimum_match_points=10.0), "improvement"),
                   (lambda m: m["self_play_search"].update(opening_depth=8.0), "profile"),
                   (lambda m: m["comparison_search"].update(exact_solver_empty_squares=16.0), "profile"),
                   (lambda m: m["denominators"].update(comparison_games=201), "caps"),
                   (lambda m: m["sources"].update({"pilot.py": "0" * 64}), "source digest"),
                   (lambda m: m["self_play_search"].update(exact_solver_empty_squares=20), "profile"),
                   (lambda m: m.update(update_count=2), "update"),
                   (lambda m: m.update(exact_cache_policy="game"), "cache/reset"),
                   (lambda m: m["self_play_openings"][0].update(side="W"), "opening")]
        for change, message in changes:
            with self.subTest(message=message):
                manifest = copy.deepcopy(original)
                change(manifest)
                self.args.manifest.write_bytes(pilot.blob(manifest))
                with self.assertRaisesRegex(training.TrainingError, message):
                    pilot.load_manifest(self.args.manifest)

    def test_baseline_manifest_and_input_are_pinned(self):
        baseline = training.read_json(self.baseline)
        baseline["provenance"]["input_manifest_digest"] = "f" * 64
        baseline.pop("artifact_digest")
        baseline["artifact_digest"] = training.digest(baseline)
        self.baseline.write_bytes(pilot.blob(baseline))
        self.mutate_manifest(lambda m: m["inputs"].update(baseline_artifact=pilot.entry(self.baseline)))
        with self.assertRaisesRegex(training.TrainingError, "baseline trainer manifest"):
            pilot.load_manifest(self.args.manifest)

    def test_baseline_forged_weights_with_valid_digest_are_rejected(self):
        baseline = training.read_json(self.baseline)
        baseline["weights"].setdefault("0", [{} for _ in range(64)])[0]["0"] = 1
        baseline["feature_max_abs"][0] = 1
        baseline["weight_digest"] = training.digest(baseline["weights"])
        baseline.pop("artifact_digest")
        baseline["artifact_digest"] = training.digest(baseline)
        training.validate_artifact(baseline)
        self.baseline.write_bytes(pilot.blob(baseline))
        self.mutate_manifest(lambda m: m["inputs"].update(baseline_artifact=pilot.entry(self.baseline)))
        with self.assertRaisesRegex(training.TrainingError, "does not reproduce"):
            pilot.load_manifest(self.args.manifest)

    def test_prepare_reset_failure_closes_process_removes_manifest_and_allows_retry(self):
        self.args.manifest.unlink()
        original_close = rf.Candidate.close
        with mock.patch.object(rf.Candidate, "new_game", side_effect=training.TrainingError("missing reset ack")), \
             mock.patch.object(rf.Candidate, "close", autospec=True, side_effect=original_close) as close:
            with self.assertRaisesRegex(training.TrainingError, "missing reset ack"):
                pilot.prepare(self.args)
        close.assert_called_once()
        self.assertIsNotNone(close.call_args.args[0].process.returncode)
        self.assertFalse(self.args.manifest.exists())
        pilot.prepare(self.args)

    def test_corpus_exclusions_reserve_training_and_full_played_positions(self):
        context = pilot.load_manifest(self.args.manifest)
        legal = [row for row in context["corpus"] if row["legal_moves"]]
        self.assertEqual(len(legal), 2)
        position = pilot.key(legal[0]["board"], legal[0]["side_to_move"])
        rows, _, excluded = pilot.independent_corpus(context, {position})
        self.assertIn(legal[0]["position_id"], excluded)
        self.assertNotIn(legal[0]["position_id"], [row["position_id"] for row in rows])
        context["baseline_keys"].add(pilot.key(legal[1]["board"], legal[1]["side_to_move"]))
        with self.assertRaisesRegex(training.TrainingError, "decision-bearing corpus"):
            pilot.independent_corpus(context, {position})

    def test_game_digest_reseal_does_not_allow_pair_or_move_tampering(self):
        output = self.complete()
        games = training.read_jsonl(output / "games.jsonl")
        for mutate in (lambda g: g.update(member=1), lambda g: g["decisions"][0].update(move="a1"),
                       lambda g: g["reset_events"].clear(), lambda g: g["decisions"][0].update(id="forged")):
            changed = copy.deepcopy(games)
            mutate(changed[0])
            changed[0]["game_digest"] = training.digest({k: v for k, v in changed[0].items() if k != "game_digest"})
            (output / "games.jsonl").write_bytes(pilot.lines(changed))
            with self.assertRaises(training.TrainingError), redirect_stderr(io.StringIO()):
                pilot.verify(self.args.manifest, output)

    def test_missing_pair_extra_game_artifact_and_metrics_fail_closed(self):
        output = self.complete()
        original = {name: (output / name).read_bytes() for name in pilot.OUTPUTS}
        games = training.read_jsonl(output / "games.jsonl")
        for changed in (games[:-1], games + [games[-1]]):
            (output / "games.jsonl").write_bytes(pilot.lines(changed))
            with self.assertRaisesRegex(training.TrainingError, "game set"), redirect_stderr(io.StringIO()):
                pilot.verify(self.args.manifest, output)
        (output / "games.jsonl").write_bytes(original["games.jsonl"])
        for name in ("teachers.jsonl", "candidate-artifact.json", "report.json"):
            (output / name).write_bytes(original[name] + b"\n")
            with self.assertRaisesRegex(training.TrainingError, "differs from replay"), redirect_stderr(io.StringIO()):
                pilot.verify(self.args.manifest, output)
            (output / name).write_bytes(original[name])

    def test_corpus_decisions_are_legally_bound_to_saved_values(self):
        output = self.complete()
        decisions = training.read_jsonl(output / "corpus-decisions.jsonl")
        decisions[0]["move"] = "a1"
        (output / "corpus-decisions.jsonl").write_bytes(pilot.lines(decisions))
        with self.assertRaisesRegex(training.TrainingError, "illegal corpus"), redirect_stderr(io.StringIO()):
            pilot.verify(self.args.manifest, output)

    def test_split_overlap_is_excluded_and_empty_metric_rejected(self):
        context = pilot.load_manifest(self.args.manifest)
        first = context["validation"][0]
        duplicate = {**first, "id": "held-out-leak"}
        context["held_out"] = [duplicate]
        with self.assertRaisesRegex(training.TrainingError, "empty independent held_out"):
            pilot.metric_rows(context, set())
        context["held_out"] = [duplicate, context["validation"][-1]]
        with self.assertRaisesRegex(training.TrainingError, "empty independent held_out"):
            pilot.metric_rows(context, set())
        context["held_out"] = [{**first, "id": "played-leak"}]
        with self.assertRaisesRegex(training.TrainingError, "empty independent"):
            pilot.metric_rows(context, {pilot.key(first["board"], first["side"])})

    def test_teacher_dedup_reserves_training_and_counts_actual_update_rows(self):
        output = self.complete()
        context = pilot.load_manifest(self.args.manifest)
        games = training.read_jsonl(output / "games.jsonl")
        teachers, _, _ = pilot.checked_games(context, games)
        keys = [pilot.key(row["board"], row["side"]) for row in teachers]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertFalse(set(keys) & context["baseline_keys"])
        context["baseline_keys"].add(keys[0])
        remaining, _, excluded = pilot.checked_games(context, games)
        self.assertEqual(len(remaining), len(teachers) - 1)
        self.assertIn(teachers[0]["id"], excluded)
        self.assertEqual((output / "teachers.jsonl").read_bytes(), pilot.lines(teachers))

    def test_reserved_continuation_is_rejected_before_cli_and_during_replay(self):
        output = self.complete()
        context = pilot.load_manifest(self.args.manifest)
        games = training.read_jsonl(output / "games.jsonl")
        row = games[0]["decisions"][10]
        position = pilot.key(row["board"], row["side"])
        context["reserved"].add(position)
        with self.assertRaisesRegex(training.TrainingError, "reserved 0018"):
            pilot.checked_games(context, games)
        player = object.__new__(pilot.GuardedCandidate)
        player.reserved = context["reserved"]
        with mock.patch.object(rf.Candidate, "choose") as choose:
            with self.assertRaisesRegex(training.TrainingError, "reserved 0018"):
                player.choose("reserved", row["board"], row["side"])
        choose.assert_not_called()

    def test_observed_terminal_states_are_excluded_from_independent_inputs(self):
        output = self.complete()
        context = pilot.load_manifest(self.args.manifest)
        games = training.read_jsonl(output / "games.jsonl")
        _, played, _ = pilot.checked_games(context, games)
        board = games[0]["terminal_board"]
        for side in ("B", "W"):
            self.assertIn(pilot.key(board, side), played)
        terminal = pilot.oracle.make_corpus_record("observed-terminal", board, "B", [], "test-fixture")
        context["corpus"].append(terminal)
        context["golden"].append({})  # Exclusion happens before saved-value use.
        _, _, excluded = pilot.independent_corpus(context, played)
        self.assertIn("observed-terminal", excluded)
        context["reserved"].add(pilot.key(board, "W"))
        with self.assertRaisesRegex(training.TrainingError, "terminal board is a reserved"):
            pilot.checked_games(context, games)

    def test_timeout_preserves_completed_evidence_and_publishes_no_report(self):
        original = rf.Candidate.choose
        count = [0]
        def fail_after_game(player, identifier, board, side):
            if identifier.startswith("self-play-p1"):
                raise training.TrainingError("candidate timed out")
            count[0] += 1
            return original(player, identifier, board, side)
        output = self.root / "failed"
        with mock.patch.object(rf.Candidate, "choose", fail_after_game), redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(training.TrainingError, "timed out"):
                pilot.run(self.args.manifest, output)
        self.assertGreater(count[0], 0)
        self.assertEqual(len(training.read_jsonl(output / "games.jsonl")), 1)
        self.assertFalse((output / "report.json").exists())
        with self.assertRaisesRegex(training.TrainingError, "missing"), redirect_stderr(io.StringIO()):
            pilot.verify(self.args.manifest, output)

    def test_failure_after_update_retains_artifact_and_no_success_report(self):
        output = self.root / "failed-metrics"
        with mock.patch.object(pilot, "metric_rows", side_effect=training.TrainingError("empty independent metric")), \
             redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(training.TrainingError, "empty independent"):
                pilot.run(self.args.manifest, output)
        self.assertTrue((output / "candidate-artifact.json").is_file())
        self.assertEqual(len(training.read_jsonl(output / "games.jsonl")), 26)
        self.assertFalse((output / "report.json").exists())

    def test_nonempty_directory_and_nonpositive_progress_rejected(self):
        output = self.root / "nonempty"
        output.mkdir()
        (output / "foreign.txt").write_text("preserve")
        with self.assertRaisesRegex(training.TrainingError, "must be empty"), redirect_stderr(io.StringIO()):
            pilot.run(self.args.manifest, output)
        self.assertEqual((output / "foreign.txt").read_text(), "preserve")
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            pilot.main(["run", "--manifest", "x", "--output-dir", "y", "--progress-every", "0"])

    def test_progress_interval_does_not_change_evidence(self):
        first = self.complete("first")
        second, log = self.root / "second", io.StringIO()
        with redirect_stderr(log):
            pilot.run(self.args.manifest, second, progress_every=1000)
        progress = [line for line in log.getvalue().splitlines() if line.startswith("progress ")]
        self.assertEqual(len(progress), 3)
        self.assertIn("6/6", progress[0])
        self.assertIn("20/20", progress[1])
        self.assertEqual({name: (first / name).read_bytes() for name in pilot.OUTPUTS},
                         {name: (second / name).read_bytes() for name in pilot.OUTPUTS})


if __name__ == "__main__":
    unittest.main()
