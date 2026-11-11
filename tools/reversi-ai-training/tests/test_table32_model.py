"""Mathematical and shared runtime contract checks; no training subprocesses."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import table32_model as m


class Table32ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((Path(__file__).resolve().parents[3] / "rust/reversi-ai/data/table32-fixture.json").read_text())

    def test_shared_fixture(self):
        self.assertEqual(self.fixture["catalog_digest"], m.CATALOG_DIGEST)
        m.validate_artifact(self.fixture["artifact"])
        for case in self.fixture["cases"]:
            with self.subTest(case=case["board"], side=case["side"]):
                self.assertEqual(m.features(case["board"], case["side"]), case["features"])
                self.assertEqual(m.phase(case["board"]), case["phase"])
                self.assertEqual(m.predict(self.fixture["artifact"], case["board"], case["side"]), case["score"])

    def test_hand_calculated_empty_row_and_stone_count(self):
        board = self.fixture["cases"][0]["board"]
        values = m.features(board, "B")
        self.assertEqual(values[0], 3**8 - 1)
        self.assertEqual(values[64], m.OFFSETS[16] + 2)
        self.assertEqual(m.phase(board), 0)
        # A full board maps to the last phase; it never indexes phase60.
        self.assertEqual(m.phase("B" * 64), 59)

    def test_reverse_involution_for_each_permutation(self):
        for offset, size in zip(m.OFFSETS, m.SIZES):
            for index in [offset, offset + size - 1, offset + size // 2, offset + 1, offset + size // 3]:
                reversed_index = m.reverse_index(index)
                self.assertTrue(offset <= reversed_index < offset + size)
                self.assertEqual(m.reverse_index(reversed_index), index)
        self.assertEqual(m.reverse_index(m.OFFSETS[16]+17), m.OFFSETS[16]+17)

    def test_round_total_then_clip(self):
        for raw, expected in [(15,0),(-15,0),(16,1),(-16,-1),(31,1),(-31,-1),(4091*65,64),(-4091*65,-64)]:
            self.assertEqual(m.runtime_score(raw), expected)
        self.assertEqual(m.runtime_score(15+15), 1)
        self.assertEqual(m.runtime_score(15)+m.runtime_score(15), 0)

    def test_partial_phase_selection_and_legacy_fallback(self):
        provenance = self.fixture["artifact"]["provenance"]
        artifact = m.make_partial_artifact({10: {m.OFFSETS[16]+2: 32}, 30: {}}, provenance)
        m.validate_partial_artifact(artifact)
        with self.assertRaises(ValueError):
            m.validate_artifact(artifact)
        initial = self.fixture["cases"][0]["board"]
        self.assertEqual(m.predict_partial(artifact, initial, "B", lambda *_: 17), 1)
        self.assertEqual(m.predict_partial(artifact, "B" * 48 + "." * 16, "B", lambda *_: 17), 17)
        with self.assertRaises(ValueError):
            m.make_partial_artifact({}, provenance)
        with self.assertRaises(ValueError):
            m.make_partial_artifact({60: {}}, provenance)

    def test_d4_predictions_share_tables_and_reverse_pairs(self):
        for case in self.fixture["cases"]:
            board, side = case["board"], case["side"]
            for reflect in (False, True):
                for rotations in range(4):
                    transformed = ["."] * 64
                    for i, cell in enumerate(board):
                        row, col = divmod(i, 8)
                        if reflect:
                            col = 7 - col
                        for _ in range(rotations):
                            row, col = col, 7 - row
                        transformed[row * 8 + col] = cell
                    transformed = "".join(transformed)
                    self.assertEqual(m.phase(board), m.phase(transformed))
                    self.assertEqual(m.predict(self.fixture["artifact"], transformed, side), case["score"])

    def test_strict_validation_and_reverse_pair(self):
        for bad in [None, [], {"format_version": 2}]:
            with self.assertRaises(ValueError):
                m.validate_artifact(bad)
        for key in ["identity", "feature_contract", "provenance", "weight_digest", "artifact_digest"]:
            artifact = copy.deepcopy(self.fixture["artifact"])
            del artifact[key]
            with self.assertRaises(ValueError):
                m.validate_artifact(artifact)
        weights = {i:{} for i in range(60)}
        weights[0][1] = 1  # Its reverse parameter is not shared.
        with self.assertRaisesRegex(ValueError, "reverse sharing"):
            m.make_artifact(weights, self.fixture["artifact"]["provenance"])
        weights[0] = {0:4092}
        with self.assertRaisesRegex(ValueError, "weight"):
            m.make_artifact(weights, self.fixture["artifact"]["provenance"])


if __name__ == "__main__":
    unittest.main()
