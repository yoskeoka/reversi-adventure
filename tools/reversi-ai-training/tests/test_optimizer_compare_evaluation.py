"""Evaluation-only preparation and offline verification fixtures."""
import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import optimizer_compare as comparison
import optimizer_compare_evaluation as evaluation
import optimizer_compare_matches as matches
import pilot
import production_cycle as cycle
import reinforcement as rf
import training


class EvaluationTests(unittest.TestCase):
    def fixture(self, temporary):
        base = Path(temporary)
        source = base / "0052-source"
        source.mkdir()
        candidate_cli = base / "candidate-cli"
        oracle_binary = base / "oracle"
        candidate_cli.write_text("pinned candidate cli")
        oracle_binary.write_text("pinned Oracle")
        adopted = base / "adopted.json"
        fixture_path = ROOT / "fixtures/tiny-winner-empty-manifest.json"
        trainer_manifest = training.read_json(fixture_path)
        rows = training.validate_records(training.validate_manifest(trainer_manifest, fixture_path.parent))
        artifact = training.artifact_from(trainer_manifest, rows, training.digest(trainer_manifest))
        adopted.write_bytes(pilot.blob(artifact))
        (source / "candidate-artifact.json").write_bytes(pilot.blob(artifact))
        (source / "selection.json").write_bytes(pilot.blob({"best_epoch": 1}))
        original_settings = {
            "seed": 20261025,
            "decision_timeout_seconds": 310,
            "candidate_executable": cycle.file_entry(candidate_cli),
            "oracle_binary": cycle.file_entry(oracle_binary),
            "openings": {"comparison": [], "oracle-match": []},
        }
        source_manifest = {"matches": original_settings}
        (source / "manifest.json").write_bytes(pilot.blob(source_manifest))
        report = {
            "status": "complete",
            "selection": {
                "control": {"validation_mse": 0.4},
                "candidate": {"validation_mse": 0.5},
                "validation_improved": False,
                "held_out": {"control_mse": 0.3, "candidate_mse": 0.35,
                             "control_sum_squared_error": 3, "candidate_sum_squared_error": 4},
            },
            "matches": {"comparison": {"status": "not-run"}, "oracle": {"status": "not-run"}},
        }
        (source / "report.json").write_bytes(pilot.blob(report))
        for phase in comparison.PHASES:
            (source / f"{phase}.receipt.json").write_bytes(pilot.blob({"phase": phase}))
        context = {"adopted": artifact, "adopted_path": adopted}
        frozen_matches = {
            "version": matches.MATCH_LED_VERSION,
            "seed": 20261026,
            "decision_timeout_seconds": 600,
            "candidate_executable": cycle.file_entry(candidate_cli),
            "oracle_binary": cycle.file_entry(oracle_binary),
            "oracle_source_sha256": "a" * 64,
            "oracle_profile": {"name": cycle.ORACLE_PROFILE.name},
            "oracle_profile_id": cycle.ORACLE_PROFILE.name,
            "match_config": dict(matches.CONFIG),
            "openings": {"comparison": [], "oracle-match": []},
        }
        stack = mock.patch.multiple(
            comparison,
            load=mock.DEFAULT,
            verify=mock.DEFAULT,
        )
        stack.start()
        self.addCleanup(stack.stop)
        comparison.load.return_value = (source_manifest, context)
        comparison.verify.return_value = report
        self.enter_context = mock.patch.object(matches, "prepare_match_led", return_value=frozen_matches)
        self.enter_context.start()
        self.addCleanup(self.enter_context.stop)
        self.validate_patch = mock.patch.object(matches, "validate_settings")
        self.validate_patch.start()
        self.addCleanup(self.validate_patch.stop)
        self.commit_patch = mock.patch.object(cycle, "source_commit", return_value="a" * 40)
        self.commit_patch.start()
        self.addCleanup(self.commit_patch.stop)
        args = argparse.Namespace(
            source_run_root=source,
            evaluation_root=base / "0053-evaluation",
            candidate_executable=candidate_cli,
            oracle_binary=oracle_binary,
            decision_timeout_seconds=None,
            seed=None,
        )
        return source, args, report, artifact

    def test_prepare_pins_source_without_changing_it_and_verify_stays_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, args, source_report, _ = self.fixture(temporary)
            before = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
            manifest = evaluation.prepare(args)
            self.assertEqual(manifest["source_run"]["tree_sha256"], evaluation.source_inventory(source)["tree_sha256"])
            self.assertEqual(before, {path.relative_to(source): path.read_bytes()
                                     for path in source.rglob("*") if path.is_file()})
            with mock.patch.object(rf, "Candidate", side_effect=AssertionError("offline verifier started a candidate")) as candidate, \
                 mock.patch.object(pilot.oracle, "run_profiled_match",
                                   side_effect=AssertionError("offline verifier started Oracle")) as oracle:
                pending = evaluation.verify(args.evaluation_root)
                candidate.assert_not_called()
                oracle.assert_not_called()
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(pending["outcome"], "pending-20")
            self.assertFalse(source_report["selection"]["validation_improved"])

    def test_source_tampering_is_rejected_before_evaluation(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, args, _, _ = self.fixture(temporary)
            evaluation.prepare(args)
            with (source / "report.json").open("ab") as handle:
                handle.write(b" ")
            with self.assertRaisesRegex(training.TrainingError, "source run changed"):
                evaluation.verify(args.evaluation_root)

    def test_evaluation_outcome_uses_match_points_when_reference_mse_is_worse(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, args, source_report, _ = self.fixture(temporary)
            source_manifest, context = comparison.load(source)
            source_identity = evaluation._source_identity(source, source_manifest, source_report)
            manifest = {"source_run": source_identity, "matches": {
                "candidate_executable": cycle.file_entry(args.candidate_executable),
                "oracle_binary": cycle.file_entry(args.oracle_binary),
                "oracle_source_sha256": "a" * 64,
                "oracle_profile": {"name": cycle.ORACLE_PROFILE.name},
                "decision_timeout_seconds": 600,
                "match_config": dict(matches.CONFIG),
            }, "baseline_artifact": cycle.file_entry(context["adopted_path"])}
            pending_matches = {
                "status": "pending", "outcome": "pending-200",
                "stage_20": {"status": "complete", "summary": {"games": 20, "match_points": 10},
                             "continuation_allowed": True},
                "stage_200": {"status": "pending"},
                "comparison": {"status": "complete", "games": 20, "match_points": 10},
                "continuation": {"eligible": True, "completed": False, "required_games": 200},
                "oracle": {"status": "not-run", "reason": "200-game baseline match is incomplete"},
                "corpus": {"status": "complete", "baseline": {}, "candidate": {}},
            }
            pending = evaluation.report(manifest, source_report, pending_matches)
            self.assertFalse(pending["reference_metrics"]["validation"]["candidate_improved"])
            self.assertEqual(pending["outcome"], "pending-200")
            pending_matches["status"] = "complete"
            pending_matches["outcome"] = "not-improved"
            pending_matches["stage_200"] = {"status": "complete", "summary": {"games": 200, "match_points": 100},
                                             "outcome": "not-improved"}
            pending_matches["comparison"] = {"status": "complete", "games": 200, "match_points": 100}
            pending_matches["continuation"]["completed"] = True
            pending_matches["oracle"] = {"status": "not-run", "reason": "candidate scored 100/200 or less against baseline"}
            result = evaluation.report(manifest, source_report, pending_matches)
            self.assertEqual(result["outcome"], "not-improved")
            self.assertEqual(result["oracle"]["status"], "not-run")
            self.assertFalse(result["adopted_model_replaced"])


if __name__ == "__main__":
    unittest.main()
