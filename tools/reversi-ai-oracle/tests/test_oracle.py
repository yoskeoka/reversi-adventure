import importlib.util
import math
from tempfile import TemporaryDirectory
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

        result = oracle.parse_solve_output(output, [8], expected_level=8)

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
            oracle.parse_solve_output(output, [1], expected_level=8)

    def test_solve_level_mismatch_fails_closed(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| 7 | 8@100% | d3 | +4 | 000:00:01.234 | 42 | 34 |",
            ]
        )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(output, [8], expected_level=8)

    def test_exact_depth_does_not_require_full_mpc_probability(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| 8 | 8@50% | d3 | +4 | 000:00:01.234 | 42 | 34 |",
                "total 42 nodes in 1.234s NPS 34",
            ]
        )

        result = oracle.parse_solve_output(output, [8], expected_level=8)

        self.assertTrue(result[0]["exact"])

    def test_malformed_summary_fails_closed(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| 8 | 8@100% | d3 | +4 | 000:00:01.234 | 42 | 34 |",
                "total nonsense",
            ]
        )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(output, [8], expected_level=8)

    def test_missing_or_duplicate_summary_fails_closed(self):
        table = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| 8 | 8@100% | d3 | +4 | 000:00:01.234 | 42 | 34 |",
            ]
        )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(table, [8], expected_level=8)

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(
                table + "\ntotal 42 nodes in 1.234s NPS 34\ntotal 42 nodes in 1.234s NPS 34",
                [8],
                expected_level=8,
            )

    def test_non_finite_timeout_fails_closed(self):
        for timeout in (math.nan, math.inf, -math.inf):
            with self.subTest(timeout=timeout):
                with self.assertRaises(oracle.OracleError):
                    oracle.validate_budget(8, timeout)

    def test_invalid_elapsed_time_fails_closed(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| 8 | 8@100% | d3 | +4 | 000:99:99.234 | 42 | 34 |",
            ]
        )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(output, [8], expected_level=8)

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

    def test_egaroucid_problem_uses_current_player_alphabet(self):
        record = oracle.generate_corpus()[0]

        self.assertEqual(
            oracle.to_egaroucid_problem(record["board"], record["side_to_move"]),
            "---------------------------OX------XO---------------------------X",
        )

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

    def test_candidate_partial_response_obeys_timeout(self):
        fixture = Path(__file__).resolve().parent / "fake_external.py"
        command = f"{__import__('sys').executable} {fixture} --partial-candidate"
        session = oracle.CandidateSession(command, fixture.parent, timeout=0.1)
        try:
            with self.assertRaises(oracle.OracleError):
                session.move("partial", "." * 64, "B")
        finally:
            session.close()

    def test_malformed_gtp_move_response_fails_closed(self):
        with self.assertRaises(oracle.OracleError):
            oracle.gtp_move_from_response(["="], "genmove black")

    def test_malformed_candidate_command_fails_closed(self):
        with self.assertRaises(oracle.OracleError):
            oracle.CandidateSession("'", Path.cwd(), timeout=1)

    def test_cache_integrity_detects_modified_binary(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            binary = source / "Egaroucid_for_Console.out"
            binary.write_bytes(b"verified")
            manifest = root / ".integrity.json"
            oracle.write_cache_integrity(manifest, source, binary)

            oracle.validate_cache_integrity(manifest, source, binary)
            binary.write_bytes(b"modified")

            with self.assertRaises(oracle.OracleError):
                oracle.validate_cache_integrity(manifest, source, binary)

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
