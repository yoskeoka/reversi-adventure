import contextlib
import io
import itertools
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import table32
import table32_inputs as inputs
import table32_model as model
import table32_store as st


def fixture_manifest(proposals=2):
    return {"seed": inputs.SEED, "producer_commit": "a" * 40, "input_kind": "fixture",
            "settings": {"max_steps": 2, "max_proposals": proposals}, "limits": {}}


def fixture_rows(folder):
    folder.mkdir()
    # Exercise repeated self-reversing coordinates and count cap in every
    # phase.  These are arithmetic fixtures, never claimed as game teachers.
    for phase in range(60):
        row = {"features": [model.OFFSETS[16] + 2] * 65, "target": 1}
        (folder / f"train-{phase:02}.jsonl").write_bytes(st.blob(row))
        (folder / f"validation-{phase:02}.jsonl").write_bytes(b"")


def complete(driver, folder):
    weights, diagnostics, paused = table32.learn_phases(driver, folder)
    if paused is not None:
        return None, None, paused
    artifact = model.make_artifact(weights, {
        "trainer_version": model.TRAINER, "optimizer": model.OPTIMIZER,
        "seed": driver.m["seed"], "input_manifest_digest": st.digest(driver.m),
        "producer_commit": driver.m["producer_commit"], "source_kind": "project-owned"})
    driver.computed("export", "candidate-artifact", artifact)
    driver.computed("diagnostics", "metrics", diagnostics)
    report = table32.final_report(driver.m, driver, "not-improved-at-pilot-scale", {
        "candidate_digest": model.digest(artifact), "diagnostics_digest": st.digest(diagnostics)})
    driver.finish()
    return artifact, report, diagnostics


class InterruptedFixture(Exception):
    pass


class InterruptingDriver(table32.Driver):
    def computed(self, *args, **kwargs):
        value = super().computed(*args, **kwargs)
        if self.journal.cursor == 73:
            raise InterruptedFixture("bounded fixture interruption")
        return value


