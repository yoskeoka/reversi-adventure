import copy
import importlib.util
import math
import os
from tempfile import TemporaryDirectory, TemporaryFile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_corpus_validator_rejects_non_integer_fields_and_protocol_ids(self):
        record = oracle.generate_corpus()[0]

        for field, value in (("schema_version", True), ("stone_count", 4.0)):
            malformed = copy.deepcopy(record)
            malformed[field] = value
            with self.subTest(field=field):
                with self.assertRaises(oracle.OracleError):
                    oracle.validate_corpus_record(malformed)

        malformed = copy.deepcopy(record)
        malformed["position_id"] = "bad\tid"
        with self.assertRaises(oracle.OracleError):
            oracle.validate_corpus_record(malformed)

    def test_configured_cache_root_is_absolute(self):
        with patch.dict(os.environ, {"REVERSI_ADVENTURE_ORACLE_CACHE": "relative/cache"}):
            self.assertTrue(oracle.cache_root().is_absolute())

    def test_strength_profile_serializes_and_generates_only_fixed_custom_arguments(self):
        profile = oracle.STRONG_ENGINE_HCAP_V1
        metadata = oracle.profile_metadata(profile)
        argv = oracle.oracle_argv(Path("oracle"), profile, solve_path=Path("positions.txt"), child_query=True)

        self.assertEqual(metadata["name"], "strong-engine-hcap-v1")
        self.assertEqual(metadata["candidate"]["exact_solver_empty_squares"], 16)
        self.assertEqual(
            argv,
            ["oracle", "-nobook", "-thread", "1", "-hash", "25",
             "-depthprobrange", "2", "42", "8", "100",
             "-depthprobrange", "43", "60", "12", "100", "-solve", "positions.txt"],
        )

    def test_profile_rejects_modified_range_and_selects_decision_position_boundary(self):
        malformed = oracle.OracleProfile(
            "strong-engine-hcap-v1", 25,
            (oracle.DepthProbabilityRange(1, 41, 8, "99"),), 12, 16,
        )
        with self.assertRaises(oracle.OracleError):
            oracle.validate_profile(malformed)
        self.assertEqual(oracle.profile_depth_at(oracle.STRONG_ENGINE_HCAP_V1, 44), 8)
        self.assertEqual(oracle.profile_depth_at(oracle.STRONG_ENGINE_HCAP_V1, 45), 12)

    def test_parse_solve_output_is_strict_and_normalizes_metrics(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| custom | 8@100% | d3 | +4 | 000:00:01.234 | 42 | 34 |",
                "total 42 nodes in 1.234s NPS 34",
            ]
        )

        result = oracle.parse_solve_output(output, [8], oracle.STRONG_ENGINE_HCAP_V1)

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
            oracle.parse_solve_output(output, [1], oracle.STRONG_ENGINE_HCAP_V1)

    def test_table_header_is_required_and_unique(self):
        row = "| custom | 8@100% | d3 | +4 | 000:00:01.234 | 42 | 34 |"
        summary = "total 42 nodes in 1.234s NPS 34"

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(f"{row}\n{summary}", [8], oracle.STRONG_ENGINE_HCAP_V1)

        duplicate_header = "| Level | Depth | Move | Score | Time | Nodes | NPS |"
        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(
                f"{duplicate_header}\n{duplicate_header}\n{row}\n{summary}",
                [8],
                oracle.STRONG_ENGINE_HCAP_V1,
            )

    def test_legacy_numeric_level_fails_closed_for_a_profile(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| 7 | 8@100% | d3 | +4 | 000:00:01.234 | 42 | 34 |",
            ]
        )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(output, [8], oracle.STRONG_ENGINE_HCAP_V1)

    def test_custom_profile_requires_full_mpc_probability(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| custom | 8@50% | d3 | +4 | 000:00:01.234 | 42 | 34 |",
                "total 42 nodes in 1.234s NPS 34",
            ]
        )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(output, [8], oracle.STRONG_ENGINE_HCAP_V1)

    def test_malformed_summary_fails_closed(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| 8 | 8@100% | d3 | +4 | 000:00:01.234 | 42 | 34 |",
                "total nonsense",
            ]
        )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(output, [8], oracle.CI_SMOKE_V1)

    def test_missing_or_duplicate_summary_fails_closed(self):
        table = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| 8 | 8@100% | d3 | +4 | 000:00:01.234 | 42 | 34 |",
            ]
        )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(table, [8], oracle.CI_SMOKE_V1)

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(
                table + "\ntotal 42 nodes in 1.234s NPS 34\ntotal 42 nodes in 1.234s NPS 34",
                [8],
                oracle.CI_SMOKE_V1,
            )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(
                table + "\ntotal 0 nodes in 0s NPS 0",
                [8],
                oracle.CI_SMOKE_V1,
            )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(
                table + "\ntotal 42 nodes in 1.234s NPS 34\n" + table.splitlines()[1],
                [8],
                oracle.CI_SMOKE_V1,
            )

    def test_non_finite_timeout_fails_closed(self):
        for timeout in (math.nan, math.inf, -math.inf):
            with self.subTest(timeout=timeout):
                with self.assertRaises(oracle.OracleError):
                    oracle.validate_budget(8, timeout)

    def test_protocol_line_limit_fails_closed(self):
        with TemporaryFile() as stream:
            stream.write(b"x" * (oracle.MAX_PROTOCOL_LINE_BYTES + 1))
            stream.seek(0)
            reader = oracle.TimedLineReader(stream)

            with self.assertRaises(oracle.OracleError):
                reader.read_line(1, "timed out", "unexpected EOF")

    def test_invalid_elapsed_time_fails_closed(self):
        output = "\n".join(
            [
                "| Level | Depth | Move | Score | Time | Nodes | NPS |",
                "| 8 | 8@100% | d3 | +4 | 000:99:99.234 | 42 | 34 |",
            ]
        )

        with self.assertRaises(oracle.OracleError):
            oracle.parse_solve_output(output, [8], oracle.CI_SMOKE_V1)

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
            profile=oracle.CI_SMOKE_V1,
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

    def test_cache_source_symlink_fails_closed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            source = root / "source"
            source.symlink_to(target, target_is_directory=True)

            with self.assertRaises(oracle.OracleError):
                oracle.validate_source_directory(source)

    def test_rust_sources_do_not_reference_the_external_oracle(self):
        repository_root = Path(__file__).resolve().parents[3]
        references = []
        for rust_file in repository_root.joinpath("rust").rglob("*.rs"):
            text = rust_file.read_text(encoding="utf-8").lower()
            if "egaroucid" in text or "reversi-ai-oracle" in text:
                references.append(rust_file)

        self.assertEqual(references, [])

    def test_benchmark_self_play_profile_runs_one_level_six_self_play_batch(self):
        self.assertEqual(
            oracle.oracle_argv(Path("oracle"), oracle.SEARCH_PERFORMANCE_SELF_PLAY_V1),
            ["oracle", "-nobook", "-thread", "1", "-hash", "25", "-level", "6"],
        )
        corpus = Path(__file__).resolve().parents[2] / "reversi-ai-benchmark" / "positions-v1.jsonl"
        records = oracle.load_jsonl(corpus)
        transcripts = [
            next(
                record["provenance"]["transcript"]
                for record in records
                if record["provenance"]["source_game"] == game
            )
            for game in range(1, 5)
        ]
        completed = __import__("subprocess").CompletedProcess(
            ["oracle"], 0, stdout="\n".join(transcripts), stderr=""
        )
        with patch.object(oracle.subprocess, "run", return_value=completed) as run:
            generated = oracle.run_fast_self_play(Path("oracle"), Path.cwd(), 4, 1)

        self.assertEqual(len(generated), 16)
        self.assertEqual(run.call_args.args[0][-3:], ["-selfplay", "4", "6"])

    def test_benchmark_transcript_replay_handles_console_implicit_passes(self):
        record = next(
            record for record in oracle.generate_corpus() if record["position_id"] == "forced-pass"
        )
        opponent = oracle.other(record["side_to_move"])
        move = oracle.legal_moves(record["board"], opponent)[0]

        board, side = oracle.replay_console_move(record["board"], record["side_to_move"], move)

        self.assertEqual(side, record["side_to_move"])
        self.assertEqual(board, oracle.apply_move(record["board"], opponent, move))

    def test_benchmark_transcript_must_reach_game_over(self):
        corpus = Path(__file__).resolve().parents[2] / "reversi-ai-benchmark" / "positions-v1.jsonl"
        transcript = oracle.load_jsonl(corpus)[0]["provenance"]["transcript"]

        with self.assertRaisesRegex(oracle.OracleError, "ends before game over"):
            oracle.benchmark_records_from_transcript(transcript[:-2], 1)

    def test_benchmark_validator_replays_records_and_rejects_d4_duplicates(self):
        corpus = Path(__file__).resolve().parents[2] / "reversi-ai-benchmark" / "positions-v1.jsonl"
        records = oracle.load_jsonl(corpus)
        oracle.validate_benchmark_corpus(records)

        duplicate = copy.deepcopy(records[0])
        duplicate["position_id"] = "d4-duplicate"
        duplicate["provenance"]["source_game"] = 5
        duplicate["provenance"]["game_record"] = duplicate["provenance"]["transcript"]
        malformed = records.copy()
        malformed[1] = duplicate
        with self.assertRaisesRegex(oracle.OracleError, "D4-equivalent"):
            oracle.validate_benchmark_corpus(malformed)

    def test_benchmark_corpus_file_must_be_canonical_json_lines(self):
        corpus = Path(__file__).resolve().parents[2] / "reversi-ai-benchmark" / "positions-v1.jsonl"
        records = oracle.load_jsonl(corpus)
        with TemporaryDirectory() as temporary:
            malformed = Path(temporary) / "positions.jsonl"
            malformed.write_text(
                "\n".join(__import__("json").dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(oracle.OracleError, "not canonical"):
                oracle.load_canonical_jsonl(malformed)


if __name__ == "__main__":
    unittest.main()
