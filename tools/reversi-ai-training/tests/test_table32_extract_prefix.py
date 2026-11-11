"""Coverage reports both imported and operator-selected start positions."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reinforcement as rf
import table32_extract as extraction
import table32_inputs as inputs


class PrefixCoverageTests(unittest.TestCase):
    def test_custom_and_imported_prefixes_are_reported_without_losing_legacy_keys(self):
        old_spec = {"game_id": "old", "split": "train", "prefix_length": 13}
        new_spec = {"game_id": "new", "split": "validation", "prefix_length": 39}
        old = {"spec": old_spec, "decisions": [{"board": rf.INITIAL, "side": "B"}],
               "final_score_black": 0}
        new = {"spec": new_spec}
        row = {"id": "new-000", "game_id": "new", "split": "validation", "prefix_length": 39,
               "board": rf.INITIAL, "side": "W", "phase": 0, "target": 0,
               "canonical_key": inputs.position_key(rf.INITIAL, "W")}
        with tempfile.TemporaryDirectory() as root, patch.object(inputs, "replay_game", return_value=[row]):
            report = extraction.build([old, new], [], [old_spec, new_spec], root,
                                      early_limit=1, target_phases=[0], expected_prefixes=[39],
                                      trusted_import_count=1)
        for name in ("prefix_rows", "raw_prefix_rows"):
            self.assertEqual(report[name]["train"]["13"], 1)
            self.assertEqual(report[name]["validation"]["39"], 1)
            self.assertEqual(report[name]["train"]["39"], 0)
            self.assertTrue(set(map(str, inputs.PREFIX_LENGTHS)) <= set(report[name]["train"]))


if __name__ == "__main__":
    unittest.main()
