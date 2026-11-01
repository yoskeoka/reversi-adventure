"""Human-operated execution supervision. Offline verification imports no runner."""
from __future__ import annotations

import fcntl
import ctypes
import math
import os
import signal
import sys
import time
from pathlib import Path

import table32_store as st


def process_resources(group, worker):
    """Sample the worker and aggregate descendants, failing closed on lost metrics."""
    own, children, user, system = 0, 0, 0.0, 0.0
    ticks = os.sysconf("SC_CLK_TCK")
    worker_seen = False
    paths = [Path(f"/proc/{worker}/stat")]
    paths.extend(path for path in Path("/proc").glob("[0-9]*/stat")
                 if path.parent.name != str(worker))
    for path in paths:
        try:
            raw = path.read_text()
            fields = raw[raw.rfind(")") + 2:].split()
            is_worker = int(path.parent.name) == worker
            if not is_worker and int(fields[2]) != group:
                continue
            status = (path.parent / "status").read_text()
            rss = next((int(line.split()[1]) for line in status.splitlines()
                        if line.startswith("VmRSS:")), None)
            if rss is None:
                # A fast worker can exit between reading stat and status.
                # Recheck its current state before treating a missing RSS as
                # an unavailable live-process metric.
                state = next((line.split()[1] for line in status.splitlines()
                              if line.startswith("State:")), None)
                if fields[0] not in ("Z", "X") and state not in ("Z", "X"):
                    fresh = path.read_text()
                    state = fresh[fresh.rfind(")") + 2:].split()[0]
                st.require(fields[0] in ("Z", "X") or state in ("Z", "X"),
                           "process RSS metrics unavailable")
                rss = 0
            if is_worker:
                own = rss
                worker_seen = True
            else:
                children += rss
            user += int(fields[11]) / ticks
            system += int(fields[12]) / ticks
        except (FileNotFoundError, ProcessLookupError):
            if path.parent.name == str(worker):
                raise ProcessLookupError("worker resource metrics unavailable")
            continue
    st.require(worker_seen, "worker resource metrics unavailable")
    return {"producer_rss_kib": own, "children_rss_kib": children,
            "user_seconds": user, "system_seconds": system}


