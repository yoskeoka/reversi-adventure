"""Process-free loss analysis fixtures using sealed combination inputs."""
import contextlib
from hashlib import sha256
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import table32_analyze as analysis
import table32_combine as combine
import table32_inputs as inputs
import table32_model as model
import table32_optimizer as optimizer
import table32_store as st
import training


def seal_report(root, manifest, report):
    report = st.seal({**report, "manifest_digest": st.digest(manifest), "completed_prefix_digest": "c" * 64})
    st.atomic(root / "report.json", report)
    st.atomic(root / "offline-verification.receipt.json", st.seal({
        "report_digest": st.digest(report), "manifest_digest": st.digest(manifest),
        "prefix_digest": report["completed_prefix_digest"]}))


def fixture(base):
    source, combined = base / "source", base / "combined"
    phases = list(analysis.PHASES)
    manifest = {"version": st.VERSION, "score_contract": training.SCORE_CONTRACT,
                "catalog_digest": model.CATALOG_DIGEST, "input_kind": "production",
                "seed": 4, "producer_commit": "a" * 40, "snapshot_digest": "b" * 64,
                "baseline": {"path": "/fixture/baseline", "sha256": st.BASELINE_SHA},
                "settings": {"target_phases": phases, "opening_coverage": {"version": "opening-coverage-v1"}},
                "generation_plan": [], "historical": {}}
    provenance = {"source_kind": "project-owned", "trainer_version": model.TRAINER,
                  "optimizer": model.OPTIMIZER, "seed": 4, "producer_commit": "a" * 40,
                  "input_manifest_digest": st.digest(manifest)}
    board, side = inputs.advance(inputs.rf.INITIAL, "B", "d3")
    features = model.features(board, side)
    weights = {p: {} for p in phases}
    weights[1] = {features[-1]: -16}
    artifact = model.make_artifact(weights, provenance)
    st.atomic(source / "manifest.json", manifest)
    st.atomic(source / "candidate-artifact.json", artifact)
    st.atomic(source / "prepare.receipt.json", st.seal({"manifest_digest": st.digest(manifest),
              "snapshot_digest": manifest["snapshot_digest"]}))
    exposure = st.blob("known-exposure")
    st.atomic_bytes(source / "exposure.jsonl", exposure)
    coverage = {"outputs": {}, "phase_rows": {split: {} for split in analysis.SPLITS}}
    diagnostics = [{"phase": 0, "source": "fixed-zero", "trained": False, "weights": {}}]
    for phase in phases:
        for split in analysis.SPLITS:
            name = f"{split}-{phase:02d}.jsonl"
            rows = []
            if (phase, split) == (1, "train"):
                rows.append({"id": "train-001", "canonical_key": inputs.position_key(board, side),
                             "board": board, "side": side, "phase": phase, "target": 2, "split": split,
                             "score_contract": model.SCORE_CONTRACT, "features": features,
                             "source_kind": "project-owned-s0-terminal"})
            content = b"".join(st.blob(row) for row in rows)
            st.atomic_bytes(source / "extracted" / name, content)
            coverage["outputs"][name] = sha256(content).hexdigest()
            coverage["phase_rows"][split][str(phase)] = len(rows)
            if phase and split == "train":
                counts = analysis.occurrences(rows)[1]
                state = {"phase": phase, "indices": [features[-1]], "weights": [-16.0]}
                st.atomic(source / "trained-phases" / f"p{phase:02d}.json", state)
                diagnostics.append({"phase": phase, "counts": {str(i): count for i, count in counts.items()},
                                    "float_state_digest": optimizer.state_digest(state)})
    coverage["raw_phase_rows"] = coverage["phase_rows"]
    seal_report(source, manifest, {"status": "complete", "outcome": "training-complete",
                "candidate_digest": model.digest(artifact), "coverage": coverage, "phases": diagnostics,
                "exposure_keys": {"path": "exposure.jsonl", "count": 1, "sha256": sha256(exposure).hexdigest()}})
    identity, _, _ = combine.source(source)
    combined_manifest = {"version": combine.VERSION, "coverage": "full", "phases": phases,
                         "source_runs": [identity], "producer_commit": "d" * 40}
    candidate = combine.candidate(combined_manifest, artifact["weights"])
    candidate_digest = model.digest(candidate)
    st.atomic(combined / "manifest.json", combined_manifest)
    st.atomic(combined / "candidate-artifact.json", candidate)
    st.atomic(combined / "prepare.receipt.json", st.seal({"manifest_digest": st.digest(combined_manifest),
              "candidate_digest": candidate_digest}))
    seal_report(combined, combined_manifest, {"status": "complete", "outcome": "not-improved-at-pilot-scale",
                "version": combine.VERSION, "candidate_digest": candidate_digest,
                "coverage": "full", "points": 6, "games": 20})
    return source, combined


