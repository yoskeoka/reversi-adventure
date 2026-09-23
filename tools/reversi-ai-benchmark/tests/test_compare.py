import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


TOOL = Path(__file__).resolve().parents[1] / "compare.py"
SPEC = importlib.util.spec_from_file_location("reversi_ai_compare", TOOL)
assert SPEC is not None and SPEC.loader is not None
compare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare)


class ComparatorTests(unittest.TestCase):
    def corpus(self):
        path = Path(__file__).resolve().parents[1] / "positions-v1.jsonl"
        return compare.load_corpus(path)

    def test_alternates_samples_and_calculates_medians(self):
        records = self.corpus()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline, candidate = root / "baseline", root / "candidate"
            baseline.write_bytes(b"baseline")
            candidate.write_bytes(b"candidate")
            calls = []

            def fake_run(argv, **_kwargs):
                binary = Path(argv[0]).name
                record = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
                calls.append((binary, record["position_id"]))
                elapsed = 100 if binary == "baseline" else 80
                output = json.dumps({
                    "position_id": record["position_id"], "elapsed_ns": elapsed,
                    "nodes_searched": 1, "outcome": {"kind": "move", "move": "a1"},
                    "score": 0, "pv": ["a1"], "completed_depth": 12,
                    "exact": record["stone_count"] == 48, "timing_success": True,
                })
                return __import__("subprocess").CompletedProcess(argv, 0, output + "\n", "")

            with patch.object(compare, "environment", return_value={"os": "test"}):
                report = compare.compare(baseline, candidate, records, 5, 1, fake_run)

        self.assertEqual(len(report["raw_samples"]), 160)
        self.assertEqual(report["positions"][0]["baseline_median_ns"], 100)
        self.assertEqual(report["positions"][0]["candidate_median_ns"], 80)
        self.assertEqual(report["positions"][0]["ratio"], 0.8)
        # First two calls are the unrecorded warm-up; measured repetition two
        # starts with candidate, proving order alternation rather than a speed assertion.
        self.assertEqual(calls[2:6], [("baseline", records[0]["position_id"]), ("candidate", records[0]["position_id"]), ("candidate", records[0]["position_id"]), ("baseline", records[0]["position_id"])])

    def test_rejects_incomplete_timing_sample(self):
        records = self.corpus()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline, candidate = root / "baseline", root / "candidate"
            baseline.write_bytes(b"baseline")
            candidate.write_bytes(b"candidate")

            def fake_run(argv, **_kwargs):
                record = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
                sample = {"position_id": record["position_id"], "elapsed_ns": 1, "nodes_searched": 1, "outcome": {}, "score": 0, "pv": [], "completed_depth": 0, "exact": False, "timing_success": False, "timing_failure_reason": "incomplete_depth"}
                return __import__("subprocess").CompletedProcess(argv, 0, json.dumps(sample) + "\n", "")

            with self.assertRaisesRegex(compare.ComparisonError, "did not complete"):
                compare.compare(baseline, candidate, records, 5, 1, fake_run)

    def test_requires_positive_repetitions(self):
        with self.assertRaisesRegex(compare.ComparisonError, "positive"):
            compare.compare(Path(__file__), Path(__file__), self.corpus(), 0, 1)


if __name__ == "__main__":
    unittest.main()
