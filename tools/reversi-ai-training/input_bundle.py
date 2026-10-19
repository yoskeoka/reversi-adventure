#!/usr/bin/env python3
"""Immutable, bounded human-operated input stages and offline provenance checks."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import random_inputs
import training
import reinforcement

ROOT = Path(__file__).resolve().parents[2]
VERSION = "reversi-ai-input-bundle-v1"
MIB = 1024 * 1024
BOUNDS = {
    "calibration-generate": (120, 256 * MIB), "calibration-verify": (120, 512 * MIB),
    "calibration-train": (300, 1024 * MIB), "generate": (600, 1024 * MIB),
    "verify": (1200, 2048 * MIB), "train": (1800, 3072 * MIB),
    "corpus": (120, 256 * MIB), "oracle": (4200, 3072 * MIB),
    "bundle-verify": (2400, 3072 * MIB), "cli-probe": (10, 3072 * MIB),
}
PRODUCERS = ("tools/reversi-ai-training/random_inputs.py", "tools/reversi-ai-training/training.py",
             "tools/reversi-ai-training/reinforcement.py", "tools/reversi-ai-training/input_bundle.py",
             "tools/reversi-ai-training/corpus.py", "tools/reversi-ai-oracle/oracle.py", "tools/reversi-ai-training/legacy.py")
BUILD_RECIPE = ["cargo", "build", "--release", "--bin", "reversi-ai-cli"]
TOTAL_WALL_SECONDS = sum(wall for wall, _ in BOUNDS.values())
PREDECESSORS = {
    "calibration-generate": set(), "calibration-verify": {"calibration-generate"},
    "calibration-train": {"calibration-verify"}, "generate": {"calibration-train"},
    "verify": {"generate"}, "train": {"verify"}, "corpus": {"train"}, "oracle": {"corpus"},
    "cli-probe": {"train"}, "bundle-verify": {"oracle", "cli-probe"},
}


def fail(message: str) -> None:
    raise training.TrainingError(message)


def canonical(value: object) -> bytes:
    return training.canonical_json(value) + b"\n"


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value))


def pin(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": training.sha256_file(path)}


def checked_pin(value: dict, base: Path) -> Path:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"} or not isinstance(value["path"], str):
        fail("invalid file identity")
    path = (base / value["path"]).resolve()
    if not path.is_file() or training.sha256_file(path) != value["sha256"]:
        fail(f"file identity mismatch: {path}")
    return path


def git(*args: str, root: Path = ROOT) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True)
    if result.returncode:
        fail("Git provenance check failed: " + " ".join(args))
    return result.stdout


def source_identity(root: Path = ROOT, *, require_clean: bool = True) -> dict:
    if require_clean and git("status", "--porcelain", root=root):
        fail("producer checkout must be clean")
    source = git("rev-parse", "HEAD", root=root).decode().strip()
    main = git("rev-parse", "origin/main", root=root).decode().strip()
    git("merge-base", "--is-ancestor", source, main, root=root)
    return {"source_commit": source, "merged_main": main, "checkout": str(root.resolve()),
            "producer_sources": {name: hashlib.sha256(git("show", f"{source}:{name}", root=root)).hexdigest()
                                 for name in PRODUCERS}}


def validate_producer_metadata(identity: dict, *, require_source_closure: bool = False) -> None:
    """Check the recorded producer identity's shape without opening its checkout."""
    if not isinstance(identity, dict) or set(identity) != {"source_commit", "merged_main", "producer_sources", "checkout"}:
        fail("invalid producer identity")
    for key in ("source_commit", "merged_main"):
        text = identity[key]
        if not isinstance(text, str) or not re.fullmatch(r"[0-9a-f]{40}", text):
            fail("invalid producer revision")
    checkout = identity["checkout"]
    if not isinstance(checkout, str) or not Path(checkout).is_absolute():
        fail("invalid producer checkout metadata")
    sources = identity["producer_sources"]
    if not isinstance(sources, dict) or not sources or any(not isinstance(name, str) for name in sources):
        fail("incomplete producer source closure")
    if require_source_closure and set(sources) != set(PRODUCERS):
        fail("incomplete producer source closure")
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
           for value in sources.values()):
        fail("invalid producer source digest")


def verify_source(identity: dict, root: Path | None = None) -> None:
    validate_producer_metadata(identity, require_source_closure=True)
    root = root or Path(identity["checkout"])
    source, main = identity["source_commit"], identity["merged_main"]
    git("merge-base", "--is-ancestor", source, main, root=root)
    git("merge-base", "--is-ancestor", main, "origin/main", root=root)
    for name, expected in identity["producer_sources"].items():
        if hashlib.sha256(git("show", f"{source}:{name}", root=root)).hexdigest() != expected:
            fail("producer bytes differ from Git revision")
        if training.sha256_file(root / name) != expected:
            fail("offline producer bytes differ from pinned revision")
        if training.sha256_file(ROOT / name) != expected:
            fail("active verifier differs from frozen producer; invoke pinned checkout tooling")


def reservation(value: dict, base: Path) -> dict:
    if not isinstance(value, dict) or set(value) != {"state", "artifact", "keys"}:
        fail("invalid acceptance reservation")
    if value["state"] == "not-yet-selected":
        if value["artifact"] is not None or value["keys"] != []:
            fail("unselected reservation must have no artifact or keys")
        return value
    if value["state"] != "reserved":
        fail("unsupported acceptance reservation state")
    artifact = checked_pin(value["artifact"], base)
    data = training.read_json(artifact)
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("openings"), list):
        fail("reserved suite requires versioned concrete openings")
    for row in data["openings"]:
        board, side = row.get("board"), row.get("side")
        if not isinstance(board, str) or len(board) != 64 or any(c not in "BW." for c in board) or side not in ("B", "W"):
            fail("invalid reserved opening")
        moves = row.get("moves")
        if not isinstance(moves, list) or not moves:
            fail("reserved opening requires concrete nonempty legal Black-start moves")
        replay_board, replay_side = reinforcement.INITIAL, "B"
        for move in moves:
            legal = reinforcement.legal_moves(replay_board, replay_side)
            if move == "pass":
                if legal or not reinforcement.legal_moves(replay_board, reinforcement.other(replay_side)):
                    fail("reserved suite has illegal pass")
            else:
                replay_board = reinforcement.apply_move(replay_board, replay_side, move)
            replay_side = reinforcement.other(replay_side)
        if (replay_board, replay_side) != (board, side) or board == reinforcement.INITIAL:
            fail("reserved suite root differs from concrete opening")
    keys = sorted({training.canonical_position_key(row["board"], row["side"]) for row in data["openings"]})
    if not keys or keys != value["keys"]:
        fail("reserved suite keys differ from openings")
    for key in keys:
        board, side = key.split(":")
        if len(board) != 64 or any(c not in "BW." for c in board) or side not in ("B", "W"):
            fail("invalid reserved opening")
    return {"state": "reserved", "artifact": pin(artifact), "keys": keys}


