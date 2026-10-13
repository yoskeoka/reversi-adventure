"""Score identities and frozen offline boundaries, using tiny stub evidence."""
import copy
import contextlib
import hashlib
import json
import shlex
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import exact_threshold as et
import exact_cache_verification_oracle as queries
import legacy_offline
import whole_game as wg
from test_whole_game import synthetic_report


class WinnerEmptyMigrationTests(unittest.TestCase):
    def test_query_identity_and_independent_terminal_score(self):
        board = "B"*56 + "W"*6 + ".."
        manifest = {"inputs": {"oracle": {"sha256": "1"*64}}}
        identity = queries.query_identity(manifest, "BW."+"B"*59+"..", "B")
        self.assertEqual(identity["score_contract"], "winner-empty-v1")
        self.assertEqual(queries.VERSION, "exact-cache-verification-v2")
        self.assertEqual(et.VERSION, "exact-threshold-assessment-v2")
        self.assertEqual(queries._terminal_score(board, "B"), 52)
        self.assertEqual(queries._terminal_score(board, "W"), -52)
        self.assertEqual(queries._terminal_score("."*64, "B"), 0)

    def test_terminal_child_receipts_check_winner_empty_independently(self):
        from test_exact_threshold import fake_oracle_solve, fake_measured
        board = "."+"B"*7+"W"+"B"*47+"W"*6+".."
        manifest = {"report_digest": "manifest", "oracle_cwd": "/fake",
                    "inputs": {"oracle": {"path": "/fake/oracle", "sha256": "1"*64}}}
        step = {"id": "winner", "board": board, "side": "B", "move": "a1",
                "search": {"exact": True, "score": 52}}
        unit = {"id": "tiny", "scope": "game", "depth": 12, "threshold": 16}
        job = {"id": "tiny-position", "unit": unit, "step": step}
        def receipt(value):
            with patch.object(et.wg.oracle, "run_solve", side_effect=fake_oracle_solve([
                    {"value": value, "exact": True, "completed_depth": 3}])), patch.object(
                    et, "measured_oracle", side_effect=fake_measured):
                return et.solve_position(manifest, job)
        correct = receipt(52)
        self.assertEqual(correct["status"], "completed")
        self.assertEqual(correct["queries"][0]["score_contract"], "winner-empty-v1")
        et.verify_position(manifest, job, correct)
        old_raw = receipt(50)
        self.assertEqual(old_raw["status"], "failed")
        self.assertEqual(old_raw["failure"], "independent Oracle score/continuation mismatch")
        et.verify_position(manifest, job, old_raw)
        resealed = copy.deepcopy(old_raw)
        resealed.update(status="completed", failure=None)
        with self.assertRaises(wg.BenchmarkError):
            et.verify_position(manifest, job, wg.sealed(resealed))
        results = [{"status": "completed", "unit": unit, "report_digest": "source", "steps": [step]}]
        stage = queries.freeze_stage(manifest, results)
        self.assertEqual(stage["roots"][0]["terminal_score"], 52)
        self.assertIsNone(stage["roots"][0]["child_query"])
        queries.verify_stage(manifest, stage, results)
        changed = copy.deepcopy(stage)
        changed["roots"][0]["terminal_score"] = 50
        with self.assertRaises(wg.BenchmarkError):
            queries.verify_stage(manifest, wg.sealed(changed), results)

    def test_resealed_new_report_and_query_identity_tampering_rejects(self):
        report = synthetic_report()
        for mutate in (lambda r: r.update(score_contract="raw"),
                       lambda r: r["games"][0]["steps"][0]["search"].update(score_contract="raw"),
                       lambda r: r["games"][0]["steps"][0]["search"].update(search_semantics_version=1),
                       lambda r: r["games"][0]["steps"][0]["search"].update(score_identity_raw="resealed")):
            changed = copy.deepcopy(report)
            mutate(changed)
            with self.assertRaises(wg.BenchmarkError):
                wg.verify(wg.sealed(changed))

    def test_legacy_report_requires_flag_and_rejects_nested_new_identity(self):
        old = synthetic_report()
        old.update(schema_version=1, runner_version="reversi-ai-whole-game-v1")
        old.pop("score_contract")
        for game in old["games"]:
            for step in game["steps"]:
                for key in ("score_contract", "search_semantics_version", "score_identity_raw"):
                    step["search"].pop(key)
        old = wg.sealed(old)
        raw = wg.canonical(old)
        with self.assertRaises(wg.BenchmarkError):
            wg.verify(old)
        wg.verify(old, legacy_offline=True)
        self.assertEqual(wg.canonical(old), raw)
        changed = copy.deepcopy(old)
        changed["games"][0]["steps"][0]["search"]["score_contract"] = "winner-empty-v1"
        with self.assertRaisesRegex(ValueError, "new score semantics"):
            wg.verify(wg.sealed(changed), legacy_offline=True)

    def test_offline_adapter_never_runs_a_workload(self):
        processes = legacy_offline.OfflineProcesses()
        for method in (processes.run, processes.Popen, processes.call, processes.check_call):
            with self.assertRaisesRegex(ValueError, "cannot start"):
                method(["oracle", "-solve", "positions.txt"])
        with self.assertRaisesRegex(ValueError, "cannot start"):
            processes.check_output(["cargo", "test"])
        with self.assertRaisesRegex(ValueError, "cannot execute"):
            legacy_offline.assessment(Path("unused"), "run", 1, "exact_threshold")

    def test_legacy_exact_cache_runner_uses_the_manifest_pinned_entrypoint(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            extracted = root/"temporary verifier"/"exact_cache_verification.py"
            recorded = root/"original worktree"/"exact_cache_verification.py"
            manifest = root/"saved manifest.json"
            temporary_command = (
                "rtk python3 "+shlex.quote(str(extracted.resolve()))
                +" run --manifest "+shlex.quote(str(manifest.resolve()))+' "$@"\n'
            ).encode()
            pinned_command = (
                "rtk python3 "+shlex.quote(str(recorded.resolve()))
                +" run --manifest "+shlex.quote(str(manifest.resolve()))+' "$@"\n'
            ).encode()
            self.assertEqual(
                legacy_offline.restore_pinned_entrypoint(temporary_command, extracted, recorded),
                pinned_command,
            )
            with self.assertRaisesRegex(ValueError, "entrypoint mismatch"):
                legacy_offline.restore_pinned_entrypoint(b"tampered runner", extracted, recorded)

    def test_legacy_manifest_harness_pins_route_original_worktree_without_relabelling(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            relative = Path("tools/reversi-ai-benchmark/exact_threshold.py")
            target = root/relative
            target.parent.mkdir(parents=True)
            target.write_bytes(b"original producer")
            pin = {"path": str(Path("/saved/original/worktree")/relative),
                   "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
            manifest = {"version": "exact-threshold-assessment-v1", "harness_revision": "a"*40,
                        "harness_files": [pin], "inputs": {"openings": {"path": "/saved/openings.json"}}}
            path = root/"manifest.json"
            path.write_bytes(wg.canonical(manifest))
            before = path.read_bytes()
            producer = SimpleNamespace(prep=SimpleNamespace(check_pin=lambda item: Path(item["path"])),
                                       wg=SimpleNamespace(), ROOT=Path("unused"),
                                       harness_paths=lambda: [target])
            def execute(saved_path, command, every):
                self.assertEqual(command, "verify-inputs")
                self.assertEqual(producer.prep.check_pin(pin), Path(pin["path"]))
                self.assertEqual(producer.prep.ROOT, Path("/saved/original/worktree"))
                self.assertEqual(producer.harness_paths(), [Path(pin["path"])])
                bad = {**pin, "sha256": "0"*64}
                with self.assertRaisesRegex(ValueError, "digest mismatch"):
                    producer.prep.check_pin(bad)
            producer.execute = execute
            @contextlib.contextmanager
            def snapshot(revision, entrypoint):
                self.assertEqual(revision, "a"*40)
                yield producer, root
            with patch.object(legacy_offline, "frozen", snapshot):
                legacy_offline.assessment(path, "verify-inputs", 1, "exact_threshold")
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
