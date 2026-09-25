import importlib.util
import hashlib
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

            def fake_run(argv):
                binary = Path(argv[0]).name
                record = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
                calls.append((binary, record["position_id"]))
                elapsed = 100 if binary == "baseline" else 80
                output = json.dumps({
                    "position_id": record["position_id"], "elapsed_ns": elapsed,
                    "board_digest": hashlib.sha256(record["board"].encode("ascii")).hexdigest(),
                    "nodes_searched": 1, "outcome": {"kind": "move", "move": "a1"},
                    "score": 0, "pv": ["a1"], "completed_depth": 16 if record["stone_count"] == 48 else 12,
                    "exact": record["stone_count"] == 48, "timing_success": True,
                })
                return compare.MeasuredProcess(0, output + "\n", "", 200, 100, 10, 1024)

            with patch.object(compare, "environment", return_value={"os": "test", "host": "test",
                                                                   "cpu_model": "test",
                                                                   "measurement_method": "linux-wait4"}):
                report = compare.compare(baseline, candidate, records, 5, 1, fake_run)
            self.assertFalse(compare.verify_report(report, records))
            relocated_baseline = root / "relocated-baseline"
            relocated_baseline.write_bytes(baseline.read_bytes())
            self.assertTrue(compare.verify_report(report, records, relocated_baseline, candidate))
            relocated_baseline.write_bytes(b"wrong")
            with self.assertRaisesRegex(compare.ComparisonError, "baseline binary digest changed"):
                compare.verify_report(report, records, relocated_baseline, candidate)
            report["workloads"][0]["geometric_mean_ratio"] = 0.9
            with self.assertRaisesRegex(compare.ComparisonError, "aggregates do not match"):
                compare.verify_report(report, records)
            report["workloads"][0]["geometric_mean_ratio"] = 0.8

        self.assertEqual(len(report["raw_samples"]), 160)
        self.assertEqual(report["positions"][0]["baseline_median_ns"], 100)
        self.assertEqual(report["positions"][0]["candidate_median_ns"], 80)
        self.assertEqual(report["positions"][0]["ratio"], 0.8)
        self.assertEqual(report["positions"][0]["baseline"]["cpu_ns"], 110)
        self.assertEqual(report["workloads"][0]["baseline_peak_rss_kib"], 1024)
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

            def fake_run(argv):
                record = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
                sample = {"position_id": record["position_id"], "elapsed_ns": 1, "nodes_searched": 1, "outcome": {}, "score": 0, "pv": [], "completed_depth": 0, "exact": False, "timing_success": False, "timing_failure_reason": "incomplete_depth"}
                return compare.MeasuredProcess(0, json.dumps(sample) + "\n", "", 200, 100, 10, 1024)

            with self.assertRaisesRegex(compare.ComparisonError, "did not complete"):
                compare.compare(baseline, candidate, records, 5, 1, fake_run)

    def test_requires_positive_repetitions(self):
        with self.assertRaisesRegex(compare.ComparisonError, "positive"):
            compare.compare(Path(__file__), Path(__file__), self.corpus(), 0, 1)

    def test_rejects_missing_resources_and_result_mismatch(self):
        records = self.corpus()
        record = records[0]
        sample = {
            "position_id": record["position_id"], "board_digest": hashlib.sha256(record["board"].encode("ascii")).hexdigest(), "elapsed_ns": 100,
            "nodes_searched": 100, "outcome": {"kind": "move", "move": "a1"},
            "score": 1, "pv": ["a1"], "completed_depth": 12,
            "exact": False, "timing_success": True,
        }
        resources = {"process_elapsed_ns": 200, "user_cpu_ns": 100,
                     "system_cpu_ns": 20, "peak_rss_kib": 1000}
        raw = [{"binary": label, "position_id": record["position_id"],
                "repetition": 1, "workload": compare.workload(record),
                "sample": dict(sample), "resource_usage": dict(resources)}
               for label in ("baseline", "candidate")]
        with self.assertRaisesRegex(compare.ComparisonError, "missing or invalid peak_rss_kib"):
            raw[1]["resource_usage"]["peak_rss_kib"] = 0
            compare.aggregate(raw, [record], [1])
        raw[1]["resource_usage"]["peak_rss_kib"] = 1000
        raw[1]["sample"]["nodes_searched"] = 99
        with self.assertRaisesRegex(compare.ComparisonError, "result or node mismatch"):
            compare.aggregate(raw, [record], [1])

    def test_rejects_duplicate_or_missing_pair(self):
        record = self.corpus()[0]
        raw = [{"binary": "baseline", "position_id": record["position_id"],
                "repetition": 1, "workload": compare.workload(record), "sample": {}}]
        with self.assertRaisesRegex(compare.ComparisonError, "missing or duplicate"):
            compare.aggregate(raw, [record], [1])


if __name__ == "__main__":
    unittest.main()