def check_acceptance_collision(openings: list[dict], exposures: dict[str, list[str]]) -> None:
    used = {key for values in exposures.values() for key in values}
    if any(training.canonical_position_key(row["board"], row["side"]) in used for row in openings):
        fail("acceptance opening collides with prior exposure")


def check_acceptance_roots(root_keys: list[str], exposure_keys: dict[str, list[str]]) -> None:
    if set(root_keys).intersection(key for keys in exposure_keys.values() for key in keys):
        fail("acceptance opening collides with prior exposure")


def process_metrics(group: int) -> tuple[int, float, set[int]]:
    """Linux process-group aggregate; disappearing processes are harmless races."""
    if sys.platform != "linux":
        fail("resource supervision requires Linux /proc")
    rss, cpu, members = 0, 0.0, set()
    ticks, page = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
    try:
        paths = list(Path("/proc").iterdir())
        for path in paths:
            if not path.name.isdecimal():
                continue
            try:
                line = (path / "stat").read_text()
            except FileNotFoundError:
                continue
            fields = line[line.rfind(")") + 2:].split()
            if int(fields[2]) != group:
                continue
            members.add(int(path.name))
            rss += int(fields[21]) * page
            cpu += (int(fields[11]) + int(fields[12])) / ticks
    except (OSError, ValueError, IndexError) as error:
        fail(f"resource metric unavailable: {error}")
    return rss, cpu, members


def progress(stage: str, done: int, status: str, elapsed: float, rss: int) -> None:
    print(f"progress input-bundle stage={stage} done={done} total=1 status={status} "
          f"elapsed_s={elapsed:.3f} rss_bytes={rss}", file=sys.stderr, flush=True)


def kill_group(group: int) -> None:
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass


@contextlib.contextmanager
def termination_cancellation():
    """Defer SIGTERM cleanup until Popen has returned its process handle."""
    cancelled = [False]
    previous = signal.getsignal(signal.SIGTERM)
    def terminate(_signal, _frame):
        cancelled[0] = True
    signal.signal(signal.SIGTERM, terminate)
    try:
        yield cancelled
    finally:
        signal.signal(signal.SIGTERM, previous)


def supervise(manifest_path: Path, output: Path, *, heartbeat_seconds: float = 5,
              metric_reader=process_metrics) -> dict:
    """Run exactly one immutable stage, leaving failure originals and never resuming."""
    manifest = training.read_json(manifest_path)
    stage = manifest.get("stage")
    if stage not in BOUNDS or manifest.get("version") != VERSION or manifest.get("total_wall_budget_seconds") != TOTAL_WALL_SECONDS:
        fail("unsupported stage manifest")
    wall, limit = BOUNDS[stage]
    if manifest.get("bounds") != {"wall_seconds": wall, "rss_bytes": limit, "sample_seconds": 1}:
        fail("stage limits differ from fixed budget")
    if not math.isfinite(heartbeat_seconds) or heartbeat_seconds <= 0:
        fail("heartbeat seconds must be positive")
    verify_source(manifest["producer"], Path(manifest["cwd"]))
    if git("status", "--porcelain", root=Path(manifest["cwd"])):
        fail("execution producer checkout must be clean")
    for identity in manifest.get("inputs", []):
        checked_pin(identity, manifest_path.parent)
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifest.json").write_bytes(manifest_path.read_bytes())
    with termination_cancellation() as cancelled:
        return _supervise_execution(manifest_path, output, manifest, heartbeat_seconds, metric_reader, cancelled)


def _supervise_execution(manifest_path, output, manifest, heartbeat_seconds, metric_reader, cancelled):
    stage = manifest["stage"]
    wall, limit = BOUNDS[stage]
    started, next_heartbeat, peak, cpu = time.monotonic(), 0.0, 0, 0.0
    reason, code, process, error_text = "failed", None, None, None
    progress(stage, 0, "running", 0, 0)
    try:
        with (output / "stdout").open("xb") as stdout, (output / "stderr").open("xb") as stderr:
            argv = [sys.executable, str(Path(manifest["cwd"]) / "tools/reversi-ai-training/input_bundle.py"),
                    "worker", "--manifest", str(manifest_path.resolve()), "--result", str((output / "result.json").resolve())]
            process = subprocess.Popen(argv, cwd=manifest["cwd"], stdout=stdout,
                                       stderr=stderr, start_new_session=True)
            while True:
                if cancelled[0]:
                    reason, error_text = "interrupted", "SIGTERM cancellation"
                    break
                elapsed = time.monotonic() - started
                rss, observed_cpu, members = metric_reader(process.pid)
                peak, cpu = max(peak, rss), max(cpu, observed_cpu)
                if elapsed >= wall:
                    reason = "wall-limit"
                    break
                if rss > limit:
                    reason = "rss-limit"
                    break
                code = process.poll()
                if code is not None and not members:
                    reason = "completed" if code == 0 else "exit-failure"
                    break
                if not members and code is None:
                    # Reap an exited leader before treating the race as metric failure.
                    code = process.poll()
                    if code is None:
                        fail("resource metrics unavailable for active stage")
                if elapsed >= next_heartbeat:
                    progress(stage, 0, "running", elapsed, rss)
                    next_heartbeat = elapsed + heartbeat_seconds
                time.sleep(min(1.0, max(0.01, wall - elapsed)))
    except (training.TrainingError, OSError, KeyboardInterrupt) as error:
        reason = "interrupted" if isinstance(error, KeyboardInterrupt) else "metric-or-launch-failure"
        error_text = str(error)
    finally:
        if process is not None:
            kill_group(process.pid)
            code = process.wait()
        if cancelled[0]:
            reason, error_text = "interrupted", "SIGTERM cancellation"
        elapsed = time.monotonic() - started
        report = {"version": VERSION, "stage": stage, "manifest_sha256": training.sha256_file(manifest_path),
                  "status": reason, "exit_code": code, "wall_seconds": elapsed, "cpu_seconds": cpu,
                  "error": error_text,
                  "peak_observed_rss_bytes": peak, "sample_seconds": 1,
                  "rss_limitation": "sampled process-group sum; instantaneous peaks and exited-child CPU may be missed",
                  "stdout_sha256": training.sha256_file(output / "stdout") if (output / "stdout").exists() else None,
                  "stderr_sha256": training.sha256_file(output / "stderr") if (output / "stderr").exists() else None}
        # Verify frozen identities after execution before publishing completion.
        if reason == "completed":
            try:
                verify_source(manifest["producer"], Path(manifest["cwd"]))
                for identity in manifest.get("inputs", []):
                    checked_pin(identity, manifest_path.parent)
                result = training.read_json(output / "result.json")
                if result.get("stage") != stage or result.get("manifest_sha256") != training.sha256_file(manifest_path):
                    fail("missing stage output verification")
                for item in result["outputs"].values():
                    checked_pin(item, output)
                report["result"] = pin(output / "result.json")
            except (training.TrainingError, OSError, ValueError, KeyError, TypeError) as error:
                report["status"] = "identity-change"
                report["error"] = str(error)
        if cancelled[0]:
            report["status"], report["error"] = "interrupted", "SIGTERM cancellation"
        save(output / ("report.json" if report["status"] == "completed" else "failure.json"), report)
        progress(stage, int(report["status"] == "completed"),
                 "saved" if report["status"] == "completed" else "failed", elapsed, peak)
    if report["status"] != "completed":
        fail(f"stage failed: {report['status']}; originals retained at {output}")
    return report


