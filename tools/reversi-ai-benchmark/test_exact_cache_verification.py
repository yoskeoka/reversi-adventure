"""Driver boundary tests: no long measurement is launched by preparation or verify."""
import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import exact_cache_verification as v

class DriverTests(unittest.TestCase):
    def test_sample_order_is_exact(self):
        self.assertEqual([g["opening_id"] for g in v.sample()["games"]],
                         ["opening-1", "opening-2", "opening-4"])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"sample.json"
            sample = copy.deepcopy(v.sample())
            sample["games"].reverse()
            p.write_bytes(v.wg.canonical(sample))
            with patch.object(v, "SAMPLE", p):
                with self.assertRaisesRegex(v.wg.BenchmarkError, "sample"):
                    v.sample()

    def test_progress_thins_only_ordinary_updates(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            p = v.Progress(3)
            p.emit("games", "game", "game", 1, 3, "saved")
            p.emit("games", "game", "game", 1, 3, "failed")
            p.emit("games", "game", "game", 1, 3, "interrupted")
            p.emit("games", "game", "game", 3, 3, "verified")
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(line.startswith("progress exact-cache-verification stage=games condition=game unit=game")
                            for line in lines))
        self.assertIn("status=verified", lines[-1])

    def test_regression_requires_actual_test_execution(self):
        m = {"report_digest": "fixture"}
        fixtures = [{"test": name,
            "argv": ["cargo", "test", "-p", "reversi-ai", "--lib", name, "--", "--exact", "--nocapture"],
            "returncode": 0, "wall_ns": 1,
            "stdout": f"test {name} ... ok\n1 passed; 0 failed;", "stderr": ""}
            for name in v.REGRESSIONS]
        result = v.wg.sealed({"version":v.VERSION,"score_contract":"winner-empty-v1","manifest_digest":"fixture",
            "fixtures":fixtures,"proved_root_score":4,"proved_selected_child_score":4})
        v.verify_regression(m,result)
        result["fixtures"][0]["stdout"]="0 passed; 0 failed;"
        with self.assertRaisesRegex(v.wg.BenchmarkError, "exactly one"):
            v.verify_regression(m,v.wg.sealed(result))

    def test_verify_never_measures_missing_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            units = v.games.units(v.sample())
            m={"output_directory":str(directory),"units":units,"historical_audit":{}}
            with patch.object(v,"verify_manifest",return_value=m), patch.object(v,"regression",return_value={}), \
                 patch.object(v.evidence,"reusable_queries",return_value=[]), patch.object(v.games,"measure_unit") as measure:
                with self.assertRaisesRegex(v.wg.BenchmarkError,"missing game"):
                    v.execute(directory/"manifest.json","verify",1)
                measure.assert_not_called()

    def test_corrupt_saved_game_stops_before_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            folder=directory/"games"
            folder.mkdir()
            units=v.games.units(v.sample())
            (folder/(units[0]["id"]+".json")).write_bytes(v.wg.canonical({"bad":True}))
            m={"output_directory":str(directory),"units":units,"historical_audit":{}}
            with patch.object(v,"verify_manifest",return_value=m), patch.object(v,"regression",return_value={}), \
                 patch.object(v.games,"measure_unit") as measure:
                with self.assertRaises((v.wg.BenchmarkError,KeyError)):
                    v.execute(directory/"manifest.json","run",1)
                measure.assert_not_called()

    def test_unknown_checkpoint_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            (directory/"games").mkdir()
            (directory/"games"/"other.json").write_text("{}")
            with self.assertRaisesRegex(v.wg.BenchmarkError,"unknown game"):
                v.saved_games({"units":v.games.units(v.sample())},directory)

    def test_immutable_failure_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"failed.json"
            failure=v.wg.sealed({"status":"failed"})
            v.immutable(path,failure)
            v.immutable(path,failure)
            with self.assertRaisesRegex(v.wg.BenchmarkError,"saved evidence mismatch"):
                v.immutable(path,v.wg.sealed({"status":"completed"}))

if __name__=="__main__":
    unittest.main()
