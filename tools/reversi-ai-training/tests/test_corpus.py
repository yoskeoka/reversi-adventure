import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import corpus
import training


class CorpusTests(unittest.TestCase):
    def test_repeat_replay_and_score_blind_split_exclusions(self):
        with contextlib.redirect_stderr(io.StringIO()), tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            corpus.generate(20261015, [], first)
            corpus.generate(20261015, [], second)
            self.assertEqual({p.name: p.read_bytes() for p in first.iterdir()},
                             {p.name: p.read_bytes() for p in second.iterdir()})
            result = corpus.verify(first, [])
            self.assertEqual(result["count"], 12)
            rows = corpus.oracle.load_jsonl(first / "corpus.jsonl")
            self.assertEqual({stone: sum(row["stone_count"] == stone for row in rows) for stone in corpus.STONES},
                             {20: 4, 40: 4, 48: 4})
            excluded = result["exposure_keys"]["oracle_root"][:1] + result["exposure_keys"]["oracle_child"][:1]
            filtered = Path(temporary) / "filtered"
            corpus.generate(20261015, excluded, filtered)
            filtered_result = corpus.verify(filtered, excluded)
            self.assertFalse(set(excluded) & set(filtered_result["exposure_keys"]["oracle_root"]))
            self.assertFalse(set(excluded) & set(filtered_result["exposure_keys"]["oracle_child"]))
            selection = json.loads((filtered / "selection.json").read_text())
            self.assertIn("split-exposure", {row["reason"] for row in selection["decisions"]})
            selection["decisions"][0]["reason"] = "tampered"
            (filtered / "selection.json").write_bytes(corpus.random_inputs.canonical(selection))
            with self.assertRaises(training.TrainingError):
                corpus.verify(filtered, excluded)

    def test_reservation_exclusion_and_domain_separation(self):
        with contextlib.redirect_stderr(io.StringIO()):
            records, games, _ = corpus.select(11, [])
            key = training.canonical_position_key(records[0]["board"], records[0]["side_to_move"])
            selected, _, evidence = corpus.select(11, [], [key])
            self.assertNotIn(key, {training.canonical_position_key(row["board"], row["side_to_move"]) for row in selected})
            self.assertIn("acceptance-reservation", {row["reason"] for row in evidence["decisions"]})
            self.assertNotEqual(games[0]["seed"], corpus.random_inputs.seed_for(11, 0))


if __name__ == "__main__":
    unittest.main()