def verify_stage(report_path: Path, producer: dict | None = None, *, visited=None) -> dict:
    visited = set() if visited is None else visited
    if report_path.resolve() in visited:
        fail("cyclic stage dependencies")
    visited = visited | {report_path.resolve()}
    report = training.read_json(report_path)
    manifest_path = report_path.parent / "manifest.json"
    manifest = training.read_json(manifest_path)
    stage = manifest.get("stage")
    if (stage not in BOUNDS or manifest.get("version") != VERSION or report.get("version") != VERSION
            or manifest.get("total_wall_budget_seconds") != TOTAL_WALL_SECONDS):
        fail("unsupported stage completion")
    wall, rss = BOUNDS[stage]
    if (report.get("stage") != stage or report.get("status") != "completed" or report.get("exit_code") != 0
            or report.get("manifest_sha256") != training.sha256_file(manifest_path)
            or manifest.get("bounds") != {"wall_seconds": wall, "rss_bytes": rss, "sample_seconds": 1}
            or report.get("sample_seconds") != 1):
        fail("stage completion identity mismatch")
    for key, limit in (("wall_seconds", wall), ("peak_observed_rss_bytes", rss), ("cpu_seconds", math.inf)):
        value = report.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= limit:
            fail("stage resource result outside fixed budget")
    if producer is not None and manifest.get("producer") != producer:
        fail("stage producer differs from bundle")
    for name in ("stdout", "stderr"):
        if training.sha256_file(report_path.parent / name) != report.get(name + "_sha256"):
            fail("stage original log identity mismatch")
    for value in manifest.get("inputs", []):
        checked_pin(value, manifest_path.parent)
    expected_inputs = {str(p.resolve()) for p in request_inputs(stage, manifest["request"])}
    if not expected_inputs.issubset({str(checked_pin(v, manifest_path.parent)) for v in manifest["inputs"]}):
        fail("stage request is not fully frozen")
    result = training.read_json(checked_pin(report["result"], report_path.parent))
    if result.get("stage") != stage or result.get("manifest_sha256") != training.sha256_file(manifest_path):
        fail("stage result identity mismatch")
    for item in result["outputs"].values():
        checked_pin(item, report_path.parent)
    kind = stage.removeprefix("calibration-")
    request = manifest["request"]
    if kind in ("generate", "verify", "train"):
        expected_names = {"generator_manifest", "games.jsonl", "train.jsonl", "validation.jsonl", "held_out.jsonl", "trainer-manifest.json", "report.json"}
        if kind == "train":
            expected_names |= {"artifact", "report"}
    elif kind == "corpus":
        expected_names = {"generator_manifest", "corpus.jsonl", "games.jsonl", "selection.json"}
    elif kind == "oracle":
        expected_names = {str(p.relative_to(Path(request["output_dir"]))) for p in Path(request["output_dir"]).rglob("*") if p.is_file()}
    else:
        expected_names = {"cli-probe"} if kind == "cli-probe" else {"bundle_manifest", "report"}
    if set(result["outputs"]) != expected_names:
        fail("stage output identity closure incomplete")
    previous = {}
    for item in manifest["inputs"]:
        original = checked_pin(item, report_path.parent)
        if original.name == "report.json":
            data = training.read_json(original)
            if data.get("version") == VERSION and data.get("stage") in PREDECESSORS[stage]:
                checked = verify_stage(original, producer, visited=visited)
                previous[checked["stage"]] = checked
    if not PREDECESSORS[stage].issubset(previous):
        fail("stage completion lacks verified predecessors")
    for parent_stage, prior in previous.items():
        if kind in ("verify", "train"):
            prior_outputs = prior["result"]["outputs"]
            for name in ("generator_manifest", "games.jsonl", "train.jsonl", "validation.jsonl", "held_out.jsonl", "trainer-manifest.json", "report.json"):
                if prior_outputs.get(name) != result["outputs"].get(name):
                    fail("stage consumed a different predecessor package")
    manifest["result"] = result
    return manifest