def _terminate_group(pid):
    # Before setsid completes the group may not yet exist.  Killing the worker
    # as well closes that startup race; after setsid both calls are harmless.
    for action, identity in ((os.killpg, pid), (os.kill, pid)):
        try:
            action(identity, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _parent_death_guard(parent):
    """Terminate this entire session when a killed supervisor cannot clean up."""
    def parent_lost(signum, frame):
        os.killpg(os.getpgrp(), signal.SIGKILL)
    signal.signal(signal.SIGUSR1, parent_lost)
    libc = ctypes.CDLL(None, use_errno=True)
    st.require(libc.prctl(1, signal.SIGUSR1, 0, 0, 0) == 0,
               "cannot install Linux parent-death guard")
    if os.getppid() != parent:
        parent_lost(signal.SIGUSR1, None)


def _failure(attempt, provenance, error):
    context_path = attempt / "progress.json"
    try:
        context = st.read(context_path) if context_path.is_file() else {}
    except (ValueError, OSError):
        context = {}
    return st.seal({**provenance, "reason": str(error),
                   "type": type(error).__name__,
                   "phase": getattr(error, "phase", context.get("phase", "worker")),
                   "unit": getattr(error, "unit", context.get("unit", "unknown")),
                   "raw_log_digests": {p.relative_to(attempt).as_posix(): st.pin(p)["sha256"]
                                       for p in attempt.rglob("*")
                                       if p.is_file() and (p.suffix in (".jsonl", ".stdout", ".stderr")
                                                          or p.name in ("stdout", "stderr"))}})


def supervise(root, manifest, worker, *, progress_every=1, resume_from=None, extend=False):
    root = Path(root)
    st.require(type(progress_every) is int and progress_every > 0,
               "progress-every must be positive")
    lock = (root / "run.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError("another table32 invocation owns this run root")
    try:
        attempts = root / "attempts"
        attempts.mkdir(exist_ok=True)
        prior = sorted(attempts.glob("[0-9]*"))
        charged = 0
        for path in prior:
            budget = st.read(path / "budget.json")["charged_seconds"]
            st.require(type(budget) in (int, float) and math.isfinite(budget) and budget >= 0,
                       "invalid persisted attempt budget")
            completion_path = path / "completion.json"
            if completion_path.is_file():
                completion = st.read(completion_path)
                st.require(completion == st.seal(completion)
                           and completion["manifest_digest"] == st.digest(manifest)
                           and completion["charged_seconds"] == budget,
                           "attempt completion/budget identity mismatch")
            charged += budget
        remaining = manifest["limits"]["wall_seconds"] - charged
        st.require(remaining > 0, "cumulative execution budget exhausted")
        attempt = attempts / f"{len(prior):04d}"
        attempt.mkdir()
        provenance = {"manifest_digest": st.digest(manifest),
                      "execution_commit": manifest["producer_commit"],
                      "effective_settings": manifest["settings"],
                      "resource_limits": manifest["limits"],
                      "resume_from": resume_from, "extend_to_200": extend,
                      "progress_every": progress_every, "prior_charged_seconds": charged}
        st.atomic(attempt / "provenance.json", provenance, once=True)
        st.atomic(attempt / "progress.json", {"phase": "input-verification", "unit": "start"})
        # Reserve the first accounting interval before executing.  The worker
        # parent-death guard ends the process group if the supervisor is lost;
        # the final reserved interval remains charged on an ungraceful exit.
        st.atomic(attempt / "budget.json", {"charged_seconds": min(remaining, 1)})
        started = time.monotonic()
        parent = os.getpid()
        pid = os.fork()
        if pid == 0:
            lock.close()
            try:
                os.setsid()
                _parent_death_guard(parent)
                worker(attempt)
            except BaseException as error:
                st.atomic(attempt / "failure.json", _failure(attempt, provenance, error), once=True)
                os._exit(2)
            os._exit(0)
        previous = {}
        def cancel(signum, frame):
            raise KeyboardInterrupt(f"cancelled by signal {signum}")
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, cancel)
        peak = {"producer_rss_kib": 0, "children_rss_kib": 0}
        failure = None
        failure_error = None
        status = None
        try:
            while True:
                done, status = os.waitpid(pid, os.WNOHANG)
                if done:
                    break
                elapsed = time.monotonic() - started
                st.atomic(attempt / "budget.json", {
                    "charged_seconds": min(remaining, math.ceil(elapsed + 1))})
                try:
                    metrics = process_resources(pid, pid)
                except ProcessLookupError:
                    done, status = os.waitpid(pid, os.WNOHANG)
                    if done:
                        break
                    raise
                for name in peak:
                    peak[name] = max(peak[name], metrics[name])
                st.atomic(attempt / "resources.json", {**metrics, "peaks": peak,
                                                       "elapsed_seconds": elapsed})
                st.require(elapsed < remaining, "cumulative wall budget exceeded")
                st.require(metrics["producer_rss_kib"] <= manifest["limits"]["producer_rss_kib"],
                           "producer RSS budget exceeded")
                st.require(metrics["children_rss_kib"] <= manifest["limits"]["child_rss_kib"],
                           "child process group RSS budget exceeded")
                time.sleep(0.2)
        except BaseException as error:
            failure = str(error)
            failure_error = error
        finally:
            # Reap the worker and terminate every remaining member of its group.
            _terminate_group(pid)
            if status is None or not done:
                _, status = os.waitpid(pid, 0)
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        elapsed = time.monotonic() - started
        charged_attempt = min(remaining, math.ceil(elapsed))
        st.atomic(attempt / "budget.json", {"charged_seconds": charged_attempt,
                                             "elapsed_seconds": elapsed})
        if (status != 0 or failure_error is not None) and not (attempt / "failure.json").exists():
            st.atomic(attempt / "failure.json", _failure(
                attempt, provenance, failure_error if failure_error is not None
                else RuntimeError(f"worker exited with status {status}")), once=True)
        st.atomic(attempt / "completion.json", st.seal({**provenance,
            "status": "complete" if status == 0 and failure is None else "failed",
            "exit_status": status, "reason": failure, "charged_seconds": charged_attempt,
            "elapsed_seconds": elapsed, "peak_resources": peak}), once=True)
        context=st.read(attempt/"progress.json")
        succeeded=status==0 and failure is None
        print(f"table32 phase={context['phase']} unit={context['unit']} completed={int(succeeded)} "
              f"total=1 elapsed_seconds={elapsed:.3f} status={'complete' if succeeded else 'failed'}",
              file=sys.stderr,flush=True)
        st.require(status == 0 and failure is None,
                   failure or f"table32 attempt failed; inspect {attempt / 'failure.json'}")
    finally:
        lock.close()
