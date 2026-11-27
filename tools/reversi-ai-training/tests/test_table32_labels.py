"""Exercise the bounded opening-label protocol against a fake Console."""
from __future__ import annotations

import fcntl
import gzip
import io
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import table32_corpus as corpus
import table32_labels as labels
import table32_store as st
from test_table32_corpus import AFTER_D3, INITIAL

FIXTURE_VERSION = "9.0.1"


class LabelTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.corpus_root = self.root / "corpus"
        self.label_root = self.root / "labels"
        self.attempt = self.root / "corpus-attempt"
        self.cwd = self.root / "runtime"
        self.cwd.mkdir()
        (self.cwd / "resources").mkdir()
        (self.cwd / "resources/eval.fixture").write_bytes(b"fixture eval\n")
        self.source_archive = self.root / "source.fixture"
        self.source_archive.write_bytes(b"fixture source\n")
        self._make_corpus()
        self.console = self._make_console()

    def _make_corpus(self):
        enumerator = self.root / "enumerator"
        enumerator.write_text(f"#!{sys.executable}\n"
                              "import sys\n"
                              "sys.stdin.buffer.read()\n"
                              f"sys.stdout.buffer.write({INITIAL!r} if sys.argv[2] == '0' else {AFTER_D3!r})\n")
        enumerator.chmod(0o755)
        with redirect_stderr(io.StringIO()):
            self.corpus = corpus.generate(self.corpus_root, enumerator, 1, attempt=self.attempt)

    def _make_console(self):
        calibration = {labels.oracle.to_egaroucid_problem(board, effective): (moves[0], score)
                       for (_, board, _, effective, _, moves), score in
                       zip(labels._calibration_queries(), (60, -44, 60, 0)) if effective}
        path = self.cwd / "console"
        path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(f"""
            import sys
            import time
            from pathlib import Path
            sys.path.insert(0, {str(TOOLS)!r})
            from pilot import oracle
            if sys.argv[1:] == ['-version']:
                print('Egaroucid for Console {FIXTURE_VERSION}.1 Fixture')
                raise SystemExit(0)
            assert sys.argv[1:6] == ['-nobook', '-thread', '1', '-hash', '25']
            assert sys.argv[6] == '-level' and sys.argv[8] == '-solve'
            level = int(sys.argv[7])
            problems = Path(sys.argv[9]).read_text().splitlines()
            calibration = {calibration!r}
            mode = Path('mode').read_text().strip() if Path('mode').exists() else ''
            print('| Level | Depth | Move | Score | Time | Nodes | NPS |')
            for problem in problems:
                if problem in calibration:
                    move, score = calibration[problem]
                    depth = 2
                else:
                    time.sleep(3 if mode == 'timeout' else 0)
                    assert len(problem) == 65 and problem[-1] == 'X'
                    board = problem[:64].translate(str.maketrans('XO-', 'BW.'))
                    move = oracle.legal_moves(board, 'B')[0]
                    score = 3 if board.count('.') == 60 else -5
                    if mode == 'illegal':
                        move = 'a1'
                    if mode == 'bad-score':
                        score = 65
                    depth = min(level, board.count('.'))
                print(f'| {{level}} | {{depth}}@100% | {{move}} | {{score:+d}} | 00:00:00.001 | 10 | 10000 |')
            n = len(problems)
            print(f'total {{10*n}} nodes in {{n/1000:g}}s NPS 10000')
            with Path('query-log').open('a') as log:
                log.write(''.join(problem + '\\n' for problem in problems))
            """))
        path.chmod(0o755)
        return path

    def cli(self, command, *extra, expected=0):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "table32_labels.py"), command,
             "--corpus-root", str(self.corpus_root), "--label-root", str(self.label_root), *extra],
            capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def prepare(self, *extra):
        return self.cli("prepare", "--binary", str(self.console), "--cwd", str(self.cwd),
                        "--source-archive", str(self.source_archive),
                        "--source-sha256", st.pin(self.source_archive)["sha256"],
                        "--source-url", "https://example.org/fixture",
                        "--version", FIXTURE_VERSION, *extra)

    def failure(self, slice_id):
        return st.read(self.label_root / f"slices/{slice_id:04d}/attempts/0000/failure.json")

    def test_preparation_does_not_query_console(self):
        self.prepare()
        self.assertFalse((self.cwd / "query-log").exists())
        self.cli("verify")
        self.cli("verify", "--complete", expected=2)

    def test_run_refuses_another_owner_of_the_label_root(self):
        self.prepare()
        with (self.label_root / "run.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.cli("run", expected=2)
        self.assertIn("another label invocation owns this run root", result.stderr)
        self.assertFalse((self.label_root / "slices").exists())

    def test_partial_run_resume_and_offline_identity(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "missing label calibration"):
            labels.dataset_identity(self.corpus_root, self.label_root, [0])
        self.cli("run", "--phase-start", "0", "--phase-end", "0")
        snapshot = labels.dataset_identity(self.corpus_root, self.label_root, [0])
        with self.assertRaisesRegex(ValueError, "no eligible labels"):
            labels.dataset_identity(self.corpus_root, self.label_root, [0],
                                    exclude_ids=["p00-000000"])
        with self.assertRaisesRegex(ValueError, "missing labels"):
            list(labels.iter_labeled(self.corpus_root, self.label_root, [0, 1]))
        original = self.label_root / "batches/p00-000000.json.gz"
        saved = (original.read_bytes(), original.stat().st_mtime_ns)
        self.cli("run", "--jobs", "2", expected=2)
        self.cli("run", "--resume", "--jobs", "2")
        self.assertEqual((original.read_bytes(), original.stat().st_mtime_ns), saved)
        self.assertEqual(len((self.cwd / "query-log").read_text().splitlines()), 5)
        self.assertEqual(snapshot, labels.dataset_identity(self.corpus_root, self.label_root, [0]))
        self.cli("verify", "--complete")
        with patch.object(labels.oracle, "run_external", side_effect=AssertionError("offline process")):
            labels.inventory(self.corpus_root, self.label_root, require_complete=True)
            rows = list(labels.iter_labeled(self.corpus_root, self.label_root, [0, 1],
                                            limit_per_phase=1))
        self.assertEqual([(row["id"], row["turn"], row["score"]) for row in rows],
                         [("p00-000000", "black", 3), ("p01-000000", "white", -5)])

    def test_tampered_label_and_runtime_fail_closed(self):
        self.prepare()
        self.cli("run", "--phase-end", "0")
        original = self.label_root / "batches/p00-000000.json.gz"
        manifest = st.read(self.label_root / "manifest.json")
        _, batch = next(labels._batches(self.corpus, manifest["settings"]))
        evidence, _ = labels._read_batch(original, batch, manifest)
        evidence["labels"][0]["score"] = 4
        original.write_bytes(gzip.compress(st.blob(st.seal(evidence)), mtime=0))
        with self.assertRaisesRegex(ValueError, "labels|scores differ"):
            list(labels.iter_labeled(self.corpus_root, self.label_root, [0]))
        with self.assertRaisesRegex(ValueError, "labels|scores differ"):
            labels.dataset_identity(self.corpus_root, self.label_root, [0], verify_scores=True)
        (self.cwd / "resources/eval.fixture").write_bytes(b"changed")
        failure = self.cli("run", "--resume", expected=2)
        evidence = self.failure(1)
        self.assertIn("runtime resources changed", evidence["reason"], failure.stderr)

    def test_timeout_then_recover_without_regenerating_finished_batch(self):
        self.prepare("--timeout-seconds", "1")
        self.cli("run", "--phase-end", "0")
        mode = self.cwd / "mode"
        mode.write_text("timeout")
        self.cli("run", "--resume", expected=2)
        evidence = self.failure(1)
        self.assertIn("timed out", evidence["reason"])
        self.assertFalse((self.label_root / "batches/p01-000000.json.gz").exists())
        mode.unlink()
        self.cli("run", "--resume")
        self.assertEqual(len((self.cwd / "query-log").read_text().splitlines()), 5)

    def test_invalid_score_and_illegal_move_never_publish(self):
        self.prepare()
        mode = self.cwd / "mode"
        mode.write_text("bad-score")
        self.cli("run", expected=2)
        bad_score = self.failure(0)
        self.assertIn("invalid teacher score", bad_score["reason"])
        mode.write_text("illegal")
        self.cli("run", "--resume", expected=2)
        illegal = self.failure(1)
        self.assertIn("illegal teacher move", illegal["reason"])
        self.assertEqual(list((self.label_root / "batches").glob("*")), [])

    def test_measurement_partial_estimate_and_rss_failure(self):
        self.prepare("--measure-per-phase", "3")
        self.cli("run", "--phase-end", "0")
        partial = labels.estimate(self.corpus_root, self.label_root)
        self.assertIsNone(partial["serial_projection_seconds"])
        self.assertFalse(partial["complete"])
        (self.cwd / "mode").write_text("timeout")
        self.cli("run", "--resume", "--max-rss-kib", "1", expected=2)
        failure = labels.estimate(self.corpus_root, self.label_root)["attempts"][-1]["failure"]
        self.assertIn("RSS budget exceeded", failure["reason"])
        (self.cwd / "mode").unlink()
        self.cli("run", "--resume")
        estimate = labels.estimate(self.corpus_root, self.label_root)
        self.assertTrue(estimate["complete"])
        self.assertGreater(estimate["serial_projection_seconds"], 0)
        with self.assertRaisesRegex(ValueError, "measurement labels cannot be imported"):
            list(labels.iter_labeled(self.corpus_root, self.label_root, [0]))

    def test_calibration_rejects_raw_margin_in_place_of_winner_empty(self):
        self.prepare()
        self.cli("run", "--phase-end", "0")
        path = self.label_root / "calibration.json"
        evidence = st.read(path)
        # 61–2 with an empty square is 59 on the board and +60 winner-empty.
        evidence["stdout"] = evidence["stdout"].replace("+60", "+59")
        st.atomic(path, st.seal(evidence))
        with self.assertRaisesRegex(ValueError, "winner-empty contract differs"):
            labels.dataset_identity(self.corpus_root, self.label_root, [0])


if __name__ == "__main__":
    unittest.main()