def load_oracle():
    path = ROOT / "tools/reversi-ai-oracle/oracle.py"
    spec = importlib.util.spec_from_file_location("input_bundle_oracle", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def cli_identity(binary: Path, producer: dict, receipt: Path) -> dict:
    verify_source(producer)
    lock = git("show", f"{producer['source_commit']}:Cargo.lock", root=Path(producer["checkout"]))
    return {"source_commit": producer["source_commit"], "cargo_lock_sha256": hashlib.sha256(lock).hexdigest(),
            "build_recipe": BUILD_RECIPE, "binary": pin(binary), "build_receipt": pin(receipt)}


def build_cli(output: Path, source_root: Path = ROOT) -> None:
    if os.environ.get("CARGO_TARGET_DIR"):
        fail("unset CARGO_TARGET_DIR before the frozen default-target CLI build")
    identity = source_identity(source_root)
    output.mkdir(parents=True, exist_ok=False)
    lock = hashlib.sha256(git("show", f"{identity['source_commit']}:Cargo.lock", root=source_root)).hexdigest()
    frozen = {"version": VERSION, "producer": identity, "cwd": str(source_root.resolve()),
              "argv": BUILD_RECIPE, "cargo_lock_sha256": lock}
    save(output / "manifest.json", frozen)
    with (output / "stdout").open("xb") as stdout, (output / "stderr").open("xb") as stderr:
        result = subprocess.run(BUILD_RECIPE, cwd=source_root, stdout=stdout, stderr=stderr)
    verify_source(identity, source_root)
    if git("status", "--porcelain", root=source_root) or result.returncode:
        save(output / "failure.json", {"exit_code": result.returncode})
        fail("CLI build failed or producer checkout changed")
    binary = source_root / "target/release/reversi-ai-cli"
    save(output / "build.json", {"version": VERSION, "manifest": pin(output / "manifest.json"),
                                "stdout": pin(output / "stdout"), "stderr": pin(output / "stderr"),
                                "exit_code": 0, "binary": pin(binary)})


def verify_build(receipt: Path, binary: Path, producer: dict, *,
                 require_current_sources: bool = True, cargo_lock_sha256: str | None = None) -> None:
    record = training.read_json(receipt)
    frozen = training.read_json(checked_pin(record["manifest"], receipt.parent))
    for name in ("stdout", "stderr"):
        checked_pin(record[name], receipt.parent)
    if require_current_sources:
        root = Path(producer["checkout"])
        expected_lock = hashlib.sha256(git("show", f"{producer['source_commit']}:Cargo.lock", root=root)).hexdigest()
        expected_cwd = str(root.resolve())
    else:
        expected_lock = cargo_lock_sha256
        expected_cwd = producer["checkout"]
    expected = {"version": VERSION, "producer": producer, "cwd": expected_cwd, "argv": BUILD_RECIPE,
                "cargo_lock_sha256": expected_lock}
    if frozen != expected or record.get("version") != VERSION or record.get("exit_code") != 0 or record.get("binary") != pin(binary):
        fail("CLI build receipt differs from pinned source/build/binary")


def verify_cli(value: dict, producer: dict, base: Path, executable: Path | None, *,
               require_current_sources: bool = True) -> dict:
    if not isinstance(value, dict) or set(value) != {"source_commit", "cargo_lock_sha256", "build_recipe", "binary", "build_receipt"}:
        fail("invalid CLI build identity")
    if (value.get("source_commit") != producer.get("source_commit")
            or not isinstance(value.get("cargo_lock_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["cargo_lock_sha256"])
            or value.get("build_recipe") != BUILD_RECIPE):
        fail("invalid CLI producer/build metadata")
    binary = checked_pin(value["binary"], base)
    receipt = checked_pin(value["build_receipt"], base)
    verify_build(receipt, binary, producer, require_current_sources=require_current_sources,
                 cargo_lock_sha256=value["cargo_lock_sha256"])
    expected = (cli_identity(binary, producer, receipt) if require_current_sources else value)
    if value != expected:
        fail("CLI source/lock/build identity mismatch")
    if executable is not None and training.sha256_file(executable) != value["binary"]["sha256"]:
        fail("pilot executable differs from bundled CLI")
    return expected


REQUEST_FIELDS = {
    "generate": {"generator_manifest", "output_dir", "progress_every"},
    "verify": {"generator_manifest", "generator_dir", "progress_every"},
    "train": {"generator_manifest", "generator_dir", "artifact", "report", "record_total", "progress_every"},
    "corpus": {"generator_manifest", "generator_dir", "seed", "output_dir", "reservation", "progress_every"},
    "oracle": {"corpus_dir", "binary", "oracle_cwd", "output_dir", "progress_every"},
    "cli-probe": {"validation", "artifact", "cli", "output_dir", "reservation"},
    "bundle-verify": {"bundle_manifest", "cli", "report"},
}


def request_inputs(stage: str, request: dict) -> list[Path]:
    kind = stage.removeprefix("calibration-")
    optional = {"runtime_receipt"} if kind == "oracle" else set()
    if (not isinstance(request, dict) or not REQUEST_FIELDS[kind].issubset(request)
            or not set(request).issubset(REQUEST_FIELDS[kind] | optional)):
        fail("invalid stage request fields")
    if "progress_every" in request:
        training.require_int(request["progress_every"], "progress interval", 1)
    if "record_total" in request:
        training.require_int(request["record_total"], "actual trainer record total", 1)
    for key in set(request) - {"seed", "record_total", "progress_every", "reservation"}:
        if not isinstance(request[key], str) or not Path(request[key]).is_absolute():
            fail("stage paths must be absolute strings")
    inputs = []
    for name in ("generator_manifest", "generator_dir", "corpus_dir", "binary", "validation", "artifact", "cli", "bundle_manifest", "runtime_receipt"):
        if name not in request or (kind == "train" and name == "artifact"):
            continue
        path = Path(request[name])
        if not path.is_absolute():
            fail("stage paths must be absolute")
        if path.is_dir():
            inputs.extend(sorted(p for p in path.rglob("*") if p.is_file()))
        elif path.is_file():
            inputs.append(path)
        else:
            fail("missing frozen stage input")
    if kind == "oracle":
        # Runtime binary and resource tree are both frozen before execution.
        runtime = Path(request["oracle_cwd"]) / "resources"
        if not runtime.is_dir():
            fail("Oracle resources are required")
        inputs.extend(sorted(p for p in runtime.rglob("*") if p.is_file()))
    if "reservation" in request:
        checked = reservation(request["reservation"], ROOT)
        if checked["artifact"] is not None:
            inputs.append(Path(checked["artifact"]["path"]))
    for name in ("output_dir", "report"):
        if name in request and not Path(request[name]).is_absolute():
            fail("stage output paths must be absolute")
    return inputs


def probe_position(validation: Path, reserved: dict) -> dict:
    for row in training.read_jsonl(validation):
        board, side = row["board"], row["side"]
        if (64 - board.count(".") <= 20 and reinforcement.legal_moves(board, side)
                and training.canonical_position_key(board, side) not in reserved["keys"]):
            return {"board": board, "side": side, "record_id": row["record_id"]}
    fail("validation has no eligible first CLI probe opening")


def probe_argv(binary: Path, artifact: Path) -> list[str]:
    return [str(binary.resolve()), "--evaluator", "trained", "--trained-artifact", str(artifact.resolve()),
            "--opening-depth", "1", "--midgame-depth", "1", "--endgame-depth", "1",
            "--exact-solver-empty-squares", "16", "--time-limit-ms", "100", "--node-limit", "1000",
            "--exact-cache-scope", "turn"]


def run_probe(validation: Path, artifact: Path, binary: Path, output: Path, reserved: dict) -> Path:
    output.mkdir(parents=True, exist_ok=False)
    position = probe_position(validation, reserved)
    requests = ["new_game\tinput-bundle-probe", f"input-bundle-probe-move\t{position['board']}\t{position['side']}"]
    frozen = {"version": VERSION, "position": position, "argv": probe_argv(binary, artifact),
              "binary": pin(binary), "artifact": pin(artifact), "validation": pin(validation),
              "requests": requests, "response_watchdog_seconds": 2}
    save(output / "manifest.json", frozen)
    process = None
    try:
        with (output / "stdout").open("xb") as stdout, (output / "stderr").open("xb") as stderr:
            process = subprocess.Popen(frozen["argv"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, bufsize=0)
            answers = []
            buffer = bytearray()
            for request in requests:
                process.stdin.write((request + "\n").encode("ascii"))
                process.stdin.flush()
                deadline = time.monotonic() + 2
                while b"\n" not in buffer:
                    wait = deadline - time.monotonic()
                    if wait <= 0 or not select.select([process.stdout], [], [], wait)[0]:
                        fail("CLI probe response watchdog exceeded")
                    data = os.read(process.stdout.fileno(), 4096)
                    stdout.write(data)
                    stdout.flush()
                    if not data:
                        fail("CLI probe exited before response")
                    buffer.extend(data)
                    if len(buffer) > 4096:
                        fail("CLI probe response too long")
                answer, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                answers.append(answer.decode("ascii") + "\n")
            if answers[0] != "new_game\tinput-bundle-probe\tready\n":
                fail("CLI probe reset acknowledgement differs")
            move = answers[1].removeprefix("input-bundle-probe-move\t").rstrip("\n")
            if answers[1] != f"input-bundle-probe-move\t{move}\n" or move not in reinforcement.legal_moves(position["board"], position["side"]):
                fail("CLI probe response is not legal")
        if pin(binary) != frozen["binary"] or pin(artifact) != frozen["artifact"]:
            fail("CLI probe runtime identity changed")
        completed = {"version": VERSION, "manifest": pin(output / "manifest.json"),
                     "stdout": pin(output / "stdout"), "stderr": pin(output / "stderr"), "move": move}
        save(output / "cli-probe.json", completed)
        return output / "cli-probe.json"
    finally:
        if process is not None:
            process.kill() if process.poll() is None else None
            process.communicate()


def verify_probe(path: Path, validation: Path, artifact: Path, cli: dict, reserved: dict) -> None:
    completed = training.read_json(path)
    original = training.read_json(checked_pin(completed["manifest"], path.parent))
    stdout = checked_pin(completed["stdout"], path.parent).read_bytes()
    checked_pin(completed["stderr"], path.parent)
    binary = checked_pin(cli["binary"], path.parent)
    position = probe_position(validation, reserved)
    expected = {"version": VERSION, "position": position, "argv": probe_argv(binary, artifact),
                "binary": pin(binary), "artifact": pin(artifact), "validation": pin(validation),
                "requests": ["new_game\tinput-bundle-probe", f"input-bundle-probe-move\t{position['board']}\t{position['side']}"],
                "response_watchdog_seconds": 2}
    move = completed.get("move")
    if (original != expected or completed.get("version") != VERSION
            or move not in reinforcement.legal_moves(position["board"], position["side"])
            or stdout != f"new_game\tinput-bundle-probe\tready\ninput-bundle-probe-move\t{move}\n".encode("ascii")):
        fail("CLI probe differs from saved raw legal/reset response")


def split_position_keys(directory: Path) -> set[str]:
    return {training.canonical_position_key(row["board"], row["side"])
            for split in random_inputs.SPLITS
            for row in training.iter_jsonl(directory / f"{split}.jsonl")}


def worker_stage(manifest_path: Path, result_path: Path) -> None:
    manifest = training.read_json(manifest_path)
    stage, request = manifest["stage"], manifest["request"]
    kind = stage.removeprefix("calibration-")
    verify_source(manifest["producer"], ROOT)
    request_inputs(stage, request)
    for item in manifest["inputs"]:
        checked_pin(item, manifest_path.parent)
    outputs, extra = {}, {}
    interval = request.get("progress_every", 1)
    if kind in ("generate", "verify", "train", "corpus"):
        generator_manifest = Path(request["generator_manifest"])
        generator = random_inputs.check_manifest(generator_manifest)
        if generator["source_commit"] != manifest["producer"]["source_commit"]:
            fail("stage generator differs from pinned producer")
        if stage.startswith("calibration-") and generator["counts"] != {"train": 4, "validation": 2, "held_out": 2}:
            fail("calibration requires exactly 4/2/2 games")
        outputs["generator_manifest"] = pin(generator_manifest)
        directory = Path(request.get("generator_dir", request.get("output_dir")))
        if kind == "generate":
            random_inputs.generate(generator_manifest, directory, interval)
        # All package verification, including re-generation, remains in the supervised group.
        if kind != "corpus":
            random_inputs.verify(generator_manifest, directory, interval)
        if kind in ("generate", "verify", "train"):
            outputs.update({p.name: pin(p) for p in directory.iterdir() if p.is_file()})
        if kind == "train":
            trainer_path = directory / "trainer-manifest.json"
            rows = training.validate_records(training.validate_manifest(training.read_json(trainer_path), directory))
            if len(rows) != request["record_total"]:
                fail("frozen trainer record total mismatch")
            artifact, report = Path(request["artifact"]), Path(request["report"])
            if artifact.exists() or report.exists():
                fail("trainer outputs already exist; rerun at fresh paths")
            artifact.parent.mkdir(parents=True, exist_ok=True)
            report.parent.mkdir(parents=True, exist_ok=True)
            training.run(trainer_path, artifact, report, interval)
            outputs.update({"artifact": pin(artifact), "report": pin(report)})
            extra["record_total"] = len(rows)
        if kind == "corpus":
            import corpus
            reserved = reservation(request["reservation"], ROOT)
            excluded = split_position_keys(directory)
            if request["seed"] == generator["seed"]:
                fail("corpus seed must be independent")
            destination = Path(request["output_dir"])
            corpus.generate(request["seed"], excluded, destination, reserved["keys"], progress_every=interval)
            corpus.verify(destination, excluded, reserved["keys"])
            outputs.update({p.name: pin(p) for p in destination.iterdir() if p.is_file()})
    elif kind == "oracle":
        destination = Path(request["output_dir"])
        oracle = load_oracle()
        rows = training.read_jsonl(Path(request["corpus_dir"]) / "corpus.jsonl")
        options = {"runtime_receipt": Path(request["runtime_receipt"])} if "runtime_receipt" in request else {}
        oracle.generate_saved_golden(rows, Path(request["binary"]), Path(request["oracle_cwd"]), destination,
                                     timeout=300, progress_every=interval, **options)
        oracle.verify_raw_golden(rows, destination)
        outputs = {str(p.relative_to(destination)): pin(p) for p in destination.rglob("*") if p.is_file()}
    elif kind == "cli-probe":
        reserved = reservation(request["reservation"], ROOT)
        path = run_probe(Path(request["validation"]), Path(request["artifact"]), Path(request["cli"]), Path(request["output_dir"]), reserved)
        verify_probe(path, Path(request["validation"]), Path(request["artifact"]),
                     {"binary": pin(Path(request["cli"]))}, reserved)
        outputs = {"cli-probe": pin(path)}
    else:
        result = verify_bundle(Path(request["bundle_manifest"]), Path(request["cli"]))
        save(Path(request["report"]), result)
        outputs = {"bundle_manifest": pin(Path(request["bundle_manifest"])), "report": pin(Path(request["report"]))}
    for item in manifest["inputs"]:
        checked_pin(item, manifest_path.parent)
    save(result_path, {"version": VERSION, "stage": stage, "manifest_sha256": training.sha256_file(manifest_path),
                       "outputs": outputs, **extra})


def strength_eligible(generator: dict, *, oracle_runtime_verified: bool) -> bool:
    """Counts alone never promote fixture runtime evidence into production input."""
    return (oracle_runtime_verified is True and generator["counts"] == random_inputs.COUNTS
            and generator["record_start_placements"] == 8 and generator["max_turns"] == 128)


def verify_bundle(path: Path, candidate_executable: Path | None = None, *, cli_path: Path | None = None,
                  require_current_sources: bool = True) -> dict:
    """Replay every input offline; never launch CLI, Oracle, generator subprocesses."""
    path = Path(path).resolve()
    manifest = training.read_json(path)
    if not isinstance(manifest, dict) or set(manifest) != {"version", "score_contract", "total_wall_budget_seconds", "producer", "generator_manifest", "generator_outputs", "baseline_artifact", "baseline_report", "corpus_outputs", "oracle_outputs", "acceptance_reservation", "cli", "cli_probe", "stages"}:
        fail("invalid completion bundle shape")
    if manifest["version"] != VERSION or manifest["score_contract"] != training.SCORE_CONTRACT or manifest["total_wall_budget_seconds"] != TOTAL_WALL_SECONDS:
        fail("unsupported bundle score identity")
    if require_current_sources:
        verify_source(manifest["producer"])
    else:
        validate_producer_metadata(manifest["producer"])
    reserved = reservation(manifest["acceptance_reservation"], path.parent)
    generator_manifest = checked_pin(manifest["generator_manifest"], path.parent)
    if require_current_sources:
        # Strict standalone verification replays the historical producer bytes.
        from legacy import producer
        source_dir = Path(manifest["producer"]["checkout"]) / "tools/reversi-ai-training"
        digests = {name: manifest["producer"]["producer_sources"][f"tools/reversi-ai-training/{name}"]
                   for name in ("training.py", "reinforcement.py", "random_inputs.py")}
        with producer("random_inputs", source_dir=source_dir, source_digests=digests) as frozen:
            generator = frozen.check_manifest(generator_manifest)
    else:
        # 0019 consumes the already-completed producer receipt and replays the
        # data with current code; source hashes remain provenance metadata.
        generator = random_inputs.check_manifest(generator_manifest, require_current_sources=False)
    if generator["source_commit"] != manifest["producer"]["source_commit"] or generator["base_commit"] != manifest["producer"]["merged_main"]:
        fail("generator revision differs from bundle")
    outputs = manifest["generator_outputs"]
    expected_names = {"games.jsonl", "train.jsonl", "validation.jsonl", "held_out.jsonl", "trainer-manifest.json", "report.json"}
    if not isinstance(outputs, dict) or set(outputs) != expected_names:
        fail("incomplete generator package")
    resolved = {name: checked_pin(value, path.parent) for name, value in outputs.items()}
    directory = resolved["train.jsonl"].parent
    if any(p.parent != directory or p.name != name for name, p in resolved.items()):
        fail("generator package must use original six-file directory")
    if require_current_sources:
        with producer("random_inputs", source_dir=source_dir, source_digests=digests) as frozen:
            frozen.verify(generator_manifest, directory)
    else:
        random_inputs.verify(generator_manifest, directory, require_current_sources=False)
    trainer = training.read_json(resolved["trainer-manifest.json"])
    records = training.validate_records(training.validate_manifest(trainer, directory))
    # All records remain available for diagnostics; the original trainer updates train only.
    artifact = training.artifact_from(trainer, records, training.digest(trainer))
    report = training.validation_report(artifact, records, training.digest(trainer))
    artifact_path = checked_pin(manifest["baseline_artifact"], path.parent)
    report_path = checked_pin(manifest["baseline_report"], path.parent)
    if artifact_path.read_bytes() != canonical(artifact) or report_path.read_bytes() != canonical(report):
        fail("baseline artifact/report differs from deterministic original trainer")
    exposures = {split: sorted(training.canonical_position_key(row["board"], row["side"])
                               for row in training.read_jsonl(resolved[f"{split}.jsonl"])) for split in random_inputs.SPLITS}
    excluded = {key for keys in exposures.values() for key in keys}
    if excluded.intersection(reserved["keys"]):
        fail("training inputs collide with reserved acceptance openings")
    import corpus
    corpus_files = manifest["corpus_outputs"]
    if set(corpus_files) != {"corpus.jsonl", "games.jsonl", "selection.json"}:
        fail("incomplete independent corpus")
    corpus_paths = {name: checked_pin(value, path.parent) for name, value in corpus_files.items()}
    corpus_dir = corpus_paths["corpus.jsonl"].parent
    if any(p.parent != corpus_dir or p.name != name for name, p in corpus_paths.items()):
        fail("corpus originals must share directory")
    corpus_result = corpus.verify(corpus_dir, excluded, reserved["keys"])
    exposures.update(corpus_result["exposure_keys"])
    oracle_files = manifest["oracle_outputs"]
    if not isinstance(oracle_files, dict) or "evidence.json" not in oracle_files or "golden.jsonl" not in oracle_files:
        fail("incomplete Oracle originals")
    oracle_paths = {name: checked_pin(value, path.parent) for name, value in oracle_files.items()}
    oracle_dir = oracle_paths["evidence.json"].parent
    actual_names = {str(p.relative_to(oracle_dir)) for p in oracle_dir.rglob("*") if p.is_file()}
    if actual_names != set(oracle_files) or any(p != (oracle_dir / name).resolve() for name, p in oracle_paths.items()):
        fail("Oracle file closure differs from bundle")
    oracle = load_oracle()
    oracle.verify_raw_golden(training.read_jsonl(corpus_paths["corpus.jsonl"]), oracle_dir)
    raw_evidence = training.read_json(oracle_paths["evidence.json"])
    oracle_receipt_pin = raw_evidence.get("runtime_receipt")
    runtime_verified = False
    if oracle_receipt_pin is not None:
        receipt = checked_pin(oracle_receipt_pin, oracle_dir)
        oracle.verify_runtime_receipt(receipt)
        runtime_verified = True
    cli = verify_cli(manifest["cli"], manifest["producer"], path.parent,
                     candidate_executable or cli_path, require_current_sources=require_current_sources)
    probe_path = checked_pin(manifest["cli_probe"], path.parent)
    verify_probe(probe_path, resolved["validation.jsonl"], artifact_path, cli, reserved)
    stages = manifest["stages"]
    required = set(BOUNDS) - {"bundle-verify"}
    if not isinstance(stages, dict) or set(stages) != required:
        fail("incomplete bounded stage completions")
    for stage, value in stages.items():
        stage_manifest = verify_stage(checked_pin(value, path.parent), manifest["producer"])
        if stage_manifest["stage"] != stage:
            fail("stage name mismatch")
        results = stage_manifest["result"]
        if stage in ("generate", "verify", "train"):
            if stage_manifest["request"].get("generator_manifest") != str(generator_manifest):
                fail("stage generator differs from completion bundle")
            if results["outputs"].get("generator_manifest") != pin(generator_manifest):
                fail("stage generator pin differs from bundle")
            if any(results["outputs"].get(name) != pin(original) for name, original in resolved.items()):
                fail("bounded generator outputs differ from bundle")
        if stage == "train" and (results["record_total"] != len(records) or results["outputs"].get("artifact") != pin(artifact_path)
                                  or results["outputs"].get("report") != pin(report_path)):
            fail("trainer stage differs from reconstructed baseline")
        if stage == "corpus" and results["outputs"].get("corpus.jsonl") != pin(corpus_paths["corpus.jsonl"]):
            fail("corpus stage differs from bundled corpus")
        if stage == "corpus" and any(results["outputs"].get(name) != pin(original) for name, original in corpus_paths.items()):
            fail("bounded corpus originals differ from bundle")
        if stage == "corpus" and (stage_manifest["request"]["generator_manifest"] != str(generator_manifest)
                                  or stage_manifest["request"]["reservation"] != reserved):
            fail("corpus exclusions differ from bundle")
        if stage == "oracle" and results["outputs"].get("golden.jsonl") != pin(oracle_paths["golden.jsonl"]):
            fail("Oracle stage differs from bundled golden")
        if stage == "oracle" and results["outputs"] != {name: pin(original) for name, original in oracle_paths.items()}:
            fail("bounded Oracle original closure differs from bundle")
        if stage == "oracle":
            request_receipt = stage_manifest["request"].get("runtime_receipt")
            expected_receipt = pin(Path(request_receipt)) if request_receipt is not None else None
            if expected_receipt != oracle_receipt_pin:
                fail("Oracle stage runtime receipt differs from raw evidence")
        if stage == "cli-probe" and results["outputs"].get("cli-probe") != pin(probe_path):
            fail("probe stage differs from bundled probe")
        if stage.startswith("calibration-"):
            calibration_path = checked_pin(results["outputs"]["generator_manifest"], path.parent)
            if require_current_sources:
                with producer("random_inputs", source_dir=source_dir, source_digests=digests) as frozen:
                    calibration = frozen.check_manifest(calibration_path)
                    frozen.verify(calibration_path, Path(stage_manifest["request"].get(
                        "generator_dir", stage_manifest["request"].get("output_dir", ""))))
            else:
                calibration = random_inputs.check_manifest(calibration_path, require_current_sources=False)
                random_inputs.verify(calibration_path,
                    Path(stage_manifest["request"].get("generator_dir", stage_manifest["request"].get("output_dir", ""))),
                    require_current_sources=False)
            if calibration["counts"] != {"train": 4, "validation": 2, "held_out": 2} or calibration["seed"] == generator["seed"]:
                fail("invalid independent calibration inputs")
            if stage == "calibration-train":
                calibrated_dir = Path(stage_manifest["request"]["generator_dir"])
                calibrated_trainer = training.read_json(calibrated_dir / "trainer-manifest.json")
                calibrated_records = training.validate_records(training.validate_manifest(calibrated_trainer, calibrated_dir))
                rebuilt = training.artifact_from(calibrated_trainer, calibrated_records, training.digest(calibrated_trainer))
                rebuilt_report = training.validation_report(rebuilt, calibrated_records, training.digest(calibrated_trainer))
                if (checked_pin(results["outputs"]["artifact"], path.parent).read_bytes() != canonical(rebuilt)
                        or checked_pin(results["outputs"]["report"], path.parent).read_bytes() != canonical(rebuilt_report)
                        or results.get("record_total") != len(calibrated_records)):
                    fail("calibration trainer reproduction mismatch")
    if corpus_result["seed"] == generator["seed"]:
        fail("corpus seed must be independent")
    production = strength_eligible(generator, oracle_runtime_verified=runtime_verified)
    inputs = {"baseline_artifact": pin(artifact_path), "baseline_manifest": pin(resolved["trainer-manifest.json"]),
              "validation": pin(resolved["validation.jsonl"]), "held_out": pin(resolved["held_out.jsonl"]),
              "corpus": pin(corpus_paths["corpus.jsonl"]), "golden": pin(oracle_paths["golden.jsonl"])}
    return {"schema_version": 1, "bundle_sha256": training.sha256_file(path), "strength_inputs": production,
            "input_kind": "production" if production else "tooling", "tooling_only": not production,
            "inputs": inputs, "acceptance_reservation": reserved, "exposure_keys": exposures, "cli": cli}


def prepare_stage(path: Path, stage: str, request: dict, cwd: Path, inputs: list[Path]) -> None:
    if stage not in BOUNDS:
        fail("unknown bounded stage")
    identity = source_identity(cwd)
    completed = set()
    for previous in inputs:
        if previous.name == "report.json":
            completed.add(verify_stage(previous, identity)["stage"])
    if not PREDECESSORS[stage].issubset(completed):
        fail("required verified prior stages are missing")
    wall, rss = BOUNDS[stage]
    frozen_inputs = request_inputs(stage, request)
    save(path, {"version": VERSION, "stage": stage, "request": request, "cwd": str(cwd.resolve()),
                "total_wall_budget_seconds": TOTAL_WALL_SECONDS,
                "producer": identity, "inputs": [pin(p) for p in [*frozen_inputs, *inputs]],
                "bounds": {"wall_seconds": wall, "rss_bytes": rss, "sample_seconds": 1}})


def _verified_bundle_with_receipt(bundle_path: Path, receipt_path: Path, verified: dict) -> dict:
    original = training.read_json(bundle_path)
    final = verify_stage(receipt_path, original["producer"])
    request, outputs = final["request"], final["result"]["outputs"]
    if final["stage"] != "bundle-verify" or request.get("bundle_manifest") != str(bundle_path):
        fail("bundle consumer requires the bounded final bundle-verify receipt")
    if outputs.get("bundle_manifest") != pin(bundle_path):
        fail("final verification receipt pins a different bundle")
    if pin(Path(request["cli"])) != verified["cli"]["binary"]:
        fail("final verification receipt pins a different CLI")
    frozen_inputs = final["inputs"]
    if pin(bundle_path) not in frozen_inputs or verified["cli"]["binary"] not in frozen_inputs:
        fail("final verification inputs omit bundle or CLI identity")
    reconstructed_report = checked_pin(outputs["report"], receipt_path.parent)
    if reconstructed_report != Path(request["report"]).resolve() or reconstructed_report.read_bytes() != canonical(verified):
        fail("final verification output differs from complete offline reconstruction")
    return {**verified, "bundle_verification_receipt": pin(receipt_path)}


def verify_for_pilot(bundle_path: Path, receipt_path: Path,
                     candidate_executable: Path | None = None) -> dict:
    """Require strict producer-source verification before bounded pilot use."""
    bundle_path, receipt_path = Path(bundle_path).resolve(), Path(receipt_path).resolve()
    verified = verify_bundle(bundle_path, candidate_executable)
    return _verified_bundle_with_receipt(bundle_path, receipt_path, verified)


def verify_for_production_cycle(bundle_path: Path, receipt_path: Path,
                                candidate_executable: Path | None = None) -> dict:
    """Verify a completed input bundle for 0019 without requiring its producer checkout."""
    bundle_path, receipt_path = Path(bundle_path).resolve(), Path(receipt_path).resolve()
    verified = verify_bundle(bundle_path, candidate_executable, require_current_sources=False)
    return _verified_bundle_with_receipt(bundle_path, receipt_path, verified)


def finalize(args) -> None:
    identity = source_identity()
    generator = args.generator_dir.resolve()
    corpus_dir, oracle_dir = args.corpus_dir.resolve(), args.oracle_dir.resolve()
    manifest = {"version": VERSION, "score_contract": training.SCORE_CONTRACT, "producer": identity,
                "total_wall_budget_seconds": TOTAL_WALL_SECONDS,
                "generator_manifest": pin(args.generator_manifest),
                "generator_outputs": {p.name: pin(p) for p in generator.iterdir() if p.is_file()},
                "baseline_artifact": pin(args.baseline_artifact), "baseline_report": pin(args.baseline_report),
                "corpus_outputs": {p.name: pin(p) for p in corpus_dir.iterdir() if p.is_file()},
                "oracle_outputs": {str(p.relative_to(oracle_dir)): pin(p) for p in oracle_dir.rglob("*") if p.is_file()},
                "acceptance_reservation": training.read_json(args.reservation) if args.reservation else
                    {"state": "not-yet-selected", "artifact": None, "keys": []},
                "cli": cli_identity(args.cli, identity, args.build_receipt),
                "cli_probe": pin(args.cli_probe),
                "stages": {stage: pin(args.stage_reports / stage / "report.json") for stage in BOUNDS if stage != "bundle-verify"}}
    # Validate before exposing the final completion; never overwrite frozen output.
    temporary = args.manifest.with_name(args.manifest.name + ".unverified")
    save(temporary, manifest)
    result = verify_bundle(temporary, args.cli)
    save(args.manifest, manifest)
    save(args.report, {**result, "bundle_sha256": training.sha256_file(args.manifest)})


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-stage")
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--stage", choices=BOUNDS, required=True)
    prepare.add_argument("--cwd", type=Path, default=ROOT)
    prepare.add_argument("--input", type=Path, action="append", default=[])
    prepare.add_argument("--request", type=Path, required=True)
    run = commands.add_parser("run-stage")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--heartbeat-seconds", type=float, default=5)
    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--cli", type=Path)
    verify.add_argument("--report", type=Path)
    complete = commands.add_parser("finalize")
    for name in ("manifest", "report", "generator-manifest", "generator-dir", "baseline-artifact", "baseline-report", "corpus-dir", "oracle-dir", "cli", "stage-reports"):
        complete.add_argument("--" + name, type=Path, required=True)
    complete.add_argument("--reservation", type=Path)
    complete.add_argument("--cli-probe", type=Path, required=True)
    complete.add_argument("--build-receipt", type=Path, required=True)
    build = commands.add_parser("build-cli")
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--cwd", type=Path, default=ROOT)
    worker = commands.add_parser("worker")
    worker.add_argument("--manifest", type=Path, required=True)
    worker.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-stage":
            prepare_stage(args.manifest, args.stage, training.read_json(args.request), args.cwd, args.input)
        elif args.command == "run-stage":
            supervise(args.manifest, args.output_dir, heartbeat_seconds=args.heartbeat_seconds)
        elif args.command == "finalize":
            finalize(args)
        elif args.command == "worker":
            worker_stage(args.manifest, args.result)
        elif args.command == "build-cli":
            build_cli(args.output_dir, args.cwd)
        else:
            result = verify_bundle(args.manifest, args.cli)
            if args.report:
                save(args.report, result)
            progress("bundle-verify", 1, "verified", 0, 0)
    except (training.TrainingError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"input bundle error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
