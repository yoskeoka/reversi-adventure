"""Small score fixtures only; the 13-empty investigation is never a CI solve."""
import hashlib
import json
import unittest
from pathlib import Path

import exact_score_contract as reference
import whole_game


class ScoreContractTests(unittest.TestCase):
    def test_small_terminal_contracts(self):
        boards = [
            ("full", "B" * 62 + "WW", 60, 60),
            ("early_both_alive", "." + "B" * 14 + "W" + "B" * 48, 61, 62),
            ("draw", "B" * 32 + "W" * 32, 0, 0),
            ("wipeout", "B" * 63 + ".", 64, 64),
            ("empty", "." * 64, 0, 0),
        ]
        for name, board, project, oracle in boards:
            for side, sign in (("B", 1), ("W", -1)):
                with self.subTest(name=name, side=side):
                    own, opponent = reference.bits(board, side)
                    self.assertEqual(reference.legal(own, opponent), 0)
                    self.assertEqual(reference.legal(opponent, own), 0)
                    self.assertEqual(reference.terminal_score(own, opponent, "project"), sign * project)
                    self.assertEqual(reference.terminal_score(own, opponent, "oracle"), sign * oracle)

    def test_forced_pass_and_terminal_child(self):
        board = ".W" + "B" * 61 + "."
        oracle = whole_game.oracle
        self.assertEqual(oracle.effective_query(board, "W"), ("B", -1))
        for contract in reference.CONTRACTS:
            root = reference.solve(board, "W", contract)
            self.assertEqual(root["score"], -64)
            self.assertEqual(root["pv"], ["pass", "a1"])
            child = oracle.apply_move(board, "B", "a1")
            self.assertEqual(reference.replay(board, "W", root["pv"]), child)
            self.assertEqual(reference.terminal_score(*reference.bits(child, "B"), contract), 64)
            with self.assertRaisesRegex(oracle.OracleError, "terminal positions"):
                oracle.effective_query(child, "W")

    def test_independent_moves_match_coordinate_adapter(self):
        oracle = whole_game.oracle
        board, side = oracle.initial_board(), "B"
        for _ in range(120):
            own, opponent = reference.bits(board, side)
            mask = reference.legal(own, opponent)
            actual = []
            while mask:
                move = mask & -mask
                mask ^= move
                name = reference.move_name(move)
                actual.append(name)
                a, b = reference.play(own, opponent, move)
                expected = oracle.apply_move(board, side, name)
                self.assertEqual(reference.bits(expected, side), (a, b))
            expected = oracle.legal_moves(board, side)
            self.assertEqual(set(actual), set(expected))
            if not expected:
                if not oracle.legal_moves(board, oracle.other(side)):
                    break
            else:
                board = oracle.apply_move(board, side, expected[0])
            side = oracle.other(side)

    def test_saved_evidence_seals_and_continuations(self):
        fixture = json.loads(Path(__file__).with_name("fixtures").joinpath("exact-score-contract-v1.json").read_bytes())
        source = fixture["source_receipt"]
        raw = fixture["source_receipt_raw_utf8"].encode("utf-8")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), source["sha256"])
        original = json.loads(raw)
        original_seal = original.pop("report_digest")
        self.assertEqual(hashlib.sha256(reference.canonical(original)).hexdigest(), original_seal)
        self.assertEqual(source["report_digest"], original_seal)
        for key in ("status", "failure", "manifest_digest", "queries"):
            self.assertEqual(source[key], original[key])
        self.assertEqual(source["step"], original["job"]["step"])
        self.assertEqual(source["job_source_digest"], original["job"]["source_digest"])
        self.assertEqual(fixture["oracle_source"]["binary"], original["oracle_binary"])
        self.assertEqual(fixture["oracle_source"]["url"], original["profile"]["oracle"]["source_url"])
        self.assertEqual(fixture["oracle_source"]["archive_sha256"], original["profile"]["oracle"]["source_sha256"])
        self.assertEqual(source["status"], "failed")
        self.assertEqual(source["report_digest"], "71e3d66ee22711778bdfd3155b0f52989d56c4ef488712936eecf2460f77675b")
        root, child = source["queries"]
        self.assertEqual(root["board"], source["step"]["board"])
        self.assertEqual(child["board"], whole_game.oracle.apply_move(root["board"], "W", "b7"))
        for query in source["queries"]:
            self.assertEqual(whole_game.oracle.effective_query(query["board"], query["side"]),
                             (query["effective_side"], query["sign"]))
            self.assertTrue(query["result"]["exact"])
        self.assertEqual(len(fixture["independent_solves"]), 4)
        solved = {(result["board"], result["contract"]): result for result in fixture["independent_solves"]}
        for contract, expected in (("project", 39), ("oracle", 40)):
            self.assertEqual(solved[root["board"], contract]["score"], expected)
            self.assertEqual(solved[root["board"], contract]["pv"][0], "b7")
            self.assertEqual(solved[child["board"], contract]["score"], -expected)
        self.assertEqual(source["step"]["search"]["score"], solved[root["board"], "project"]["score"])
        self.assertEqual(root["result"]["value"], solved[root["board"], "oracle"]["score"])
        self.assertEqual(child["result"]["value"], solved[child["board"], "oracle"]["score"])
        reference_source_sha256 = hashlib.sha256(Path(reference.__file__).read_bytes()).hexdigest()
        for result in fixture["independent_solves"]:
            value = dict(result)
            seal = value.pop("report_digest")
            self.assertEqual(hashlib.sha256(reference.canonical(value)).hexdigest(), seal)
            self.assertLessEqual(result["peak_rss_kib"], 1572864)
            self.assertEqual(result["wall_limit_seconds"], 30)
            self.assertEqual(result["reference_source_sha256"], reference_source_sha256)
            self.assertEqual(result["status"], "completed")
            self.assertLessEqual(result["elapsed_seconds"], 30)
            if result["status"] == "completed":
                leaf = reference.replay(result["board"], result["side"], result["pv"])
                self.assertEqual(leaf, result["terminal_board"])
                self.assertEqual(reference.terminal_score(*reference.bits(leaf, result["side"]), result["contract"]), result["score"])
                board, side = result["board"], result["side"]
                oracle = whole_game.oracle
                for move in result["pv"]:
                    legal = oracle.legal_moves(board, side)
                    if move == "pass":
                        self.assertFalse(legal)
                        self.assertTrue(oracle.legal_moves(board, oracle.other(side)))
                    else:
                        self.assertIn(move, legal)
                        board = oracle.apply_move(board, side, move)
                    side = oracle.other(side)
                self.assertEqual(board, leaf)
                self.assertFalse(oracle.legal_moves(board, "B"))
                self.assertFalse(oracle.legal_moves(board, "W"))
                self.assertEqual(result["terminal_counts"], {cell: leaf.count(cell) for cell in "BW."})
            else:
                self.assertIsNone(result["score"])


if __name__ == "__main__":
    unittest.main()
