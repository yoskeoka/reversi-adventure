#!/usr/bin/env python3
"""Human-operated, gated exact-threshold assessment with durable unit evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import whole_game as wg

spec = importlib.util.spec_from_file_location("measurement_prepare", Path(__file__).with_name("prepare-whole-game-measurement.py"))
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)
VERSION = "exact-threshold-assessment-v1"
STARTED = time.monotonic()
THRESHOLDS = (16, 20, 24)
SCOPES = ("turn", "game")
LAST_PROGRESS = {"stage": "verify", "unit": {"threshold": 16, "scope": "turn", "stage": "pilot"}, "done": 0, "total": 24}
CAPS = {"timeout_seconds": 310, "max_rss_kib": 1572864,
        "pilot_node_limit": None, "max_decisions": 120,
        "heuristic_tt_entries": 1048576, "exact_table_entries": 262144}


def sha(value) -> str:
    return hashlib.sha256(wg.canonical(value)).hexdigest()


def verify_seal(value: dict) -> None:
    wg.require(value == wg.sealed(value), "assessment digest mismatch")


def transform_coordinate(move: str, transform: str) -> str:
    if move == "pass":
        return move
    row, column = wg.oracle.parse_coordinate(move)
    if transform == "rotate-180":
        row, column = 7-row, 7-column
    elif transform == "main-diagonal":
        row, column = column, row
    elif transform == "anti-diagonal":
        row, column = 7-column, 7-row
    else:
        wg.require(transform == "identity", "unknown root transform")
    return wg.oracle.coordinate(row, column)


def transform_board(board: str, transform: str) -> str:
    cells = ["."]*64
    for index, cell in enumerate(board):
        move = transform_coordinate(wg.oracle.coordinate(index//8, index%8), transform)
        row, column = wg.oracle.parse_coordinate(move)
        cells[8*row+column] = cell
    return "".join(cells)


def verify_root_history(root: dict) -> None:
    board, side = wg.oracle.initial_board(), "B"
    for offset in range(0, len(root["opening"]), 2):
        board, side = wg.oracle.replay_console_move(board, side, root["opening"][offset:offset+2])
    for step in root["prefix"]:
        legal = wg.oracle.legal_moves(board, side)
        wg.require(step["board"] == board and step["side"] == side
                   and step["seat"] == (side if root["assignment"] == 0 else wg.oracle.other(side)), "root history identity mismatch")
        move = step["move"]
        wg.require(move in legal if legal else move == "pass" and not terminal(board, side), "root history illegal move/pass")
        if move != "pass":
            board = wg.oracle.apply_move(board, side, move)
        side = wg.oracle.other(side)
    wg.require(board == root["board"] and side == root["side"] and board.count(".") == 24
               and bool(wg.oracle.legal_moves(board, side)), "root history does not reach legal 24-empty root")


def freeze_roots(report: dict) -> list[dict]:
    wg.verify(report)
    wg.require(report["kind"] == "cli" and report["settings"]["midgame_depth"] == 8
               and report["settings"]["exact_cache_scope"] == "game"
               and report["settings"]["exact_empty"] == 16, "roots require verified game-8 control")
    roots, seen, counts = [], set(), {"B": 0, "W": 0}
    for game in report["games"]:
        for turn, step in enumerate(game["steps"]):
            key = step["board"], step["side"]
            if step["board"].count(".") != 24 or not wg.oracle.legal_moves(*key):
                continue
            if key in seen or counts[step["side"]] == 2:
                continue
            seen.add(key)
            counts[step["side"]] += 1
            roots.append({"id": f"window-{len(roots)+1}", "board": step["board"], "side": step["side"],
                          "assignment": game["assignment"], "source_step_id": step["id"],
                          "opening_id": game["opening_id"], "opening": game["opening"], "transform": "identity",
                          "prefix": [{k: s[k] for k in ("board", "side", "move", "seat")}
                                     for s in game["steps"][:turn]]})
    if counts == {"B": 2, "W": 1}:
        source = next(root for root in roots if root["side"] == "W")
        for transform in ("rotate-180", "main-diagonal", "anti-diagonal"):
            wg.require(transform_board(wg.oracle.initial_board(), transform) == wg.oracle.initial_board(), "root transform must preserve initial colors")
            board = transform_board(source["board"], transform)
            if (board, source["side"]) in seen:
                continue
            roots.append({**source, "id": f"window-{len(roots)+1}", "board": board, "transform": transform,
                "opening": "".join(transform_coordinate(source["opening"][i:i+2], transform)
                                   for i in range(0, len(source["opening"]), 2)),
                "prefix": [{**step, "board": transform_board(step["board"], transform),
                            "move": transform_coordinate(step["move"], transform)} for step in source["prefix"]],
                "source_root_id": source["id"], "source_board": source["board"],
                "source_opening": source["opening"], "source_prefix": source["prefix"]})
            counts["W"] += 1
            break
    wg.require(counts == {"B": 2, "W": 2}, "source lacks two distinct legal roots per color even with white symmetry fallback")
    for root in roots:
        verify_root_history(root)
    return roots


def units(stage: str, roots: list[dict], thresholds=THRESHOLDS) -> list[dict]:
    starts = roots if stage == "pilot" else [
        {**row, "assignment": assignment, "opening_id": row["id"], "opening": row["moves"]}
        for row in wg.opening_rows() for assignment in (0, 1)]
    return [{"id": f"{stage}-{threshold}-{depth}-{scope}-{row['id']}-seat{row['assignment']}",
             "stage": stage, "threshold": threshold, "scope": scope, "depth": depth,
             "start": row} for threshold in thresholds for depth in ((8,) if stage == "pilot" else (12, 8))
            for scope in SCOPES for row in starts]


class Progress:
    def __init__(self, every=1):
        wg.require(type(every) is int and every > 0, "progress interval must be positive")
        self.started, self.every = STARTED, every

    def emit(self, stage, unit, done, total, status):
        LAST_PROGRESS.update(stage=stage, unit=unit, done=done, total=total)
        if status in ("running", "skipped", "verified", "saved") and done % self.every and done != total:
            return
        print(f"progress exact-threshold stage={stage} threshold={unit['threshold']} scope={unit['scope']} "
              f"unit={'position' if stage == 'oracle' else 'window' if unit['stage'] == 'pilot' else 'game'} "
              f"done={done} total={total} status={status} elapsed_s={time.monotonic()-self.started:.3f}",
              file=sys.stderr, flush=True)


def harness_paths():
    return [*prep.harness_paths(), Path(__file__).resolve()]


def resume_sources(m):
    resume = m.get("resume")
    if not resume:
        return []
    old = prep.load(prep.check_pin(resume["manifest"]))
    verify_seal(old)
    wg.require(old["version"] == VERSION, "resume source version mismatch")
    for key in ("source_revision", "host", "inputs", "caps", "roots", "source_report_digest",
                "cache_lifetime", "reset_protocol", "oracle_cwd", "pilot_units", "pilot_total"):
        wg.require(old[key] == m[key], f"resume source {key} mismatch")
    wg.require(re.fullmatch(r"[0-9a-f]{40}", old["harness_revision"]), "resume harness revision invalid")
    wg.require([p["path"] for p in old["harness_files"]] == [str(p.resolve()) for p in harness_paths()],
               "resume harness registry mismatch")
    for item in old["harness_files"]:
        relative = Path(item["path"]).relative_to(prep.ROOT)
        raw = subprocess.check_output(["git", "-C", str(prep.ROOT), "show", f"{old['harness_revision']}:{relative}"])
        wg.require(hashlib.sha256(raw).hexdigest() == item["sha256"], "resume source harness differs from recorded commit")
    results, seen = [], set()
    for pin in resume["units"]:
        raw = prep.load(prep.check_pin(pin))
        unit = raw["unit"]
        wg.require(unit in m["pilot_units"] and unit["id"] not in seen, "resume source unit duplicate/unknown")
        wg.require(Path(pin["path"]) == unit_path(Path(old["output_directory"])/"pilot", unit),
                   "resume source unit path mismatch")
        seen.add(unit["id"])
        verify_seal(raw)
        resources = process_resources(raw["seat_processes"], raw["steps"], raw["failed_attempt"])
        wg.require(raw["resources"] in (process_resources(raw["seat_processes"]), resources),
                   "resume source resource aggregate mismatch")
        verify_unit(old, unit, wg.sealed({**raw, "resources": resources}))
        results.append(wg.sealed({**raw, "manifest_digest": m["report_digest"],
            "resources": resources,
            "imported_from": {"manifest": resume["manifest"], "unit": pin, "report_digest": raw["report_digest"]}}))
    return results


def prepare(args) -> Path:
    Progress().emit("verify", LAST_PROGRESS["unit"], 0, 24, "running")
    wg.require(sys.platform == "linux", "CPU/RSS assessment requires Linux")
    wg.require(args.output_dir.is_absolute() and not args.output_dir.exists(), "output directory must be new and absolute")
    wg.require(re.fullmatch(r"[0-9a-f]{40}", args.source_revision) is not None, "source revision requires full commit hash")
    subprocess.run(["git", "-C", str(prep.ROOT), "cat-file", "-e", args.source_revision+"^{commit}"], check=True)
    wg.require(args.harness_revision == prep.revision(), "harness revision differs from checkout")
    inputs = {name: prep.pin(path) for name, path in (
        ("cli", args.cli_binary), ("oracle", args.oracle_binary), ("artifact", args.artifact),
        ("openings", wg.OPENINGS), ("source_report", args.source_report))}
    source = prep.load(args.source_report)
    roots = freeze_roots(source)
    for name in ("cli", "oracle"):
        wg.require(os.access(inputs[name]["path"], os.X_OK), "input binary is not executable")
    # Probe protocol only: no decision search or long measurement during prepare.
    prep.probe_reset(args.cli_binary, args.artifact, CAPS["timeout_seconds"])
    resume_path = getattr(args, "resume_manifest", None)
    resume = None
    if resume_path:
        old = prep.load(resume_path)
        folder = Path(old["output_directory"])/"pilot"
        resume = {"manifest": prep.pin(resume_path), "units": [prep.pin(p) for p in sorted(folder.glob("*.json"))]}
    manifest = wg.sealed({"version": VERSION, "source_revision": args.source_revision,
        "harness_revision": args.harness_revision, "harness_files": [prep.pin(p) for p in harness_paths()],
        "host": prep.host(), "inputs": inputs, "caps": CAPS, "roots": roots,
        "source_report_digest": source["report_digest"], "cache_lifetime": "one-game",
        "reset_protocol": "new_game-v1", "output_directory": str(args.output_dir),
        "oracle_cwd": str((args.oracle_cwd or args.oracle_binary.parent).resolve(strict=True)),
        "pilot_units": units("pilot", roots), "pilot_total": 24, "resume": resume})
    imported = resume_sources(manifest)
    args.output_dir.mkdir(parents=True)
    path = args.output_dir / "manifest.json"
    wg.atomic_write(path, manifest)
    for result in imported:
        wg.atomic_write(unit_path(args.output_dir/"pilot", result["unit"]), result)
    script = args.output_dir / "run-exact-threshold.sh"
    command = " ".join(shlex.quote(p) for p in ["rtk", "python3", str(Path(__file__).resolve()), "run", "--manifest", str(path)])
    prep.atomic(script, ("#!/usr/bin/env bash\nset -euo pipefail\n"+command+' "$@"\n').encode())
    script.chmod(0o755)
    verify_manifest(path)
    Progress().emit("verify", manifest["pilot_units"][-1], 0, 24, "verified")
    print(f"rtk bash {shlex.quote(str(script))}")
    return path


def verify_manifest(path: Path) -> dict:
    m = prep.load(path)
    verify_seal(m)
    wg.require(m["version"] == VERSION and m["host"] == prep.host()
               and m["harness_revision"] == prep.revision() and m["caps"] == CAPS,
               "assessment host, harness or caps mismatch")
    wg.require([p["path"] for p in m["harness_files"]] == [str(p.resolve()) for p in harness_paths()], "harness registry mismatch")
    for item in [*m["inputs"].values(), *m["harness_files"]]:
        prep.check_pin(item)
    wg.require(Path(m["inputs"]["openings"]["path"]) == wg.OPENINGS.resolve(), "openings path mismatch")
    source = prep.load(Path(m["inputs"]["source_report"]["path"]))
    wg.require(m["roots"] == freeze_roots(source) and m["source_report_digest"] == source["report_digest"], "root selection changed")
    wg.require(m["pilot_units"] == units("pilot", m["roots"]) and m["pilot_total"] == 24
               and m["cache_lifetime"] == "one-game" and m["reset_protocol"] == "new_game-v1", "pilot identity mismatch")
    resume_sources(m)
    return m


def terminal(board, side):
    return not wg.oracle.legal_moves(board, side) and not wg.oracle.legal_moves(board, wg.oracle.other(side))


def phase(board, threshold):
    occupied = 64-board.count(".")
    return "exact" if occupied >= 64-threshold else "opening" if occupied <= 20 else "midgame" if occupied <= 44 else "endgame"


def reached(unit, board, side):
    return terminal(board, side) or unit["stage"] == "pilot" and board.count(".") <= 12


def process_resources(usages, steps=(), attempt=None):
    peaks = [v["peak_rss_kib"] for v in usages.values()]
    peaks.extend(raw["peak_rss_kib"] for step in steps for raw in (step["cpu_before"], step["cpu_after"]))
    peaks.extend(step["peak_observation"]["peak_rss_kib"] for step in steps if step.get("peak_observation"))
    if attempt:
        peaks.extend(attempt[k]["peak_rss_kib"] for k in ("before_usage", "after_usage", "last_resource_observation", "peak_observation")
                     if isinstance(attempt.get(k), dict))
    return {"user_cpu_ns": sum(v["user_cpu_ns"] for v in usages.values()),
            "system_cpu_ns": sum(v["system_cpu_ns"] for v in usages.values()),
            "peak_rss_kib": max(peaks, default=0)}


def measure_unit(m, unit) -> dict:
    seats, steps, resets, usages = {}, [], {}, {}
    started, timestamp = time.monotonic_ns(), time.time_ns()
    board, side = unit["start"]["board"], unit["start"]["side"]
    failure, interrupted, attempt = None, False, None
    try:
        for label in ("B", "W"):
            seats[label] = wg.Seat("cli", Path(m["inputs"]["cli"]["path"]), Path(m["inputs"]["artifact"]["path"]),
                unit["depth"], CAPS["timeout_seconds"], label, cache_scope=unit["scope"], exact_empty=unit["threshold"],
                node_limit=CAPS["pilot_node_limit"] if unit["stage"] == "pilot" else None, max_rss_kib=CAPS["max_rss_kib"])
            resets[label] = seats[label].new_game(unit["id"])
        for turn in range(CAPS["max_decisions"]):
            if reached(unit, board, side):
                break
            legal = wg.oracle.legal_moves(board, side)
            label = side if unit["start"]["assignment"] == 0 else wg.oracle.other(side)
            seat = seats[label]
            before = wg.proc_usage(seat.process.pid)
            attempt = {"id": f"{unit['id']}-turn{turn}", "board": board, "side": side, "seat": label,
                       "legal_move_count": len(legal), "phase": phase(board, unit["threshold"]),
                       "before_usage": before}
            decision_started = time.monotonic_ns()
            try:
                move, elapsed = seat.choose(attempt["id"], board, side)
            finally:
                attempt["observed_elapsed_ns"] = time.monotonic_ns()-decision_started
                attempt["last_resource_observation"] = getattr(seat, "last_observation", None)
                attempt["peak_observation"] = getattr(seat, "peak_observation", None)
                seat.collect_diagnostics()
                attempt["observed_search"] = seat.diagnostics.get(attempt["id"])
            after = wg.proc_usage(seat.process.pid)
            attempt.update(observed_move=move, after_usage=after)
            wg.require(move in legal if legal else move == "pass", "illegal assessment move")
            sample = seat.diagnostics.get(attempt["id"])
            step = {k: attempt[k] for k in ("id", "board", "side", "seat", "legal_move_count", "phase")}
            step.update(move=move, decision_elapsed_ns=elapsed, search=sample,
                cpu_before=before, cpu_after=after,
                decision_cpu_ns=after["user_cpu_ns"]+after["system_cpu_ns"]-before["user_cpu_ns"]-before["system_cpu_ns"],
                process_peak_rss_kib=after["peak_rss_kib"])
            if attempt["peak_observation"] is not None:
                step["peak_observation"] = attempt["peak_observation"]
            wg.validate_cli_diagnostic(step, sample, unit["depth"], unit["threshold"])
            wg.require(process_resources({}, [step])["peak_rss_kib"] <= CAPS["max_rss_kib"], "peak RSS cap exceeded")
            wg.require(unit["stage"] != "pilot" or CAPS["pilot_node_limit"] is None
                       or sample["nodes"] <= CAPS["pilot_node_limit"], "pilot node cap exceeded")
            steps.append(step)
            attempt = None
            if move != "pass":
                board = wg.oracle.apply_move(board, side, move)
            side = wg.oracle.other(side)
        else:
            raise wg.BenchmarkError("assessment exceeded maximum decisions")
        for label, seat in seats.items():
            usages[label] = seat.close()
        wg.require(process_resources(usages, steps)["peak_rss_kib"] <= CAPS["max_rss_kib"], "peak RSS cap exceeded")
    except KeyboardInterrupt:
        interrupted = True
        raise
    except (wg.BenchmarkError, OSError, ValueError) as exc:
        failure = str(exc)
    finally:
        for label, seat in seats.items():
            usage = seat.abort()
            if usage is not None:
                usages[label] = usage
    wg.require(not interrupted, "interrupted unit cannot be published")
    return wg.sealed({"version": VERSION, "manifest_digest": m["report_digest"], "unit": unit,
        "status": "failed" if failure else "completed", "failure": failure, "failed_attempt": attempt,
        "session_id": uuid.uuid4().hex, "started_at_ns": timestamp, "ended_at_ns": time.time_ns(),
        "wall_ns": time.monotonic_ns()-started, "steps": steps, "reset_events": resets,
        "seat_processes": usages, "resources": process_resources(usages, steps, attempt), "end_board": board, "end_side": side})


def verify_unit(m, unit, result):
    verify_seal(result)
    wg.require(result.get("version") == VERSION and result.get("manifest_digest") == m["report_digest"]
               and result.get("unit") == unit and result.get("status") in ("completed", "failed"), "unit identity mismatch")
    wg.require(type(result.get("wall_ns")) is int and result["wall_ns"] > 0
               and type(result.get("started_at_ns")) is int and result["ended_at_ns"] >= result["started_at_ns"]
               and isinstance(result.get("session_id"), str), "unit lifecycle missing")
    usages = result["seat_processes"]
    wg.require(set(usages).issubset({"B", "W"}), "unknown seat resources")
    for item in usages.values():
        wg.require(all(type(item.get(k)) is int and item[k] >= 0 for k in
            ("user_cpu_ns", "system_cpu_ns", "peak_rss_kib", "startup_ns", "shutdown_ns")), "raw resources missing")
    wg.require(result["resources"] == process_resources(usages, result["steps"], result["failed_attempt"]), "unit resource aggregate mismatch")
    board, side = unit["start"]["board"], unit["start"]["side"]
    wg.require(isinstance(result["steps"], list) and len(result["steps"]) <= CAPS["max_decisions"], "unit step count invalid")
    for turn, step in enumerate(result["steps"]):
        legal = wg.oracle.legal_moves(board, side)
        label = side if unit["start"]["assignment"] == 0 else wg.oracle.other(side)
        wg.require(not reached(unit, board, side), "steps after completed window/game")
        wg.require(step["id"] == f"{unit['id']}-turn{turn}" and step["board"] == board
                   and step["side"] == side and step["seat"] == label
                   and step["legal_move_count"] == len(legal) and step["phase"] == phase(board, unit["threshold"]), "unit replay mismatch")
        move = step["move"]
        wg.require(move in legal if legal else move == "pass" and not terminal(board, side), "invalid unit move/pass")
        wg.validate_cli_diagnostic(step, step["search"], unit["depth"], unit["threshold"])
        wg.require(unit["stage"] != "pilot" or CAPS["pilot_node_limit"] is None
                   or step["search"]["nodes"] <= CAPS["pilot_node_limit"], "node cap violated")
        before, after = step["cpu_before"], step["cpu_after"]
        if "peak_observation" in step:
            raw = step["peak_observation"]
            wg.require(isinstance(raw, dict) and set(raw) == {"user_cpu_ns", "system_cpu_ns", "peak_rss_kib"}
                       and all(type(raw[k]) is int and raw[k] >= 0 for k in raw)
                       and raw["peak_rss_kib"] <= CAPS["max_rss_kib"]
                       and all(before[k] <= raw[k] <= after[k] for k in ("user_cpu_ns", "system_cpu_ns")),
                       "decision polling resources invalid")
        for key in ("user_cpu_ns", "system_cpu_ns", "peak_rss_kib"):
            wg.require(type(before.get(key)) is int and type(after.get(key)) is int and before[key] >= 0 and after[key] >= 0
                       and (key == "peak_rss_kib" or before[key] <= after[key]), "decision raw resources invalid")
        wg.require(step["decision_cpu_ns"] == after["user_cpu_ns"]+after["system_cpu_ns"]-before["user_cpu_ns"]-before["system_cpu_ns"]
                   and step["process_peak_rss_kib"] == after["peak_rss_kib"]
                   and max(before["peak_rss_kib"], after["peak_rss_kib"]) <= CAPS["max_rss_kib"]
                   and type(step["decision_elapsed_ns"]) is int and step["decision_elapsed_ns"] >= 0, "decision resource totals mismatch")
        if move != "pass":
            board = wg.oracle.apply_move(board, side, move)
        side = wg.oracle.other(side)
    wg.require(result["end_board"] == board and result["end_side"] == side, "unit end state mismatch")
    # /proc rounds down to clock ticks; wait4 includes startup, reset and shutdown.
    for label, usage in usages.items():
        for key in ("user_cpu_ns", "system_cpu_ns"):
            measured = sum(s["cpu_after"][key]-s["cpu_before"][key] for s in result["steps"] if s["seat"] == label)
            wg.require(measured <= usage[key], "decision CPU exceeds wait4 total")
    if result["status"] == "completed":
        wg.require(reached(unit, board, side) and not result["failure"] and result["failed_attempt"] is None
                   and set(usages) == {"B", "W"} and result["resources"]["peak_rss_kib"] <= CAPS["max_rss_kib"], "incomplete unit")
        wg.require(set(result["reset_events"]) == {"B", "W"}, "both reset acknowledgements required")
        for event in result["reset_events"].values():
            wg.require(event["game_id"] == unit["id"] and event["acknowledged"] is True
                       and event["protocol"] == "new_game-v1", "unit reset mismatch")
    else:
        wg.require(isinstance(result["failure"], str) and bool(result["failure"]), "failure reason missing")
        attempt = result["failed_attempt"]
        if attempt is not None:
            wg.require(attempt["board"] == board and attempt["side"] == side
                       and attempt["id"] == f"{unit['id']}-turn{len(result['steps'])}"
                       and attempt["seat"] == (side if unit["start"]["assignment"] == 0 else wg.oracle.other(side))
                       and attempt["legal_move_count"] == len(wg.oracle.legal_moves(board, side))
                       and attempt["phase"] == phase(board, unit["threshold"])
                       and type(attempt["observed_elapsed_ns"]) is int and attempt["observed_elapsed_ns"] >= 0,
                       "failure attempt replay mismatch")


def semantic_pair(turn, game):
    wg.require(turn["status"] == game["status"] == "completed", "comparison requires completed units")
    a, b = turn["unit"], game["unit"]
    wg.require(a["scope"] == "turn" and b["scope"] == "game"
               and {k: v for k, v in a.items() if k not in ("id", "scope")} ==
                   {k: v for k, v in b.items() if k not in ("id", "scope")}, "comparison workload mismatch")
    wg.require(len(turn["steps"]) == len(game["steps"]), "semantic decision count mismatch")
    for old, new in zip(turn["steps"], game["steps"]):
        wg.require(all(old[k] == new[k] for k in ("board", "side", "seat", "move", "phase", "legal_move_count"))
                   and all(old["search"][k] == new["search"][k] for k in ("score", "completed_depth", "exact", "outcome")), "semantic mismatch")
    wg.require(turn["end_board"] == game["end_board"] and turn["end_side"] == game["end_side"], "semantic outcome mismatch")


def oracle_jobs(results):
    return [{"id": f"{result['unit']['id']}-position-{index}", "unit": result["unit"],
             "source_digest": result["report_digest"], "step": step}
            for result in results if result["status"] == "completed"
            for index, step in enumerate(result["steps"]) if step["search"]["exact"]]


def proc_exit_observation(pid):
    """Linux PF_EXITING is set before exit_mm, before wait4 can reap the task."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return {"missing": True, "exiting": True}
    fields = raw[raw.rfind(")")+2:].split()
    state, flags = fields[0], int(fields[6])
    # include/linux/sched.h: PF_EXITING=0x4; stat field 9 exposes task flags.
    return {"stat": raw, "state": state, "flags": flags,
            "exiting": bool(flags & 0x4) or state in ("X", "Z")}


