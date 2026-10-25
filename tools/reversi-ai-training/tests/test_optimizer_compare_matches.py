"""Small mocked diagnostic runs; never a strength or production comparison."""

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import optimizer_compare_matches as matches
import pilot
import production_cycle as cycle
import reinforcement as rf
import training


class FakeCandidate:
    def __init__(self, executable, artifact, config, timeout, capture_diagnostics=False):
        self.config = config

    def new_game(self, identifier):
        pass

    def choose_with_diagnostic(self, identifier, board, side):
        legal = rf.legal_moves(board, side)
        return (legal[0] if legal else "pass"), {
            "completed_depth": 12, "exact": True, "nodes": 1, "elapsed_us": 1,
            "outcome": "move" if legal else "pass"}

    def close(self):
        pass


class ComparisonMatchTests(unittest.TestCase):
    def setup_context(self, root):
        candidate, oracle_binary = root / "candidate", root / "oracle"
        candidate.write_text("fake candidate")
        oracle_binary.write_text("fake Oracle")
        fixture = ROOT / "fixtures/tiny-winner-empty-manifest.json"
        manifest = training.read_json(fixture)
        records = training.validate_records(training.validate_manifest(manifest, fixture.parent))
        artifact = training.artifact_from(manifest, records, training.digest(manifest))
        adopted = root / "adopted.json"
        adopted.write_bytes(pilot.blob(artifact))
        board, side = rf.INITIAL, "B"
        legal = rf.legal_moves(board, side)
        corpus = [{"position_id": "small-corpus", "board": board, "side_to_move": side,
                   "legal_moves": legal}]
        golden = [{"analysis": {"best_value": 2,
                                 "evaluations": [{"move": move, "value": 2} for move in legal]}}]
        context = {"adopted": artifact, "adopted_path": adopted, "teachers": [],
                   "validation": [], "held_out": [], "corpus": corpus, "golden": golden,
                   "exposure_keys": {"opening": [pilot.key(board, side)]},
                   "source_context": {"reserved": set(), "baseline_keys": set(), "manifest": {
                       "oracle_binary": cycle.file_entry(oracle_binary),
                       "oracle_profile": pilot.oracle.profile_metadata(cycle.ORACLE_PROFILE),
                       "oracle_version": pilot.oracle.ORACLE_VERSION,
                       "oracle_source_sha256": pilot.oracle.SOURCE_SHA256}}}
        settings = matches.prepare(context, 20261025, candidate, oracle_binary, 310)
        return context, settings, adopted

    def test_fresh_paired_openings_determinism_and_identity_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            context, settings, adopted = self.setup_context(Path(temporary))
            matches.validate_settings(context, settings)
            pools = settings["openings"]
            roots = []
            for name in ("comparison", "oracle-match"):
                self.assertEqual(len(pools[name]), 10)
                for pair in pools[name]:
                    self.assertEqual(pilot.key(pair[0]["board"], pair[0]["side"]),
                                     pilot.key(pair[1]["board"], pair[1]["side"]))
                    self.assertEqual(pair[1], cycle.transform_opening(pair[0], 2))
                    roots.append(pilot.key(pair[0]["board"], pair[0]["side"]))
            self.assertEqual(len(set(roots)), 20)
            modified = copy.deepcopy(settings)
            modified["match_config"]["exact_solver_empty_squares"] = 12
            with self.assertRaises(training.TrainingError):
                matches.validate_settings(context, modified)
            Path(settings["oracle_binary"]["path"]).write_text("different Oracle")
            with self.assertRaises(training.TrainingError):
                matches.validate_settings(context, settings)

    def test_skipped_counts_never_claim_twenty_games(self):
        report = matches.skipped("integer validation did not improve")
        self.assertEqual(report["comparison"]["status"], "not-run")
        self.assertEqual(report["comparison"]["games"], 0)
        self.assertEqual(report["oracle"]["games"], 0)

    def test_resume_only_unfinished_game_and_verify_launches_no_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, settings, artifact = self.setup_context(root)
            output = root / "output"
            observed = []
            def interrupt(phase, completed, total):
                observed.append((phase, completed))
                if phase == "matches" and completed == 1:
                    raise training.TrainingError("fixture interruption")
            with mock.patch.object(rf, "Candidate", FakeCandidate), \
                 mock.patch.object(pilot.oracle, "run_profiled_match") as oracle:
                with self.assertRaisesRegex(training.TrainingError, "fixture interruption"):
                    matches.run(context, settings, artifact, output, interrupt)
                first = (output / "games.jsonl").read_bytes()
                self.assertEqual(len(training.read_jsonl(output / "games.jsonl")), 1)
                # Equal deterministic players result in one win each per pair.
                report = matches.run(context, settings, artifact, output)
                self.assertTrue((output / "games.jsonl").read_bytes().startswith(first))
                self.assertEqual(report["comparison"]["games"], 20)
                self.assertEqual(report["comparison"]["match_points"], 10)
                self.assertEqual(report["oracle"]["status"], "not-run")
                oracle.assert_not_called()
            with mock.patch.object(rf, "Candidate") as candidate, \
                 mock.patch.object(pilot.oracle, "run_profiled_match") as oracle:
                self.assertEqual(matches.verify(context, settings, artifact, output), report)
                candidate.assert_not_called()
                oracle.assert_not_called()
            saved = training.read_json(output / "report.json")
            saved["comparison"]["match_points"] = 20
            (output / "report.json").write_bytes(pilot.blob(saved))
            with self.assertRaisesRegex(training.TrainingError, "report does not replay"):
                matches.verify(context, settings, artifact, output)

    def test_partial_game_tampering_rejected_and_timeout_preserves_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, settings, artifact = self.setup_context(root)
            output = root / "output"
            class TimeoutCandidate(FakeCandidate):
                def choose_with_diagnostic(self, identifier, board, side):
                    if identifier.startswith("optimizer-comparison-p0-m1"):
                        raise training.TrainingError("candidate timed out")
                    return super().choose_with_diagnostic(identifier, board, side)
            with mock.patch.object(rf, "Candidate", TimeoutCandidate):
                with self.assertRaisesRegex(training.TrainingError, "timed out"):
                    matches.run(context, settings, artifact, output)
            games = training.read_jsonl(output / "games.jsonl")
            self.assertEqual(len(games), 1)
            games[0]["member"] = 1
            (output / "games.jsonl").write_bytes(pilot.lines(games))
            with mock.patch.object(rf, "Candidate") as candidate:
                with self.assertRaises(training.TrainingError):
                    matches.run(context, settings, artifact, output)
                candidate.assert_not_called()

    def test_oracle_gate_rejects_saved_game_without_majority(self):
        with tempfile.TemporaryDirectory() as temporary:
            context, settings, artifact = self.setup_context(Path(temporary))
            with self.assertRaisesRegex(training.TrainingError, "gate or cap"):
                matches._verify_oracle(context, settings, [{"game": 1}], False)

    def test_majority_unlocks_oracle_and_oracle_timeout_preserves_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, settings, artifact = self.setup_context(root)
            output = root / "output"
            # Isolate the majority gate; the underlying twenty games still replay.
            summary = {"games": 20, "wins": 11, "losses": 9, "draws": 0, "match_points": 11}
            with mock.patch.object(rf, "Candidate", FakeCandidate), \
                 mock.patch.object(rf, "match_summary", return_value=summary), \
                 mock.patch.object(pilot.oracle, "run_profiled_match",
                                   side_effect=training.TrainingError("fixture Oracle timeout")) as oracle:
                with self.assertRaisesRegex(training.TrainingError, "Oracle timeout"):
                    matches.run(context, settings, artifact, output)
                self.assertEqual(len(training.read_jsonl(output / "games.jsonl")), 20)
                self.assertEqual(len(training.read_jsonl(output / "corpus-decisions.jsonl")), 2)
                self.assertFalse((output / "report.json").exists())
                oracle.assert_called_once()
                self.assertEqual(oracle.call_args.args[3], settings["openings"]["oracle-match"])
                self.assertEqual(oracle.call_args.args[4], cycle.ORACLE_PROFILE)
                self.assertEqual(oracle.call_args.args[5], matches.CONFIG)
                self.assertEqual(oracle.call_args.args[6], 310)
                self.assertEqual(oracle.call_args.kwargs["initial_games"], [])

    def test_actual_oracle_primitive_accepts_player_protocol_and_offline_replays(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, settings, artifact = self.setup_context(root)
            # Tiny legal forced-pass/endgame roots avoid thousands of fake solves.
            # These exercise the actual primitive and complete independent replay.
            opening = {"board": "BW." + "B" * 61, "side": "B", "moves": [], "rotation": 0}
            pairs = [[opening, copy.deepcopy(opening)]]
            primitive_settings = copy.deepcopy(settings)
            primitive_settings["openings"]["oracle-match"] = pairs
            records = []
            with mock.patch.object(rf, "Candidate", FakeCandidate), \
                 mock.patch.object(pilot.oracle, "run_solve", return_value=[{
                     "move": "c1", "completed_depth": 12, "exact": True}]) as solve:
                candidate = matches._Player(settings, artifact, set())
                try:
                    report = pilot.oracle.run_profiled_match(
                        Path(settings["oracle_binary"]["path"]), root, candidate,
                        pairs, cycle.ORACLE_PROFILE, settings["match_config"], 310,
                        on_game=records.append)
                finally:
                    candidate.close()
            self.assertEqual(report["games"], 2)
            self.assertEqual(len(records), 2)
            self.assertEqual(solve.call_count, 1)
            for index, game in enumerate(records):
                cycle.validate_oracle_game(primitive_settings, game, index)
            records[0]["candidate_score"] = 0
            with self.assertRaises(training.TrainingError):
                cycle.validate_oracle_game(primitive_settings, records[0], 0)

    def test_resource_evidence_rejects_over_budget_and_missing_exact(self):
        telemetry = {"completed_depth": 12, "exact": False, "nodes": 1,
                     "elapsed_us": 1, "outcome": "move"}
        with self.assertRaisesRegex(training.TrainingError, "required exact"):
            matches._telemetry(telemetry, "BW." + "B" * 61, "B")
        telemetry["nodes"] = 10000001
        with self.assertRaisesRegex(training.TrainingError, "resource"):
            matches._telemetry(telemetry, rf.INITIAL, "B")


if __name__ == "__main__":
    unittest.main()
