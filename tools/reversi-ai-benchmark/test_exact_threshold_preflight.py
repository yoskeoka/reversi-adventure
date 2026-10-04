"""Preflight rejects inconsistent derived evidence without starting a search."""

import copy
import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import exact_threshold as et
from test_exact_threshold import FakeSeat, SOURCE, USAGE, fake_oracle_solve, fake_measured


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.roots = et.freeze_roots(SOURCE)
        self.manifest = {"report_digest": "manifest-one", "roots": self.roots,
            "pilot_units": et.units("pilot", self.roots), "output_directory": str(self.directory),
            "inputs": {"cli": {"path": "/fake/cli"}, "artifact": {"path": "/fake/artifact"},
                       "oracle": {"path": "/fake/oracle", "sha256": "1" * 64}}, "oracle_cwd": "/fake"}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.stack.enter_context(patch.object(et.wg, "Seat", FakeSeat))
        self.stack.enter_context(patch.object(et.wg, "proc_usage", side_effect=lambda _pid: dict(USAGE)))
        self.stack.enter_context(patch.object(et, "verify_manifest", return_value=self.manifest))
        FakeSeat.failure = et.wg.BenchmarkError("fixture incomplete search")
        self.addCleanup(setattr, FakeSeat, "failure", None)
        self.pilot = [et.measure_unit(self.manifest, u) for u in self.manifest["pilot_units"]]
        for result in self.pilot:
            et.verify_unit(self.manifest, result["unit"], result)
            self.save_unit(result)
        self.save_oracle_stage("pilot", self.pilot, [])
        admitted, reasons = et.admitted_thresholds(self.pilot, [])
        self.gate = et.wg.sealed({"version": et.VERSION, "manifest_digest": self.manifest["report_digest"],
            "thresholds": admitted, "excluded": reasons, "units": [], "total": 0,
            "pilot_digests": [r["report_digest"] for r in self.pilot], "oracle_digests": []})

    def save_unit(self, result):
        directory = self.directory / result["unit"]["stage"]
        directory.mkdir(exist_ok=True)
        et.wg.atomic_write(et.unit_path(directory, result["unit"]), result)

    def save_oracle_stage(self, stage, results, receipts):
        jobs = et.oracle_jobs(results)
        et.wg.atomic_write(self.directory / (stage + "-oracle-manifest.json"), et.wg.sealed({
            "version": et.VERSION, "manifest_digest": self.manifest["report_digest"],
            "jobs": jobs, "total": len(jobs)}))
        directory = self.directory / (stage + "-oracle")
        directory.mkdir(exist_ok=True)
        for receipt in receipts:
            et.wg.atomic_write(directory / (receipt["job"]["id"] + ".json"), receipt)

    def reject_before_launch(self, message):
        with patch.object(et, "measure_unit", side_effect=AssertionError("measurement started")) as measure, \
             patch.object(et, "solve_position", side_effect=AssertionError("Oracle started")) as solve:
            with self.assertRaisesRegex(et.wg.BenchmarkError, message):
                et.execute(self.directory / "manifest.json", "run", 1)
            measure.assert_not_called()
            solve.assert_not_called()

    def test_resealed_gate_metadata_and_admission_rejected_before_launch(self):
        for field in ("pilot_digests", "oracle_digests", "excluded", "thresholds"):
            changed = copy.deepcopy(self.gate)
            if field == "excluded":
                changed[field]["16"] = "different reason"
            elif field == "thresholds":
                changed[field] = [20]
                changed["units"] = et.units("full", self.roots, [20])
                changed["total"] = 32
            else:
                changed[field] = ["wrong-source"]
            et.wg.atomic_write(self.directory / "full-manifest.json", et.wg.sealed(changed))
            with self.subTest(field=field):
                self.reject_before_launch("full gate derived evidence mismatch")

    def test_resealed_summary_rejected_before_launch(self):
        et.wg.atomic_write(self.directory / "full-manifest.json", self.gate)
        self.save_oracle_stage("full", [], [])
        summary = et.assessment_summary([], [], [], self.gate["excluded"])
        et.wg.atomic_write(self.directory / "assessment.json", summary)
        et.preflight(self.manifest, self.directory)
        summary["interpretation"] = "unsupported performance conclusion"
        et.wg.atomic_write(self.directory / "assessment.json", et.wg.sealed(summary))
        self.reject_before_launch("assessment derived evidence mismatch")

    def test_existing_gate_requires_every_oracle_receipt_before_launch(self):
        FakeSeat.failure = None
        self.pilot[0] = et.measure_unit(self.manifest, self.pilot[0]["unit"])
        self.save_unit(self.pilot[0])
        jobs = et.oracle_jobs(self.pilot)
        self.assertGreater(len(jobs), 0)
        self.save_oracle_stage("pilot", self.pilot, [])
        self.gate["pilot_digests"] = [r["report_digest"] for r in self.pilot]
        et.wg.atomic_write(self.directory / "full-manifest.json", et.wg.sealed(self.gate))
        self.reject_before_launch("full gate has missing pilot or Oracle evidence")

    def test_partial_oracle_without_published_gate_can_resume(self):
        FakeSeat.failure = None
        self.pilot[0] = et.measure_unit(self.manifest, self.pilot[0]["unit"])
        self.save_unit(self.pilot[0])
        jobs = et.oracle_jobs(self.pilot)
        self.assertGreater(len(jobs), 1)
        with patch.object(et.wg.oracle, "run_solve", side_effect=fake_oracle_solve()), \
             patch.object(et, "measured_oracle", side_effect=fake_measured):
            receipt = et.solve_position(self.manifest, jobs[0])
        et.verify_position(self.manifest, jobs[0], receipt)
        self.save_oracle_stage("pilot", self.pilot, [receipt])
        et.preflight(self.manifest, self.directory)


if __name__ == "__main__":
    unittest.main()
