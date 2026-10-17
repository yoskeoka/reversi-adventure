"""Streaming diagnostics and a production-sized synthetic corpus memory regression."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
import input_bundle as bundle
import reinforcement
import training


class JsonlStreamingTests(unittest.TestCase):
    def test_precomputed_board_keys_match_original_coordinate_transforms(self):
        for board in (reinforcement.INITIAL, "." * 64, "BW." * 21 + "B",
                      reinforcement.apply_move(reinforcement.INITIAL, "B", "d3")):
            for symmetry in range(8):
                expected = "".join(board[training.transform(square, training.inverse(symmetry))]
                                   for square in range(64))
                self.assertEqual(training.board_key(board, symmetry), expected)

    def test_streams_without_read_text_and_preserves_rows_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rows.jsonl"
            path.write_text('\n{"id":1}\n \n{"id":2}\n')
            with patch.object(Path, "read_text", side_effect=AssertionError("bulk read")):
                self.assertEqual(list(training.iter_jsonl(path)), [{"id": 1}, {"id": 2}])
                self.assertEqual(training.read_jsonl(path), [{"id": 1}, {"id": 2}])
            for invalid, diagnostic in (("{", "invalid JSON"), ("[]", "record must be an object"),
                                        ('{"value":NaN}', "non-finite"),
                                        ('{"value":Infinity}', "non-finite")):
                with self.subTest(invalid=invalid):
                    path.write_text('{"id":1}\n\n' + invalid + "\n")
                    rows = training.iter_jsonl(path)
                    self.assertEqual(next(rows), {"id": 1})
                    with self.assertRaises(training.TrainingError) as caught:
                        next(rows)
                    self.assertIn(f"{path}:3:", str(caught.exception))
                    self.assertIn(diagnostic, str(caught.exception))
            with self.assertRaisesRegex(training.TrainingError, "cannot read"):
                list(training.iter_jsonl(path.with_name("missing.jsonl")))

    def test_split_exclusions_match_list_reader_and_d4_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            board = reinforcement.apply_move(reinforcement.INITIAL, "B", "d3")
            mirrored = board[::-1]
            for split, rows in zip(bundle.random_inputs.SPLITS,
                                   ([{"board": board, "side": "W"}],
                                    [{"board": mirrored, "side": "W"}],
                                    [{"board": board, "side": "B"}])):
                (directory / f"{split}.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in rows))
            expected = {training.canonical_position_key(row["board"], row["side"])
                        for split in bundle.random_inputs.SPLITS
                        for row in training.read_jsonl(directory / f"{split}.jsonl")}
            self.assertEqual(len(expected), 2)
            with patch.object(training, "read_jsonl", side_effect=AssertionError("bulk reader")):
                self.assertEqual(bundle.split_position_keys(directory), expected)

    @unittest.skipUnless(sys.platform == "linux", "Linux resource budget regression")
    def test_full_size_synthetic_exclusions_and_corpus_replay_fit_256_mib(self):
        # These synthetic rows exercise memory only; they are never production evidence.
        script = r"""
import json, resource, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import corpus, input_bundle, training
limit = 256 * 1024 * 1024
resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
directory = Path(sys.argv[2])
index = 0
for split, count in (("train", 107210), ("validation", 13396), ("held_out", 13415)):
    with (directory / (split + ".jsonl")).open("w") as stream:
        for _ in range(count):
            board = format(index, "018b").translate(str.maketrans("01", "BW")) + "." * 46
            stream.write(json.dumps({"board": board, "side": "B", "padding": "x" * 384}) + "\n")
            index += 1
keys = input_bundle.split_position_keys(directory)
assert len(keys) > 100000
output = directory / "corpus"
corpus.generate(11, keys, output, progress_every=256)
result = corpus.verify(output, keys)
print(json.dumps({"records": index, "keys": len(keys), "roots": result["count"],
                  "rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
"""
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, "-c", script, str(TOOL), temporary],
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        measured = json.loads(result.stdout)
        self.assertEqual(measured["records"], 134021)
        self.assertEqual(measured["roots"], 12)
        self.assertLess(measured["rss_kib"], 256 * 1024)
        print(f"synthetic corpus memory regression: {measured}", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