class Table32CycleOptimizerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.folder = self.base / "rows"
        fixture_rows(self.folder)
        self.stderr = contextlib.redirect_stderr(io.StringIO())
        self.stderr.__enter__()
        self.addCleanup(self.stderr.__exit__, None, None, None)

    def driver(self, name, *, execute=True, manifest=None, cls=table32.Driver):
        root = self.base / name
        root.mkdir(exist_ok=True)
        return cls(root, manifest or fixture_manifest(), execute=execute)

    def test_all_phase_training_precedes_export_and_count_diagnostics(self):
        driver = self.driver("continuous")
        artifact, report, diagnostics = complete(driver, self.folder)
        phases = [st.read(path)["phase"] for path in sorted((driver.root / "units").glob("*.json"))]
        first_export = phases.index("export")
        self.assertEqual(set(phases[:first_export]), {"phase-training"})
        self.assertEqual(set(phases[first_export:]), {"export", "diagnostics"})
        self.assertEqual(len(list((driver.root / "trained-phases").glob("p*.json"))), 60)
        self.assertEqual(set(artifact["weights"]), {str(p) for p in range(60)})
        for diagnostic in diagnostics:
            self.assertEqual(list(diagnostic["counts"].values()), [130])
            self.assertEqual(list(diagnostic["capped_counts"].values()), [50])
            self.assertEqual(diagnostic["unobserved_parameters"], model.PARAMETER_COUNT - 1)
            self.assertEqual(diagnostic["observed_parameters"], 1)
            self.assertEqual(diagnostic["occurrence_histogram"]["130"], 1)
            self.assertEqual(diagnostic["occurrence_histogram"]["0"], model.PARAMETER_COUNT - 1)
            self.assertEqual(diagnostic["capped_occurrence_histogram"]["50"], 1)
            self.assertEqual(diagnostic["table_coverage"][16]["observed"], 1)
            self.assertEqual(diagnostic["validation_precision"]["prediction_clipping"]["float_rate"], None)
            self.assertEqual(diagnostic["validation_status"], "validation-unavailable")
        self.assertTrue(report["tooling_only"])

    def test_multi_digit_parameter_diagnostics_replay_after_json_storage(self):
        (self.folder/"train-00.jsonl").write_bytes(st.blob({
            "features":[6560,20000,612366],"target":1}))
        continuous=complete(self.driver("diagnostics"),self.folder)
        self.assertTrue(all(type(k) is str for k in continuous[2][0]["counts"]))
        with patch("subprocess.Popen",side_effect=AssertionError("offline process")):
            replay=complete(self.driver("diagnostics",execute=False),self.folder)
        self.assertEqual(st.digest(continuous[1]),st.digest(replay[1]))

    def test_precision_metrics_distinguish_clip_quantization_and_runtime_rounding(self):
        rows = [{"features": [0, 0], "target": 1}]
        measured = table32.phase_precision_metrics(rows, {0: 1100.25}, {0: 1100})
        self.assertEqual(measured["prediction_clipping"], {
            "rows": 1, "float_count": 1, "export_count": 1, "float_rate": 1, "export_rate": 1})
        self.assertEqual(measured["errors"]["float_to_export_raw32"]["squared_error"], .25)
        self.assertEqual(measured["errors"]["runtime_disc"]["squared_error"], 63 ** 2)
        self.assertEqual(measured["errors"]["export_to_runtime_disc"]["squared_error"], 0)
        self.assertEqual(measured["errors"]["export_raw32"]["units"], "raw32")
        rounding = table32.phase_precision_metrics(rows, {0: 7.5}, {0: 8})
        self.assertEqual(rounding["errors"]["export_clipped_disc"]["mse"], .25)
        self.assertEqual(rounding["errors"]["runtime_disc"]["mse"], 0)
        self.assertEqual(rounding["errors"]["export_to_runtime_disc"]["mse"], .25)

    def test_interrupted_phase_training_matches_continuous_artifact_and_report(self):
        continuous = complete(self.driver("continuous"), self.folder)
        with self.assertRaises(InterruptedFixture):
            complete(self.driver("resumed", cls=InterruptingDriver), self.folder)
        resumed = complete(self.driver("resumed"), self.folder)
        self.assertEqual(model.digest(continuous[0]), model.digest(resumed[0]))
        self.assertEqual(st.digest(continuous[1]), st.digest(resumed[1]))
        self.assertEqual(continuous[2], resumed[2])
        with patch("subprocess.Popen", side_effect=AssertionError("no subprocess in offline replay")):
            offline = complete(self.driver("resumed", execute=False), self.folder)
        self.assertEqual(st.digest(offline[1]), st.digest(resumed[1]))

    def test_export_slice_excludes_old_prefix_revalidation_time(self):
        manifest = fixture_manifest(proposals=3)
        continuous = complete(self.driver("continuous", manifest=manifest), self.folder)
        # Pause after the first newly completed export proposal.
        with patch.object(table32, "time", SimpleNamespace(monotonic=iter((0, 61)).__next__)):
            paused = complete(self.driver("resumed", manifest=manifest), self.folder)
        self.assertEqual(paused, (None, None, 0))
        # Old-prefix replay takes 10,000 artificial seconds.  New proposals
        # take one second each and must continue rather than repeatedly pause.
        ticks = itertools.chain((0, 10000, 10001, 10002, 10003), itertools.count(10004))
        with patch.object(table32, "time", SimpleNamespace(monotonic=ticks.__next__)):
            resumed = complete(self.driver("resumed", manifest=manifest), self.folder)
        self.assertIsNotNone(resumed[0])
        self.assertEqual(model.digest(continuous[0]), model.digest(resumed[0]))
        self.assertEqual(st.digest(continuous[1]), st.digest(resumed[1]))

    def test_materialized_state_is_checked_against_reconstructed_arithmetic(self):
        driver = self.driver("tampered")
        complete(driver, self.folder)
        path = driver.root / "trained-phases/p23.json"
        state = st.read(path)
        state["weights"][0] += .25
        st.atomic(path, state)
        with self.assertRaisesRegex(Exception, "materialization differs"):
            complete(self.driver("tampered", execute=False), self.folder)


if __name__ == "__main__":
    unittest.main()