class AnalyzeTests(unittest.TestCase):
    def test_runtime_losses_and_read_only_receipt_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source, combined = fixture(base)
            relocated = source.rename(base / "relocated")
            before = (st.inventory(relocated), st.inventory(combined))
            with mock.patch("subprocess.Popen", side_effect=AssertionError("external process")):
                report = analysis.analyze(combined, [relocated], True)
            self.assertEqual(len(report["phases"]), 60)
            phase0, phase1 = report["phases"][:2]
            self.assertTrue(phase0["fixed_zero"])
            self.assertIsNone(phase0["splits"]["train"]["integer"]["mse"])
            self.assertEqual(phase0["splits"]["train"]["missing_reason"], "no-saved-rows-for-fixed-zero-phase")
            self.assertNotIn("float", phase0["splits"]["train"])
            train = phase1["splits"]["train"]
            self.assertEqual(train["side_rows"], {"B": 0, "W": 1})
            self.assertEqual(train["teacher_rows"], {"project-owned-s0-terminal": 1})
            self.assertEqual((train["integer"]["mse"], train["integer"]["mae"]), (9, 3))
            self.assertEqual((train["float"]["mse"], train["float"]["mae"]), (6.25, 2.5))
            self.assertEqual(phase1["source_root"], "source")
            self.assertIsNone(phase1["splits"]["test"]["integer"]["mae"])
            self.assertEqual(report, analysis.analyze(combined, [relocated], True))
            self.assertEqual(before, (st.inventory(relocated), st.inventory(combined)))

    def test_clipping_and_rounding(self):
        rows = [{"features": [0], "target": 60}, {"features": [1], "target": -60},
                {"features": [2], "target": 0}]
        # First two predictions clip to ±64. The last rounds +0.5 to +1.
        weights = {0: 4091, 1: -4091, 2: 16}
        integer = optimizer.loss(rows, weights, integer=True)
        floating = optimizer.loss(rows, weights)
        self.assertEqual((integer["squared_error"], integer["absolute_error"]), (33, 9))
        self.assertEqual((floating["squared_error"], floating["absolute_error"]), (32.25, 8.5))

    def test_match_era_diagnostics_payload_is_pinned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = {"phases": [], "coverage": {}}
            report = {"manifest_digest": "a" * 64, "diagnostics_digest": st.digest(value)}
            entry = {"manifest_digest": report["manifest_digest"], "phase": "diagnostics",
                     "unit": "metrics", "value": value}
            unit = root / "units" / "0000000.json"
            st.atomic(unit, st.seal(entry))
            self.assertEqual(value, analysis.saved_diagnostics(root, report))
            st.atomic(unit, st.seal({**entry, "value": {**value, "coverage": {"changed": True}}}))
            with self.assertRaisesRegex(training.TrainingError, "saved diagnostics differ"):
                analysis.saved_diagnostics(root, report)

    def test_refuses_tampering_and_output_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            source, combined = fixture(Path(temp))
            with contextlib.redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit):
                analysis.main(["--combined-root", str(combined), "--output-dir", str(source / "out")])
            self.assertIn("output overlaps input", stderr.getvalue())
            self.assertFalse((source / "out").exists())
            path = source / "extracted" / "train-01.jsonl"
            saved = path.read_bytes()
            st.atomic_bytes(path, saved + b"\n")
            with self.assertRaisesRegex(training.TrainingError, "extracted rows changed"):
                analysis.analyze(combined, [source], False)
            st.atomic_bytes(path, saved)
            old_manifest = st.read(combined / "manifest.json")
            candidate = st.read(combined / "candidate-artifact.json")
            candidate["weights"]["1"] = {}
            candidate = combine.candidate(old_manifest, candidate["weights"])
            digest = model.digest(candidate)
            st.atomic(combined / "candidate-artifact.json", candidate)
            st.atomic(combined / "prepare.receipt.json", st.seal({"manifest_digest": st.digest(old_manifest),
                      "candidate_digest": digest}))
            seal_report(combined, old_manifest, {**st.read(combined / "report.json"), "candidate_digest": digest})
            with self.assertRaisesRegex(training.TrainingError, "source phase weights differ: 1"):
                analysis.analyze(combined, [source], False)

    def test_plots_preserve_missing_phases(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("Matplotlib is required to render plots")
        with tempfile.TemporaryDirectory() as temp:
            source, combined = fixture(Path(temp))
            report = analysis.analyze(combined, [source], False)
        for metric in ("mse", "mae"):
            image = analysis.plot(report, metric)
            self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(image, analysis.plot(report, metric))


if __name__ == "__main__":
    unittest.main()
