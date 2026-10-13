#!/usr/bin/env python3
"""Run the human-operated 0040 efficiency8 measurement through Oracle checks.

Example:
  rtk python3 tools/reversi-ai-benchmark/run-efficiency8-closeout.py \
    --oracle-binary /opt/egaroucid/Egaroucid_for_Console \
    --oracle-cwd /opt/egaroucid/data \
    --output-dir /var/tmp/reversi-ai-efficiency8-2026-10-13 \
    --max-rss-kib 1572864
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

import whole_game as wg

ROOT = Path(__file__).resolve().parents[2]
RUNNER_VERSION = "reversi-ai-efficiency8-closeout-v2"
LEGACY_RUNNER_VERSION = "reversi-ai-efficiency8-closeout-v1"
LEGACY_SOURCE_REVISION = "b82b04d691bffd1866cc02e28416eaebaf2b4680"
GAME_TIMEOUT_SECONDS = 600
ORACLE_TIMEOUT_SECONDS = 600
SAMPLE_GAMES = 8
BUILD_PACKAGE = "reversi-ai"
BUILD_TARGET = "reversi-ai-cli"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise wg.BenchmarkError(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def seal(value: dict, key: str) -> dict:
    result = {name: item for name, item in value.items() if name != key}
    result[key] = sha256_bytes(wg.canonical(result))
    return result


def read_object(path: Path) -> dict:
    return wg.read_canonical(path)


def write_once(path: Path, value: dict, *, digest_key: str | None = None) -> dict:
    sealed = seal(value, digest_key) if digest_key else value
    if path.exists():
        require(read_object(path) == sealed, f"existing evidence mismatch: {path}")
    else:
        wg.atomic_write(path, sealed)
    return sealed


def emit_stage(stage: str, status: str, elapsed_s: float, *, identity: str | None = None) -> None:
    suffix = f" identity={identity}" if identity else ""
    print(f"progress efficiency8 stage={stage} status={status} elapsed_s={elapsed_s:.3f}{suffix}",
          file=sys.stderr, flush=True)


def source_revision(root: Path) -> str:
    result = subprocess.run(["rtk", "git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True)
    revision = result.stdout.strip()
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, "source revision must be a full Git SHA")
    return revision


def require_clean_checkout(root: Path) -> None:
    result = subprocess.run(["rtk", "git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
                            check=True, capture_output=True, text=True)
    require(not result.stdout.strip(), "measurement requires a clean source checkout")


def is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def oracle_runtime(binary: Path, cwd: Path) -> dict:
    binary = binary.resolve(strict=True)
    cwd = cwd.resolve(strict=True)
    require(binary.is_file() and os.access(binary, os.X_OK), "Oracle binary is not executable")
    require(cwd.is_dir(), "Oracle working directory is missing")
    return wg.oracle_runtime_identity(binary, cwd)


def prepare_output_directory(path: Path, root: Path) -> Path:
    path = path.expanduser().resolve()
    require(path != root and not is_within(root, path),
            "output directory cannot contain or replace the source checkout")
    if is_within(path, root):
        ignored = subprocess.run(["rtk", "git", "-C", str(root), "check-ignore", "--quiet", "--no-index", str(path)],
                                 check=False)
        require(ignored.returncode == 0, "output directory inside the checkout must be Git-ignored")
    path.mkdir(parents=True, exist_ok=True)
    require(path.is_dir() and os.access(path, os.W_OK), "output directory is not writable")
    return path


def build_release(root: Path, output_dir: Path, revision: str, *, allow_build: bool = True) -> tuple[dict, int]:
    target_dir = output_dir / "build" / "target"
    binary = target_dir / "release" / BUILD_TARGET
    receipt_path = output_dir / "build-receipt.json"
    command = ["rtk", "cargo", "build", "--release", "-p", BUILD_PACKAGE, "--bin", BUILD_TARGET,
               "--target-dir", str(target_dir)]
    started = time.monotonic_ns()
    if receipt_path.exists():
        receipt = read_object(receipt_path)
        require(receipt.get("receipt_digest") == seal(receipt, "receipt_digest")["receipt_digest"]
                and receipt.get("source_revision") == revision
                and receipt.get("command") == command,
                "release build receipt identity mismatch")
        require(receipt.get("cli", {}).get("path") == str(binary.resolve())
                and binary.is_file() and os.access(binary, os.X_OK)
                and wg.digest(binary) == receipt.get("cli", {}).get("sha256"),
                "release CLI does not match its build receipt")
        return receipt, time.monotonic_ns() - started

    require(allow_build, "compatible saved build receipt is required to resume this run")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, cwd=root, check=True)
    require(binary.is_file() and os.access(binary, os.X_OK), "release CLI binary was not produced")
    receipt = seal({"schema_version": 1, "source_revision": revision, "command": command,
                    "cli": {"path": str(binary.resolve()), "sha256": wg.digest(binary)},
                    "cargo_version": subprocess.run(["rtk", "cargo", "--version"], cwd=root, check=True,
                                                     capture_output=True, text=True).stdout.strip(),
                    "rustc_version": subprocess.run(["rtk", "rustc", "--version"], cwd=root, check=True,
                                                     capture_output=True, text=True).stdout.strip()},
                   "receipt_digest")
    wg.atomic_write(receipt_path, receipt)
    return receipt, time.monotonic_ns() - started


def run_identity(root: Path, output_dir: Path, revision: str, build: dict,
                 runtime: dict, max_rss_kib: int, progress_every: int) -> dict:
    cli = build["cli"]
    harness = {}
    for name in ("run-efficiency8-closeout.py", "whole_game.py", "exact_threshold.py",
                 "prepare-whole-game-measurement.py"):
        path = Path(__file__).with_name(name)
        harness[name] = {"path": str(path.resolve()), "sha256": wg.digest(path)}
    oracle_script = root / "tools/reversi-ai-oracle/oracle.py"
    harness["oracle.py"] = {"path": str(oracle_script.resolve()), "sha256": wg.digest(oracle_script)}
    openings = wg.OPENINGS
    return seal({"schema_version": 1, "runner_version": RUNNER_VERSION,
                 "score_contract": wg.SCORE_CONTRACT, "source_revision": revision,
                 "cli": cli, "oracle": runtime,
                 "settings": {"sample": "efficiency8", "games": SAMPLE_GAMES,
                              "evaluator": "strategic", "opening_depth": 8,
                              "midgame_depth": 8, "endgame_depth": 8, "exact_empty": 16,
                              "cache_scope": "turn", "search_time_limit_ms": None,
                              "node_limit": None, "game_timeout_seconds": GAME_TIMEOUT_SECONDS,
                              "oracle_timeout_seconds": ORACLE_TIMEOUT_SECONDS,
                              "max_rss_kib_per_process": max_rss_kib,
                              "progress_every": progress_every},
                 "host": wg.execution_host_identity(),
                 "openings_sha256": wg.digest(openings), "harness": harness,
                 "output_directory": str(output_dir)}, "identity_digest")


def same_linux_host_except_kernel(saved: dict, current: dict) -> bool:
    try:
        wg.verify_execution_host(saved)
        wg.verify_execution_host(current)
    except wg.BenchmarkError:
        return False
    if saved["node"] != current["node"] or saved["machine"] != current["machine"]:
        return False
    kernel = re.compile(r"^Linux-([0-9]+(?:\.[0-9]+)*)(-.+)$")
    saved_match, current_match = kernel.fullmatch(saved["system"]), kernel.fullmatch(current["system"])
    return (saved_match is not None and current_match is not None
            and saved_match.group(2) == current_match.group(2))


def git_blob_sha256(root: Path, revision: str, relative_path: str) -> str:
    result = subprocess.run(["rtk", "git", "-C", str(root), "show", f"{revision}:{relative_path}"],
                            check=True, capture_output=True)
    return sha256_bytes(result.stdout)


def validate_saved_identity(identity: dict, *, root: Path, output_dir: Path, current_revision: str,
                            runtime: dict, max_rss_kib: int, progress_every: int) -> str:
    require(identity.get("identity_digest") == seal(identity, "identity_digest")["identity_digest"],
            "saved closeout identity digest mismatch")
    require(identity.get("schema_version") == 1, "unsupported closeout identity schema")
    saved_revision = identity.get("source_revision")
    require(isinstance(saved_revision, str) and re.fullmatch(r"[0-9a-f]{40}", saved_revision) is not None,
            "saved closeout source revision invalid")
    runner = identity.get("runner_version")
    if runner == LEGACY_RUNNER_VERSION:
        require(saved_revision == LEGACY_SOURCE_REVISION,
                "unsupported legacy closeout source revision")
    else:
        require(runner == RUNNER_VERSION and saved_revision == current_revision,
                "unsupported closeout runner or source revision")
    require(set(identity) == {"schema_version", "runner_version", "score_contract", "source_revision",
            "cli", "oracle", "settings", "host", "openings_sha256", "harness", "output_directory",
            "identity_digest"}, "saved closeout identity fields invalid")
    ancestor = subprocess.run(["rtk", "git", "-C", str(root), "merge-base", "--is-ancestor",
                               saved_revision, current_revision], check=False, capture_output=True)
    require(ancestor.returncode == 0, "saved closeout source is not an ancestor of the current revision")
    expected_settings = {"sample": "efficiency8", "games": SAMPLE_GAMES, "evaluator": "strategic",
        "opening_depth": 8, "midgame_depth": 8, "endgame_depth": 8, "exact_empty": 16,
        "cache_scope": "turn", "search_time_limit_ms": None, "node_limit": None,
        "game_timeout_seconds": GAME_TIMEOUT_SECONDS, "oracle_timeout_seconds": ORACLE_TIMEOUT_SECONDS,
        "max_rss_kib_per_process": max_rss_kib, "progress_every": progress_every}
    require(identity.get("score_contract") == wg.SCORE_CONTRACT
            and identity.get("settings") == expected_settings
            and identity.get("oracle") == runtime
            and identity.get("output_directory") == str(output_dir),
            "saved closeout input identity changed")
    require(same_linux_host_except_kernel(identity.get("host"), wg.execution_host_identity()),
            "saved closeout host differs beyond Linux kernel release")
    openings_relative = "tools/reversi-ai-benchmark/whole-game-openings-v1.json"
    require(identity.get("openings_sha256") == wg.digest(Path(__file__).with_name("whole-game-openings-v1.json"))
            and identity["openings_sha256"] == git_blob_sha256(root, saved_revision, openings_relative),
            "saved closeout openings changed")
    harness_paths = {
        "run-efficiency8-closeout.py": "tools/reversi-ai-benchmark/run-efficiency8-closeout.py",
        "whole_game.py": "tools/reversi-ai-benchmark/whole_game.py",
        "exact_threshold.py": "tools/reversi-ai-benchmark/exact_threshold.py",
        "prepare-whole-game-measurement.py": "tools/reversi-ai-benchmark/prepare-whole-game-measurement.py",
        "oracle.py": "tools/reversi-ai-oracle/oracle.py"}
    harness = identity.get("harness")
    require(isinstance(harness, dict) and set(harness) == set(harness_paths),
            "saved closeout harness identity invalid")
    for name, relative_path in harness_paths.items():
        item = harness[name]
        current_path = (root / relative_path).resolve()
        require(isinstance(item, dict) and set(item) == {"path", "sha256"}
                and item.get("path") == str(current_path)
                and item.get("sha256") == git_blob_sha256(root, saved_revision, relative_path),
                f"saved closeout harness changed: {name}")
    expected_cli = output_dir / "build" / "target" / "release" / BUILD_TARGET
    cli = identity.get("cli")
    require(isinstance(cli, dict) and set(cli) == {"path", "sha256"}
            and cli.get("path") == str(expected_cli.resolve())
            and re.fullmatch(r"[0-9a-f]{64}", str(cli.get("sha256", ""))) is not None,
            "saved closeout CLI identity invalid")
    return saved_revision


def store_or_verify_identity(path: Path, identity: dict, output_dir: Path) -> None:
    if path.exists():
        require(read_object(path) == identity, "existing closeout run identity mismatch")
        return
    known = ("whole-game-report.json", "report-verification.json", "oracle-evidence.json",
             "oracle-verification.json", "summary.json", "stage-state.json", "oracle-checkpoints")
    require(not any((output_dir / name).exists() for name in known),
            "run evidence exists without its pinned run identity")
    wg.atomic_write(path, identity)


def validate_output_contents(output_dir: Path) -> None:
    allowed = {"runner.lock", "build", "build-receipt.json", "run-identity.json", "stage-state.json",
               "whole-game-report.json", "whole-game-checkpoints", "report-verification.json",
               "oracle-checkpoints", "oracle-evidence.json", "oracle-verification.json", "summary.json"}
    unknown = [path.name for path in output_dir.iterdir()
               if path.name not in allowed and not path.name.startswith(".unfinished-")]
    require(not unknown, f"unknown output files: {', '.join(sorted(unknown))}")


class StageTracker:
    def __init__(self, output_dir: Path, identity: dict, invocation_started: float, *,
                 current_revision: str, record_invocation: bool = True):
        self.path = output_dir / "stage-state.json"
        self.identity = identity
        self.invocation_started = invocation_started
        current_invocation = {"host": wg.execution_host_identity(), "source_revision": current_revision,
                              "started_at_unix_ns": time.time_ns()}
        if self.path.exists():
            self.state = read_object(self.path)
            require(self.state.get("state_digest") == seal(self.state, "state_digest")["state_digest"]
                    and self.state.get("identity_digest") == identity["identity_digest"],
                    "closeout stage state identity mismatch")
            require(self.state.get("schema_version") in (1, 2)
                    and isinstance(self.state.get("stages"), dict), "closeout stage state schema invalid")
            if self.state["schema_version"] == 1:
                self.state = {**self.state, "schema_version": 2,
                    "invocations": [{"host": identity["host"],
                                     "source_revision": identity["source_revision"],
                                     "started_at_unix_ns": None}]}
            else:
                require(isinstance(self.state.get("invocations"), list),
                        "closeout invocation history invalid")
            for item in self.state["invocations"]:
                require(isinstance(item, dict)
                        and set(item) == {"host", "source_revision", "started_at_unix_ns"},
                        "closeout invocation record invalid")
                wg.verify_execution_host(item["host"])
                require(item["source_revision"] is None
                        or isinstance(item["source_revision"], str)
                        and re.fullmatch(r"[0-9a-f]{40}", item["source_revision"]) is not None,
                        "closeout invocation revision invalid")
                require(item["started_at_unix_ns"] is None
                        or type(item["started_at_unix_ns"]) is int and item["started_at_unix_ns"] > 0,
                        "closeout invocation timestamp invalid")
            if record_invocation:
                self.state["invocations"].append(current_invocation)
                self._save()
        else:
            self.state = {"schema_version": 2, "identity_digest": identity["identity_digest"],
                          "stages": {}, "invocations": [current_invocation] if record_invocation else []}
            self._save()

    def _save(self) -> None:
        wg.atomic_write(self.path, seal(self.state, "state_digest"))

    def run(self, stage: str, callback, *, success_status: str = "completed"):
        emit_stage(stage, "started", time.monotonic() - self.invocation_started,
                   identity=self.identity["identity_digest"])
        started = time.monotonic_ns()
        try:
            result = callback()
        except BaseException:
            elapsed = time.monotonic_ns() - started
            record = self.state["stages"].setdefault(stage, {"elapsed_ns": 0, "attempts": 0, "failures": 0})
            record["elapsed_ns"] += elapsed
            record["attempts"] += 1
            record["failures"] += 1
            record["status"] = "failed"
            self._save()
            emit_stage(stage, "failed", time.monotonic() - self.invocation_started,
                       identity=self.identity["identity_digest"])
            raise
        elapsed = time.monotonic_ns() - started
        record = self.state["stages"].setdefault(stage, {"elapsed_ns": 0, "attempts": 0, "failures": 0})
        record["elapsed_ns"] += elapsed
        record["attempts"] += 1
        record["status"] = success_status
        self._save()
        emit_stage(stage, success_status, time.monotonic() - self.invocation_started,
                   identity=self.identity["identity_digest"])
        return result

    def add_bootstrap(self, stage: str, elapsed_ns: int, status: str) -> None:
        record = self.state["stages"].setdefault(stage, {"elapsed_ns": 0, "attempts": 0, "failures": 0})
        record["elapsed_ns"] += elapsed_ns
        record["attempts"] += 1
        record["status"] = status
        self._save()


def validate_measurement_report(report: dict, report_path: Path, identity: dict,
                                cli: Path, args, output_dir: Path) -> dict:
    wg.verify(report, cli)
    require(report.get("binary") == identity["cli"],
            "whole-game report binary differs from the pinned release CLI")
    expected_args = argparse.Namespace(kind="cli-persistent", binary=cli, artifact=None,
        evaluator="strategic", opening_depth=8, midgame_depth=8, endgame_depth=8,
        exact_empty=16, cache_scope="turn", timeout_seconds=GAME_TIMEOUT_SECONDS,
        search_time_limit_ms=None, node_limit=None, max_rss_kib=args.max_rss_kib,
        max_decisions=120, game_sample="efficiency8", source_revision=identity["source_revision"])
    expected_measurement_identity = wg.measurement_identity(expected_args)
    require(report.get("identity") == expected_measurement_identity
            and report.get("condition_id") == "efficiency8"
            and report.get("settings", {}).get("max_rss_kib") == args.max_rss_kib,
            "whole-game report does not match the efficiency8 run identity")
    require(len(report.get("games", [])) == SAMPLE_GAMES
            and report.get("performance_summary") is not None,
            "whole-game report is not the complete efficiency8 sample")
    require(wg.digest(report_path) == sha256_bytes(wg.canonical(report)),
            "whole-game report file digest mismatch")
    return report


def report_marker(report: dict, report_path: Path, identity: dict) -> dict:
    return seal({"schema_version": 1, "run_identity_digest": identity["identity_digest"],
                 "report_digest": report["report_digest"], "report_file_sha256": wg.digest(report_path),
                 "cli_sha256": identity["cli"]["sha256"]}, "verification_digest")


def probe_cli(cli: Path, max_rss_kib: int) -> None:
    seat = wg.Seat("cli", cli, None, 8, 10, "efficiency8-preflight", cache_scope="turn",
        exact_empty=16, max_rss_kib=max_rss_kib, opening_depth=8, endgame_depth=8,
        unbounded_search=True, evaluator="strategic")
    try:
        seat.new_game("efficiency8-preflight")
        usage = seat.close()
    finally:
        if seat.process is not None:
            seat.abort()
    require(usage["peak_rss_kib"] <= max_rss_kib, "CLI preflight exceeded the configured RSS cap")


def require_pinned_oracle_runtime(oracle: dict) -> None:
    current = wg.oracle_runtime_identity(Path(oracle["binary"]["path"]),
                                         Path(oracle["working_directory"]))
    require(current == oracle, "Oracle runtime changed after closeout preflight")


def require_pinned_cli(cli: Path, identity: dict) -> None:
    require(str(cli.resolve()) == identity["cli"]["path"]
            and wg.digest(cli) == identity["cli"]["sha256"],
            "release CLI changed after closeout build")


def oracle_marker(report: dict, evidence: dict, evidence_path: Path, identity: dict) -> dict:
    return seal({"schema_version": 1, "run_identity_digest": identity["identity_digest"],
                 "report_digest": report["report_digest"], "oracle_evidence_digest": evidence["report_digest"],
                 "oracle_evidence_file_sha256": wg.digest(evidence_path),
                 "oracle_binary_sha256": identity["oracle"]["binary"]["sha256"],
                 "timeout_seconds": ORACLE_TIMEOUT_SECONDS,
                 "max_rss_kib": identity["settings"]["max_rss_kib_per_process"]}, "verification_digest")


def final_summary(report: dict, evidence: dict, report_path: Path, evidence_path: Path,
                  identity: dict, tracker: StageTracker, invocation_elapsed_ns: int) -> dict:
    games = []
    wall_seconds = []
    for record in report["games"]:
        wall_ns = record["wall_ns"]
        seconds = wall_ns / 1_000_000_000
        wall_seconds.append(seconds)
        games.append({"id": f"{record['opening_id']}-seat{record['assignment']}",
                      "opening_id": record["opening_id"], "assignment": record["assignment"],
                      "wall_ns": wall_ns, "wall_seconds": seconds})
    require(len(games) == SAMPLE_GAMES and all(value >= 0 for value in wall_seconds),
            "cannot summarize incomplete game timing")
    ordered = sorted(wall_seconds)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    flat_queries = []
    for position in evidence["positions"]:
        for query in position["queries"]:
            search, process = query["search"], query["process"]
            flat_queries.append({"position_id": position["id"], "role": query["role"],
                "board": query["board"], "side": query["side"],
                "effective_side": query["effective_side"], "score": search["value"],
                "exact": search["exact"], "completed_depth": search["completed_depth"],
                "nodes": search["nodes"], "search_elapsed_ms": search["elapsed_ms"],
                "process_wall_ns": process["wall_ns"],
                "user_cpu_ns": process["resources"]["user_cpu_ns"],
                "system_cpu_ns": process["resources"]["system_cpu_ns"],
                "peak_rss_kib": process["resources"]["peak_rss_kib"],
                "execution_host": query["execution_host"]})
    require(flat_queries, "Oracle evidence contains no measured queries")
    stage_elapsed = {name: record["elapsed_ns"] for name, record in tracker.state["stages"].items()}
    oracle_aggregate = {
        "positions": len(evidence["positions"]), "queries": len(flat_queries),
        "search_elapsed_ms": sum(query["search_elapsed_ms"] for query in flat_queries),
        "nodes": sum(query["nodes"] for query in flat_queries),
        "process_wall_ns": sum(query["process_wall_ns"] for query in flat_queries),
        "user_cpu_ns": sum(query["user_cpu_ns"] for query in flat_queries),
        "system_cpu_ns": sum(query["system_cpu_ns"] for query in flat_queries),
        "peak_rss_kib": max(query["peak_rss_kib"] for query in flat_queries)}
    return seal({"schema_version": 1, "runner_version": RUNNER_VERSION,
        "score_contract": wg.SCORE_CONTRACT, "run_identity_digest": identity["identity_digest"],
        "source_revision": identity["source_revision"], "cli": identity["cli"], "oracle": identity["oracle"],
        "settings": identity["settings"], "whole_game_report": {
            "path": str(report_path), "file_sha256": wg.digest(report_path),
            "report_digest": report["report_digest"]},
        "oracle_evidence": {"path": str(evidence_path), "file_sha256": wg.digest(evidence_path),
            "report_digest": evidence["report_digest"]},
        "games": games, "performance": {"mean_seconds": sum(wall_seconds) / len(wall_seconds),
            "nearest_rank_p95_seconds": p95, "mean_goal_seconds": 180,
            "p95_review_seconds": 300, "limits_are_non_cutoff_indicators": True},
        "oracle_aggregate": oracle_aggregate, "oracle_queries": flat_queries,
        "host_invocations": tracker.state["invocations"],
        "stage_elapsed_ns": stage_elapsed, "active_stage_elapsed_ns": sum(stage_elapsed.values()),
        "invocation_elapsed_ns": invocation_elapsed_ns}, "summary_digest")


def verify_existing_summary(output_dir: Path, identity: dict, cli: Path, args) -> dict:
    summary_path = output_dir / "summary.json"
    summary = read_object(summary_path)
    require(summary.get("summary_digest") == seal(summary, "summary_digest")["summary_digest"]
            and summary.get("schema_version") == 1
            and summary.get("runner_version") == RUNNER_VERSION
            and summary.get("run_identity_digest") == identity["identity_digest"]
            and summary.get("source_revision") == identity["source_revision"]
            and summary.get("cli") == identity["cli"]
            and summary.get("oracle") == identity["oracle"]
            and summary.get("settings") == identity["settings"],
            "existing closeout summary identity or digest mismatch")
    report_path, evidence_path = output_dir / "whole-game-report.json", output_dir / "oracle-evidence.json"
    report, evidence = read_object(report_path), read_object(evidence_path)
    validate_measurement_report(report, report_path, identity, cli, args, output_dir)
    wg.verify_oracle_evidence(report, evidence, Path(identity["oracle"]["binary"]["path"]),
        oracle_cwd=Path(identity["oracle"]["working_directory"]),
        timeout_seconds=ORACLE_TIMEOUT_SECONDS,
        max_rss_kib=identity["settings"]["max_rss_kib_per_process"])
    wg.verify_oracle_checkpoints(report, evidence, Path(identity["oracle"]["binary"]["path"]),
        Path(identity["oracle"]["working_directory"]), output_dir / "oracle-checkpoints",
        timeout_seconds=ORACLE_TIMEOUT_SECONDS,
        max_rss_kib=identity["settings"]["max_rss_kib_per_process"])
    require(summary["whole_game_report"] == {"path": str(report_path), "file_sha256": wg.digest(report_path),
            "report_digest": report["report_digest"]}
            and summary["oracle_evidence"] == {"path": str(evidence_path), "file_sha256": wg.digest(evidence_path),
            "report_digest": evidence["report_digest"]}, "existing closeout summary artifact digest mismatch")
    require(read_object(output_dir / "report-verification.json") == report_marker(report, report_path, identity),
            "existing whole-game verification marker mismatch")
    require(read_object(output_dir / "oracle-verification.json") == oracle_marker(report, evidence, evidence_path, identity),
            "existing Oracle verification marker mismatch")
    state_path = output_dir / "stage-state.json"
    require(state_path.is_file(), "closeout stage state is missing")
    tracker = StageTracker(output_dir, identity, time.monotonic(),
                           current_revision=identity["source_revision"], record_invocation=False)
    expected_summary = final_summary(report, evidence, report_path, evidence_path, identity, tracker,
                                     summary.get("invocation_elapsed_ns", -1))
    require(summary == expected_summary, "existing closeout summary content mismatch")
    return summary


def run_closeout(args, *, root: Path = ROOT) -> dict:
    invocation_started = time.monotonic()
    invocation_started_ns = time.monotonic_ns()
    root = root.resolve(strict=True)
    emit_stage("preflight", "started", 0)
    require(platform.system() == "Linux" and hasattr(os, "wait4"), "efficiency8 requires Linux wait4")
    require(type(args.max_rss_kib) is int and args.max_rss_kib > 0,
            "--max-rss-kib must be a positive integer")
    require(type(args.progress_every) is int and args.progress_every > 0,
            "--progress-every must be a positive integer")
    oracle = oracle_runtime(args.oracle_binary, args.oracle_cwd)
    revision = source_revision(root)
    require_clean_checkout(root)
    output_dir = prepare_output_directory(args.output_dir, root)
    preflight_elapsed_ns = time.monotonic_ns() - invocation_started_ns
    with (output_dir / "runner.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise wg.BenchmarkError("another efficiency8 closeout is using this output directory") from exc
        emit_stage("preflight", "completed", time.monotonic() - invocation_started)
        emit_stage("build", "started", time.monotonic() - invocation_started)
        identity_path = output_dir / "run-identity.json"
        if identity_path.exists():
            identity = read_object(identity_path)
            saved_revision = validate_saved_identity(identity, root=root, output_dir=output_dir,
                current_revision=revision, runtime=oracle, max_rss_kib=args.max_rss_kib,
                progress_every=args.progress_every)
            build, build_elapsed_ns = build_release(root, output_dir, saved_revision, allow_build=False)
            require(build.get("cli") == identity["cli"],
                    "saved closeout CLI differs from its build receipt")
        else:
            build, build_elapsed_ns = build_release(root, output_dir, revision)
            identity = run_identity(root, output_dir, revision, build, oracle,
                                    args.max_rss_kib, args.progress_every)
            store_or_verify_identity(identity_path, identity, output_dir)
        emit_stage("build", "completed", time.monotonic() - invocation_started)
        validate_output_contents(output_dir)
        cli = Path(identity["cli"]["path"])
        require_pinned_cli(cli, identity)
        if (output_dir / "summary.json").exists():
            emit_stage("report-verification", "started", time.monotonic() - invocation_started,
                       identity=identity["identity_digest"])
            emit_stage("report-verification", "verified", time.monotonic() - invocation_started,
                       identity=identity["identity_digest"])
            emit_stage("oracle-verification", "started", time.monotonic() - invocation_started,
                       identity=identity["identity_digest"])
            summary = verify_existing_summary(output_dir, identity, cli, args)
            emit_stage("oracle-verification", "verified", time.monotonic() - invocation_started,
                       identity=identity["identity_digest"])
            performance = summary["performance"]
            print(f"progress efficiency8 stage=complete games=8 mean_s={performance['mean_seconds']:.3f} "
                  f"nearest_rank_p95_s={performance['nearest_rank_p95_seconds']:.3f} "
                  f"oracle_positions={summary['oracle_aggregate']['positions']} "
                  f"elapsed_s={time.monotonic() - invocation_started:.3f}", file=sys.stderr, flush=True)
            print(f"verified existing efficiency8 summary: {output_dir / 'summary.json'}")
            return summary

        tracker = StageTracker(output_dir, identity, invocation_started, current_revision=revision)
        tracker.add_bootstrap("preflight", preflight_elapsed_ns, "completed")
        tracker.add_bootstrap("build", build_elapsed_ns, "completed")
        report_path = output_dir / "whole-game-report.json"
        checkpoints = output_dir / "whole-game-checkpoints"
        if report_path.exists():
            existing_report = validate_measurement_report(read_object(report_path), report_path,
                                                          identity, cli, args, output_dir)
            marker_path = output_dir / "report-verification.json"
            if marker_path.exists():
                require(read_object(marker_path) == report_marker(existing_report, report_path, identity),
                        "existing whole-game verification marker mismatch")
            oracle_checkpoints = output_dir / "oracle-checkpoints"
            oracle_binary = Path(oracle["binary"]["path"])
            if oracle_checkpoints.exists():
                wg.preflight_oracle_checkpoints(existing_report, oracle_binary,
                    Path(oracle["working_directory"]), ORACLE_TIMEOUT_SECONDS, args.max_rss_kib,
                    oracle_checkpoints, identity["host"])
            existing_evidence_path = output_dir / "oracle-evidence.json"
            if existing_evidence_path.exists():
                existing_evidence = read_object(existing_evidence_path)
                wg.verify_oracle_evidence(existing_report, existing_evidence, oracle_binary,
                    oracle_cwd=Path(oracle["working_directory"]),
                    timeout_seconds=ORACLE_TIMEOUT_SECONDS, max_rss_kib=args.max_rss_kib)
                wg.verify_oracle_checkpoints(existing_report, existing_evidence, oracle_binary,
                    Path(oracle["working_directory"]), oracle_checkpoints,
                    timeout_seconds=ORACLE_TIMEOUT_SECONDS, max_rss_kib=args.max_rss_kib)
        expected_args = argparse.Namespace(kind="cli-persistent", binary=cli, artifact=None,
            evaluator="strategic", opening_depth=8, midgame_depth=8, endgame_depth=8,
            exact_empty=16, cache_scope="turn", timeout_seconds=GAME_TIMEOUT_SECONDS,
            search_time_limit_ms=None, node_limit=None, max_rss_kib=args.max_rss_kib,
            max_decisions=120, game_sample="efficiency8", output=report_path,
            checkpoint_dir=checkpoints, progress_every=args.progress_every,
            source_revision=identity["source_revision"])
        measurement_identity = wg.measurement_identity(expected_args)
        measurement_manifest_digest = sha256_bytes(wg.canonical(measurement_identity))
        wg.preflight_measurement_checkpoints(expected_args, measurement_manifest_digest,
                                             "efficiency8", checkpoints)

        tracker.run("cli-preflight", lambda: probe_cli(cli, args.max_rss_kib), success_status="verified")
        require_pinned_cli(cli, identity)

        def game_progress(game_id: str, done: int, total: int, game_s: float, elapsed_s: float) -> None:
            if done % args.progress_every and done != total:
                return
            print(f"progress efficiency8 stage=self-play game={game_id} done={done} total={total} "
                  f"game_s={game_s:.3f} elapsed_s={elapsed_s:.3f}", file=sys.stderr, flush=True)

        report = tracker.run("self-play", lambda: wg.measure_resumable(
            expected_args, measurement_manifest_digest, "efficiency8", checkpoints,
            conditions_done=0, conditions_total=1, game_progress=game_progress))
        report = validate_measurement_report(report, report_path, identity, cli, args, output_dir)

        def verify_report_stage():
            wg.verify(report, cli)
            marker = report_marker(report, report_path, identity)
            write_once(output_dir / "report-verification.json", marker)
            return marker
        tracker.run("report-verification", verify_report_stage, success_status="verified")

        evidence_path = output_dir / "oracle-evidence.json"
        oracle_checkpoints = output_dir / "oracle-checkpoints"
        oracle_binary = Path(oracle["binary"]["path"])

        def oracle_progress(position_id: str, done: int, total: int,
                            query_elapsed_ms: int, elapsed_s: float) -> None:
            if done % args.progress_every and done != total:
                return
            print(f"progress efficiency8 stage=oracle-check position={position_id} done={done} total={total} "
                  f"query_elapsed_ms={query_elapsed_ms} elapsed_s={elapsed_s:.3f}",
                  file=sys.stderr, flush=True)

        def run_oracle_stage():
            require_pinned_oracle_runtime(oracle)
            if evidence_path.exists():
                evidence = read_object(evidence_path)
                wg.verify_oracle_evidence(report, evidence, oracle_binary,
                    oracle_cwd=Path(oracle["working_directory"]),
                    timeout_seconds=ORACLE_TIMEOUT_SECONDS, max_rss_kib=args.max_rss_kib)
                wg.verify_oracle_checkpoints(report, evidence, oracle_binary,
                    Path(oracle["working_directory"]), oracle_checkpoints,
                    timeout_seconds=ORACLE_TIMEOUT_SECONDS, max_rss_kib=args.max_rss_kib)
                if evidence.get("schema_version") == 3:
                    evidence = wg.oracle_evidence(report, oracle_binary, Path(oracle["working_directory"]),
                        ORACLE_TIMEOUT_SECONDS, max_rss_kib=args.max_rss_kib,
                        checkpoint_dir=oracle_checkpoints, progress_every=args.progress_every,
                        progress_callback=oracle_progress, legacy_execution_host=identity["host"])
                    wg.atomic_write(evidence_path, evidence)
            else:
                evidence = wg.oracle_evidence(report, oracle_binary, Path(oracle["working_directory"]),
                    ORACLE_TIMEOUT_SECONDS, max_rss_kib=args.max_rss_kib,
                    checkpoint_dir=oracle_checkpoints, progress_every=args.progress_every,
                    progress_callback=oracle_progress, legacy_execution_host=identity["host"])
                wg.verify_oracle_evidence(report, evidence, oracle_binary,
                    oracle_cwd=Path(oracle["working_directory"]),
                    timeout_seconds=ORACLE_TIMEOUT_SECONDS, max_rss_kib=args.max_rss_kib)
                wg.verify_oracle_checkpoints(report, evidence, oracle_binary,
                    Path(oracle["working_directory"]), oracle_checkpoints,
                    timeout_seconds=ORACLE_TIMEOUT_SECONDS, max_rss_kib=args.max_rss_kib)
                wg.atomic_write(evidence_path, evidence)
            require_pinned_oracle_runtime(oracle)
            return evidence

        evidence = tracker.run("oracle-check", run_oracle_stage)
        wg.verify_oracle_evidence(report, evidence, oracle_binary,
            oracle_cwd=Path(oracle["working_directory"]),
            timeout_seconds=ORACLE_TIMEOUT_SECONDS, max_rss_kib=args.max_rss_kib)
        wg.verify_oracle_checkpoints(report, evidence, oracle_binary,
            Path(oracle["working_directory"]), oracle_checkpoints,
            timeout_seconds=ORACLE_TIMEOUT_SECONDS, max_rss_kib=args.max_rss_kib)

        def verify_oracle_stage():
            marker = oracle_marker(report, evidence, evidence_path, identity)
            write_once(output_dir / "oracle-verification.json", marker)
            return marker
        tracker.run("oracle-verification", verify_oracle_stage, success_status="verified")

        elapsed_ns = time.monotonic_ns() - invocation_started_ns
        summary = final_summary(report, evidence, report_path, evidence_path, identity, tracker, elapsed_ns)
        summary_path = output_dir / "summary.json"
        require(not summary_path.exists(), "success summary already exists and was not validated")
        wg.atomic_write(summary_path, summary)
        performance = summary["performance"]
        print(f"progress efficiency8 stage=complete games=8 mean_s={performance['mean_seconds']:.3f} "
              f"nearest_rank_p95_s={performance['nearest_rank_p95_seconds']:.3f} "
              f"oracle_positions={summary['oracle_aggregate']['positions']} "
              f"elapsed_s={elapsed_ns / 1_000_000_000:.3f}", file=sys.stderr, flush=True)
        print(f"verified efficiency8 closeout: {summary_path}")
        return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle-binary", type=Path, required=True)
    parser.add_argument("--oracle-cwd", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-rss-kib", type=int, required=True)
    parser.add_argument("--progress-every", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        run_closeout(args)
    except (wg.BenchmarkError, OSError, ValueError, KeyError, TypeError,
            subprocess.CalledProcessError) as exc:
        print(f"efficiency8 closeout error: {exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("efficiency8 closeout interrupted; verified checkpoints are retained for resume",
              file=sys.stderr, flush=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
