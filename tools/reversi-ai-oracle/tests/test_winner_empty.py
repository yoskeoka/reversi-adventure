"""Tiny independent score migration checks; no Oracle process is started."""
import copy
import contextlib
import io
from tempfile import TemporaryDirectory
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]/"oracle.py"
SPEC = importlib.util.spec_from_file_location("winner_empty_oracle", MODULE)
# Dataclasses resolve their defining module through sys.modules.
import sys
oracle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = oracle
SPEC.loader.exec_module(oracle)


class WinnerEmptyTests(unittest.TestCase):
    def fixtures(self):
        corpus = oracle.load_canonical_jsonl(MODULE.with_name("winner-empty-v1-corpus.jsonl"))
        golden = oracle.load_canonical_jsonl(MODULE.with_name("winner-empty-v1-golden.jsonl"))
        return corpus, golden

    def test_terminal_scores_include_empty_winner_draw_and_empty_board(self):
        for board, expected in (("B"*56+"W"*6+"..", 52),
                                ("BBBB...."*4+"....WWWW"*4, 0),
                                ("B"*62+"..", 64), ("W"*62+"..", -64),
                                ("B"*40+"W"*24, 16), ("."*64, 0)):
            for side, sign in (("B", 1), ("W", -1)):
                with self.subTest(board=board, side=side):
                    self.assertEqual(oracle.terminal_score(board, side), sign*expected)

    def test_tiny_golden_root_child_terminal_leaf_without_queries(self):
        corpus, golden = self.fixtures()
        def no_queries(queries, *args, **kwargs):
            self.assertEqual(queries, [])
            return []
        with patch.object(oracle, "run_solve", side_effect=no_queries), patch.object(
            oracle.subprocess, "Popen", side_effect=AssertionError("workload started")):
            analyses = oracle.analyze_records(corpus, Path("unused"), Path("unused"), oracle.CI_SMOKE_V1, 1, None)
        self.assertEqual(oracle.golden_projection(analyses), golden)
        oracle.verify_saved_golden(corpus, golden)
        children = {r["position_id"]: r["analysis"] for r in golden if r["legal_moves"]}
        self.assertEqual(children["wipeout-child"]["best_value"], 64)
        self.assertEqual(children["winner-child"]["best_value"], 52)
        config = oracle.analysis_config(1, 1, 16)
        record = next(r for r in corpus if r["position_id"] == "winner-child")
        with patch.object(oracle, "run_analysis_solve", return_value=[]) as solve:
            response = oracle.analyze_position("child", record["board"], "B", config, Path("unused"), Path("unused"), 1)
        self.assertEqual(solve.call_args.args[0], [])
        self.assertEqual(response["scores"][0]["value"], 52)
        self.assertEqual(response["schema_version"], 2)
        self.assertEqual(response["score_contract"], "winner-empty-v1")

    def test_pinned_old_golden_requires_explicit_offline_and_preserves_bytes(self):
        corpus_path, golden_path = oracle.default_paths()
        before = golden_path.read_bytes()
        corpus, golden = oracle.load_jsonl(corpus_path), oracle.load_jsonl(golden_path)
        with self.assertRaisesRegex(oracle.OracleError, "identity"):
            oracle.verify_saved_golden(corpus, golden)
        oracle.verify_saved_golden(corpus, golden, legacy_offline=True)
        self.assertEqual(golden_path.read_bytes(), before)

    def test_saved_metadata_and_relabelled_terminal_values_reject(self):
        corpus, golden = self.fixtures()
        mutations = [lambda r: r.update(score_contract="old"),
                     lambda r: r.update(schema_version=1),
                     lambda r: r["profile"]["oracle"].update(source_sha256="0"*64),
                     lambda r: r["profile"]["oracle"].update(version="8"),
                     lambda r: r["analysis"].update(best_value=50),
                     lambda r: r["analysis"].update(unverified=True)]
        for mutate in mutations:
            changed = copy.deepcopy(golden)
            mutate(changed[0])
            with self.assertRaises(oracle.OracleError):
                oracle.verify_saved_golden(corpus, changed)
        changed = copy.deepcopy(golden)
        child = next(r for r in changed if r["position_id"] == "winner-child")
        child["analysis"]["best_value"] = child["analysis"]["evaluations"][0]["value"] = 50
        with self.assertRaisesRegex(oracle.OracleError, "terminal"):
            oracle.verify_saved_golden(corpus, changed)

    def test_generators_reject_existing_evidence_before_any_process(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)/"old-evidence.jsonl"
            path.write_bytes(b"original frozen evidence\n")
            before = path.read_bytes()
            for command in ("generate-golden", "generate-benchmark-reference"):
                arguments = [command, "--output", str(path)]
                if command == "generate-benchmark-reference":
                    arguments += ["--corpus", str(path)]
                with self.subTest(command=command), patch.object(oracle, "ensure_oracle") as ensure, \
                        patch.object(oracle, "run_solve") as solve, contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(oracle.command_main(arguments), 1)
                    ensure.assert_not_called()
                    solve.assert_not_called()
                    self.assertEqual(path.read_bytes(), before)

    def test_pass_child_effective_side_keeps_root_sign(self):
        forced = next(r for r in oracle.generate_corpus() if r["position_id"] == "forced-pass")
        expected_side, sign = oracle.effective_query(forced["board"], forced["side_to_move"])
        with patch.object(oracle, "run_solve", return_value=[{"value": 7, "completed_depth": 16,
                "nodes": 1, "elapsed_ms": 0, "exact": True}]):
            report = oracle.analyze_records([forced], Path("unused"), Path("unused"), oracle.CI_SMOKE_V1, 1, None)[0]
        self.assertEqual(expected_side, oracle.other(forced["side_to_move"]))
        self.assertEqual(report["analysis"]["best_value"], sign*7)


if __name__ == "__main__":
    unittest.main()
