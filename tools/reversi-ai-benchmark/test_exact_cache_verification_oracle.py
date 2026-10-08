"""Offline Oracle subset, cap, provenance, failure and resume checks."""

import copy
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import exact_cache_verification_oracle as ov
from test_exact_threshold import fake_oracle_solve, fake_measured
from test_whole_game import synthetic_report


class OracleTests(unittest.TestCase):
    def setUp(self):
        self.m = {"report_digest": "a"*64, "inputs": {"oracle": {
            "path": "/fake/oracle", "sha256": "b"*64}}, "oracle_cwd": "/fake"}
        source = synthetic_report(8)
        self.results = [{"unit": {"scope": "game", "id": str(i)}, "status": "completed",
                         "report_digest": str(i), "steps": game["steps"]}
                        for i, game in enumerate(source["games"][:3])]
        self.progress = SimpleNamespace(emit=lambda *args: None)

    def measured(self, query, value=0):
        with patch.object(ov.wg.oracle, "run_solve", side_effect=fake_oracle_solve([
            {"value": value, "exact": True, "completed_depth": query["identity"]["board"].count(".")}])), \
             patch.object(ov.et, "measured_oracle", side_effect=fake_measured):
            receipt = ov.measure_query(self.m, query)
        ov.verify_query(self.m, query, receipt)
        return receipt

    def test_fixed_selection_order_caps_and_queries(self):
        stage = ov.freeze_stage(self.m, self.results)
        ov.verify_stage(self.m, stage, self.results)
        self.assertLessEqual(len(stage["roots"]), 9)
        self.assertLessEqual(stage["total"], 18)
        for result in self.results:
            candidates = [s for s in result["steps"] if s["search"]["exact"]
                          and s["board"].count(".") <= 12]
            expected = []
            for rows in (candidates[:1], [s for s in candidates if s["board"].count(".") <= 8][:1], candidates[-1:]):
                for s in rows:
                    if s["id"] not in expected:
                        expected.append(s["id"])
            self.assertEqual([r["step"]["id"] for r in stage["roots"] if r["unit_id"] == result["unit"]["id"]], expected)
        bad = copy.deepcopy(stage)
        bad["roots"] = list(reversed(bad["roots"]))
        with self.assertRaises(ov.wg.BenchmarkError):
            ov.verify_stage(self.m, ov.wg.sealed(bad), self.results)

    def test_no_selection_and_failed_game_no_extra_queries(self):
        self.results[0]["status"] = "failed"
        self.results[1]["unit"]["scope"] = "turn"
        self.results[2]["steps"] = []
        stage = ov.freeze_stage(self.m, self.results)
        self.assertEqual(stage["total"], 0)
        self.assertEqual(stage["roots"], [])

    def test_dedup_query_and_per_game_root(self):
        result = copy.deepcopy(self.results[0])
        result["unit"]["id"] = "other"
        stage = ov.freeze_stage(self.m, [self.results[0], result])
        one = ov.freeze_stage(self.m, [self.results[0]])
        self.assertEqual(stage["total"], one["total"])
        self.assertEqual(len(stage["roots"]), 2*len(one["roots"]))

    def test_reuse_complete_query_with_failed_parent_provenance(self):
        stage = ov.freeze_stage(self.m, self.results)
        query = stage["queries"][0]
        receipt = self.measured(query)
        reused = {"identity": query["identity"], "child_query": query["child_query"],
                  "result": receipt["result"], "process_observation": receipt["process_observation"],
                  "verified": True, "provenance": {"receipt_digest": "failed-parent", "query_index": 0,
                                                    "producer_revision": "42f6d57"}}
        reused["process_observation"].pop("returncode")
        reused["process_observation"].pop("exit_status")
        reduced = ov.freeze_stage(self.m, self.results, [reused])
        self.assertEqual(reduced["total"], stage["total"]-1)
        self.assertEqual(reduced["reused"][query["id"]], reused)
        for field in ("verified", "provenance"):
            bad = copy.deepcopy(reused)
            bad.pop(field)
            with self.assertRaises(ov.wg.BenchmarkError):
                ov.freeze_stage(self.m, self.results, [bad])
        bad = copy.deepcopy(reused)
        bad["identity"]["score_contract"] = "adjusted-by-one"
        self.assertEqual(ov.freeze_stage(self.m, self.results, [bad]), stage)

    def test_raw_output_resources_digest_exit_and_deadline_rejected(self):
        query = ov.freeze_stage(self.m, self.results)["queries"][0]
        receipt = self.measured(query)
        for mutation in ("stdout", "resources", "exit", "timeout", "digest", "score"):
            bad = copy.deepcopy(receipt)
            observation = bad["process_observation"]
            if mutation == "stdout":
                observation["stdout"] = ""
            elif mutation == "resources":
                observation["resources"]["peak_rss_kib"] = ov.MAX_RSS+1
            elif mutation == "exit":
                observation["returncode"] = 1
                observation["exit_status"] = 256
            elif mutation == "timeout":
                observation["wall_ns"] = ov.TIMEOUT*1_000_000_000
            elif mutation == "score":
                bad["result"]["value"] += 1
            else:
                bad["manifest_digest"] = "changed"
            with self.subTest(mutation=mutation), self.assertRaises((ov.wg.BenchmarkError, ov.wg.oracle.OracleError)):
                ov.verify_query(self.m, query, ov.wg.sealed(bad))

    def test_saved_failures_skip_and_interrupt_resume_only_missing(self):
        stage = ov.freeze_stage(self.m, self.results)
        stage["queries"] = stage["queries"][:2]
        stage["total"] = 2
        stage = ov.wg.sealed(stage)
        receipt = self.measured(stage["queries"][0])
        receipt.update(status="failed", failure="Oracle decision timeout", result=None)
        receipt["process_observation"]["wall_ns"] = 30_000_000_000
        receipt = ov.wg.sealed(receipt)
        ov.verify_query(self.m, stage["queries"][0], receipt)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            ov.wg.atomic_write(directory / f"{stage['queries'][0]['id']}.json", receipt)
            with patch.object(ov, "measure_query", side_effect=KeyboardInterrupt) as run:
                with self.assertRaises(KeyboardInterrupt):
                    ov.run_stage(self.m, stage, directory, self.progress)
                self.assertEqual(run.call_count, 1)
            second = self.measured(stage["queries"][1])
            with patch.object(ov, "measure_query", return_value=second) as run:
                summary = ov.run_stage(self.m, stage, directory, self.progress)
                self.assertEqual(run.call_count, 1)
                self.assertFalse(summary["completed"])
            with patch.object(ov, "measure_query", side_effect=AssertionError("must skip")):
                ov.run_stage(self.m, stage, directory, self.progress, verify_only=True)

    def test_mismatch_preserves_raw_scores_and_fails_assessment(self):
        stage = ov.freeze_stage(self.m, self.results[:1])
        receipts = [self.measured(q, 39) for q in stage["queries"]]
        summary = ov.assess(stage, receipts)
        self.assertFalse(summary["completed"])
        self.assertTrue(any(r["root_score"] in (39, -39) for r in summary["roots"]))
        self.assertTrue(summary["failures"])

    def test_preflight_checks_existing_only_and_rejects_unknown(self):
        stage = ov.freeze_stage(self.m, self.results)
        receipt = self.measured(stage["queries"][0])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertEqual(ov.preflight_stage(self.m, stage, directory), {})
            ov.wg.atomic_write(directory / f"{stage['queries'][0]['id']}.json", receipt)
            self.assertEqual(len(ov.preflight_stage(self.m, stage, directory)), 1)
            ov.wg.atomic_write(directory / "unknown.json", receipt)
            with self.assertRaisesRegex(ov.wg.BenchmarkError, "unknown Oracle"):
                ov.preflight_stage(self.m, stage, directory)

    def test_reused_raw_mutation_and_incomplete_query_rejected(self):
        stage = ov.freeze_stage(self.m, self.results)
        query = stage["queries"][0]
        receipt = self.measured(query)
        receipt["result"]["value"] = True
        with self.assertRaisesRegex(ov.wg.BenchmarkError, "types"):
            ov.verify_query(self.m, query, ov.wg.sealed(receipt))
        with patch.object(ov.wg.oracle, "run_solve", side_effect=fake_oracle_solve([
            {"value": 0, "exact": False, "completed_depth": 0}])), \
             patch.object(ov.et, "measured_oracle", side_effect=fake_measured):
            incomplete = ov.measure_query(self.m, query)
        ov.verify_query(self.m, query, incomplete)
        self.assertEqual(incomplete["failure"], "independent Oracle incomplete")

    def test_process_failures_require_matching_raw_reason(self):
        query = ov.freeze_stage(self.m, self.results)["queries"][0]
        good = self.measured(query)
        for reason in ("Oracle decision timeout", "Oracle peak RSS cap exceeded", "Oracle process failed"):
            failed = copy.deepcopy(good)
            failed.update(status="failed", failure=reason, result=None)
            observation = failed["process_observation"]
            if reason.endswith("timeout"):
                observation["wall_ns"] = ov.TIMEOUT*1_000_000_000
            elif "RSS" in reason:
                observation["resources"]["peak_rss_kib"] = ov.MAX_RSS+1
            else:
                observation.update(returncode=-9, exit_status=9)
            ov.verify_query(self.m, query, ov.wg.sealed(failed))
            failed["failure"] = "invented failure"
            with self.subTest(reason=reason), self.assertRaises(ov.wg.BenchmarkError):
                ov.verify_query(self.m, query, ov.wg.sealed(failed))

    def test_duplicate_reuse_allows_timings_but_rejects_conflicting_value(self):
        stage = ov.freeze_stage(self.m, self.results)
        query = stage["queries"][0]
        good = self.measured(query)
        reused = {"identity": query["identity"], "child_query": query["child_query"],
                  "result": good["result"], "process_observation": good["process_observation"],
                  "verified": True, "provenance": {"receipt_digest": "a"*64, "query_index": 0,
                                                    "producer_revision": "42f6d57"}}
        other = copy.deepcopy(reused)
        other["process_observation"]["wall_ns"] += 100
        self.assertEqual(ov.freeze_stage(self.m, self.results, [reused, other])["total"], stage["total"]-1)
        conflict = self.measured(query, 1)
        other.update(result=conflict["result"], process_observation=conflict["process_observation"])
        with self.assertRaisesRegex(ov.wg.BenchmarkError, "conflicting"):
            ov.freeze_stage(self.m, self.results, [reused, other])


if __name__ == "__main__":
    unittest.main()
