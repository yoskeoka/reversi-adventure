import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pattern_training", ROOT / "training.py")
assert SPEC is not None and SPEC.loader is not None
training = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(training)


class PatternTrainingTests(unittest.TestCase):
    def fixture_manifest(self):
        return ROOT / "fixtures" / "tiny-manifest.json"

    def load_fixture(self):
        manifest = training.read_json(self.fixture_manifest())
        loaded = training.validate_manifest(manifest, self.fixture_manifest().parent)
        return manifest, training.validate_records(loaded)

    def test_tiny_fixture_is_deterministic_and_contract_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_artifact, first_report = root / "one.json", root / "one-report.json"
            second_artifact, second_report = root / "two.json", root / "two-report.json"
            for artifact, report in ((first_artifact, first_report), (second_artifact, second_report)):
                training.run(self.fixture_manifest(), artifact, report)
                training.validate_artifact(training.read_json(artifact))
            self.assertEqual(first_artifact.read_bytes(), second_artifact.read_bytes())
            self.assertEqual(first_report.read_bytes(), second_report.read_bytes())
            self.assertEqual(training.read_json(first_artifact)["feature_contract"]["catalog_digest"], training.catalog_digest())
            self.assertEqual(set(training.read_json(first_report)["phase_metrics"]), {"6"})

    def test_rejects_symmetry_equivalent_split_leakage(self):
        manifest, records = self.load_fixture()
        leaking = {"schema_version": 1, "record_id": "symmetry-copy", "source": "tiny-fixture-v1",
                   "license": "CC0-1.0", "source_digest": "fixture-source-v1", "split": "held_out",
                   "board": records[0]["board"], "side": "B",
                   "target": {"semantics": training.TARGET_SEMANTICS, "value": 8}}
        loaded = [(manifest["inputs"][0], [leaking, leaking])]
        with self.assertRaises(training.TrainingError):
            training.validate_records(loaded)

    def test_rejects_missing_license_and_corrupt_artifact(self):
        manifest, records = self.load_fixture()
        bad_entry = copy.deepcopy(manifest["inputs"][0])
        bad_entry["license"] = ""
        with self.assertRaises(training.TrainingError):
            training.validate_records([(bad_entry, [])])
        artifact = training.artifact_from(manifest, records, training.digest(manifest))
        artifact["weight_digest"] = "0" * 64
        with self.assertRaises(training.TrainingError):
            training.validate_artifact(artifact)

    def test_rejects_incomplete_provenance_and_noncanonical_table_keys(self):
        manifest, records = self.load_fixture()
        artifact = training.artifact_from(manifest, records, training.digest(manifest))
        del artifact["provenance"]["seed"]
        artifact["artifact_digest"] = training.digest({key: value for key, value in artifact.items() if key != "artifact_digest"})
        with self.assertRaises(training.TrainingError):
            training.validate_artifact(artifact)
        artifact = training.artifact_from(manifest, records, training.digest(manifest))
        artifact["weights"] = {"not-a-phase": [{} for _ in range(training.FEATURE_COUNT)]}
        artifact["weight_digest"] = training.digest(artifact["weights"])
        artifact["artifact_digest"] = training.digest({key: value for key, value in artifact.items() if key != "artifact_digest"})
        with self.assertRaises(training.TrainingError):
            training.validate_artifact(artifact)

    def test_feature_vectors_match_the_fixed_catalog_contract(self):
        board = "BW.........................WB......BW..........................."
        phase, vector = training.extract_features(board, "B")
        self.assertEqual(phase, 2)
        self.assertEqual(len(vector), training.FEATURE_COUNT)
        self.assertEqual(vector[:8], [0, 0, 0, 2349, 0, 3645, 0, 0])
        self.assertEqual(training.catalog_digest(), "4d75868b40ab5aed")


if __name__ == "__main__":
    unittest.main()
