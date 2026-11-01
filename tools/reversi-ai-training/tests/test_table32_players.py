"""Protocol replay fixtures; all subprocess entry points are mocked."""
import copy
import io
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reinforcement as rf
import table32_inputs as inputs
import table32_players as players
import table32_store as st
import training


class Table32PlayerTests(unittest.TestCase):
    def runtime(self):
        return {"binary": {"path": "/fixture/not-executed-oracle"},
                "working_directory": "/fixture/not-executed"}

    def test_profile_reads_every_remaining_empty_and_uses_full_probability(self):
        profile = players.full_solve_profile()
        for occupied in range(4, 64):
            self.assertEqual(players.oracle.profile_depth_at(profile, occupied), 64 - occupied)
        argv = players.oracle.oracle_argv(Path("/fixture/oracle"), profile, solve_path=Path("/fixture/problem"))
        self.assertEqual(argv[:7], ["/fixture/oracle", "-nobook", "-thread", "1", "-hash", "25", "-depthprobrange"])
        self.assertEqual(argv[-2:], ["-solve", "/fixture/problem"])

    def test_terminal_query_never_calls_effective_query_or_subprocess(self):
        root = {"id": "terminal", "board": "B" * 63 + ".", "side": "W"}
        query = inputs.oracle_query(root)
        with mock.patch.object(players.oracle, "effective_query", side_effect=AssertionError("terminal normalization")), \
             mock.patch.object(players.subprocess, "run", side_effect=AssertionError("subprocess")):
            result = players.query_oracle(query, self.runtime(), 310, Path("/unused"))
            self.assertEqual(result["result"], {"score": -64, "exact": True, "completed_depth": 1})
            self.assertEqual(result["raw"], {"terminal": True})

    def test_forced_pass_oracle_changes_effective_side_and_restores_sign(self):
        board = "WB." + "W" * 61
        query = inputs.oracle_query({"id": "forced-pass", "board": board, "side": "B"})
        output = "\n".join(["| Level | Depth | Move | Score | Time | Nodes | NPS |",
                             "| custom | 1@100% | c1 | +64 | 000:00:00.001 | 1 | 1000 |",
                             "total 1 nodes in 0.001s NPS 1000"])
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(players.oracle,"runtime_identity",return_value=self.runtime()), \
             mock.patch.object(players.subprocess, "run", return_value=SimpleNamespace(stdout=output, stderr="", returncode=0)) as run:
            saved = players.query_oracle(query, self.runtime(), 310, Path(directory))
            self.assertEqual(saved["result"], {"score": -64, "exact": True, "completed_depth": 1})
            self.assertEqual(saved["raw"]["problem"], players.oracle.to_egaroucid_problem(board, "W") + "\n")
            self.assertEqual(run.call_count, 1)
            players.verify_query(query, saved, self.runtime(), 310)
            changed = copy.deepcopy(saved)
            changed["result"]["score"] = 64
            with self.assertRaises(training.TrainingError):
                players.verify_query(query, changed, self.runtime(), 310)

    def test_timeout_saves_partial_oracle_stderr_without_marking_completion(self):
        query = inputs.oracle_query({"id": "timeout", "board": rf.INITIAL, "side": "B"})
        error = subprocess.TimeoutExpired(["fixture"], 310, output=b"partial\n", stderr=b"crash\xff")
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(players.oracle,"runtime_identity",return_value=self.runtime()), \
             mock.patch.object(players.subprocess, "run", side_effect=error):
            with self.assertRaises(subprocess.TimeoutExpired):
                players.query_oracle(query, self.runtime(), 310, Path(directory))
            log = st.read(Path(directory) / "oracle.jsonl")
            self.assertEqual(log["stderr_hex"], b"crash\xff".hex())
            self.assertEqual(log["stdout_hex"], b"partial\n".hex())
            self.assertIsNone(log["returncode"])

    def test_oracle_live_runtime_change_is_preserved_and_rejected(self):
        board="WB."+"W"*61
        query=inputs.oracle_query({"id":"changed","board":board,"side":"W"})
        changed={**self.runtime(),"binary":{"path":"/fixture/changed-oracle"}}
        response=SimpleNamespace(stdout="unused",stderr="changed runtime",returncode=0)
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(players.oracle,"runtime_identity",side_effect=[self.runtime(),changed]), \
             mock.patch.object(players.subprocess,"run",return_value=response):
            with self.assertRaisesRegex(training.TrainingError,"changed during"):
                players.query_oracle(query,self.runtime(),310,Path(directory))
            raw=st.read(Path(directory)/"oracle.jsonl")
            self.assertEqual(raw["runtime_before"],self.runtime())
            self.assertEqual(raw["runtime_after"],changed)

    def test_player_live_artifact_change_rejected_before_request(self):
        with tempfile.TemporaryDirectory() as directory:
            executable,artifact=Path(directory)/"cli",Path(directory)/"artifact"
            executable.write_text("fixture cli")
            artifact.write_text("fixture artifact")
            player=players.Player.__new__(players.Player)
            player.expected_pins={"executable":st.pin(executable),"artifact":st.pin(artifact)}
            player.config,player.log=dict(inputs.TEACHER_SETTINGS),None
            result=player.decision("pass","WB."+"W"*61,"B")
            self.assertEqual(result["raw"]["pins_before"],player.expected_pins)
            self.assertEqual(result["raw"]["pins_after"],player.expected_pins)
            artifact.write_text("changed fixture artifact")
            with self.assertRaisesRegex(training.TrainingError,"input digest changed"):
                player.decision("pass","WB."+"W"*61,"B")

    def test_forced_pass_has_legality_evidence_and_no_fabricated_search(self):
        player = players.Player.__new__(players.Player)
        player.config, player.log = dict(inputs.TEACHER_SETTINGS), None
        board = "WB." + "W" * 61
        with mock.patch.object(player, "new_game", side_effect=AssertionError("no request")):
            result = player.decision("pass", board, "B")
        self.assertEqual(result["move"], "pass")
        self.assertEqual(result["completed_depth"], 0)
        self.assertFalse(result["exact"])
        self.assertTrue(result["forced_pass"])
        inputs.validate_decision(board, "B", result, inputs.TEACHER_SETTINGS)
        with self.assertRaises(training.TrainingError):
            players.validate_raw_decision("pass", rf.INITIAL, "B", result, inputs.TEACHER_SETTINGS)

    def test_raw_search_and_reset_are_checked_and_shallow_score_rejected(self):
        raw = {"request": "unit\t" + rf.INITIAL + "\tB", "stdout": "unit\td3\n",
               "reset": {"request": "new_game\tunit", "stdout": "new_game\tunit\tready\n"},
               "stderr": "search_diagnostic_v1\tposition_id=unit\toutcome=move\tscore=3\tcompleted_depth=11\texact=false\tnodes=3\telapsed_us=1001"}
        result = {"move": "d3", "score": 3, "completed_depth": 11,
                  "exact": False, "nodes": 3, "elapsed_ms": 2, "raw": raw}
        players.validate_raw_decision("unit", rf.INITIAL, "B", result, inputs.TEACHER_SETTINGS)
        for field, value in (("reset", {}), ("stderr", raw["stderr"].replace("score=3", "score=none")),
                             ("stderr", raw["stderr"] + "\tscore=3")):
            changed = copy.deepcopy(result)
            changed["raw"][field] = value
            with self.assertRaises(training.TrainingError):
                players.validate_raw_decision("unit", rf.INITIAL, "B", changed, inputs.TEACHER_SETTINGS)

    def test_stderr_reader_preserves_crash_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            player = players.Player.__new__(players.Player)
            player.process = SimpleNamespace(stderr=io.BytesIO(b"panic\xff\n"))
            player.log, player.log_lock = Path(directory) / "candidate.jsonl", threading.Lock()
            player.argv, player.diagnostic_lines = ["/fixture/cli"], queue.Queue()
            player._read_diagnostics()
            saved = st.read(player.log)
            self.assertEqual(saved["bytes_hex"], b"panic\xff\n".hex())
            self.assertEqual(player.diagnostic_lines.get(), b"panic\xff\n")
            self.assertIsNone(player.diagnostic_lines.get())


if __name__ == "__main__":
    unittest.main()
