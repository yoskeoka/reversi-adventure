import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("raw_oracle", Path(__file__).resolve().parents[1] / "oracle.py")
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


class RawOracleTests(unittest.TestCase):
    def fake(self, argv, **kwargs):
        rows = []
        for problem in Path(argv[-1]).read_text().splitlines():
            board = problem[:-1].replace("X", "B").replace("O", "W").replace("-", ".")
            depth = min(board.count("."), oracle.profile_depth_at(oracle.STRONG_ENGINE_HCAP_V1, 63 - board.count(".")))
            move = oracle.legal_moves(board, "B")[0]
            rows.append(f"| custom | {depth}@100% | {move} | +2 | 0:00:00.000 | 1 | 1000 |")
        stdout = "| " + " | ".join(oracle.HEADER) + " |\n" + "\n".join(rows) + f"\ntotal {len(rows)} nodes in 0s NPS {len(rows) * 1000}\n"
        return subprocess.CompletedProcess(argv, 0, stdout, "fake stderr\n")

    def setup(self, directory):
        binary = directory / "fake-oracle"
        binary.write_text("fake")
        resources = directory / "resources"
        resources.mkdir()
        (resources / "eval.dat").write_text("evaluation")
        record = oracle.make_corpus_record("root", oracle.initial_board(), "B", [], "test")
        return binary, [record]

    def test_rebuild_offline_and_reject_resealed_mapping_and_missing_query(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary, records = self.setup(directory)
            output = directory / "saved"
            expected = oracle.generate_saved_golden(records, binary, directory, output, runner=self.fake)
            with patch.object(oracle.subprocess, "run", side_effect=AssertionError("offline process")), \
                 patch.object(oracle, "runtime_identity", side_effect=AssertionError("offline runtime read")):
                self.assertEqual(oracle.verify_raw_golden(records, output), expected)
            saved = json.loads((output / "evidence.json").read_text())
            bad = copy.deepcopy(saved)
            bad["roots"][0]["mapping"][0]["root_sign"] *= -1
            (output / "evidence.json").write_bytes(oracle.raw_canonical(bad))
            with self.assertRaisesRegex(oracle.OracleError, "mapping"):
                oracle.verify_raw_golden(records, output)
            (output / "evidence.json").write_bytes(oracle.raw_canonical(saved))
            (output / "root-00" / "query-00.stdout").write_text("invalid\n")
            with self.assertRaises(oracle.OracleError):
                oracle.verify_raw_golden(records, output)

    def test_failure_retains_raw_and_does_not_publish_golden(self):
        for failure in ("nonzero", "timeout", "resource-change", "binary-change"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                binary, records = self.setup(directory)
                output = directory / "saved"
                def failed(argv, **kwargs):
                    if failure == "timeout":
                        raise subprocess.TimeoutExpired(argv, 300, output=b"partial", stderr=b"timeout")
                    result = self.fake(argv, **kwargs)
                    if failure == "nonzero":
                        result.returncode = 2
                    elif failure == "resource-change":
                        (directory / "resources" / "eval.dat").write_text("changed")
                    else:
                        binary.write_text("changed")
                    return result
                with self.assertRaises(oracle.OracleError):
                    oracle.generate_saved_golden(records, binary, directory, output, runner=failed)
                self.assertFalse((output / "golden.jsonl").exists())
                self.assertTrue((output / "root-00" / "query-00.problem").is_file())
                self.assertTrue((output / "root-00" / "query-00.stderr").is_file())
                self.assertEqual(json.loads((output / "evidence.json").read_text())["status"], "failed")

    def test_pass_terminal_and_empty_award(self):
        records = oracle.load_jsonl(Path(oracle.__file__).with_name("corpus.jsonl"))
        passes = [row for row in records if row["outcome"]["kind"] == "Pass"]
        terminals = oracle.load_jsonl(Path(oracle.__file__).with_name("winner-empty-v1-corpus.jsonl"))
        records = passes[:1] + terminals[:5]
        self.assertTrue(passes)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary, _ = self.setup(directory)
            output = directory / "saved"
            expected = oracle.generate_saved_golden(records, binary, directory, output, runner=self.fake)
            self.assertEqual(oracle.verify_raw_golden(records, output), expected)
            evidence = json.loads((output / "evidence.json").read_text())
            self.assertFalse(evidence["roots"][0]["observations"][0]["child_query"])
            self.assertEqual(evidence["roots"][0]["mapping"][0]["move"], "pass")

    def test_resealed_runtime_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary, records = self.setup(directory)
            output = directory / "saved"
            oracle.generate_saved_golden(records, binary, directory, output, runner=self.fake)
            saved = json.loads((output / "evidence.json").read_text())
            for identity in (saved["runtime_before"], saved["runtime_after"]):
                identity["binary"]["sha256"] = "not-a-sha"
            (output / "evidence.json").write_bytes(oracle.raw_canonical(saved))
            with self.assertRaisesRegex(oracle.OracleError, "runtime identity"):
                oracle.verify_raw_golden(records, output)

    def test_missing_and_malformed_raw_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary, records = self.setup(directory)
            output = directory / "saved"
            oracle.generate_saved_golden(records, binary, directory, output, runner=self.fake)
            original = json.loads((output / "evidence.json").read_text())
            for field, value in (("roots", None), ("timeout_seconds", "300"), ("runtime_before", None)):
                with self.subTest(field=field):
                    bad = copy.deepcopy(original)
                    bad[field] = value
                    (output / "evidence.json").write_bytes(oracle.raw_canonical(bad))
                    with self.assertRaises(oracle.OracleError):
                        oracle.verify_raw_golden(records, output)
            (output / "evidence.json").write_bytes(oracle.raw_canonical(original))
            (output / "root-00" / "query-00.problem").unlink()
            with self.assertRaises(oracle.OracleError):
                oracle.verify_raw_golden(records, output)

    def test_prepared_runtime_source_archive_and_offline_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary, records = self.setup(directory)
            source = directory / 'source'
            (source / 'bin/resources').mkdir(parents=True)
            (source / 'bin/resources/eval.dat').write_text('evaluation')
            (source / 'README').write_text('tiny pinned test source')
            cache = directory / 'cache'
            cache.mkdir()
            archive = cache / f'egaroucid-v{oracle.ORACLE_VERSION}.tar.gz'
            with tarfile.open(archive, 'w:gz') as output:
                output.add(source, arcname='Egaroucid-test')
            with patch.object(oracle, 'SOURCE_SHA256', oracle.sha256_file(archive)), \
                 patch.object(oracle, 'cache_root', return_value=cache), \
                 patch.object(oracle, 'ensure_oracle', return_value=(binary, source)) as setup:
                path = oracle.prepare_saved_runtime(directory / 'prepared', timeout=7)
                setup.assert_called_once_with(7)
                receipt = oracle.verify_runtime_receipt(path)
                self.assertEqual(receipt['source_tree_sha256'], oracle.sha256_tree(source))
                self.assertEqual(receipt['runtime'], oracle.runtime_identity(binary, directory))
                saved = directory / 'saved'
                oracle.generate_saved_golden(records, binary, directory, saved,
                                             runtime_receipt=path, runner=self.fake)
                evidence = json.loads((saved / 'evidence.json').read_text())
                self.assertEqual(evidence['runtime_receipt'], oracle.raw_pin(path))
                with patch.object(oracle.subprocess, 'run', side_effect=AssertionError('offline process')), \
                     patch.object(oracle, 'ensure_oracle', side_effect=AssertionError('offline setup')):
                    self.assertEqual(oracle.verify_runtime_receipt(path), receipt)
                    oracle.verify_raw_golden(records, saved)
                for field, value in (('profile', oracle.profile_metadata(oracle.CI_SMOKE_V1)),
                                     ('source_tree_sha256', '0' * 64), ('producer_sha256', '0' * 64),
                                     ('build_recipe', {'build': ['fake']})):
                    with self.subTest(field=field):
                        bad = copy.deepcopy(receipt)
                        bad[field] = value
                        path.write_bytes(oracle.raw_canonical(bad))
                        with self.assertRaises(oracle.OracleError):
                            oracle.verify_runtime_receipt(path)
                path.write_bytes(oracle.raw_canonical(receipt))
                Path(receipt['source_archive']['path']).write_bytes(b'changed archive')
                with self.assertRaisesRegex(oracle.OracleError, 'archive/source'):
                    oracle.verify_runtime_receipt(path)

    def test_arbitrary_runtime_cannot_use_preparation_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary, records = self.setup(directory)
            with patch.object(oracle, 'verify_runtime_receipt', return_value={
                    'runtime': {**oracle.runtime_identity(binary, directory), 'resources_digest': '0' * 64}}):
                with self.assertRaisesRegex(oracle.OracleError, 'differs from prepared'):
                    oracle.generate_saved_golden(records, binary, directory, directory / 'saved',
                                                 runtime_receipt=directory / 'receipt', runner=self.fake)


if __name__ == "__main__":
    unittest.main()
