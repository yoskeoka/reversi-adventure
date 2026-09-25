import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnose


class DiagnosticTests(unittest.TestCase):
    def test_rejects_trace_or_node_mismatch(self):
        corpus = Path(__file__).resolve().parents[1] / "positions-v1.jsonl"
        records = diagnose.load_corpus(corpus)
        rows = []
        for record in records:
            rows.append({
                "position_id": record["position_id"], "board_digest": "board",
                "outcome": {"kind": "move", "move": "a1"}, "score": 1,
                "pv": ["a1"], "completed_depth": 0, "exact": False,
                "nodes_searched": 1, "node_limit": 100,
                "evaluator": "trained", "artifact_sha256": "a" * 64,
                "evaluator_context": 1,
                "cost_diagnostics": {"trace_sha256": "b" * 64,
                                     "trace_events": 1, "counters": {}},
            })
        with TemporaryDirectory() as temp:
            paths = [Path(temp) / name for name in ("original", "tuned", "trained")]
            for path in paths:
                path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            self.assertEqual(len(diagnose.report(corpus, *paths)["positions"]), 16)
            changed = json.loads(paths[1].read_text(encoding="utf-8").splitlines()[0])
            changed["cost_diagnostics"]["trace_sha256"] = "c" * 64
            paths[1].write_text(json.dumps(changed) + "\n" +
                                "".join(json.dumps(row) + "\n" for row in rows[1:]), encoding="utf-8")
            with self.assertRaisesRegex(diagnose.ComparisonError, "ordered trace mismatch"):
                diagnose.report(corpus, *paths)
            changed["cost_diagnostics"]["trace_sha256"] = "b" * 64
            changed["nodes_searched"] = 2
            paths[1].write_text(json.dumps(changed) + "\n" +
                                "".join(json.dumps(row) + "\n" for row in rows[1:]), encoding="utf-8")
            with self.assertRaisesRegex(diagnose.ComparisonError, "result or node mismatch"):
                diagnose.report(corpus, *paths)
