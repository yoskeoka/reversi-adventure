import fcntl
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import table32_process as process
import table32_store as st


def manifest(wall=10, rss=262144):
    return {"producer_commit": "a" * 40, "settings": {"fixture": True},
            "limits": {"wall_seconds": wall, "producer_rss_kib": rss,
                       "child_rss_kib": 1572864}}


def _alive(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        return raw[raw.rfind(")") + 2:].split()[0] not in ("Z", "X")
    except FileNotFoundError:
        return False


@unittest.skipUnless(sys.platform == "linux", "Linux resource supervision contract")
class Table32ProcessTests(unittest.TestCase):
    def test_live_worker_metrics_available(self):
        metrics = process.process_resources(os.getpgrp(), os.getpid())
        self.assertGreater(metrics["producer_rss_kib"], 0)
        self.assertGreaterEqual(metrics["user_seconds"], 0)

    def test_missing_rss_fails_closed_except_zombie(self):
        def reader(path, *args, **kwargs):
            if path.name == "stat":
                return "123 (fixture) S 1 123 " + "0 " * 20
            return "Name: fixture\n"
        with patch.object(Path, "glob", return_value=[]), patch.object(Path, "read_text", reader):
            with self.assertRaisesRegex(Exception, "RSS metrics unavailable"):
                process.process_resources(123, 123)
        def zombie(path, *args, **kwargs):
            return reader(path).replace(") S ", ") Z ")
        with patch.object(Path, "glob", return_value=[]), patch.object(Path, "read_text", zombie):
            self.assertEqual(process.process_resources(123, 123)["producer_rss_kib"], 0)

    def test_normal_attempts_charge_cumulatively_and_never_reset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = manifest(wall=2)
            def worker(attempt):
                (attempt / "fixture.done").write_text("complete")
            process.supervise(root, settings, worker)
            process.supervise(root, settings, worker)
            self.assertEqual(sum(st.read(path / "budget.json")["charged_seconds"]
                                 for path in (root / "attempts").iterdir()), 2)
            with self.assertRaisesRegex(Exception, "cumulative execution budget exhausted"):
                process.supervise(root, settings, worker)

    def test_worker_exiting_between_stat_and_status_has_no_live_rss(self):
        def reader(path, *args, **kwargs):
            if path.name == "stat":
                return "123 (fixture) R 1 123 " + "0 " * 20
            return "Name: fixture\nState:\tZ (zombie)\n"
        with patch.object(Path,"glob",return_value=[]),patch.object(Path,"read_text",reader):
            self.assertEqual(process.process_resources(123,123)["producer_rss_kib"],0)

    def test_worker_failure_preserves_stage_settings_and_raw_log_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def worker(attempt):
                st.atomic(attempt / "progress.json", {"phase": "generation", "unit": "game-004"})
                (attempt / "raw.stdout").write_text("fixture diagnostic")
                raise ValueError("fixture interrupted search")
            with self.assertRaisesRegex(Exception, "attempt failed"):
                process.supervise(root, manifest(), worker)
            attempt = root / "attempts/0000"
            failure = st.read(attempt / "failure.json")
            self.assertEqual((failure["phase"], failure["unit"]), ("generation", "game-004"))
            self.assertEqual(failure["effective_settings"], {"fixture": True})
            self.assertEqual(failure["resource_limits"], manifest()["limits"])
            self.assertEqual(failure["raw_log_digests"]["raw.stdout"], st.pin(attempt / "raw.stdout")["sha256"])
            self.assertEqual(st.read(attempt / "completion.json")["status"], "failed")

    def test_rss_violation_has_failure_receipt_and_reaps_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def worker(attempt):
                (attempt / "worker.pid").write_text(str(os.getpid()))
                time.sleep(2)
            with self.assertRaisesRegex(Exception, "producer RSS budget exceeded"):
                process.supervise(root, manifest(rss=1), worker)
            attempt = root / "attempts/0000"
            failure = st.read(attempt / "failure.json")
            self.assertIn("producer RSS budget exceeded", failure["reason"])
            self.assertEqual(failure["phase"], "input-verification")
            self.assertLessEqual(st.read(attempt / "budget.json")["charged_seconds"], 1)
            pid_path = attempt / "worker.pid"
            if pid_path.exists():
                self.assertFalse(_alive(int(pid_path.read_text())))

    def test_lock_and_invalid_persisted_budget_fail_before_new_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def worker(attempt):
                raise AssertionError("must not launch")
            with (root / "run.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, "another table32 invocation"):
                    process.supervise(root, manifest(), worker)
            st.atomic(root / "attempts/0000/budget.json", {"charged_seconds": -1})
            with self.assertRaisesRegex(Exception, "invalid persisted attempt budget"):
                process.supervise(root, manifest(), worker)
            self.assertFalse((root / "attempts/0001").exists())

    def test_supervisor_failure_hashes_logs_after_group_termination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original_terminate = process._terminate_group
            def terminate(pid):
                # Model the last child log write between detection and reap.
                (root / "attempts/0000/raw.stdout").write_text("final child log tail")
                original_terminate(pid)
            with patch.object(process, "process_resources", side_effect=RuntimeError("fixture metrics lost")), \
                    patch.object(process, "_terminate_group", side_effect=terminate):
                with self.assertRaisesRegex(Exception, "fixture metrics lost"):
                    process.supervise(root, manifest(), lambda attempt: time.sleep(2))
            attempt = root / "attempts/0000"
            failure = st.read(attempt / "failure.json")
            self.assertEqual(failure["type"], "RuntimeError")
            self.assertEqual(failure["reason"], "fixture metrics lost")
            self.assertEqual(failure["raw_log_digests"]["raw.stdout"], st.pin(attempt / "raw.stdout")["sha256"])

    def test_changed_manifest_cannot_reuse_attempt_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process.supervise(root, manifest(), lambda attempt: None)
            changed = manifest()
            changed["settings"] = {"fixture": "changed"}
            with self.assertRaisesRegex(Exception, "identity mismatch"):
                process.supervise(root, changed, lambda attempt: None)

    def test_hard_killed_supervisor_stops_group_and_leaves_reserved_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            supervisor = os.fork()
            if supervisor == 0:
                def worker(attempt):
                    child = os.fork()
                    if child == 0:
                        while True:
                            time.sleep(.02)
                    st.atomic(attempt / "fixture-pids.json", {"worker": os.getpid(), "child": child})
                    while True:
                        time.sleep(.02)
                try:
                    process.supervise(root, manifest(), worker)
                finally:
                    os._exit(0)
            try:
                path = root / "attempts/0000/fixture-pids.json"
                deadline = time.monotonic() + 3
                while not path.is_file() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(path.is_file(), "fixture worker failed to start")
                pids = st.read(path)
                os.kill(supervisor, signal.SIGKILL)
                os.waitpid(supervisor, 0)
                supervisor = None
                deadline = time.monotonic() + 3
                while any(_alive(pid) for pid in pids.values()) and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertFalse(any(_alive(pid) for pid in pids.values()))
                budget = st.read(root / "attempts/0000/budget.json")["charged_seconds"]
                self.assertGreaterEqual(budget, 1)
                self.assertLess(budget, 10)
                # A new invocation retains the old charge and can continue
                # completed units within the same unchanged remaining budget.
                process.supervise(root, manifest(), lambda attempt: None)
                self.assertEqual(st.read(root / "attempts/0001/provenance.json")["prior_charged_seconds"], budget)
            finally:
                if supervisor is not None:
                    os.kill(supervisor, signal.SIGKILL)
                    os.waitpid(supervisor, 0)


if __name__ == "__main__":
    unittest.main()
