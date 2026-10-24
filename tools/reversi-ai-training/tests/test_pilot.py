"""Bounded fake-CLI tests of the pilot evidence contract, never strength runs."""

import argparse
import copy
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pilot
import random_inputs
import reinforcement as rf
import training
import production_cycle
from types import SimpleNamespace


class RuntimeEstimateTests(unittest.TestCase):
    def failing_opening(self):
        # First Oracle opening from production seed 20261014.
        board, side = rf.INITIAL, "B"
        moves = "c4 c3 e6 f4 d3 b4".split()
        for move in moves:
            self.assertIn(move, rf.legal_moves(board, side))
            board, side = rf.apply_move(board, side, move), rf.other(side)
        return {"board": board, "side": side, "moves": moves, "rotation": 0}

    def legal_replay(self, opening):
        board, side = opening["board"], opening["side"]
        positions = []
        while True:
            legal = rf.legal_moves(board, side)
            if not legal:
                side = rf.other(side)
                legal = rf.legal_moves(board, side)
            if not legal:
                return positions, board
            positions.append((board, side))
            board, side = rf.apply_move(board, side, legal[0]), rf.other(side)

    def context(self, opening):
        return {"manifest": {
            "openings": {"oracle-match": [[opening]]},
            "oracle_binary": {"path": "/fixture/oracle"},
            "candidate_executable": {"path": "/fixture/candidate"},
            "match_config": dict(production_cycle.MATCH_CONFIG),
            "decision_timeout_seconds": 30,
            "requested_counts": {"self_play_games": 6,
                                 "baseline_comparison_games": 40, "oracle_match_games": 2}},
            "paths": {"baseline_artifact": "/fixture/baseline.json"}}

    def test_seed_20261014_uses_last_legal_position_before_terminal_41(self):
        opening = self.failing_opening()
        original = copy.deepcopy(opening)
        positions, terminal = self.legal_replay(opening)
        self.assertEqual(64 - terminal.count("."), 41)
        self.assertFalse(rf.legal_moves(terminal, "B"))
        self.assertFalse(rf.legal_moves(terminal, "W"))

        representatives = production_cycle.runtime_representatives(opening)
        self.assertEqual([item["requested_occupied_count"] for item in representatives], [10, 30, 48])
        self.assertEqual([item["actual_occupied_count"] for item in representatives], [10, 30, 40])
        self.assertEqual((representatives[-1]["board"], representatives[-1]["side"]), positions[-1])
        for item in representatives:
            self.assertNotEqual(item["board"], terminal)
            self.assertTrue(rf.legal_moves(item["board"], item["side"]))
        self.assertEqual(opening, original)

    def test_ordinary_replay_selects_exact_target_positions(self):
        opening = {"board": rf.INITIAL, "side": "B"}
        positions, _ = self.legal_replay(opening)
        representatives = production_cycle.runtime_representatives(opening)
        for item, target in zip(representatives, (4, 30, 48)):
            expected = next(position for position in positions if 64 - position[0].count(".") == target)
            self.assertEqual((item["board"], item["side"]), expected)
            self.assertEqual(item["requested_occupied_count"], target)
            self.assertEqual(item["actual_occupied_count"], target)

    def test_forced_pass_at_target_selects_legal_side_without_mutating_opening(self):
        opening = {"board": "BW." + "B" * 61, "side": "W"}
        original = dict(opening)
        self.assertFalse(rf.legal_moves(opening["board"], "W"))
        self.assertEqual(rf.legal_moves(opening["board"], "B"), ["c1"])
        representatives = production_cycle.runtime_representatives(opening)
        self.assertEqual(representatives[0], {"board": opening["board"], "side": "B",
                         "requested_occupied_count": 63, "actual_occupied_count": 63})
        self.assertEqual(opening, original)

    def test_terminal_opening_fails_before_starting_search_processes(self):
        context = self.context({"board": "B" * 64, "side": "B"})
        original = copy.deepcopy(context)
        with mock.patch.object(rf, "Candidate") as candidate, \
             mock.patch.object(production_cycle.oracle_module, "run_solve") as solve:
            with self.assertRaisesRegex(training.TrainingError, "could not select a legal representative"):
                production_cycle.runtime_estimate(context)
        candidate.assert_not_called()
        solve.assert_not_called()
        self.assertEqual(context, original)

    def test_estimate_measures_three_legal_profiles_and_preserves_projection(self):
        context = self.context(self.failing_opening())
        original = copy.deepcopy(context)
        representatives = production_cycle.runtime_representatives(
            context["manifest"]["openings"]["oracle-match"][0][0])
        with mock.patch.object(rf, "Candidate") as candidate, \
             mock.patch.object(production_cycle.oracle_module, "run_solve") as solve, \
             mock.patch.object(production_cycle.time, "monotonic", side_effect=range(12)):
            estimate = production_cycle.runtime_estimate(context)
        project = candidate.return_value
        self.assertEqual(solve.call_count, 3)
        self.assertEqual(project.new_game.call_args_list,
                         [mock.call(f"0019-runtime-estimate-{index}") for index in range(3)])
        self.assertEqual(project.choose_with_diagnostic.call_args_list,
                         [mock.call(f"0019-runtime-estimate-{index}", item["board"], item["side"])
                          for index, item in enumerate(representatives)])
        for call, item in zip(solve.call_args_list, representatives):
            self.assertEqual(call.args[0], [(item["board"], item["side"])])
            self.assertEqual(call.args[3], production_cycle.ORACLE_PROFILE)
            self.assertEqual(call.kwargs, {"child_query": False})
        project.close.assert_called_once_with()
        self.assertEqual(estimate["representative_searches"], [
            {"phase": phase, "requested_occupied_count": requested, "actual_occupied_count": actual,
             "oracle_seconds": 1, "candidate_seconds": 1}
            for phase, requested, actual in (("opening", 10, 10), ("midgame", 30, 30), ("endgame", 48, 40))])
        self.assertEqual(estimate["core_seconds"], [991.8, 1983.6])
        self.assertEqual(estimate["estimated_oracle_decisions_per_game"], 29)
        self.assertEqual(estimate["oracle_match_seconds"], 116)
        self.assertEqual(estimate["combined_seconds"], [1107.8, 2099.6])
        self.assertEqual(context, original)