def measured_oracle(argv, *, cwd, timeout, observations):
    """Bound an independent solve and retain CPU/RSS plus raw console output."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(argv, cwd=cwd, stdout=out, stderr=err)
        started, deadline = time.monotonic_ns(), time.monotonic()+timeout
        receipt = {"argv": [str(p) for p in argv], "wall_ns": 0, "last_observation": None,
                   "resources": None, "exit_status": None, "returncode": None}
        observations.append(receipt)
        def record_exit(status, usage):
            process.returncode = os.waitstatus_to_exitcode(status)
            receipt.update(exit_status=status, returncode=process.returncode,
                resources={"user_cpu_ns": round(usage.ru_utime*1e9),
                           "system_cpu_ns": round(usage.ru_stime*1e9), "peak_rss_kib": usage.ru_maxrss})
        exiting = False
        try:
            while True:
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if not pid and not exiting:
                    try:
                        receipt["last_observation"] = wg.proc_usage(process.pid)
                    except (FileNotFoundError, wg.BenchmarkError) as exc:
                        # Exit can remove VmHWM between the nonblocking wait
                        # and /proc sampling. Final wait4 evidence is required;
                        # a still-running child with no RSS remains a failure.
                        receipt["sampling_failure"] = str(exc)
                        pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                        if not pid:
                            receipt["exit_observation"] = proc_exit_observation(process.pid)
                            if not receipt["exit_observation"]["exiting"]:
                                raise
                            exiting = True
                if pid:
                    record_exit(status, usage)
                    wg.require(time.monotonic() < deadline, "Oracle decision timeout")
                    wg.require(process.returncode == 0, "Oracle process failed")
                    wg.require(usage.ru_maxrss <= CAPS["max_rss_kib"], "Oracle peak RSS cap exceeded")
                    break
                if receipt["last_observation"] is not None:
                    wg.require(receipt["last_observation"]["peak_rss_kib"] <= CAPS["max_rss_kib"], "Oracle peak RSS cap exceeded")
                wg.require(time.monotonic() < deadline, "Oracle decision timeout")
                time.sleep(0.02)
        finally:
            if process.returncode is None:
                process.kill()
                _, status, usage = os.wait4(process.pid, 0)
                record_exit(status, usage)
            receipt["wall_ns"] = time.monotonic_ns()-started
            out.seek(0)
            err.seek(0)
            receipt["stdout"], receipt["stderr"] = out.read().decode("utf-8"), err.read().decode("utf-8")
        return subprocess.CompletedProcess(argv, process.returncode, receipt["stdout"], receipt["stderr"])


def solve_position(m, job):
    binary = Path(m["inputs"]["oracle"]["path"])
    profile = wg.oracle.profile_from_name(f"whole-game-depth-{job['unit']['depth']}-exact-{job['unit']['threshold']}")
    queries, failure, observations = [], None, []
    step = job["step"]
    def solve(board, side, child_query):
        effective, sign = wg.oracle.effective_query(board, side)
        raw = wg.oracle.run_solve([(board, effective)], binary, Path(m["oracle_cwd"]), profile,
                                  CAPS["timeout_seconds"], child_query=child_query,
                                  runner=lambda argv, **kw: measured_oracle(argv, observations=observations, **kw))[0]
        queries.append({"board": board, "side": side, "effective_side": effective,
                        "sign": sign, "child_query": child_query, "result": raw})
        wg.require(raw["exact"] and raw["completed_depth"] >= board.count("."), "independent Oracle incomplete")
        return sign*int(raw["value"])
    try:
        root = solve(step["board"], step["side"], False)
        if step["move"] == "pass":
            selected = root
        else:
            child = wg.oracle.apply_move(step["board"], step["side"], step["move"])
            if terminal(child, wg.oracle.other(step["side"])):
                own, other = child.count(step["side"]), child.count(wg.oracle.other(step["side"]))
                selected = 64 if other == 0 else -64 if own == 0 else own-other
            else:
                selected = -solve(child, wg.oracle.other(step["side"]), True)
        wg.require(root == selected == step["search"]["score"], "independent Oracle score/continuation mismatch")
    except (wg.BenchmarkError, wg.oracle.OracleError, OSError, ValueError) as exc:
        failure = str(exc)
    return wg.sealed({"version": VERSION, "manifest_digest": m["report_digest"], "job": job,
        "oracle_binary": m["inputs"]["oracle"], "profile": wg.oracle.profile_metadata(profile),
        "status": "failed" if failure else "completed", "failure": failure, "queries": queries,
        "process_observations": observations})


def verify_position(m, job, result):
    verify_seal(result)
    step = job["step"]
    profile = wg.oracle.profile_from_name(f"whole-game-depth-{job['unit']['depth']}-exact-{job['unit']['threshold']}")
    expected_profile = wg.oracle.profile_metadata(profile)
    wg.require(result["version"] == VERSION and result["manifest_digest"] == m["report_digest"]
               and result["job"] == job and result["oracle_binary"] == m["inputs"]["oracle"]
               and result["profile"] == expected_profile, "Oracle checkpoint identity mismatch")
    wg.require(result["status"] in ("completed", "failed") and isinstance(result["queries"], list), "Oracle status invalid")
    failed = result["status"] == "failed"
    wg.require(isinstance(result["failure"], str) and bool(result["failure"]) if failed
               else result["failure"] is None, "Oracle failure reason invalid")
    expected = [(step["board"], step["side"], False)]
    terminal_score = None
    if step["move"] != "pass":
        child = wg.oracle.apply_move(step["board"], step["side"], step["move"])
        if not terminal(child, wg.oracle.other(step["side"])):
            expected.append((child, wg.oracle.other(step["side"]), True))
        else:
            own, other = child.count(step["side"]), child.count(wg.oracle.other(step["side"]))
            terminal_score = 64 if other == 0 else -64 if own == 0 else own-other
    queries, observations = result["queries"], result.get("process_observations")
    wg.require(isinstance(observations, list) and len(queries) <= len(expected)
               and len(queries) <= len(observations) <= min(len(expected), len(queries)+1),
               "Oracle raw process evidence/count mismatch")
    if not failed:
        wg.require(len(queries) == len(expected), "Oracle query count mismatch")
    values, incomplete = [], False
    for index, observation in enumerate(observations):
        board, side, child_query = expected[index]
        effective, sign = wg.oracle.effective_query(board, side)
        paired = index < len(queries)
        wg.require(not incomplete and isinstance(observation, dict), "Oracle invalid query stage")
        argv, resources = observation.get("argv"), observation.get("resources")
        wg.require(isinstance(argv, list) and len(argv) >= 2 and isinstance(argv[-1], str)
                   and argv[-2] == "-solve"
                   and argv == wg.oracle.oracle_argv(Path(m["inputs"]["oracle"]["path"]), profile,
                       solve_path=Path(argv[-1]), child_query=child_query), "Oracle raw command mismatch")
        wg.require(isinstance(resources, dict)
                   and all(type(resources.get(k)) is int and resources[k] >= 0
                           for k in ("user_cpu_ns", "system_cpu_ns"))
                   and type(resources.get("peak_rss_kib")) is int and resources["peak_rss_kib"] > 0
                   and type(observation.get("wall_ns")) is int and observation["wall_ns"] > 0
                   and isinstance(observation.get("stdout"), str) and isinstance(observation.get("stderr"), str),
                   "Oracle raw resources/output missing")
        sampled = observation.get("last_observation")
        if sampled is not None:
            wg.require(isinstance(sampled, dict)
                       and all(type(sampled.get(k)) is int and sampled[k] >= 0
                               for k in ("user_cpu_ns", "system_cpu_ns"))
                       and type(sampled.get("peak_rss_kib")) is int and sampled["peak_rss_kib"] > 0,
                       "Oracle raw sampled resources invalid")
        cap_exceeded = max(resources["peak_rss_kib"], sampled["peak_rss_kib"] if sampled else 0) > CAPS["max_rss_kib"]
        if "sampling_failure" in observation:
            wg.require(isinstance(observation["sampling_failure"], str) and bool(observation["sampling_failure"]),
                       "Oracle exit observation invalid" if "exit_observation" in observation else "Oracle sampling failure invalid")
        if "exit_observation" in observation:
            exit_raw = observation["exit_observation"]
            wg.require(isinstance(exit_raw, dict) and type(exit_raw.get("exiting")) is bool
                       and bool(observation.get("sampling_failure")), "Oracle exit observation invalid")
            if "missing" in exit_raw:
                wg.require(set(exit_raw) == {"missing", "exiting"} and exit_raw["missing"] is True
                           and exit_raw["exiting"] is True, "Oracle exit observation invalid")
            else:
                wg.require(set(exit_raw) == {"stat", "state", "flags", "exiting"}
                           and isinstance(exit_raw["stat"], str) and ")" in exit_raw["stat"],
                           "Oracle exit observation invalid")
                fields = exit_raw["stat"][exit_raw["stat"].rfind(")")+2:].split()
                wg.require(len(fields) > 6 and fields[6].isdigit(), "Oracle exit observation invalid")
                flags = int(fields[6])
                wg.require(type(exit_raw["flags"]) is int and exit_raw["flags"] == flags
                           and exit_raw["state"] == fields[0]
                           and exit_raw["exiting"] == bool(flags & 0x4 or fields[0] in ("X", "Z"))
                           and (not paired or exit_raw["exiting"]), "Oracle exit observation invalid")
        # Failed attempts retain their actual exit, including signals. Missing
        # historical evidence remains immutable and needs its pinned verifier.
        has_exit = "exit_status" in observation or "returncode" in observation
        wg.require(type(observation.get("exit_status")) is int
                   and type(observation.get("returncode")) is int
                   and os.waitstatus_to_exitcode(observation["exit_status"]) == observation["returncode"],
                   "Oracle normal exit evidence invalid" if paired else "Oracle exit evidence invalid")
        if paired:
            wg.require(observation["returncode"] == 0, "Oracle normal exit evidence missing")
            wg.require(not cap_exceeded and observation["wall_ns"] < CAPS["timeout_seconds"]*1_000_000_000,
                       "Oracle successful process exceeded resource cap")
            query = queries[index]
            wg.require(isinstance(query, dict) and query.get("board") == board and query.get("side") == side
                       and query.get("effective_side") == effective and type(query.get("sign")) is int and query["sign"] == sign
                       and query.get("child_query") is child_query and isinstance(query.get("result"), dict),
                       "Oracle raw query identity mismatch")
            raw = query["result"]
            wg.require(type(raw.get("exact")) is bool
                       and all(type(raw.get(k)) is int for k in ("completed_depth", "value", "nodes", "elapsed_ms", "nps")),
                       "Oracle raw solve types invalid")
            wg.require(wg.oracle.parse_solve_output(observation["stdout"], [board.count(".")], profile) == [raw]
                       and raw["move"] in wg.oracle.legal_moves(board, effective), "Oracle raw output mismatch")
            incomplete = raw["exact"] is not True or raw["completed_depth"] < board.count(".")
            values.append(sign*int(raw["value"]))
        else:
            # This last attempt did not produce an accepted parsed query. Check
            # retained raw evidence without converting its failure into success.
            if result["failure"] == "Oracle peak RSS cap exceeded":
                wg.require(cap_exceeded, "Oracle RSS failure lacks exceeded cap")
            if result["failure"] == "Oracle decision timeout":
                wg.require(observation["wall_ns"] >= CAPS["timeout_seconds"]*1_000_000_000,
                           "Oracle timeout lacks elapsed deadline")
            if result["failure"] == "Oracle process failed":
                wg.require(has_exit and observation["returncode"] != 0, "Oracle process failure lacks nonzero exit")
            reason = result["failure"]
            known_process_failure = (
                cap_exceeded and reason == "Oracle peak RSS cap exceeded"
                or observation["wall_ns"] >= CAPS["timeout_seconds"]*1_000_000_000 and reason == "Oracle decision timeout"
                or has_exit and observation["returncode"] != 0 and reason == "Oracle process failed"
                or reason == observation.get("sampling_failure")
                   and not observation.get("exit_observation", {}).get("exiting", False))
            if not known_process_failure:
                wg.require(not cap_exceeded, "Oracle failure reason does not match exceeded cap")
                if has_exit:
                    wg.require(observation["returncode"] == 0 and not cap_exceeded,
                               "Oracle failure reason does not match process")
                try:
                    parsed = wg.oracle.parse_solve_output(observation["stdout"], [board.count(".")], profile)
                    move = parsed[0]["move"]
                    parse_failure = (f"Egaroucid returned an illegal continuation move for {effective}: {move!r}"
                                     if move not in wg.oracle.legal_moves(board, effective) else None)
                except wg.oracle.OracleError as exc:
                    parse_failure = str(exc)
                wg.require(parse_failure is not None and reason == parse_failure,
                           "Oracle failure reason does not match raw output")
    if incomplete:
        wg.require(failed and len(observations) == len(queries)
                   and result["failure"] == "independent Oracle incomplete", "Oracle incomplete stage mismatch")
    elif len(queries) == len(expected):
        selected = terminal_score if terminal_score is not None else -values[1] if len(values) == 2 else values[0]
        matches = values[0] == selected == step["search"]["score"]
        wg.require((failed and not matches and result["failure"] == "independent Oracle score/continuation mismatch")
                   or (not failed and matches), "Oracle score/failure stage mismatch")
    else:
        wg.require(failed and result["failure"] not in
                   ("independent Oracle incomplete", "independent Oracle score/continuation mismatch"),
                   "Oracle failure does not match reached stage")
        if len(observations) == len(queries):
            wg.require(re.fullmatch(r"\[Errno -?\d+\] .+", result["failure"], re.DOTALL) is not None,
                       "Oracle prelaunch failure lacks OS error evidence")


def immutable(path, expected):
    if path.exists():
        wg.require(prep.load(path) == expected, f"existing stage evidence mismatch: {path}")
    else:
        wg.atomic_write(path, expected)


def unit_path(directory, unit):
    return directory / f"{unit['id']}.json"


def run_units(m, rows, directory, progress, verify_only=False):
    directory.mkdir(parents=True, exist_ok=True)
    known = {u["id"] for u in rows}
    results = {}
    imports = {r["unit"]["id"]: r for r in resume_sources(m)}
    for path in directory.iterdir():
        if path.name.startswith(".unfinished-"):
            continue
        wg.require(path.suffix == ".json" and path.stem in known, "unknown unit checkpoint")
        unit = next(u for u in rows if u["id"] == path.stem)
        result = prep.load(path)
        verify_unit(m, unit, result)
        if unit["id"] in imports or "imported_from" in result:
            wg.require(result == imports.get(unit["id"]), "imported unit provenance mismatch")
        results[unit["id"]] = result
    for index, unit in enumerate(rows):
        if unit["id"] in results:
            progress.emit(unit["stage"], unit, index+1, len(rows), "skipped")
            continue
        wg.require(not verify_only, "missing assessment unit")
        progress.emit(unit["stage"], unit, index, len(rows), "running")
        try:
            result = measure_unit(m, unit)
        except KeyboardInterrupt:
            progress.emit(unit["stage"], unit, index, len(rows), "interrupted")
            raise
        verify_unit(m, unit, result)
        wg.atomic_write(unit_path(directory, unit), result)
        results[unit["id"]] = result
        progress.emit(unit["stage"], unit, index+1, len(rows), "failed" if result["status"] == "failed" else "saved")
    return [results[u["id"]] for u in rows]


def run_oracle(m, results, directory, progress, verify_only=False):
    jobs = oracle_jobs(results)
    stage = wg.sealed({"version": VERSION, "manifest_digest": m["report_digest"], "jobs": jobs, "total": len(jobs)})
    stage_path = directory.parent / (directory.name+"-manifest.json")
    wg.require(not verify_only or stage_path.exists(), "missing Oracle stage manifest")
    immutable(stage_path, stage)
    directory.mkdir(parents=True, exist_ok=True)
    known = {j["id"]: j for j in jobs}
    existing = {}
    for path in directory.iterdir():
        if path.name.startswith(".unfinished-"):
            continue
        wg.require(path.suffix == ".json" and path.stem in known, "unknown Oracle checkpoint")
        item = prep.load(path)
        verify_position(m, known[path.stem], item)
        existing[path.stem] = item
    receipts = []
    for index, job in enumerate(jobs):
        if job["id"] in existing:
            item = existing[job["id"]]
            progress.emit("oracle", job["unit"], index+1, len(jobs), "skipped")
        else:
            wg.require(not verify_only, "missing Oracle position")
            progress.emit("oracle", job["unit"], index, len(jobs), "running")
            try:
                item = solve_position(m, job)
            except KeyboardInterrupt:
                progress.emit("oracle", job["unit"], index, len(jobs), "interrupted")
                raise
            verify_position(m, job, item)
            wg.atomic_write(directory / (job["id"]+".json"), item)
            progress.emit("oracle", job["unit"], index+1, len(jobs), "failed" if item["status"] == "failed" else "saved")
        receipts.append(item)
    return receipts


def admitted_thresholds(results, receipts):
    admitted, reasons = [], {}
    for threshold in THRESHOLDS:
        group = [r for r in results if r["unit"]["threshold"] == threshold]
        try:
            wg.require(len(group) == 8 and all(r["status"] == "completed" for r in group), "pilot windows incomplete/failed")
            turns = [r for r in group if r["unit"]["scope"] == "turn"]
            games = [r for r in group if r["unit"]["scope"] == "game"]
            wg.require(len(turns) == len(games) == 4
                       and len({sha(r["unit"]["start"]) for r in turns}) == 4
                       and {sha(r["unit"]["start"]) for r in turns} == {sha(r["unit"]["start"]) for r in games},
                       "pilot scope/root coverage missing")
            for turn in [r for r in group if r["unit"]["scope"] == "turn"]:
                game = next(r for r in group if r["unit"]["scope"] == "game" and r["unit"]["start"] == turn["unit"]["start"])
                semantic_pair(turn, game)
            expected = oracle_jobs(group)
            actual = [r for r in receipts if r["job"]["unit"]["threshold"] == threshold]
            wg.require(expected and [r["job"] for r in actual] == expected
                       and all(r["status"] == "completed" for r in actual), "Oracle evidence missing/incomplete/failed")
            admitted.append(threshold)
        except wg.BenchmarkError as exc:
            reasons[str(threshold)] = str(exc)
    return admitted, reasons


def phase_totals(results):
    rows = {}
    for result in results:
        for step in result["steps"]:
            key = step["phase"]
            row = rows.setdefault(key, {"nodes": 0, "wall_ns": 0, "cpu_ns": 0, "decisions": 0,
                                       "legal_move_count_sum": 0, "cache_hits": 0})
            for field, value in (("nodes", step["search"]["nodes"]), ("wall_ns", step["decision_elapsed_ns"]),
                ("cpu_ns", step["decision_cpu_ns"]), ("decisions", 1), ("legal_move_count_sum", step["legal_move_count"]),
                ("cache_hits", step["search"]["cache_hits"])):
                row[field] += value
    return rows


def exact_root_totals(results):
    groups = {"first_per_seat": [], "subsequent_per_seat": []}
    for result in results:
        seen = set()
        for step in result["steps"]:
            if not step["search"]["exact"]:
                continue
            key = "subsequent_per_seat" if step["seat"] in seen else "first_per_seat"
            groups[key].append(step)
            seen.add(step["seat"])
    return {name: {"roots": len(steps), "nodes": sum(s["search"]["nodes"] for s in steps),
        "cpu_ns": sum(s["decision_cpu_ns"] for s in steps), "wall_ns": sum(s["decision_elapsed_ns"] for s in steps),
        "cache_probes": sum(s["search"]["cache_probes"] for s in steps),
        "cache_hits": sum(s["search"]["cache_hits"] for s in steps),
        "cache_stores": sum(s["search"]["cache_stores"] for s in steps),
        "position_ids": [s["id"] for s in steps]} for name, steps in groups.items()}


def assessment_summary(results, receipts, admitted, reasons):
    conditions = []
    for threshold in admitted:
        for depth in (12, 8):
            group = [r for r in results if r["unit"]["threshold"] == threshold and r["unit"]["depth"] == depth]
            record = {"threshold": threshold, "depth": depth, "status": "failed", "failure": None}
            try:
                wg.require(len(group) == 16 and all(r["status"] == "completed" for r in group), "full condition incomplete/failed; no partial averages")
                expected = oracle_jobs(group)
                actual = [r for r in receipts if r["job"]["unit"]["threshold"] == threshold and r["job"]["unit"]["depth"] == depth]
                wg.require([r["job"] for r in actual] == expected and actual and all(r["status"] == "completed" for r in actual), "full Oracle evidence incomplete/failed")
                scopes = {scope: [r for r in group if r["unit"]["scope"] == scope] for scope in SCOPES}
                for turn, game in zip(scopes["turn"], scopes["game"]):
                    semantic_pair(turn, game)
                totals = {scope: {"wall_ns": sum(r["wall_ns"] for r in rows),
                    "cpu_ns": sum(r["resources"]["user_cpu_ns"]+r["resources"]["system_cpu_ns"] for r in rows),
                    "peak_rss_kib": max(r["resources"]["peak_rss_kib"] for r in rows),
                    "phase": phase_totals(rows), "exact_roots": exact_root_totals(rows)} for scope, rows in scopes.items()}
                wg.require(all(t["cpu_ns"] > 0 for t in totals.values()), "CPU evidence missing")
                record.update(status="completed", totals=totals,
                    wall_ratio=totals["game"]["wall_ns"]/totals["turn"]["wall_ns"],
                    cpu_ratio=totals["game"]["cpu_ns"]/totals["turn"]["cpu_ns"])
                for total in totals.values():
                    total["mean_game_wall_ns"] = total["wall_ns"]/8
                    total["exact_wall_fraction"] = total["phase"]["exact"]["wall_ns"]/total["wall_ns"]
                record["exact_changes"] = {key: {"turn": totals["turn"]["phase"]["exact"][key],
                    "game": totals["game"]["phase"]["exact"][key],
                    "reduction": totals["turn"]["phase"]["exact"][key]-totals["game"]["phase"]["exact"][key],
                    "ratio": (totals["game"]["phase"]["exact"][key]/totals["turn"]["phase"]["exact"][key]
                              if totals["turn"]["phase"]["exact"][key] else None)} for key in ("nodes", "cpu_ns", "wall_ns")}
            except wg.BenchmarkError as exc:
                record["failure"] = str(exc)
            conditions.append(record)
    return wg.sealed({"version": VERSION, "admitted_thresholds": admitted, "pilot_exclusions": reasons,
        "conditions": conditions, "unit_digests": [r["report_digest"] for r in results],
        "oracle_digests": [r["report_digest"] for r in receipts],
        "interpretation": "Single serial run; no significance claim. Pilot window timings excluded from full-game comparisons. Production adoption requires human decision in 0040."})


def preflight(m, directory):
    """Recompute saved derived evidence before starting any process."""
    imported = {r["unit"]["id"]: r for r in resume_sources(m)}
    known = {u["id"]: u for u in m["pilot_units"]}
    gate_path, gate = directory/"full-manifest.json", None
    if gate_path.exists():
        gate = prep.load(gate_path)
        verify_seal(gate)
        wg.require(gate["manifest_digest"] == m["report_digest"]
                   and gate["thresholds"] == [t for t in THRESHOLDS if t in gate["thresholds"]]
                   and gate["units"] == units("full", m["roots"], gate["thresholds"])
                   and gate["total"] == len(gate["units"]), "full gate identity mismatch")
        known.update({u["id"]: u for u in gate["units"]})
    sources = {}
    for stage in ("pilot", "full"):
        folder = directory/stage
        if not folder.exists():
            continue
        for file in folder.iterdir():
            if file.name.startswith(".unfinished-"):
                continue
            wg.require(file.suffix == ".json" and file.stem in known
                       and known[file.stem]["stage"] == stage, "unknown saved stage unit")
            result = prep.load(file)
            verify_unit(m, known[file.stem], result)
            if file.stem in imported or "imported_from" in result:
                wg.require(result == imported.get(file.stem), "imported unit provenance mismatch")
            sources[file.stem] = result
    ordered = {stage: [sources[u["id"]] for u in known.values()
                       if u["stage"] == stage and u["id"] in sources]
               for stage in ("pilot", "full")}
    receipts, stage_jobs = {}, {}
    for stage in ("pilot", "full"):
        folder = directory/(stage+"-oracle")
        stage_path = directory/(stage+"-oracle-manifest.json")
        receipts[stage] = {}
        if not folder.exists() and not stage_path.exists():
            continue
        wg.require(stage_path.exists(), "Oracle stage manifest missing")
        wg.require(len(ordered[stage]) == sum(u["stage"] == stage for u in known.values()),
                   "Oracle stage has missing source units")
        stage_manifest = prep.load(stage_path)
        verify_seal(stage_manifest)
        jobs = oracle_jobs(ordered[stage])
        wg.require(stage_manifest == wg.sealed({"version": VERSION,
            "manifest_digest": m["report_digest"], "jobs": jobs,
            "total": len(jobs)}), "Oracle stage sources mismatch")
        stage_jobs[stage] = jobs
        if not folder.exists():
            continue
        by_id = {job["id"]: job for job in jobs}
        for file in folder.iterdir():
            if file.name.startswith(".unfinished-"):
                continue
            wg.require(file.suffix == ".json" and file.stem in by_id, "unknown saved Oracle position")
            result = prep.load(file)
            verify_position(m, by_id[file.stem], result)
            receipts[stage][file.stem] = result
    if gate is not None:
        wg.require(len(ordered["pilot"]) == len(m["pilot_units"])
                   and "pilot" in stage_jobs
                   and len(receipts["pilot"]) == len(stage_jobs["pilot"]),
                   "full gate has missing pilot or Oracle evidence")
        pilot_receipts = [receipts["pilot"][j["id"]] for j in stage_jobs["pilot"]]
        admitted, reasons = admitted_thresholds(ordered["pilot"], pilot_receipts)
        expected_gate = wg.sealed({"version": VERSION, "manifest_digest": m["report_digest"],
            "thresholds": admitted, "excluded": reasons,
            "units": units("full", m["roots"], admitted),
            "total": len(units("full", m["roots"], admitted)),
            "pilot_digests": [r["report_digest"] for r in ordered["pilot"]],
            "oracle_digests": [r["report_digest"] for r in pilot_receipts]})
        wg.require(gate == expected_gate, "full gate derived evidence mismatch")
    summary_path = directory/"assessment.json"
    if summary_path.exists():
        summary = prep.load(summary_path)
        verify_seal(summary)
        wg.require(gate is not None and len(ordered["full"]) == gate["total"]
                   and "full" in stage_jobs
                   and len(receipts["full"]) == len(stage_jobs["full"]),
                   "assessment has missing full or Oracle evidence")
        full_receipts = [receipts["full"][j["id"]] for j in stage_jobs["full"]]
        expected_summary = assessment_summary(ordered["full"], full_receipts,
                                               gate["thresholds"], gate["excluded"])
        wg.require(summary == expected_summary, "assessment derived evidence mismatch")


def execute(path, command, every):
    m = verify_manifest(path)
    if command == "verify-inputs":
        return
    directory, progress = Path(m["output_directory"]), Progress(every)
    verify_only = command == "verify"
    with wg.exclusive_lock(directory):
        preflight(m, directory)
        pilot = run_units(m, m["pilot_units"], directory/"pilot", progress, verify_only)
        oracle = run_oracle(m, pilot, directory/"pilot-oracle", progress, verify_only)
        admitted, reasons = admitted_thresholds(pilot, oracle)
        rows = units("full", m["roots"], admitted)
        gate = wg.sealed({"version": VERSION, "manifest_digest": m["report_digest"], "thresholds": admitted,
            "excluded": reasons, "units": rows, "total": len(rows),
            "pilot_digests": [r["report_digest"] for r in pilot], "oracle_digests": [r["report_digest"] for r in oracle]})
        wg.require(not verify_only or (directory/"full-manifest.json").exists(), "missing full gate manifest")
        immutable(directory/"full-manifest.json", gate)
        if command == "pilot":
            return
        full = run_units(m, rows, directory/"full", progress, verify_only)
        full_oracle = run_oracle(m, full, directory/"full-oracle", progress, verify_only)
        summary = assessment_summary(full, full_oracle, admitted, reasons)
        wg.require(not verify_only or (directory/"assessment.json").exists(), "missing assessment summary")
        immutable(directory/"assessment.json", summary)
        for unit in (rows[-1:] or m["pilot_units"][-1:]):
            progress.emit("verify", unit, len(rows), len(rows), "verified")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    for name in ("cli-binary", "oracle-binary", "artifact", "source-report", "output-dir"):
        p.add_argument("--"+name, type=Path, required=True)
    p.add_argument("--oracle-cwd", type=Path)
    p.add_argument("--resume-manifest", type=Path)
    p.add_argument("--source-revision", required=True)
    p.add_argument("--harness-revision", required=True)
    for name in ("run", "pilot", "verify", "verify-inputs"):
        p = sub.add_parser(name)
        p.add_argument("--manifest", type=Path, required=True)
        p.add_argument("--progress-every", type=int, default=1)
    args = parser.parse_args(argv)
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.command == "prepare":
            prepare(args)
        else:
            execute(args.manifest, args.command, args.progress_every)
    except KeyboardInterrupt:
        Progress().emit(LAST_PROGRESS["stage"], LAST_PROGRESS["unit"], LAST_PROGRESS["done"], LAST_PROGRESS["total"], "interrupted")
        return 130
    except (wg.BenchmarkError, wg.oracle.OracleError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        Progress().emit("verify", LAST_PROGRESS["unit"], LAST_PROGRESS["done"], LAST_PROGRESS["total"], "failed")
        print(f"exact-threshold assessment error: {exc}", file=sys.stderr, flush=True)
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
