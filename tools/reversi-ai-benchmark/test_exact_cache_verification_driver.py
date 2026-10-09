"""Driver identity and saved-game resume boundaries, using offline fakes."""

import copy
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import exact_cache_verification as v


class DriverBoundaryTests(unittest.TestCase):
    def manifest(self, directory):
        resource = directory/"oracle-resource"
        resource.write_bytes(b"frozen-resource")
        units = v.games.units(v.sample())
        revision = "a"*40
        m = {"version": v.VERSION, "score_contract": "winner-empty-v1", "source_revision": revision, "harness_revision": revision,
             "host": {"host": "fixture"}, "settings": copy.deepcopy(v.SETTINGS),
             "games_total": 3, "conditions_total": 2, "sample": v.sample(), "units": units,
             "policies": {"turn": "exact-cache-cross-decision-suspended-v1", "game": "diagnostic-game-v1"},
             "harness_files": [v.prep.pin(resource)], "source_files": [v.prep.pin(resource)],
             "inputs": {"artifact": v.prep.pin(resource), "cli": v.prep.pin(resource)},
             "build": {"source_revision": revision,
                       "argv": ["cargo", "build", "--locked", "--release", "-p", "reversi-ai", "--bin", "reversi-ai-cli"],
                       "returncode": 0, "wall_ns": 1, "stdout": "", "stderr": "", "binary": v.prep.pin(resource)},
             "oracle_resources": [v.prep.pin(resource)],
             "oracle_cwd": str(directory), "output_directory": str(directory),
             "outputs": v.outputs(directory, units), "evidence_directory": str(directory),
             "historical_audit": {"verified": "fixture"}}
        (directory/"run-exact-cache-verification.sh").write_bytes(v.script_bytes(directory))
        return m, resource

    def verification_environment(self, stack, m, resource):
        stack.enter_context(patch.object(v, "ROOT", resource.parent))
        stack.enter_context(patch.object(v.subprocess, "check_output", return_value=resource.read_bytes()))
        stack.enter_context(patch.object(v.prep, "revision", return_value="a"*40))
        stack.enter_context(patch.object(v.prep, "host", return_value={"host": "fixture"}))
        stack.enter_context(patch.object(v, "harness_paths", return_value=[resource]))
        stack.enter_context(patch.object(v, "source_paths", return_value=[resource]))
        stack.enter_context(patch.object(v, "oracle_files", return_value=[resource]))
        stack.enter_context(patch.object(v.evidence, "verify_evidence", return_value=m["historical_audit"]))

    def test_manifest_mutations_fail_before_games_or_oracle(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            m, resource = self.manifest(directory)
            with ExitStack() as stack:
                self.verification_environment(stack, m, resource)
                game = stack.enter_context(patch.object(v.games, "measure_unit"))
                oracle = stack.enter_context(patch.object(v.queries, "measure_query"))
                mutations = {
                    "source": lambda item: item.update(source_revision="b"*40),
                    "host": lambda item: item.update(host={"host": "changed"}),
                    "settings": lambda item: item["settings"].update(exact_empty=16),
                    "input-digest": lambda item: item["inputs"]["artifact"].update(sha256="0"*64),
                    "source-digest": lambda item: item["source_files"][0].update(sha256="0"*64),
                    "harness-digest": lambda item: item["harness_files"][0].update(sha256="0"*64),
                    "oracle-resource": lambda item: item["oracle_resources"][0].update(sha256="0"*64),
                    "build-source": lambda item: item["build"].update(source_revision="b"*40),
                    "build-binary": lambda item: item["build"]["binary"].update(sha256="0"*64),
                }
                for name, mutate in mutations.items():
                    changed = copy.deepcopy(m)
                    mutate(changed)
                    v.wg.atomic_write(directory/"manifest.json", v.wg.sealed(changed))
                    with self.subTest(name=name), self.assertRaises(v.wg.BenchmarkError):
                        v.execute(directory/"manifest.json", "run", 1)
                game.assert_not_called()
                oracle.assert_not_called()

    def test_launch_script_mutation_fails_before_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            m, resource = self.manifest(directory)
            v.wg.atomic_write(directory/"manifest.json", v.wg.sealed(m))
            (directory/"run-exact-cache-verification.sh").write_text("changed")
            with ExitStack() as stack:
                self.verification_environment(stack, m, resource)
                game = stack.enter_context(patch.object(v.games, "measure_unit"))
                oracle = stack.enter_context(patch.object(v.queries, "measure_query"))
                with self.assertRaisesRegex(v.wg.BenchmarkError, "script identity"):
                    v.execute(directory/"manifest.json", "run", 1)
                game.assert_not_called()
                oracle.assert_not_called()

    def test_valid_frozen_manifest_uses_recorded_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            m, resource = self.manifest(directory)
            v.wg.atomic_write(directory/"manifest.json", v.wg.sealed(m))
            with ExitStack() as stack:
                self.verification_environment(stack, m, resource)
                # A later docs-only commit is allowed when recorded source and
                # harness still match both git history and current file pins.
                stack.enter_context(patch.object(v.prep, "revision", return_value="b"*40))
                self.assertEqual(v.verify_manifest(directory/"manifest.json")["source_revision"], "a"*40)

    def test_prepare_never_measures_and_rejects_unrelated_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root/"fake-cli"
            binary.write_bytes(b"pinned-executable")
            binary.chmod(0o755)
            artifact = root/"artifact.json"
            artifact.write_text("{}")
            args = SimpleNamespace(output_dir=root/"run", source_revision="a"*40,
                                   cli_binary=binary, oracle_binary=binary, artifact=artifact,
                                   oracle_cwd=root, evidence_dir=root)
            build = {"binary": v.prep.pin(binary)}
            with ExitStack() as stack:
                stack.enter_context(patch.object(v.prep, "revision", return_value="a"*40))
                stack.enter_context(patch.object(v.subprocess, "check_output", return_value=""))
                builder = stack.enter_context(patch.object(v, "build_cli", return_value=build))
                stack.enter_context(patch.object(v.training, "validate_artifact"))
                stack.enter_context(patch.object(v, "oracle_files", return_value=[artifact]))
                stack.enter_context(patch.object(v.evidence, "verify_evidence", return_value={}))
                reset = stack.enter_context(patch.object(v.prep, "probe_reset"))
                regression = stack.enter_context(patch.object(v, "regression"))
                stack.enter_context(patch.object(v, "verify_manifest"))
                stack.enter_context(patch.object(v, "harness_paths", return_value=[]))
                stack.enter_context(patch.object(v, "source_paths", return_value=[]))
                game = stack.enter_context(patch.object(v.games, "measure_unit"))
                oracle = stack.enter_context(patch.object(v.queries, "measure_query"))
                self.assertTrue(v.prepare(args).exists())
                self.assertTrue((args.output_dir/"run-exact-cache-verification.sh").exists())
                reset.assert_called_once()
                regression.assert_called_once()
                args.output_dir = root/"unrelated"
                builder.return_value = {"binary": {"sha256": "0"*64}}
                with self.assertRaisesRegex(v.wg.BenchmarkError, "clean repaired-source"):
                    v.prepare(args)
                self.assertFalse(args.output_dir.exists())
                game.assert_not_called()
                oracle.assert_not_called()

    def test_oracle_failure_suppresses_condition_averages(self):
        summary = {"conditions": [{"averages": {"wall_ns": 1}, "status": "completed"}]}
        with patch.object(v.games, "summary", return_value=copy.deepcopy(summary)):
            result = v.report({"report_digest": "m"}, [], {"completed": False}, {"report_digest": "r"})
        self.assertNotIn("averages", result["games"]["conditions"][0])
        self.assertFalse(result["production_adoption"])

    def test_interrupt_resumes_only_missing_games_and_skips_saved_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            units = v.games.units(v.sample())
            m = {"output_directory": str(directory), "units": units, "historical_audit": {}}
            reg = {"report_digest": "regression"}
            v.wg.atomic_write(directory/"regression.json", reg)
            def receipt(unit):
                failed = unit == units[0]
                return v.wg.sealed({"unit": unit, "status": "failed" if failed else "completed",
                                    "failure": "saved failure" if failed else None})
            stage = {"total": 0}
            with ExitStack() as stack:
                stack.enter_context(patch.object(v, "verify_manifest", return_value=m))
                stack.enter_context(patch.object(v, "regression", return_value=reg))
                stack.enter_context(patch.object(v, "verify_regression"))
                stack.enter_context(patch.object(v.games, "verify_unit"))
                stack.enter_context(patch.object(v.evidence, "reusable_queries", return_value=[]))
                stack.enter_context(patch.object(v.queries, "freeze_stage", return_value=stage))
                stack.enter_context(patch.object(v.queries, "preflight_stage", return_value={}))
                stack.enter_context(patch.object(v.queries, "run_stage", return_value={"completed": False}))
                stack.enter_context(patch.object(v, "report", return_value={"report_digest": "report"}))
                with patch.object(v.games, "measure_unit", side_effect=[receipt(units[0]), KeyboardInterrupt]) as measure:
                    with self.assertRaises(KeyboardInterrupt):
                        v.execute(directory/"manifest.json", "run", 1)
                    self.assertEqual(measure.call_count, 2)
                self.assertEqual(len(list((directory/"games").glob("*.json"))), 1)
                first = (directory/"games"/(units[0]["id"]+".json")).read_bytes()
                with patch.object(v.games, "measure_unit", side_effect=lambda manifest, unit: receipt(unit)) as measure:
                    v.execute(directory/"manifest.json", "run", 1)
                    self.assertEqual([call.args[1]["id"] for call in measure.call_args_list],
                                     [unit["id"] for unit in units[1:]])
                self.assertEqual((directory/"games"/(units[0]["id"]+".json")).read_bytes(), first)
                with patch.object(v.games, "measure_unit") as measure:
                    v.execute(directory/"manifest.json", "verify", 1)
                    measure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
