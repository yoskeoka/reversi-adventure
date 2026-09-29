import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("setup.py")
SPEC = importlib.util.spec_from_file_location("playground_setup", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_install_publishes_demo_and_verified_oracle_paths_last(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary = directory / "oracle"
            binary.write_text("oracle")
            binary.chmod(0o755)
            data_dir = directory / "data"
            data_dir.mkdir()

            def run(command, **_kwargs):
                if "train" in command:
                    Path(command[command.index("--artifact") + 1]).write_text("artifact")
                    Path(command[command.index("--report") + 1]).write_text("report")
                elif "validate" in command:
                    self.assertEqual(Path(command[-1]).read_text(), "artifact")
                else:
                    self.fail(f"unexpected subprocess: {command}")

            with patch.dict(os.environ, {"REVERSI_ADVENTURE_PLAYGROUND_SETUP_DIR": str(directory / "setup")}), \
                 patch.object(setup, "oracle_paths", return_value=(binary, data_dir)), \
                 patch.object(setup.subprocess, "run", side_effect=run):
                setup.install()
            prepared = json.loads((directory / "setup" / "prepared.json").read_text())
            self.assertEqual(prepared["oracle"], {"binary": str(binary), "dataDir": str(data_dir)})
            self.assertEqual(prepared["trained"],
                             {"artifact": str(directory / "setup" / "demo-trained-artifact.json"), "demo": True})
            self.assertEqual(Path(prepared["trained"]["artifact"]).read_text(), "artifact")

    def test_setup_directory_must_be_outside_checkout(self):
        with patch.dict(os.environ, {"REVERSI_ADVENTURE_PLAYGROUND_SETUP_DIR": str(setup.ROOT / "tmp")}):
            with self.assertRaisesRegex(ValueError, "outside the checkout"):
                setup.setup_directory()


if __name__ == "__main__":
    unittest.main()