class ProductionSourceTests(unittest.TestCase):
    def test_dirty_checkout_is_rejected_even_with_a_full_commit(self):
        with mock.patch.object(production_cycle.subprocess, "run", side_effect=[
                SimpleNamespace(stdout="a" * 40 + "\n"),
                SimpleNamespace(stdout=" M tools/reversi-ai-training/production_cycle.py\n")]):
            with self.assertRaisesRegex(training.TrainingError, "clean source checkout"):
                production_cycle.source_commit()

    def test_missing_short_or_uppercase_commit_is_rejected_before_status(self):
        for value in ("", "a" * 39, "A" * 40):
            with self.subTest(commit=value), mock.patch.object(
                    production_cycle.subprocess, "run", return_value=SimpleNamespace(stdout=value)) as run:
                with self.assertRaisesRegex(training.TrainingError, "source commit"):
                    production_cycle.source_commit()
                self.assertEqual(run.call_count, 1)


class PilotTests(unittest.TestCase):
    def setUp(self):
        commit_patch = mock.patch.object(production_cycle, "source_commit", return_value="a" * 40)
        self.execution_commit = commit_patch.start()
        self.addCleanup(commit_patch.stop)
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

    def bundle_stub(self, production=False, profiled=False):
        """Unit-test the pilot adapter; producer verification has separate tests."""
        path = self.root / "input-bundle.json"
        path.write_bytes(pilot.blob({"fixture": "adapter-only"}))
        receipt = self.root / "bundle-verification-receipt.json"
        receipt.write_bytes(pilot.blob({"fixture": "adapter-only-receipt"}))
        executable = self.args.candidate_executable
        original = training.read_json(self.args.manifest)
        verified = {"schema_version": 1, "bundle_sha256": training.sha256_file(path),
            "strength_inputs": production, "input_kind": "production" if production else "tooling",
            "tooling_only": not production,
            "inputs": {name: {field: original["inputs"][name][field] for field in ("path", "sha256")}
                       for name in ("baseline_artifact", "baseline_manifest", "validation", "held_out", "corpus", "golden")},
            "acceptance_reservation": {"state": "not-yet-selected", "artifact": None, "keys": []},
            "exposure_keys": {"train": [], "validation": [], "held_out": [], "oracle_root": [], "oracle_child": []},
            "cli": {"adapter_test": True}, "bundle_verification_receipt": pilot.entry(receipt)}
        verifier = mock.Mock(return_value=verified)
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(sys.modules, {"input_bundle": SimpleNamespace(
            verify_for_pilot=verifier, verify_for_production_cycle=verifier)}).start()
        self.args.manifest.unlink()
        fixture_cli = ROOT / "fixtures" / ("fake-production-candidate-v1.py" if profiled
                                             else "fake-self-play-v1.py")
        executable.write_text("#!/usr/bin/env python3\nimport runpy\n"
                              f"runpy.run_path({str(fixture_cli)!r}, run_name='__main__')\n")
        executable.chmod(0o755)
        self.args.input_bundle = path
        self.args.bundle_verification_receipt = receipt
        self.args.reserved_openings = None
        pilot.prepare(self.args)
        return verified, verifier

    def one_command_args(self, run_root):
        return argparse.Namespace(
            run_root=run_root,
            input_bundle=self.args.input_bundle,
            bundle_verification_receipt=self.args.bundle_verification_receipt,
            candidate_executable=self.args.candidate_executable,
            oracle_binary=None,
            seed=self.args.seed,
            opening_plies=self.args.opening_plies,
            time_limit_ms=self.args.time_limit_ms,
            node_limit=self.args.node_limit,
            decision_timeout_seconds=self.args.decision_timeout_seconds,
            progress_every=100,
            self_play_games=6,
            baseline_comparison_games=20,
            oracle_match_games=0,
            resume_from=None,
        )

    def production_args(self, run_root):
        fixture = training.read_json(ROOT / "fixtures" / "production-execute-v1.json")
        args = self.one_command_args(run_root)
        args.oracle_binary = self.root / "pinned-oracle-fixture"
        args.oracle_binary.write_text("#!/usr/bin/env python3\nraise SystemExit(0)\n")
        args.oracle_binary.chmod(0o755)
        args.seed = fixture["seed"]
        args.self_play_games = fixture["counts"]["self_play_games"]
        args.baseline_comparison_games = fixture["counts"]["baseline_comparison_games"]
        args.oracle_match_games = fixture["counts"]["oracle_match_games"]
        args.resume_from = None
        return args

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

    def test_one_command_prepares_runs_and_offline_verifies(self):
        self.bundle_stub()
        run_root = self.root / "one-command"
        args = self.one_command_args(run_root)
        stdout = io.StringIO()
        with redirect_stderr(io.StringIO()), redirect_stdout(stdout):
            report = pilot.execute(args)

        self.assertTrue((run_root / "manifest.json").is_file())
        self.assertTrue((run_root / "output" / "report.json").is_file())
        self.assertEqual(report["actual_counts"]["self_play_games"], 6)
        self.assertEqual(report["actual_counts"]["comparison_games"], 20)
        self.assertTrue(report["tooling_only"])
        self.assertFalse(report["production_authorized"])
        self.assertIn(f"pilot verified report={run_root / 'output' / 'report.json'}", stdout.getvalue())
        report_bytes = (run_root / "output" / "report.json").read_bytes()
        with self.assertRaisesRegex(training.TrainingError, "run root already exists"):
            pilot.execute(args)
        self.assertEqual((run_root / "output" / "report.json").read_bytes(), report_bytes)

    def test_one_command_atomically_reserves_run_root_before_preparation(self):
        self.bundle_stub()
        run_root = self.root / "raced-one-command"
        run_root.mkdir()
        args = self.one_command_args(run_root)

        # Model two callers that both observed a missing root: the exclusive
        # mkdir must still reject the second caller before preparation.
        with mock.patch.object(Path, "exists", return_value=False), \
             mock.patch.object(pilot, "prepare") as prepare:
            with self.assertRaisesRegex(training.TrainingError, "run root already exists"):
                pilot.execute(args)

        prepare.assert_not_called()
        self.assertTrue(run_root.is_dir())

    def test_one_command_keeps_partial_output_and_stops_before_verification(self):
        self.bundle_stub()
        run_root = self.root / "failed-one-command"
        args = self.one_command_args(run_root)

        def fail_run(manifest_path, output_dir, progress_every):
            self.assertTrue(manifest_path.is_file())
            output_dir.mkdir()
            (output_dir / "games.jsonl").write_text("partial\n", encoding="utf-8")
            raise training.TrainingError("synthetic batch failure")

        with mock.patch.object(pilot, "run", side_effect=fail_run), \
             mock.patch.object(pilot, "verify") as verify, \
             redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(training.TrainingError, "synthetic batch failure"):
                pilot.execute(args)

        self.assertTrue((run_root / "manifest.json").is_file())
        self.assertEqual((run_root / "output" / "games.jsonl").read_text(encoding="utf-8"), "partial\n")
        verify.assert_not_called()

    def test_0019_execute_is_deterministic_and_reports_all_phase_evidence(self):
        self.bundle_stub(production=True, profiled=True)
        fixture = training.read_json(ROOT / "fixtures" / "production-execute-v1.json")

        def oracle_move(queries, _binary, _cwd, profile, _timeout, **_kwargs):
            board, side = queries[0]
            legal = production_cycle.oracle_module.legal_moves(board, side)
            empty = board.count(".")
            depth = production_cycle.oracle_module.profile_depth_at(
                profile, board.count("B") + board.count("W"))
            return [{"move": legal[0], "completed_depth": min(empty, depth),
                     "exact": empty <= production_cycle.oracle_module.profile_exact_threshold(profile)}]

        snapshots = []
        reports = []
        for name in ("production-one", "production-two"):
            args = self.production_args(self.root / name)
            args.opening_plies = fixture["opening_plies"]
            with mock.patch.object(production_cycle, "runtime_estimate", return_value={"fixture": True}), \
                 mock.patch.object(production_cycle.oracle_module, "run_solve", side_effect=oracle_move), \
                 redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                report = pilot.execute(args)
            root = args.run_root
            self.assertEqual(report["requested_counts"], fixture["counts"])
            self.assertEqual(report["actual_counts"], fixture["counts"])
            self.assertEqual(report["oracle_match"]["profile"]["name"], fixture["oracle_profile"])
            self.assertEqual(set(report["phase_receipts"]), set(production_cycle.PHASES[:-1]))
            self.assertEqual(report["run_status"], "complete")
            snapshots.append({str(path.relative_to(root)): path.read_bytes()
                              for path in root.rglob("*") if path.is_file()})
            reports.append(report)
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(reports[0], reports[1])
        manifest = training.read_json(self.root / "production-one" / "manifest.json")
        self.assertEqual(reports[0]["execution_commit"], manifest["execution_commit"])
        self.assertNotIn("sources", manifest)
        self.assertNotIn("sources", reports[0])
        with mock.patch.object(production_cycle, "source_commit", return_value="f" * 40):
            context = production_cycle.load_context(self.root / "production-one" / "manifest.json")
        self.assertEqual(context["manifest"]["execution_commit"], manifest["execution_commit"])

    def test_0019_resume_verifies_predecessors_and_retries_selected_phase(self):
        self.bundle_stub(production=True, profiled=True)
        args = self.production_args(self.root / "resumable-production")

        with mock.patch.object(production_cycle, "runtime_estimate", return_value={"fixture": True}), \
             mock.patch.object(production_cycle, "phase_baseline_match",
                               side_effect=training.TrainingError("synthetic interruption")), \
             redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(training.TrainingError, "synthetic interruption"):
                pilot.execute(args)

        root = args.run_root
        self.assertTrue((root / "phases" / "baseline-match" / "attempt-0001" / "failure.json").is_file())
        args.resume_from = "baseline-match"
        self.execution_commit.return_value = "f" * 40
        args.baseline_comparison_games += 2
        args.decision_timeout_seconds = 45

        self_play = root / "phases" / "self-play" / "attempt-0001" / "games.jsonl"
        original = self_play.read_bytes()
        self_play.write_bytes(original + b"tampered\n")
        args.resume_from = "baseline-match"
        with mock.patch.object(production_cycle, "runtime_estimate", return_value={"fixture": True}), \
             redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(training.TrainingError, "predecessor phase"):
                pilot.execute(args)
        self_play.write_bytes(original)

        def oracle_move(queries, _binary, _cwd, profile, _timeout, **_kwargs):
            board, side = queries[0]
            legal = production_cycle.oracle_module.legal_moves(board, side)
            empty = board.count(".")
            depth = production_cycle.oracle_module.profile_depth_at(
                profile, board.count("B") + board.count("W"))
            return [{"move": legal[0], "completed_depth": min(empty, depth),
                     "exact": empty <= production_cycle.oracle_module.profile_exact_threshold(profile)}]

        with mock.patch.object(production_cycle, "runtime_estimate", return_value={"fixture": True}), \
             mock.patch.object(production_cycle.oracle_module, "run_solve", side_effect=oracle_move), \
             redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            report = pilot.execute(args)
        self.assertEqual(report["run_status"], "complete")
        self.assertTrue((root / "phases" / "baseline-match" / "attempt-0002" / "receipt.json").is_file())
        self.assertTrue((root / "phases" / "baseline-match" / "attempt-0001" / "failure.json").is_file())
        provenance = training.read_json(root / "phases" / "baseline-match" / "attempt-0002" / "provenance.json")
        self.assertEqual(provenance["execution_commit"], "f" * 40)
        self.assertEqual(provenance["effective_settings"]["decision_timeout_seconds"], 45)
        self.assertEqual(provenance["effective_settings"]["requested_counts"]["baseline_comparison_games"],
                         args.baseline_comparison_games)

    @staticmethod
    def fixture_oracle_move(queries, _binary, _cwd, profile, _timeout, **_kwargs):
        board, side = queries[0]
        module = production_cycle.oracle_module
        depth = module.profile_depth_at(profile, 64 - board.count("."))
        return [{"move": module.legal_moves(board, side)[0],
                 "completed_depth": min(board.count("."), depth),
                 "exact": board.count(".") <= module.profile_exact_threshold(profile)}]

    def run_production_fixture(self, args, *, fail_after=None, emitted=None):
        real_match = production_cycle.oracle_module.run_profiled_match
        def match(*positional, **kwargs):
            save_game = kwargs["on_game"]
            def save(game):
                save_game(game)
                if emitted is not None:
                    emitted.append(game["game"])
                if game["game"] == fail_after:
                    raise training.TrainingError("fixture Oracle timeout")
            kwargs["on_game"] = save
            return real_match(*positional, **kwargs)
        with mock.patch.object(production_cycle, "runtime_estimate", return_value={"fixture": True}), \
             mock.patch.object(production_cycle.oracle_module, "run_solve", side_effect=self.fixture_oracle_move), \
             mock.patch.object(production_cycle.oracle_module, "run_profiled_match", side_effect=match), \
             redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            return pilot.execute(args)

    def test_0019_legacy_seven_game_prefix_retries_twice_without_rewriting_evidence(self):
        self.bundle_stub(production=True, profiled=True)
        args = self.production_args(self.root / "legacy-production")
        args.oracle_match_games = 20
        with self.assertRaisesRegex(training.TrainingError, "fixture Oracle timeout"):
            self.run_production_fixture(args, fail_after=7)
        root = args.run_root
        # Model the unmodified schema-2 predecessor receipts and failure output
        # emitted by the previous executor, before attempt provenance existed.
        for phase in production_cycle.PHASES:
            for attempt in production_cycle.phase_dirs(root, phase):
                for name in ("provenance.json", "game-provenance.jsonl"):
                    (attempt / name).unlink(missing_ok=True)
                receipt_path = attempt / "receipt.json"
                if receipt_path.exists():
                    receipt = training.read_json(receipt_path)
                    receipt.pop("receipt_digest")
                    receipt["schema_version"] = 1
                    receipt["outputs"].pop("provenance.json", None)
                    receipt["receipt_digest"] = training.digest(receipt)
                    receipt_path.write_bytes(pilot.blob(receipt))
                failure_path = attempt / "failure.json"
                if failure_path.exists():
                    failure = training.read_json(failure_path)
                    failure["schema_version"] = 1
                    failure.pop("failure_digest", None)
                    failure.pop("outputs", None)
                    failure_path.write_bytes(pilot.blob(failure))
        original = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        legacy_games_path = root / "phases/oracle-match/attempt-0001/games.jsonl"
        legacy_games = training.read_jsonl(legacy_games_path)
        context = production_cycle.load_context(root / "manifest.json")
        predecessors = production_cycle.require_predecessors(
            root, "oracle-match", training.sha256_file(root / "manifest.json"))
        wrong_digest = copy.deepcopy(legacy_games)
        wrong_digest[2]["game_digest"] = "0" * 64
        for broken in (legacy_games[:2] + legacy_games[3:],
                       legacy_games[:2] + legacy_games[1:2] + legacy_games[2:],
                       legacy_games[:2] + [legacy_games[3], legacy_games[2]] + legacy_games[4:],
                       wrong_digest):
            legacy_games_path.write_bytes(pilot.lines(broken))
            games, _ = production_cycle.oracle_prefix(
                context, predecessors, root / "phases/oracle-match/attempt-0002")
            self.assertEqual(games, legacy_games[:2])
        legacy_games_path.write_bytes(original[legacy_games_path])
        args.resume_from = "oracle-match"
        args.decision_timeout_seconds = 45
        self.execution_commit.return_value = "b" * 40
        emitted = []
        with self.assertRaisesRegex(training.TrainingError, "fixture Oracle timeout"):
            self.run_production_fixture(args, fail_after=9, emitted=emitted)
        self.assertEqual(emitted, [8, 9])
        second = root / "phases/oracle-match/attempt-0002"
        production_cycle.verify_failure(second)
        second_snapshot = {path: path.read_bytes() for path in second.iterdir() if path.is_file()}
        args.decision_timeout_seconds = 60
        self.execution_commit.return_value = "c" * 40
        emitted = []
        report = self.run_production_fixture(args, emitted=emitted)
        self.assertEqual(emitted, list(range(10, 21)))
        self.assertEqual(report["run_status"], "complete")
        self.assertEqual(report["actual_counts"]["oracle_match_games"], 20)
        third = root / "phases/oracle-match/attempt-0003"
        games = training.read_jsonl(third / "games.jsonl")
        self.assertEqual([game["game"] for game in games], list(range(1, 21)))
        origins = training.read_jsonl(third / "game-provenance.jsonl")
        self.assertEqual([row["provenance"]["execution_commit"] for row in origins],
                         ["a" * 40] * 7 + ["b" * 40] * 2 + ["c" * 40] * 11)
        self.assertEqual([row["provenance"]["effective_settings"]["decision_timeout_seconds"] for row in origins],
                         [30] * 7 + [45] * 2 + [60] * 11)
        for path, content in {**original, **second_snapshot}.items():
            self.assertEqual(path.read_bytes(), content, str(path))
        # A fresh offline verifier must reconstruct mixed-commit attempts from
        # disk without execute() supplying the current invocation context.
        manifest_path = root / "manifest.json"
        context = production_cycle.load_context(manifest_path)
        manifest_digest = training.sha256_file(manifest_path)
        predecessors = production_cycle.require_predecessors(root, "offline-verification", manifest_digest)
        with mock.patch.object(rf, "Candidate", side_effect=AssertionError("offline candidate")), \
             mock.patch.object(production_cycle.oracle_module, "run_solve", side_effect=AssertionError("offline Oracle")):
            for phase, attempt in predecessors.items():
                production_cycle.semantic_phase_check(context, phase, attempt, predecessors)
            self.assertEqual(production_cycle.build_final_report(context, predecessors, manifest_digest), report)

    def test_0019_upstream_settings_require_earliest_phase_before_search(self):
        self.bundle_stub(production=True, profiled=True)
        args = self.production_args(self.root / "upstream-boundary")
        with self.assertRaisesRegex(training.TrainingError, "fixture Oracle timeout"):
            self.run_production_fixture(args, fail_after=1)
        args.resume_from = "oracle-match"
        args.self_play_games += 2
        with mock.patch.object(production_cycle, "runtime_estimate") as estimate, \
             mock.patch.object(rf, "Candidate") as candidate:
            with self.assertRaisesRegex(training.TrainingError, "resume-from self-play"):
                pilot.execute(args)
        estimate.assert_not_called()
        candidate.assert_not_called()

    def test_0019_failed_attempt_provenance_tampering_is_detected(self):
        self.bundle_stub(production=True, profiled=True)
        args = self.production_args(self.root / "tamper-production")
        with self.assertRaisesRegex(training.TrainingError, "fixture Oracle timeout"):
            self.run_production_fixture(args, fail_after=1)
        attempt = args.run_root / "phases/oracle-match/attempt-0001"
        path = attempt / "provenance.json"
        original = path.read_bytes()
        failure_path = attempt / "failure.json"
        original_failure = failure_path.read_bytes()
        provenance = training.read_json(path)
        provenance["execution_commit"] = "bad"
        path.write_bytes(pilot.blob(provenance))
        with self.assertRaisesRegex(training.TrainingError, "output digest mismatch"):
            production_cycle.verify_failure(attempt)
        with self.assertRaisesRegex(training.TrainingError, "execution commit"):
            production_cycle.validate_provenance(provenance, "oracle-match")
        provenance.pop("execution_commit")
        with self.assertRaisesRegex(training.TrainingError, "execution commit"):
            production_cycle.validate_provenance(provenance, "oracle-match")
        path.write_bytes(original)
        production_cycle.verify_failure(attempt)
        context = production_cycle.load_context(args.run_root / "manifest.json")
        for mutate in (
                lambda p: p["effective_settings"].update(decision_timeout_seconds=0),
                lambda p: p["effective_settings"]["openings"]["oracle-match"][0][0].update(rotation=7),
                lambda p: p["input_identities"]["oracle_binary"].update(sha256="0" * 64),
                lambda p: p["predecessors"].update({"self-play": "0" * 64})):
            provenance = training.read_json(path)
            mutate(provenance)
            path.write_bytes(pilot.blob(provenance))
            failure = training.read_json(failure_path)
            failure["outputs"]["provenance.json"] = training.sha256_file(path)
            failure.pop("failure_digest")
            failure["failure_digest"] = training.digest(failure)
            failure_path.write_bytes(pilot.blob(failure))
            with self.assertRaises(training.TrainingError):
                production_cycle.verify_failed_attempts(args.run_root, context)
            path.write_bytes(original)
            failure_path.write_bytes(original_failure)
        path.unlink()
        with self.assertRaisesRegex(training.TrainingError, "output digest mismatch"):
            production_cycle.verify_failure(attempt)
        path.write_bytes(original)
        failure = training.read_json(failure_path)
        failure["error"] = "modified failure text"
        failure_path.write_bytes(pilot.blob(failure))
        with self.assertRaisesRegex(training.TrainingError, "failure record digest mismatch"):
            production_cycle.verify_failure(attempt)

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
        self.args.bundle_verification_receipt = directory / "stages/bundle-verify/report.json"
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
        original_manifest = self.args.manifest.read_bytes()
        original_receipt = self.args.bundle_verification_receipt.read_bytes()
        failed = training.read_json(self.args.bundle_verification_receipt)
        failed["status"] = "failed"
        self.args.bundle_verification_receipt.write_bytes(pilot.blob(failed))
        self.mutate_manifest(lambda manifest: manifest["inputs"].update(
            bundle_verification_receipt=pilot.entry(self.args.bundle_verification_receipt)))
        with self.assertRaises(training.TrainingError), redirect_stderr(io.StringIO()):
            pilot.verify(self.args.manifest, output)
        self.args.bundle_verification_receipt.write_bytes(original_receipt)
        self.args.manifest.write_bytes(original_manifest)
        mismatched = directory / "stages/train/report.json"
        self.mutate_manifest(lambda manifest: manifest["inputs"].update(
            bundle_verification_receipt=pilot.entry(mismatched)))
        with self.assertRaises(training.TrainingError), redirect_stderr(io.StringIO()):
            pilot.verify(self.args.manifest, output)
        self.args.manifest.write_bytes(original_manifest)
        forged_bundle = bundle_path.with_name("forged-bundle.json")
        input_bundle.save(forged_bundle, dict(completion, verified=True))
        self.mutate_manifest(lambda manifest: manifest["inputs"].update(input_bundle=pilot.entry(forged_bundle)))
        with self.assertRaisesRegex(training.TrainingError, "shape"), redirect_stderr(io.StringIO()):
            pilot.verify(self.args.manifest, output)

    def test_bundle_receipt_is_required_and_pinned_even_with_eligibility_flags(self):
        self.bundle_stub(production=True)
        original = self.args.manifest.read_bytes()
        manifest = training.read_json(self.args.manifest)
        manifest["inputs"].pop("bundle_verification_receipt")
        self.args.manifest.write_bytes(pilot.blob(manifest))
        with self.assertRaisesRegex(training.TrainingError, "pilot inputs"):
            pilot.load_manifest(self.args.manifest)
        self.args.manifest.write_bytes(original)
        self.args.bundle_verification_receipt.write_bytes(b"changed receipt")
        with self.assertRaisesRegex(training.TrainingError, "receipt digest mismatch"):
            pilot.load_manifest(self.args.manifest)
        self.args.manifest.unlink()
        self.args.bundle_verification_receipt = None
        with self.assertRaisesRegex(training.TrainingError, "requires.*receipt"):
            pilot.prepare(self.args)
        self.assertFalse(self.args.manifest.exists())

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
