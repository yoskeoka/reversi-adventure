import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("setup.py")
SPEC = importlib.util.spec_from_file_location("playground_setup", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_install_publishes_adopted_model_without_training(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary = directory / "oracle"
            binary.write_text("oracle")
            binary.chmod(0o755)
            data_dir = directory / "data"
            data_dir.mkdir()

            def run(command, **_kwargs):
                self.assertEqual(command[2:4], ["validate", "--artifact"])
                self.assertEqual(Path(command[-1]).read_bytes(), setup.ADOPTED_ARTIFACT.read_bytes())

            with patch.dict(os.environ, {"REVERSI_ADVENTURE_PLAYGROUND_SETUP_DIR": str(directory / "setup")}), \
                 patch.object(setup, "oracle_paths", return_value=(binary, data_dir)), \
                 patch.object(setup.subprocess, "run", side_effect=run):
                setup.install()
            prepared = json.loads((directory / "setup" / "prepared.json").read_text())
            self.assertEqual(prepared["oracle"], {"binary": str(binary), "dataDir": str(data_dir)})
            self.assertEqual(prepared["trained"],
                             {"artifact": str(directory / "setup" / setup.ADOPTED_ARTIFACT.name), "demo": False})
            self.assertEqual(Path(prepared["trained"]["artifact"]).read_bytes(), setup.ADOPTED_ARTIFACT.read_bytes())

    def test_start_migrates_demo_and_preserves_oracle_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            package = directory / "package"
            (package / "node_modules").mkdir(parents=True)
            config = directory / "prepared.json"
            oracle = {"binary": "/verified/oracle", "dataDir": "/verified/data"}
            config.write_text(json.dumps({"trained": {"artifact": "/old/demo.json", "demo": True}, "oracle": oracle}))
            with patch.dict(os.environ, {"REVERSI_ADVENTURE_PLAYGROUND_SETUP_DIR": str(directory),
                                        "PLAYGROUND_CONFIG": "/custom/override.json"}), \
                 patch.object(setup, "PACKAGE", package), \
                 patch.object(setup.subprocess, "run") as run, \
                 patch.object(setup.os, "execvpe") as launch:
                setup.start()
                prepared = json.loads(config.read_text())
                self.assertEqual(prepared["oracle"], oracle)
                self.assertFalse(prepared["trained"]["demo"])
                self.assertEqual(Path(prepared["trained"]["artifact"]).read_bytes(), setup.ADOPTED_ARTIFACT.read_bytes())
                self.assertEqual(run.call_count, 1)
                self.assertEqual(launch.call_args.args[0:2], ("pnpm", ["pnpm", "--dir", str(package), "dev"]))
                self.assertEqual(launch.call_args.args[2]["PLAYGROUND_CONFIG"], "/custom/override.json")
                self.assertEqual(launch.call_args.args[2]["PLAYGROUND_PREPARED_CONFIG"], str(config))
                setup.start()
                self.assertEqual(run.call_count, 1, "a correct pinned cache should be reused")

    def test_missing_or_changed_source_preserves_prepared_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "source.json"
            config = directory / "prepared.json"
            original = '{"trained":{"artifact":"/old/demo.json","demo":true}}'
            config.write_text(original)
            with patch.dict(os.environ, {"REVERSI_ADVENTURE_PLAYGROUND_SETUP_DIR": str(directory)}), \
                 patch.object(setup, "ADOPTED_ARTIFACT", source), \
                 patch.object(setup, "oracle_paths", return_value=(directory / "oracle", directory)), \
                 patch.object(setup.subprocess, "run") as run:
                with self.assertRaises(FileNotFoundError):
                    setup.install()
                source.write_text("changed")
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    setup.install()
                run.assert_not_called()
            self.assertEqual(config.read_text(), original)

    def test_validation_failure_preserves_prepared_and_previous_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory / "prepared.json"
            config.write_text('{"trained":{"artifact":"/old/demo.json"}}')
            original = config.read_bytes()
            artifact = directory / setup.ADOPTED_ARTIFACT.name
            artifact.write_bytes(b"previous cached bytes")
            with patch.dict(os.environ, {"REVERSI_ADVENTURE_PLAYGROUND_SETUP_DIR": str(directory)}), \
                 patch.object(setup, "oracle_paths", return_value=(directory / "oracle", directory)), \
                 patch.object(setup.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["validate"])):
                with self.assertRaises(subprocess.CalledProcessError):
                    setup.install()
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(artifact.read_bytes(), b"previous cached bytes")
            self.assertEqual(list(directory.glob(".adopted-*")), [])

    def test_changed_cache_is_restored_from_adopted_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            artifact = directory / setup.ADOPTED_ARTIFACT.name
            artifact.write_text("modified")
            with patch.object(setup.subprocess, "run") as run:
                trained = setup.adopted_trained(directory)
            run.assert_called_once()
            self.assertFalse(trained["demo"])
            self.assertEqual(artifact.read_bytes(), setup.ADOPTED_ARTIFACT.read_bytes())

    def test_setup_directory_must_be_outside_checkout(self):
        with patch.dict(os.environ, {"REVERSI_ADVENTURE_PLAYGROUND_SETUP_DIR": str(setup.ROOT / "tmp")}):
            with self.assertRaisesRegex(ValueError, "outside the checkout"):
                setup.setup_directory()


if __name__ == "__main__":
    unittest.main()
