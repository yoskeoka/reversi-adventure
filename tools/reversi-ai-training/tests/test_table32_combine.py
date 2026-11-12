"""Small, process-free tests for combined table32 evidence."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import table32
import table32_combine as combine
import table32_model as model
import table32_store as st
import training
from test_table32_cycle import Providers


class CombineTests(unittest.TestCase):
    def source(self, root, phases, outcome="training-complete"):
        root.mkdir()
        manifest = {"version": st.VERSION, "score_contract": training.SCORE_CONTRACT,
                    "catalog_digest": model.CATALOG_DIGEST, "input_kind": "production",
                    "seed": 4, "producer_commit": "a" * 40, "snapshot_digest": "b" * 64,
                    "baseline": {"path": "/fixture/baseline", "sha256": st.BASELINE_SHA},
                    "settings": {"target_phases": phases}, "generation_plan": [], "historical": {}}
        provenance = {"source_kind": "project-owned", "trainer_version": model.TRAINER,
                      "optimizer": model.OPTIMIZER, "seed": 4,
                      "producer_commit": "a" * 40, "input_manifest_digest": st.digest(manifest)}
        artifact = model.make_partial_artifact({p: {} for p in phases}, provenance)
        st.atomic(root / "manifest.json", manifest)
        st.atomic(root / "candidate-artifact.json", artifact)
        st.atomic(root / "prepare.receipt.json", st.seal({"manifest_digest": st.digest(manifest),
                  "snapshot_digest": manifest["snapshot_digest"]}))
        st.atomic_bytes(root / "exposure.jsonl", st.blob("known-exposure"))
        report = st.seal({"manifest_digest": st.digest(manifest), "status": "complete", "outcome": outcome,
                          "candidate_digest": model.digest(artifact), "completed_prefix_digest": "c" * 64,
                          "exposure_keys": {"path": "exposure.jsonl", "count": 1,
                                            "sha256": training.sha256_file(root / "exposure.jsonl")}})
        st.atomic(root / "report.json", report)
        st.atomic(root / "offline-verification.receipt.json", st.seal({"report_digest": st.digest(report),
                  "manifest_digest": st.digest(manifest), "prefix_digest": report["completed_prefix_digest"]}))
        return manifest, artifact

    def test_saved_sources_overlap_corruption_and_full_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            self.source(base / "early", list(range(12)))
            self.source(base / "late", list(range(12, 60)), "not-improved-at-pilot-scale")
            records, weights, exposure = combine.collect([base / "early", base / "late"])
            self.assertEqual(len(weights), 60)
            self.assertEqual(exposure, {"known-exposure"})
            self.assertEqual(records[1]["outcome"], "not-improved-at-pilot-scale")
            manifest = {"producer_commit": "d" * 40}
            artifact = combine.candidate(manifest, weights)
            self.assertEqual(artifact["identity"], model.IDENTITY)
            self.assertEqual(artifact["provenance"]["input_manifest_digest"], st.digest(manifest))
            with self.assertRaisesRegex(training.TrainingError, "duplicate source"):
                combine.collect([base / "early", base / "early"])
            self.source(base / "overlap", [11, 12])
            with self.assertRaisesRegex(training.TrainingError, "duplicate phase"):
                combine.collect([base / "early", base / "overlap"])
            st.atomic_bytes(base / "late" / "exposure.jsonl", st.blob("tampered"))
            with self.assertRaisesRegex(training.TrainingError, "exposure digest"):
                combine.collect([base / "late"])

    def test_match_interrupt_resume_and_offline_verification(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temp)
            manifest = {"version": combine.VERSION, "producer_commit": "a" * 40, "seed": 9,
                        "coverage": "partial", "phases": [40], "input_kind": "fixture",
                        "settings": {"target_phases": [40], "time_limit_ms": None,
                                     "node_limit": None, "decision_timeout_seconds": None},
                        "limits": st.LIMITS, "exposure_digest": st.digest(["old"]), "source_runs": []}
            artifact = combine.candidate(manifest, {40: {}})
            st.atomic(root / "candidate-artifact.json", artifact)
            provider = Providers()
            calls = 0
            def interrupted(kind, identifier, board, side, config):
                nonlocal calls
                calls += 1
                if calls == 70:
                    raise RuntimeError("fixture interruption")
                return provider.choose(kind, identifier, board, side, config)
            with self.assertRaisesRegex(RuntimeError, "fixture interruption"):
                combine.evaluate(table32.Driver(root, manifest, execute=True,
                                 providers=(interrupted, provider.solve)), artifact, {"old"})
            saved = len(list((root / "units").glob("*.json")))
            self.assertGreater(saved, 3)
            driver = table32.Driver(root, manifest, execute=True, providers=(provider.choose, provider.solve))
            report = combine.evaluate(driver, artifact, {"old"})
            driver.finish()
            self.assertEqual(report["games"], 20)
            self.assertEqual(report["match_profile"]["opening_depth"], 4)
            self.assertFalse(report["full_pilot_equivalent"])
            name = "screening-report.json" if report["outcome"] == "awaiting-explicit-continue" else "report.json"
            st.atomic(root / name, report)
            with mock.patch.object(combine, "load", return_value=(manifest, artifact, {"old"})), \
                 mock.patch("subprocess.run", side_effect=AssertionError("offline subprocess")), \
                 mock.patch("subprocess.Popen", side_effect=AssertionError("offline subprocess")):
                self.assertEqual(combine.verify(root), report)

    def test_full_candidate_screen_then_explicit_extension(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temp)
            manifest = {"version": combine.VERSION, "producer_commit": "a" * 40, "seed": 9,
                        "coverage": "full", "phases": list(range(60)), "input_kind": "fixture",
                        "settings": {"time_limit_ms": None, "node_limit": None,
                                     "decision_timeout_seconds": None}, "limits": st.LIMITS,
                        "exposure_digest": st.digest(["old"]), "source_runs": []}
            artifact = combine.candidate(manifest, {p: {} for p in range(60)})
            st.atomic(root / "candidate-artifact.json", artifact)
            provider = Providers()
            def game(index, opening, choose, config):
                self.assertEqual(config["opening_depth"], 12)
                return {"index": index, "decisions": [], "terminal_board": opening["board"],
                        "score_candidate": 1, "points": 1}
            with mock.patch.object(table32, "match_game", side_effect=game):
                driver = table32.Driver(root, manifest, execute=True, providers=(provider.choose, provider.solve))
                screen = combine.evaluate(driver, artifact, {"old"})
                driver.finish()
                self.assertEqual((screen["games"], screen["outcome"]), (20, "awaiting-explicit-continue"))
                st.atomic(root / "screening-report.json", screen)
                st.atomic(root / "screening-verification.receipt.json", st.seal({
                    "report_digest": st.digest(screen), "manifest_digest": st.digest(manifest),
                    "prefix_digest": screen["completed_prefix_digest"]}))
                driver = table32.Driver(root, manifest, execute=True, providers=(provider.choose, provider.solve))
                report = combine.evaluate(driver, artifact, {"old"}, extend=True)
                driver.finish()
                self.assertEqual((report["games"], report["points"], report["outcome"]),
                                 (200, 200, "promising-at-pilot-scale"))
                self.assertEqual(report["match_profile"]["fallback"], "none")
                st.atomic(root / "report.json", report)
                with mock.patch.object(combine, "load", return_value=(manifest, artifact, {"old"})), \
                     mock.patch("subprocess.Popen", side_effect=AssertionError("offline subprocess")):
                    self.assertEqual(combine.verify(root), report)
                    st.atomic(root / "screening-report.json", {**screen, "points": 0})
                    with self.assertRaisesRegex(training.TrainingError, "screening report differs"):
                        combine.verify(root)


if __name__ == "__main__":
    unittest.main()
