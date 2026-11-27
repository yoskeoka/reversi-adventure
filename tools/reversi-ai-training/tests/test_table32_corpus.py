"""Exercise corpus persistence and verification with two tiny frontiers."""
from contextlib import redirect_stderr
import gzip
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import table32_corpus as corpus
import table32_store as st
import training


INITIAL = b"0000000810000000 0000001008000000 B 0\n"
AFTER_D3 = b"0000000818080000 0000001000000000 W 0\n"


class CorpusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "positions"
        self.attempt = Path(temporary.name) / "attempt"
        self.enumerator = Path(temporary.name) / "enumerator"
        self.enumerator.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            "assert sys.argv[1] in ('engine', 'scalar')\n"
            f"initial, after_d3 = {INITIAL!r}, {AFTER_D3!r}\n"
            "previous = sys.stdin.buffer.read()\n"
            "if sys.argv[2] == '0':\n"
            "    assert previous == b''\n"
            "    sys.stdout.buffer.write(initial)\n"
            "else:\n"
            "    assert sys.argv[2] == '1' and previous == initial\n"
            "    sys.stdout.buffer.write(after_d3)\n"
        )
        self.enumerator.chmod(0o755)

    def generate(self, root=None):
        with redirect_stderr(io.StringIO()):
            return corpus.generate(root or self.root, self.enumerator, 1, attempt=self.attempt)

    def test_deterministic_bytes_and_role(self):
        first = self.generate()
        other_root = self.root.with_name("repeat")
        second = self.generate(other_root)
        self.assertEqual(first, second)
        for name in ["manifest.json", *(s["path"] for s in first["shards"])]:
            self.assertEqual((self.root / name).read_bytes(), (other_root / name).read_bytes())
        self.assertEqual(corpus.verify(self.root, self.enumerator), first)
        position, = corpus.iter_shard(self.root, first["shards"][1])
        self.assertEqual(position["id"], "p01-000000")
        board, side = corpus.decode_position(position)
        self.assertEqual((board[19], board.count("B"), board.count("W"), side), ("B", 4, 1, "W"))
        reserved_key = training.canonical_position_key(training.board_key(board, 2), side)
        other_side = training.canonical_position_key(board, "B")
        self.assertEqual(corpus.find_position_ids(self.root, [reserved_key, other_side]),
                         {reserved_key: "p01-000000"})

    def test_resume_preserves_finished_shard(self):
        frontier = corpus._frontier

        def interrupt(*args):
            if args[2] == 1:
                raise KeyboardInterrupt
            return frontier(*args)

        with patch.object(corpus, "_frontier", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self.generate()
        completed = self.root / "shards/p00-000.jsonl.gz"
        before = (completed.read_bytes(), completed.stat().st_mtime_ns)
        with patch.object(corpus, "_frontier", wraps=frontier) as reopened:
            self.assertEqual(self.generate()["total_count"], 2)
        self.assertEqual((completed.read_bytes(), completed.stat().st_mtime_ns), before)
        self.assertEqual([call.args[2] for call in reopened.call_args_list], [1])

    def test_digest_and_semantic_validation(self):
        manifest = self.generate()
        shard = manifest["shards"][0]
        path = self.root / shard["path"]
        row, = corpus.iter_shard(self.root, shard)
        path.write_bytes(gzip.compress(st.blob({**row, "black": "0000000000000011"}), mtime=0))
        with self.assertRaisesRegex(training.TrainingError, "digest differs"):
            list(corpus.iter_shard(self.root, shard))
        shard["sha256"] = training.sha256_file(path)
        st.atomic(self.root / "manifest.json", st.seal(manifest))
        with self.assertRaisesRegex(training.TrainingError, "independent corpus replay differs"):
            corpus.verify(self.root, self.enumerator)


if __name__ == "__main__":
    unittest.main()
