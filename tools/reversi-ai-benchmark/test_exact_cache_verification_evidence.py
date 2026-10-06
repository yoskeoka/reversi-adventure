"""Focused offline evidence checks; no games or external Oracle execution."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import exact_cache_verification_evidence as evidence
import whole_game as wg


class EvidenceTests(unittest.TestCase):
    def test_failed_receipt_queries_keep_original_failure_and_process(self):
        receipt = {"queries": [{"board": "."*64, "effective_side": "W", "child_query": True,
                                "result": {"value": -2, "exact": True}}],
                   "oracle_binary": {"sha256": "binary"}, "profile": {"depth": 12},
                   "process_observations": [{"stdout": "raw -2", "resources": {"peak_rss_kib": 42}}],
                   "report_digest": "failed-receipt", "status": "failed",
                   "failure": "independent Oracle score/continuation mismatch"}
        before = copy.deepcopy(receipt)
        record = evidence.query_record(receipt, 0, {"path": "receipt", "sha256": "pin"})
        self.assertEqual(record["result"]["value"], -2)
        self.assertTrue(record["child_query"])
        self.assertEqual(record["process_observation"], receipt["process_observations"][0])
        self.assertEqual(record["provenance"]["receipt_status"], "failed")
        self.assertEqual(record["provenance"]["receipt_failure"], receipt["failure"])
        self.assertEqual(receipt, before)
        self.assertEqual(record["identity"]["profile_digest"], hashlib.sha256(wg.canonical(receipt["profile"])).hexdigest())

    def test_reuse_requires_same_oracle_binary(self):
        profile = wg.oracle.profile_metadata(wg.oracle.profile_from_name("whole-game-depth-12-exact-20"))
        profile_digest = hashlib.sha256(wg.canonical(profile)).hexdigest()
        rows = [{"identity": {"oracle_binary_sha256": value, "profile_digest": profile_digest,
                              "score_contract": evidence.SCORE_CONTRACT}} for value in ("old", "current")]
        rows.append({"identity": {"oracle_binary_sha256": "current", "profile_digest": "wrong",
                                  "score_contract": evidence.SCORE_CONTRACT}})
        rows.append({"identity": {"oracle_binary_sha256": "current", "profile_digest": profile_digest,
                                  "score_contract": "wrong"}})
        self.assertEqual(evidence.reusable_queries({"inputs": {"oracle": {"sha256": "current"}}},
                                                  {"queries": rows}), [rows[1]])

    def test_canonical_raw_evidence_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"receipt.json"
            path.write_text('{"a": 1}\n')
            with self.assertRaisesRegex(wg.BenchmarkError, "noncanonical"):
                evidence.load(path)
            path.write_bytes(wg.canonical({"a": 1}))
            self.assertEqual(evidence.load(path), {"a": 1})

    def test_wrong_frozen_producer_code_rejected_before_import(self):
        manifest = {"harness_files": [{"path": "/old/"+relative, "sha256": "0"*64}
                                     for relative in evidence.FILES]}
        with patch.object(evidence.subprocess, "check_output", return_value=b"changed code"):
            with self.assertRaisesRegex(wg.BenchmarkError, "producer source digest"):
                with evidence.frozen_producer(manifest):
                    self.fail("unverified producer must never load")

    def test_wrong_historical_manifest_rejected_before_git(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"manifest.json"
            path.write_bytes(wg.canonical({"report_digest": "changed", "harness_revision": evidence.PRODUCER}))
            with patch.object(evidence.subprocess, "check_output") as git:
                with self.assertRaisesRegex(wg.BenchmarkError, "historical manifest mismatch"):
                    evidence.verify_evidence(directory)
                git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
