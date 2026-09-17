import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).resolve().parents[1] / "oracle.py"
SPEC = importlib.util.spec_from_file_location("reversi_ai_oracle", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


class OracleHarnessTests(unittest.TestCase):
    def test_generated_corpus_covers_phases_and_terminal_outcomes(self):
        records = oracle.generate_corpus()
        oracle.validate_corpus(records)

        self.assertEqual(len(records), 10)
        self.assertEqual({record["phase"] for record in records}, {"opening", "midgame", "endgame"})
        self.assertIn("Pass", {record["outcome"]["kind"] for record in records})
        self.assertIn("GameOver", {record["outcome"]["kind"] for record in records})
        self.assertEqual(records[0]["legal_moves"], ["c4", "d3", "e6", "f5"])

    def test_parse_solve_output_is_strict_and_normalizes_metrics(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| 8 | 8@100% | d3 | +4 | 000:00:01.234 | 42 | 34 |",
                "total 42 nodes in 1.234s NPS 34",
            ]
        )

        result = oracle.parse_solve_output(output, [8])

        self.assertEqual(
            result,
            [
                {
                    "move": "d3",
                    "value": 4,
                    "completed_depth": 8,
                    "nodes": 42,
                    "elapsed_ms": 1234,
                    "nps": 34,
                    "exact": True,
                }
            ],
        )

    def test_pass_rows_fail_closed_because_their_score_is_not_reported(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| - | - | ps | - | 000:00:00.001 | 0 | 0 |",
            ]
        )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(output, [1])

    def test_golden_projection_removes_only_machine_dependent_elapsed_time(self):
        reports = [
            {
                "analysis": {
                    "evaluations": [
                        {
                            "move": "d3",
                            "value": 4,
                            "completed_depth": 8,
                            "nodes": 42,
                            "elapsed_ms": 1234,
                            "exact": True,
                        }
                    ]
                }
            }
        ]

        projected = oracle.golden_projection(reports)

        self.assertNotIn("elapsed_ms", projected[0]["analysis"]["evaluations"][0])
        self.assertEqual(projected[0]["analysis"]["evaluations"][0]["nodes"], 42)
        self.assertIn("elapsed_ms", reports[0]["analysis"]["evaluations"][0])

    def test_effective_query_flips_perspective_for_forced_pass(self):
        record = next(record for record in oracle.generate_corpus() if record["position_id"] == "forced-pass")

        side, sign = oracle.effective_query(record["board"], record["side_to_move"])

        self.assertEqual(side, "W")
        self.assertEqual(sign, -1)

    def test_analysis_maps_each_root_move_and_candidate_regret(self):
        record = oracle.generate_corpus()[0]
        fixture = Path(__file__).resolve().parent / "fake_external.py"
        command = f"{__import__('sys').executable} {fixture} --candidate"

        reports = oracle.analyze_records(
            [record],
            fixture,
            fixture.parent,
            level=8,
            timeout=5,
            candidate_command=command,
        )

        analysis = reports[0]["analysis"]
        self.assertEqual(len(analysis["evaluations"]), len(record["legal_moves"]))
        self.assertEqual(analysis["selected_move"], "d3")
        self.assertEqual(analysis["selected_value"], -1)
        self.assertEqual(analysis["regret"], 0)

    def test_rust_sources_do_not_reference_the_external_oracle(self):
        repository_root = Path(__file__).resolve().parents[3]
        references = []
        for rust_file in repository_root.joinpath("rust").rglob("*.rs"):
            text = rust_file.read_text(encoding="utf-8").lower()
            if "egaroucid" in text or "reversi-ai-oracle" in text:
                references.append(rust_file)

        self.assertEqual(references, [])


if __name__ == "__main__":
    unittest.main()
