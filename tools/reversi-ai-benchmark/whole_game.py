#!/usr/bin/env python3
"""Human-operated, serial whole-game self-play measurement and offline verifier."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import signal
import uuid
import hashlib
import json
import os
import platform
import re
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reversi-ai-oracle"))
import oracle  # noqa: E402  (project-owned adapter; Egaroucid remains external)

VERSION = "reversi-ai-whole-game-v3"
SCORE_CONTRACT = "winner-empty-v1"
OPENINGS = Path(__file__).with_name("whole-game-openings-v1.json")
DIAGNOSTIC = re.compile(
    r"search_diagnostic_v1\tposition_id=([^\t]+)\telapsed_us=(\d+)\tnodes=(\d+)"
    r"\texact=(true|false)\tscore=(-?\d+|none)\tcompleted_depth=(\d+)"
    r"\toutcome=(move|pass|game_over)\tcache_probes=(\d+)\tcache_hits=(\d+)\tcache_stores=(\d+)"
)
SCORE_IDENTITY = re.compile(
    r"score_contract_v1\tposition_id=([^\t]+)\tscore_contract=(winner-empty-v1)"
    r"\tsearch_semantics_version=(2)"
)
CACHE_POLICY = re.compile(
    r"exact_cache_policy_v1\tposition_id=([^\t]+)\texact_cache_scope=([^\t]+)"
    r"\texact_cache_policy=([^\t]+)"
)


class BenchmarkError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BenchmarkError(message)


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def opening_rows(path: Path = OPENINGS) -> list[dict]:
    raw = path.read_bytes()
    data = json.loads(raw)
    require(raw == canonical(data), "openings must be canonical JSON")
    require(data.get("schema_version") == 1 and isinstance(data.get("openings"), list)
            and len(data["openings"]) == 4, "expected four version-1 openings")
    rows = []
    for index, item in enumerate(data["openings"], 1):
        require(item.get("id") == f"opening-{index}" and isinstance(item.get("moves"), str)
                and re.fullmatch(r"(?:[a-h][1-8]){6}", item["moves"]) is not None,
                "opening id or transcript is invalid")
        board, side = oracle.initial_board(), "B"
        for offset in range(0, len(item["moves"]), 2):
            board, side = oracle.replay_console_move(board, side, item["moves"][offset:offset + 2])
        rows.append({"id": item["id"], "moves": item["moves"], "board": board, "side": side})
    require(len({(row["board"], row["side"]) for row in rows}) == 4, "duplicate opening boards")
    return rows


def measurement_rows(sample: str, rows: list[dict] | None = None) -> list[tuple[dict, int]]:
    available = rows or opening_rows()
    assignments = [(row, assignment) for row in available for assignment in (0, 1)]
    if sample == "full8":
        return assignments
    if sample == "efficiency3":
        wanted = (("opening-1", 0), ("opening-2", 0), ("opening-4", 0))
        by_id = {(row["id"], assignment): (row, assignment) for row, assignment in assignments}
        return [by_id[key] for key in wanted]
    raise BenchmarkError("unknown whole-game sample")


def profile(midgame_depth: int, exact_empty: int = 16) -> oracle.OracleProfile:
    return oracle.profile_from_name(f"whole-game-depth-{midgame_depth}-exact-{exact_empty}")


def proc_usage(pid: int) -> dict[str, int]:
    """Read cumulative per-process CPU and peak RSS while a persistent seat lives."""
    stat = Path(f"/proc/{pid}/stat").read_text()
    fields = stat[stat.rfind(")") + 2:].split()
    ticks = os.sysconf("SC_CLK_TCK")
    status = Path(f"/proc/{pid}/status").read_text()
    match = re.search(r"^VmHWM:\s+(\d+) kB$", status, re.MULTILINE)
    require(match is not None, "process peak RSS is unavailable")
    return {"user_cpu_ns": int(fields[11]) * 1_000_000_000 // ticks,
            "system_cpu_ns": int(fields[12]) * 1_000_000_000 // ticks,
            "peak_rss_kib": int(match.group(1))}


def wait_measured(process: subprocess.Popen, timeout: float) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid, status, usage = os.wait4(process.pid, os.WNOHANG)
        if pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            require(process.returncode == 0, f"seat process exited {process.returncode}")
            return {"user_cpu_ns": round(usage.ru_utime * 1_000_000_000),
                    "system_cpu_ns": round(usage.ru_stime * 1_000_000_000),
                    "peak_rss_kib": usage.ru_maxrss}
        time.sleep(0.01)
    process.kill()
    os.wait4(process.pid, 0)
    raise BenchmarkError("seat process did not exit within timeout")


class Seat:
    def __init__(self, kind: str, binary: Path, artifact: Path | None, depth: int,
                 timeout: float, label: str, cwd: Path | None = None,
                 cache_scope: str = "game", exact_empty: int = 16,
                 node_limit: int | None = None, max_rss_kib: int | None = None,
                 capture_cache_policy: bool = False,
                 opening_depth: int = 12, endgame_depth: int = 12,
                 search_time_limit_ms: int | None = None):
        require(exact_empty in (16, 20, 24), "unsupported exact threshold")
        require(all(type(depth) is int and 1 <= depth <= 64
                    for depth in (opening_depth, depth, endgame_depth)), "invalid phase depth")
        require(search_time_limit_ms is None or type(search_time_limit_ms) is int and search_time_limit_ms > 0,
                "invalid search time limit")
        require(node_limit is None or type(node_limit) is int and node_limit > 0, "invalid node limit")
        require(max_rss_kib is None or type(max_rss_kib) is int and max_rss_kib > 0, "invalid RSS limit")
        self.exact_empty, self.node_limit, self.max_rss_kib = exact_empty, node_limit, max_rss_kib
        self.capture_cache_policy = capture_cache_policy
        self.score_identities = {}
        self.last_observation: dict | None = None
        self.peak_observation: dict | None = None
        self.kind, self.timeout, self.label, self.depth = kind, timeout, label, depth
        self.opening_depth, self.endgame_depth = opening_depth, endgame_depth
        self.search_time_limit_ms = search_time_limit_ms
        self.stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        started = time.monotonic_ns()
        self.started_at_ns = time.time_ns()
        if kind == "oracle":
            self.gtp = oracle.GtpSession(binary, cwd or binary.parent, profile(depth, exact_empty), timeout)
            self.process = self.gtp.process
            self.buffer = bytearray()
        else:
            require(artifact is not None, "CLI requires a trained artifact")
            search_time_limit_ms = (search_time_limit_ms if search_time_limit_ms is not None
                                    else int(timeout * 1000) - 1000)
            argv = [str(binary), "--evaluator", "trained", "--trained-artifact", str(artifact),
                    "--opening-depth", str(opening_depth), "--midgame-depth", str(depth),
                    "--endgame-depth", str(endgame_depth), "--exact-solver-empty-squares", str(exact_empty),
                    "--time-limit-ms", str(search_time_limit_ms)]
            if node_limit is not None:
                argv.extend(["--node-limit", str(node_limit)])
            if kind != "cli-legacy":
                argv.extend(["--exact-cache-scope", cache_scope])
            self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=self.stderr, bufsize=0)
            self.gtp = None
            self.buffer = bytearray()
        self.startup_ns = time.monotonic_ns() - started
        self.diagnostics: dict[str, dict] = {}
        self.cache_policies: dict[str, dict] = {}
        self.diagnostic_offset = 0

    def gtp_command(self, command: str) -> list[str]:
        require(self.gtp is not None, "GTP command sent to CLI")
        return self.gtp.command(command)

    def observe_resources(self) -> dict:
        usage = proc_usage(self.process.pid)
        self.last_observation = usage
        if self.peak_observation is None or usage["peak_rss_kib"] > self.peak_observation["peak_rss_kib"]:
            self.peak_observation = dict(usage)
        require(self.max_rss_kib is None or usage["peak_rss_kib"] <= self.max_rss_kib,
                "peak RSS cap exceeded")
        return usage

    def choose(self, identifier: str, board: str, side: str,
               game_deadline: float | None = None) -> tuple[str, int]:
        self.peak_observation = None
        started = time.monotonic_ns()
        if self.gtp:
            command = f"genmove {'black' if side == 'B' else 'white'}"
            move = oracle.gtp_move_from_response(self.gtp.command(command), command)
        else:
            assert self.process.stdin and self.process.stdout
            self.process.stdin.write(f"{identifier}\t{board}\t{side}\n".encode("ascii"))
            self.process.stdin.flush()
            deadline = time.monotonic() + self.timeout
            if game_deadline is not None:
                deadline = min(deadline, game_deadline)
            while b"\n" not in self.buffer:
                remaining = deadline - time.monotonic()
                require(remaining > 0, f"whole-game wall limit exceeded at {identifier}"
                        if game_deadline is not None and game_deadline <= time.monotonic()
                        else f"CLI timed out at {identifier}")
                if self.max_rss_kib is not None:
                    self.observe_resources()
                ready, _, _ = select.select([self.process.stdout], [], [], min(remaining, 0.05)
                                            if self.max_rss_kib is not None else remaining)
                if not ready and self.max_rss_kib is not None:
                    continue
                require(bool(ready), f"CLI timed out at {identifier}")
                chunk = os.read(self.process.stdout.fileno(), 4096)
                require(bool(chunk), f"CLI exited at {identifier}")
                self.buffer.extend(chunk)
                require(len(self.buffer) <= 4096, "CLI response too long")
            line, _, remainder = self.buffer.partition(b"\n")
            self.buffer = bytearray(remainder)
            answer = line.decode("ascii").split("\t")
            require(len(answer) == 2 and answer[0] == identifier, "CLI response id mismatch")
            move = answer[1]
        if self.max_rss_kib is not None:
            self.observe_resources()
        return move, time.monotonic_ns() - started

    def close(self) -> dict:
        started = time.monotonic_ns()
        if self.gtp:
            self.gtp.command("quit")
        elif self.process.stdin:
            self.process.stdin.close()
        usage = wait_measured(self.process, self.timeout)
        shutdown_ns = time.monotonic_ns() - started
        if self.process.stdout:
            self.process.stdout.close()
        self.collect_diagnostics()
        self.stderr.close()
        return {"startup_ns": self.startup_ns, "shutdown_ns": shutdown_ns,
                "started_at_ns": self.started_at_ns, "ended_at_ns": time.time_ns(), **usage}

    def collect_diagnostics(self) -> None:
        self.stderr.seek(self.diagnostic_offset)
        lines = self.stderr.readlines()
        self.diagnostic_offset = self.stderr.tell()
        for line in lines:
            contract = SCORE_IDENTITY.fullmatch(line.rstrip("\n"))
            if contract:
                identifier, value, semantics = contract.groups()
                require(identifier not in self.score_identities, "duplicate CLI score identity id")
                self.score_identities[identifier] = {"score_contract": value,
                    "search_semantics_version": int(semantics), "score_identity_raw": line.rstrip("\n")}
            policy = CACHE_POLICY.fullmatch(line.rstrip("\n"))
            if policy and self.capture_cache_policy:
                identifier, scope, value = policy.groups()
                require(identifier not in self.cache_policies, "duplicate CLI cache policy id")
                self.cache_policies[identifier] = {"scope": scope, "policy": value,
                                                   "raw": line.rstrip("\n")}
            match = DIAGNOSTIC.fullmatch(line.rstrip("\n"))
            if match:
                identifier, elapsed, nodes, exact, score, completed_depth, outcome, probes, hits, stores = match.groups()
                require(identifier not in self.diagnostics, "duplicate CLI diagnostic id")
                self.diagnostics[identifier] = {
                    "elapsed_us": int(elapsed), "nodes": int(nodes), "exact": exact == "true",
                    "score": None if score == "none" else int(score),
                    "completed_depth": int(completed_depth), "outcome": outcome,
                    "cache_probes": int(probes), "cache_hits": int(hits), "cache_stores": int(stores),
                }
        for identifier, identity in self.score_identities.items():
            if identifier in self.diagnostics:
                self.diagnostics[identifier].update(identity)
        for identifier, policy in self.cache_policies.items():
            if identifier in self.diagnostics:
                self.diagnostics[identifier]["exact_cache_policy"] = policy

    def new_game(self, identifier: str, game_deadline: float | None = None) -> dict:
        started = time.monotonic_ns()
        if self.gtp:
            self.gtp.command("clear_board")
        else:
            assert self.process.stdin and self.process.stdout
            self.process.stdin.write(f"new_game\t{identifier}\n".encode("ascii"))
            self.process.stdin.flush()
            deadline = time.monotonic() + self.timeout
            if game_deadline is not None:
                deadline = min(deadline, game_deadline)
            while b"\n" not in self.buffer:
                remaining = deadline - time.monotonic()
                require(remaining > 0, "whole-game wall limit exceeded during reset"
                        if game_deadline is not None and game_deadline <= time.monotonic()
                        else "new_game acknowledgement timed out")
                ready, _, _ = select.select([self.process.stdout], [], [], remaining)
                require(bool(ready), "new_game acknowledgement timed out")
                chunk = os.read(self.process.stdout.fileno(), 4096)
                require(bool(chunk), "new_game acknowledgement missing")
                self.buffer.extend(chunk)
                require(len(self.buffer) <= 4096, "new_game acknowledgement too long")
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            require(line.decode("ascii") == f"new_game\t{identifier}\tready",
                    "new_game acknowledgement mismatch")
        return {"game_id": identifier, "acknowledged": True,
                "elapsed_ns": time.monotonic_ns() - started,
                "protocol": "gtp-clear-board" if self.gtp else "new_game-v1"}

    def abort(self) -> dict | None:
        started = time.monotonic_ns()
        result = None
        if self.process.returncode is None:
            self.process.kill()
            try:
                _, status, usage = os.wait4(self.process.pid, 0)
                self.process.returncode = os.waitstatus_to_exitcode(status)
                result = {"startup_ns": self.startup_ns,
                          "shutdown_ns": max(1, time.monotonic_ns()-started),
                          "user_cpu_ns": round(usage.ru_utime*1_000_000_000),
                          "system_cpu_ns": round(usage.ru_stime*1_000_000_000),
                          "peak_rss_kib": usage.ru_maxrss,
                          "started_at_ns": self.started_at_ns, "ended_at_ns": time.time_ns()}
            except ChildProcessError:
                pass
        for stream in (self.process.stdin, self.process.stdout, self.stderr):
            if stream:
                stream.close()
        return result


def replay_opening_on_oracle(seats: dict[str, Seat], transcript: str) -> None:
    board, side = oracle.initial_board(), "B"
    for offset in range(0, len(transcript), 2):
        move = transcript[offset:offset + 2]
        if not oracle.legal_moves(board, side):
            for seat in seats.values():
                seat.gtp_command(f"play {'black' if side == 'B' else 'white'} PASS")
            side = oracle.other(side)
        require(move in oracle.legal_moves(board, side), "invalid opening transcript")
        for seat in seats.values():
            seat.gtp_command(f"play {'black' if side == 'B' else 'white'} {move}")
        board, side = oracle.apply_move(board, side, move), oracle.other(side)


def game(row: dict, assignment: int, seats: dict[str, Seat], kind: str,
         timeout: float, max_decisions: int,
         game_time_limit_seconds: float | None = None) -> dict:
    board, side = row["board"], row["side"]
    if kind == "oracle":
        replay_opening_on_oracle(seats, row["moves"])
    steps = []
    started = time.monotonic_ns()
    game_deadline = (time.monotonic() + game_time_limit_seconds
                     if game_time_limit_seconds is not None else None)
    for turn in range(max_decisions):
        require(game_deadline is None or time.monotonic() < game_deadline,
                f"whole-game wall limit exceeded at {row['id']}-seat{assignment}")
        legal = oracle.legal_moves(board, side)
        if not legal and not oracle.legal_moves(board, oracle.other(side)):
            break
        seat_label = side if assignment == 0 else oracle.other(side)
        identifier = f"{row['id']}-seat{assignment}-turn{turn}"
        active_seat = seats[seat_label]
        if hasattr(active_seat, "peak_observation"):
            active_seat.peak_observation = None
        before_usage = active_seat.observe_resources() if hasattr(active_seat, "observe_resources") else None
        if legal or kind != "oracle":
            if game_deadline is None:
                move, elapsed = seats[seat_label].choose(identifier, board, side)
            else:
                move, elapsed = seats[seat_label].choose(identifier, board, side, game_deadline)
        else:
            move, elapsed = "pass", 0
        after_usage = active_seat.observe_resources() if before_usage is not None else None
        require(move in legal if legal else move == "pass", f"illegal move at {identifier}")
        if kind == "oracle":
            if move == "pass":
                for seat in seats.values():
                    seat.gtp_command(f"play {'black' if side == 'B' else 'white'} PASS")
            else:
                opponent = seats[oracle.other(seat_label)]
                opponent.gtp_command(f"play {'black' if side == 'B' else 'white'} {move}")
        steps.append({"id": identifier, "board": board, "side": side, "seat": seat_label,
                      "move": move, "decision_elapsed_ns": elapsed})
        if before_usage is not None:
            steps[-1].update({"legal_move_count": len(legal),
                             "phase": decision_phase(board, getattr(active_seat, "exact_empty", 16)),
                             "resource_observations": {"before": before_usage, "after": after_usage},
                             "resources": {"user_cpu_ns": after_usage["user_cpu_ns"] - before_usage["user_cpu_ns"],
                                           "system_cpu_ns": after_usage["system_cpu_ns"] - before_usage["system_cpu_ns"],
                                           "peak_rss_kib": after_usage["peak_rss_kib"]}})
            peak = getattr(active_seat, "peak_observation", None)
            if peak is not None:
                steps[-1]["resource_observations"]["peak"] = dict(peak)
        if move != "pass":
            board = oracle.apply_move(board, side, move)
        side = oracle.other(side)
    else:
        raise BenchmarkError("game exceeded max decisions")
    counts = {"B": board.count("B"), "W": board.count("W")}
    return {"opening_id": row["id"], "assignment": assignment, "opening": row["moves"],
            "start_board": row["board"], "start_side": row["side"], "steps": steps,
            "wall_ns": time.monotonic_ns() - started, "terminal_board": board,
            "score_black": counts["B"] - counts["W"], "completed": True}


def validate_game(record: dict, row: dict, assignment: int) -> None:
    require(record.get("opening_id") == row["id"] and record.get("opening") == row["moves"]
            and record.get("assignment") == assignment and record.get("start_board") == row["board"]
            and record.get("start_side") == row["side"] and record.get("completed") is True,
            "game identity or completion mismatch")
    require(type(record.get("wall_ns")) is int and record["wall_ns"] > 0, "game wall missing")
    board, side = row["board"], row["side"]
    steps = record.get("steps")
    require(isinstance(steps, list) and 1 <= len(steps) <= 120, "decision count invalid")
    for turn, step in enumerate(steps):
        legal = oracle.legal_moves(board, side)
        seat = side if assignment == 0 else oracle.other(side)
        require(step.get("id") == f"{row['id']}-seat{assignment}-turn{turn}"
                and step.get("board") == board and step.get("side") == side
                and step.get("seat") == seat, "decision state mismatch")
        move = step.get("move")
        require(move in legal if legal else move == "pass" and bool(oracle.legal_moves(board, oracle.other(side))),
                "illegal move or pass")
        require(type(step.get("decision_elapsed_ns")) is int and step["decision_elapsed_ns"] >= 0,
                "decision time invalid")
        if move != "pass":
            board = oracle.apply_move(board, side, move)
        side = oracle.other(side)
    require(not oracle.legal_moves(board, side) and not oracle.legal_moves(board, oracle.other(side))
            and record.get("terminal_board") == board
            and record.get("score_black") == board.count("B") - board.count("W"),
            "terminal game mismatch")


def totals(games: list[dict]) -> dict:
    return {"games": len(games), "wall_ns": sum(game["wall_ns"] for game in games),
            "decision_ns": sum(step["decision_elapsed_ns"] for game in games for step in game["steps"]),
            "decisions": sum(len(game["steps"]) for game in games),
            "searches": sum(sum(step["move"] != "pass" for step in game["steps"]) if game.get("cache") is None
                            else len(game["steps"]) for game in games),
            "user_cpu_ns": sum(game["resources"]["user_cpu_ns"] for game in games),
            "system_cpu_ns": sum(game["resources"]["system_cpu_ns"] for game in games),
            "peak_rss_kib": max(game["resources"]["peak_rss_kib"] for game in games),
            "cache_probes": sum(game["cache"]["probes"] for game in games if game["cache"]),
            "cache_hits": sum(game["cache"]["hits"] for game in games if game["cache"]),
            "cache_stores": sum(game["cache"]["stores"] for game in games if game["cache"])}


def decision_phase(board: str, exact_empty: int = 16) -> str:
    occupied = 64 - board.count(".")
    return ("exact" if 64 - occupied <= exact_empty else "opening" if occupied <= 20
            else "endgame" if occupied >= 45 else "midgame")


def validate_cli_diagnostic(step: dict, sample: dict, midgame_depth: int,
                            exact_empty: int = 16, opening_depth: int = 12,
                            endgame_depth: int = 12,
                            search_time_limit_ms: int | None = None,
                            node_limit: int | None = None) -> None:
    require(exact_empty in (16, 20, 24), "unsupported exact threshold")
    require(isinstance(sample, dict) and sample.get("score_contract") == SCORE_CONTRACT
            and sample.get("search_semantics_version") == 2
            and sample.get("score_identity_raw") == (
                f"score_contract_v1\tposition_id={step['id']}\tscore_contract={SCORE_CONTRACT}\tsearch_semantics_version=2"),
            "CLI score identity missing or inconsistent")
    require(isinstance(sample, dict) and type(sample.get("exact")) is bool
            and sample.get("outcome") in ("move", "pass", "game_over")
            and all(type(sample.get(key)) is int and sample[key] >= 0
                    for key in ("elapsed_us", "nodes", "completed_depth",
                                "cache_probes", "cache_hits", "cache_stores")),
            "CLI search diagnostic missing")
    occupied = 64 - step["board"].count(".")
    exact = 64 - occupied <= exact_empty
    forced_pass = step["move"] == "pass"
    if exact:
        expected_depth = 64 - occupied
    elif forced_pass:
        expected_depth = 0
    else:
        expected_depth = (opening_depth if occupied <= 20 else
                          endgame_depth if occupied >= 45 else midgame_depth)
    expected_score = int if exact or not forced_pass else type(None)
    require(type(sample.get("score")) is expected_score
            and sample["completed_depth"] == expected_depth
            and sample["exact"] == exact
            and sample["outcome"] == ("pass" if forced_pass else "move"),
            "incomplete or inconsistent CLI search")
    require(search_time_limit_ms is None or sample["elapsed_us"] <= search_time_limit_ms * 1000,
            "CLI search exceeded configured time limit")
    require(node_limit is None or sample["nodes"] <= node_limit,
            "CLI search exceeded configured node limit")


def attach_diagnostics(record: dict, seats: dict[str, Seat], kind: str) -> None:
    if kind in ("oracle", "cli-legacy"):
        record["cache"] = None
        record["search_count"] = sum(step["move"] != "pass" for step in record["steps"])
        return
    sums = {"probes": 0, "hits": 0, "stores": 0}
    for step in record["steps"]:
        diagnostic = seats[step["seat"]].diagnostics.get(step["id"])
        require(diagnostic is not None, f"missing CLI diagnostic for {step['id']}")
        try:
            validate_cli_diagnostic(step, diagnostic, seats[step["seat"]].depth,
                                    getattr(seats[step["seat"]], "exact_empty", 16),
                                    getattr(seats[step["seat"]], "opening_depth", 12),
                                    getattr(seats[step["seat"]], "endgame_depth", 12),
                                    getattr(seats[step["seat"]], "search_time_limit_ms", None),
                                    getattr(seats[step["seat"]], "node_limit", None))
        except BenchmarkError as exc:
            raise BenchmarkError(f"{exc} at {step['id']}") from exc
        step["search"] = diagnostic
        for key in sums:
            sums[key] += diagnostic[f"cache_{key}"]
    record["cache"] = sums
    record["search_count"] = len(record["steps"])


def persistent_games(rows: list[dict], binary: Path, artifact: Path, depth: int,
                     timeout: float, max_decisions: int, max_rss_kib: int,
                     cache_scope: str) -> tuple[list[dict], dict]:
    seats: dict[str, Seat] = {}
    games = []
    try:
        for side in ("B", "W"):
            seats[side] = Seat("cli", binary, artifact, depth, timeout, side,
                               cache_scope=cache_scope)
        for row in rows:
            for assignment in (0, 1):
                before = {side: proc_usage(seat.process.pid) for side, seat in seats.items()}
                record = game(row, assignment, seats, "cli", timeout, max_decisions)
                after = {side: proc_usage(seat.process.pid) for side, seat in seats.items()}
                usages = {
                    side: {"startup_ns": 0, "shutdown_ns": 0,
                           "user_cpu_ns": after[side]["user_cpu_ns"] - before[side]["user_cpu_ns"],
                           "system_cpu_ns": after[side]["system_cpu_ns"] - before[side]["system_cpu_ns"],
                           "peak_rss_kib": after[side]["peak_rss_kib"]}
                    for side in ("B", "W")
                }
                record["seat_processes"] = usages
                record["resources"] = {"user_cpu_ns": sum(item["user_cpu_ns"] for item in usages.values()),
                                       "system_cpu_ns": sum(item["system_cpu_ns"] for item in usages.values()),
                                       "peak_rss_kib": max_observed_rss(usages, record)}
                require(record["resources"]["peak_rss_kib"] <= max_rss_kib, "peak RSS cap exceeded")
                games.append(record)
                print(f"progress whole-game {len(games)}/8 opening={row['id']} seat={assignment} "
                      f"game={record['wall_ns'] / 1e9:.1f}s", file=sys.stderr, flush=True)
        process_totals = {side: seat.close() for side, seat in seats.items()}
        for record in games:
            attach_diagnostics(record, seats, "cli")
        return games, process_totals
    finally:
        for seat in seats.values():
            seat.abort()


def measured_game(row: dict, assignment: int, kind: str, binary: Path, artifact: Path | None,
                  depth: int, timeout: float, max_decisions: int, max_rss_kib: int,
                  cwd: Path | None, cache_scope: str) -> dict:
    seats = {}
    try:
        for side in ("B", "W"):
            seats[side] = Seat(kind, binary, artifact, depth, timeout, side, cwd,
                               cache_scope)
        record = game(row, assignment, seats, kind, timeout, max_decisions)
        usages = {side: seat.close() for side, seat in seats.items()}
        attach_diagnostics(record, seats, kind)
        record["resources"] = {"user_cpu_ns": sum(item["user_cpu_ns"] for item in usages.values()),
                               "system_cpu_ns": sum(item["system_cpu_ns"] for item in usages.values()),
                               "peak_rss_kib": max_observed_rss(usages, record)}
        record["seat_processes"] = usages
        require(record["resources"]["peak_rss_kib"] <= max_rss_kib, "peak RSS cap exceeded")
        validate_game(record, row, assignment)
        require(record.get("search_count") == (sum(step["move"] != "pass" for step in record["steps"])
                if kind in ("oracle", "cli-legacy") else len(record["steps"])), "search count mismatch")
        return record
    finally:
        for seat in seats.values():
            seat.abort()


def run(args: argparse.Namespace) -> dict:
    require(args.kind in ("oracle", "cli", "cli-persistent"), "legacy CLI measurement is offline-only")
    require(sys.platform == "linux", "CPU/RSS measurement requires Linux")
    require(args.timeout_seconds > 1 and args.max_rss_kib > 0 and args.max_decisions >= 120,
            "invalid resource caps")
    require(args.binary.is_file() and (args.kind == "oracle" or args.artifact and args.artifact.is_file()),
            "binary or trained artifact is missing")
    require(args.kind != "oracle" or args.artifact is None, "oracle workload does not use a trained artifact")
    require(args.kind not in ("oracle", "cli-legacy") or args.cache_scope == "game",
            "legacy/oracle workload has no CLI cache scope")
    rows = opening_rows()
    games = []
    started = time.monotonic()
    process_totals = None
    if args.kind == "cli-persistent":
        assert args.artifact is not None
        games, process_totals = persistent_games(rows, args.binary, args.artifact,
                                                  args.midgame_depth, args.timeout_seconds,
                                                  args.max_decisions, args.max_rss_kib, args.cache_scope)
    else:
        for row in rows:
            for assignment in (0, 1):
                games.append(measured_game(row, assignment, args.kind, args.binary, args.artifact,
                                           args.midgame_depth, args.timeout_seconds,
                                           args.max_decisions, args.max_rss_kib, args.oracle_cwd,
                                           args.cache_scope))
                print(f"progress whole-game {len(games)}/8 opening={row['id']} seat={assignment} "
                      f"game={games[-1]['wall_ns'] / 1e9:.1f}s elapsed={time.monotonic() - started:.1f}s",
                      file=sys.stderr, flush=True)
    report = {"schema_version": 3, "score_contract": SCORE_CONTRACT, "runner_version": VERSION, "kind": args.kind,
              "openings_sha256": digest(OPENINGS), "binary": {"path": str(args.binary.resolve()),
              "sha256": digest(args.binary)},
              "artifact": ({"path": str(args.artifact.resolve()), "sha256": digest(args.artifact)}
                           if args.artifact else None),
              "oracle_profile": oracle.profile_metadata(profile(args.midgame_depth)) if args.kind == "oracle" else None,
              "settings": {"opening_depth": 12, "midgame_depth": args.midgame_depth,
                           "endgame_depth": 12, "exact_empty": 16, "timeout_seconds": args.timeout_seconds,
                           "exact_cache_scope": args.cache_scope,
                           "max_decisions": args.max_decisions, "max_rss_kib": args.max_rss_kib,
                           "process_lifetime": ("all-games-per-seat" if args.kind == "cli-persistent"
                                                else "one-game-per-seat")},
              "environment": {"host": platform.node(), "cpu_model": platform.processor(),
                              "os": platform.platform(), "measurement": "linux-wait4"},
              "games": games, "aggregate": totals(games), "process_totals": process_totals}
    report["report_digest"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def max_observed_rss(processes: dict, record: dict) -> int:
    peaks = [p["peak_rss_kib"] for p in processes.values()]
    for step in record["steps"]:
        raw = step.get("resource_observations", {})
        peaks.extend(v["peak_rss_kib"] for v in raw.values())
        if "resources" in step:
            peaks.append(step["resources"]["peak_rss_kib"])
    return max(peaks)


def verify_game(record: dict, row: dict, assignment: int, kind: str, settings: dict,
                require_decision_resources: bool = False) -> None:
    validate_game(record, row, assignment)
    require(record.get("search_count") == (sum(step["move"] != "pass" for step in record["steps"])
            if kind in ("oracle", "cli-legacy") else len(record["steps"])), "search count mismatch")
    resources, processes = record.get("resources"), record.get("seat_processes")
    require(isinstance(processes, dict) and set(processes) == {"B", "W"}, "missing seat process data")
    for seat in processes.values():
        require(all(type(seat.get(key)) is int and seat[key] >= (1 if key == "peak_rss_kib" or
                    (kind != "cli-persistent" and key in ("startup_ns", "shutdown_ns")) else 0)
                    for key in ("startup_ns", "shutdown_ns", "user_cpu_ns", "system_cpu_ns", "peak_rss_kib")),
                "missing process CPU/RSS/startup/shutdown")
    decision_fields = {"legal_move_count", "phase", "resources", "resource_observations"}
    if require_decision_resources:
        require(all(decision_fields.issubset(step) for step in record["steps"]),
                "complete decision resources required")
    expected = {"user_cpu_ns": sum(seat["user_cpu_ns"] for seat in processes.values()),
                "system_cpu_ns": sum(seat["system_cpu_ns"] for seat in processes.values()),
                "peak_rss_kib": max_observed_rss(processes, record)}
    require(resources == expected and resources["peak_rss_kib"] <= settings["max_rss_kib"],
            "game resource totals mismatch")
    for step in record["steps"]:
        if any(key in step for key in decision_fields):
            require(type(step.get("legal_move_count")) is int and step.get("legal_move_count") == len(oracle.legal_moves(step["board"], step["side"]))
                    and step.get("phase") == decision_phase(step["board"], settings["exact_empty"]),
                    "decision phase or legal move count mismatch")
            usage = step.get("resources")
            require(isinstance(usage, dict) and set(usage) == {"user_cpu_ns", "system_cpu_ns", "peak_rss_kib"}
                    and all(type(usage[key]) is int and usage[key] >= (1 if key == "peak_rss_kib" else 0)
                            for key in usage)
                    and usage["peak_rss_kib"] <= settings["max_rss_kib"],
                    "decision resources invalid")
            if "resource_observations" in step:
                observations = step["resource_observations"]
                require(isinstance(observations, dict) and set(observations) in (
                            {"before", "after"}, {"before", "after", "peak"}),
                        "decision observations missing")
                for raw in observations.values():
                    require(isinstance(raw, dict) and set(raw) == set(usage)
                            and all(type(raw[key]) is int and raw[key] >= (1 if key == "peak_rss_kib" else 0)
                                    for key in raw)
                            and raw["peak_rss_kib"] <= settings["max_rss_kib"], "decision observations invalid")
                before, after = observations["before"], observations["after"]
                require(all(after[key] >= before[key] for key in ("user_cpu_ns", "system_cpu_ns"))
                        and max(before["peak_rss_kib"], after["peak_rss_kib"]) <= settings["max_rss_kib"]
                        and usage == {"user_cpu_ns": after["user_cpu_ns"] - before["user_cpu_ns"],
                                      "system_cpu_ns": after["system_cpu_ns"] - before["system_cpu_ns"],
                                      "peak_rss_kib": after["peak_rss_kib"]},
                        "decision resources do not match observations")
                if "peak" in observations:
                    peak = observations["peak"]
                    require(all(before[key] <= peak[key] <= after[key]
                                for key in ("user_cpu_ns", "system_cpu_ns")),
                            "decision peak CPU outside observations")
    for side in ("B", "W"):
        for key in ("user_cpu_ns", "system_cpu_ns"):
            observed = sum(step.get("resources", {}).get(key, 0) for step in record["steps"] if step["seat"] == side)
            require(observed <= processes[side][key], "decision CPU exceeds process total")
    if kind in ("cli", "cli-persistent"):
        cache = {"probes": 0, "hits": 0, "stores": 0}
        for step in record["steps"]:
            sample = step.get("search")
            validate_cli_diagnostic(step, sample, settings["midgame_depth"], settings["exact_empty"],
                                    settings.get("opening_depth", 12), settings.get("endgame_depth", 12),
                                    settings.get("search_time_limit_ms"), settings.get("node_limit"))
            for key in cache:
                cache[key] += sample[f"cache_{key}"]
        require(record.get("cache") == cache, "cache totals mismatch")
    else:
        require(record.get("cache") is None and all("search" not in step for step in record["steps"]),
                "legacy/oracle workload has unexpected diagnostics")


def verify_v1(report: dict, binary: Path | None = None, artifact: Path | None = None) -> None:
    _verify_complete(report, binary, artifact)


def efficiency_performance_gate(games: list[dict]) -> dict:
    require(len(games) == 3, "efficiency sample requires exactly three completed games")
    total_wall_ns = sum(record["wall_ns"] for record in games)
    mean_wall_ns = total_wall_ns / len(games)
    max_game_ns = max(record["wall_ns"] for record in games)
    return {"game_count": len(games), "max_game_target_ns": 300_000_000_000,
            "mean_game_target_ns": 180_000_000_000, "max_game_ns": max_game_ns,
            "mean_game_ns": mean_wall_ns,
            "max_game_within_target": max_game_ns <= 300_000_000_000,
            "mean_within_target": mean_wall_ns <= 180_000_000_000}


def _verify_complete(report: dict, binary: Path | None = None, artifact: Path | None = None,
                     allowed_exact: tuple[int, ...] = (16,),
                     require_decision_resources: bool = False) -> None:
    require(report.get("schema_version") == 1 and report.get("runner_version") == VERSION,
            "unsupported whole-game report")
    saved = report.get("report_digest")
    require(saved == hashlib.sha256(canonical({k: v for k, v in report.items() if k != "report_digest"})).hexdigest(),
            "report digest mismatch")
    require(report.get("openings_sha256") == digest(OPENINGS), "opening corpus digest mismatch")
    kind = report.get("kind")
    require(kind in ("oracle", "cli", "cli-persistent", "cli-legacy"), "invalid workload kind")
    require((report.get("artifact") is None if kind == "oracle" else report.get("artifact") is not None),
            "artifact workload identity mismatch")
    if binary:
        require(digest(binary) == report["binary"]["sha256"], "binary digest mismatch")
    if artifact:
        require(report.get("artifact") is not None and digest(artifact) == report["artifact"]["sha256"],
                "artifact digest mismatch")
    settings = report.get("settings")
    require(isinstance(settings, dict)
            and all(type(settings.get(key, default)) is int and 1 <= settings.get(key, default) <= 64
                    for key, default in (("opening_depth", 12), ("midgame_depth", 12),
                                         ("endgame_depth", 12)))
            and settings.get("exact_empty") in allowed_exact
            and (settings.get("node_limit") is None or type(settings.get("node_limit")) is int
                 and settings["node_limit"] > 0)
            and (settings.get("search_time_limit_ms") is None
                 or type(settings.get("search_time_limit_ms")) is int
                 and settings["search_time_limit_ms"] > 0)
            and settings.get("exact_cache_scope") in ("game", "turn")
            and settings.get("process_lifetime") == ("all-games-per-seat" if kind == "cli-persistent"
                                                     else "one-game-per-seat"), "search settings mismatch")
    if kind == "oracle":
        require(settings.get("opening_depth", 12) == 12 and settings.get("endgame_depth", 12) == 12,
                "unsupported Oracle phase profile")
    sample = settings.get("game_sample", "full8")
    rows = measurement_rows(sample)
    game_limit = settings.get("game_time_limit_seconds")
    require(game_limit is None or type(game_limit) in (int, float) and game_limit > 0,
            "invalid whole-game wall limit")
    if sample == "efficiency3":
        require(kind == "cli-persistent" and settings.get("opening_depth") == 8
                and settings.get("midgame_depth") == 8 and settings.get("endgame_depth") == 8
                and settings.get("exact_empty") == 16 and settings.get("exact_cache_scope") == "turn"
                and type(settings.get("search_time_limit_ms")) is int
                and settings["search_time_limit_ms"] > 0
                and type(settings.get("node_limit")) is int and settings["node_limit"] > 0
                and game_limit == 300, "invalid TrainedEvaluator efficiency sample settings")
    elif game_limit is not None:
        require(game_limit > 0, "invalid whole-game wall limit")
    expected_oracle_profile = (oracle.profile_metadata(profile(settings["midgame_depth"], settings["exact_empty"]))
                               if kind == "oracle" else None)
    require(report.get("oracle_profile") == expected_oracle_profile, "oracle profile mismatch")
    require(report.get("environment", {}).get("measurement") == "linux-wait4", "missing CPU/RSS method")
    games = report.get("games")
    require(isinstance(games, list) and len(games) == len(rows), "incomplete whole-game sample")
    for index, (row, assignment) in enumerate(rows):
        record = games[index]
        verify_game(record, row, assignment, kind, settings, require_decision_resources)
        require(game_limit is None or record["wall_ns"] <= game_limit * 1_000_000_000,
                "game exceeded configured wall limit")
    require(report.get("aggregate") == totals(games), "whole-game aggregate mismatch")
    expected_gate = (efficiency_performance_gate(games) if sample == "efficiency3" else None)
    require(report.get("performance_gate") == expected_gate, "whole-game performance gate mismatch")
    if kind == "cli-persistent":
        process_totals = report.get("process_totals")
        require(isinstance(process_totals, dict) and set(process_totals) == {"B", "W"},
                "persistent process totals missing")
        for side in ("B", "W"):
            item = process_totals[side]
            require(all(type(item.get(key)) is int and item[key] > 0 for key in
                        ("startup_ns", "shutdown_ns", "peak_rss_kib")), "persistent lifecycle missing")
            require(item["user_cpu_ns"] >= sum(game["seat_processes"][side]["user_cpu_ns"] for game in games)
                    and item["system_cpu_ns"] >= sum(game["seat_processes"][side]["system_cpu_ns"] for game in games),
                    "persistent CPU totals mismatch")
    else:
        require(report.get("process_totals") is None, "unexpected persistent totals")


def comparison(baseline: dict, candidate: dict) -> dict:
    verify(baseline)
    verify(candidate)
    require(baseline["kind"] == candidate["kind"] == "cli", "compare one-game CLI workloads")
    require(baseline["settings"]["exact_cache_scope"] == "turn"
            and candidate["settings"]["exact_cache_scope"] == "game", "compare turn and game cache scopes")
    for key in ("binary", "artifact", "environment", "openings_sha256"):
        require(baseline[key] == candidate[key], f"comparison {key} mismatch")
    require({key: value for key, value in baseline["settings"].items() if key != "exact_cache_scope"}
            == {key: value for key, value in candidate["settings"].items() if key != "exact_cache_scope"},
            "comparison search or resource settings mismatch")
    positions = 0
    for old_game, new_game in zip(baseline["games"], candidate["games"]):
        require(len(old_game["steps"]) == len(new_game["steps"]), "game decision count changed")
        for old_step, new_step in zip(old_game["steps"], new_game["steps"]):
            for key in ("board", "side", "move"):
                require(old_step[key] == new_step[key], f"semantic {key} mismatch")
            for key in ("score", "completed_depth", "exact", "outcome"):
                require(old_step["search"][key] == new_step["search"][key],
                        f"semantic {key} mismatch")
            positions += 1
    old, new = baseline["aggregate"], candidate["aggregate"]
    old_cpu = old["user_cpu_ns"] + old["system_cpu_ns"]
    new_cpu = new["user_cpu_ns"] + new["system_cpu_ns"]
    require(old["wall_ns"] > 0 and old_cpu > 0 and new_cpu > 0, "wall/CPU evidence missing")
    result = {"schema_version": 2, "score_contract": SCORE_CONTRACT, "runner_version": VERSION,
              "baseline_report_digest": baseline["report_digest"],
              "candidate_report_digest": candidate["report_digest"],
              "semantic_positions": positions,
              "wall_ratio": new["wall_ns"] / old["wall_ns"],
              "cpu_ratio": new_cpu / old_cpu,
              "baseline_peak_rss_kib": old["peak_rss_kib"],
              "candidate_peak_rss_kib": new["peak_rss_kib"],
              "baseline_nodes": sum(step["search"]["nodes"] for game in baseline["games"] for step in game["steps"]),
              "candidate_nodes": sum(step["search"]["nodes"] for game in candidate["games"] for step in game["steps"]),
              "baseline_cache": {key: old[f"cache_{key}"] for key in ("probes", "hits", "stores")},
              "candidate_cache": {key: new[f"cache_{key}"] for key in ("probes", "hits", "stores")}}
    result["report_digest"] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def oracle_evidence(report: dict, binary: Path, cwd: Path, timeout: float, progress_enabled: bool = True) -> dict:
    """Human-operated independent solve of each exact decision and selected move."""
    verify(report)
    require(report["kind"] in ("cli", "cli-persistent"), "oracle check requires a diagnostic CLI report")
    require(binary.is_file() and timeout > 0, "oracle binary or timeout invalid")
    selected_profile = profile(report["settings"]["midgame_depth"], report["settings"]["exact_empty"])
    cached: dict[tuple[str, str, str], tuple[int, int]] = {}
    rows = []
    started = time.monotonic()
    exact_steps = [step for game in report["games"] for step in game["steps"] if step["search"]["exact"]]
    for index, step in enumerate(exact_steps, 1):
        board, side, move = step["board"], step["side"], step["move"]
        key = board, side, move
        if key not in cached:
            effective_side, root_sign = oracle.effective_query(board, side)
            root = oracle.run_solve([(board, effective_side)], binary, cwd, selected_profile,
                                    timeout, child_query=False)[0]
            require(root["exact"], f"oracle root was incomplete at {step['id']}")
            root_score = root_sign * int(root["value"])
            if move == "pass":
                selected_score = root_score
            else:
                child = oracle.apply_move(board, side, move)
                if not oracle.legal_moves(child, oracle.other(side)) and not oracle.legal_moves(child, side):
                    selected_score = oracle.terminal_score(child, side)
                else:
                    child_side, child_sign = oracle.effective_query(child, oracle.other(side))
                    continuation = oracle.run_solve([(child, child_side)], binary, cwd,
                                                    selected_profile, timeout, child_query=True)[0]
                    require(continuation["exact"], f"oracle continuation was incomplete at {step['id']}")
                    selected_score = -child_sign * int(continuation["value"])
            cached[key] = root_score, selected_score
        root_score, selected_score = cached[key]
        require(step["search"]["score"] == root_score == selected_score,
                f"oracle exact score or selected move mismatch at {step['id']}")
        rows.append({"id": step["id"], "board": board, "side": side, "move": move,
                     "cli_score": step["search"]["score"], "oracle_score": root_score,
                     "selected_score": selected_score})
        if progress_enabled:
            print(f"progress whole-game-oracle-check {index}/{len(exact_steps)} "
                  f"position={step['id']} elapsed={time.monotonic() - started:.1f}s",
                  file=sys.stderr, flush=True)
    result = {"schema_version": 2, "score_contract": SCORE_CONTRACT, "runner_version": VERSION,
              "cli_report_digest": report["report_digest"],
              "oracle_binary_sha256": digest(binary),
              "oracle_profile": oracle.profile_metadata(selected_profile),
              "positions": rows}
    result["report_digest"] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def verify_oracle_evidence(report: dict, evidence: dict, binary: Path | None = None) -> None:
    verify(report)
    require(report["kind"] in ("cli", "cli-persistent"), "oracle evidence requires diagnostic CLI report")
    require(evidence.get("schema_version") == 2 and evidence.get("score_contract") == SCORE_CONTRACT
            and evidence.get("runner_version") == VERSION
            and evidence.get("cli_report_digest") == report["report_digest"],
            "oracle evidence identity mismatch")
    require(evidence.get("report_digest") == hashlib.sha256(canonical(
        {key: value for key, value in evidence.items() if key != "report_digest"})).hexdigest(),
        "oracle evidence digest mismatch")
    if binary:
        require(digest(binary) == evidence.get("oracle_binary_sha256"), "oracle binary digest mismatch")
    require(isinstance(evidence.get("oracle_binary_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", evidence["oracle_binary_sha256"]) is not None,
            "oracle binary digest missing")
    require(evidence.get("oracle_profile") == oracle.profile_metadata(profile(report["settings"]["midgame_depth"], report["settings"]["exact_empty"])),
            "oracle evidence profile mismatch")
    steps = [step for game in report["games"] for step in game["steps"] if step.get("search", {}).get("exact")]
    rows = evidence.get("positions")
    require(isinstance(rows, list) and len(rows) == len(steps), "oracle evidence position count mismatch")
    for step, row in zip(steps, rows):
        require(row == {"id": step["id"], "board": step["board"], "side": step["side"],
                        "move": step["move"], "cli_score": step["search"]["score"],
                        "oracle_score": step["search"]["score"],
                        "selected_score": step["search"]["score"]},
                "oracle evidence score or position mismatch")


RESUMABLE_VERSION = VERSION


def sealed(value: dict, key: str = "report_digest") -> dict:
    value = {name: item for name, item in value.items() if name != key}
    value[key] = hashlib.sha256(canonical(value)).hexdigest()
    return value


def read_canonical(path: Path) -> dict:
    raw = path.read_bytes()
    value = json.loads(raw)
    require(isinstance(value, dict) and raw == canonical(value), "noncanonical JSON")
    return value


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".unfinished-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def exclusive_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BenchmarkError("measurement already locked") from exc
        yield


def progress(stage: str, condition: str, done: int, total: int, games: int,
             status: str, started: float, every: int = 1, game_total: int = 8) -> None:
    if status in ("saved", "measuring") and games % every:
        return
    print(f"progress whole-game stage={stage} condition={condition} conditions={done}/{total} "
          f"games={games}/{game_total} status={status} elapsed_s={time.monotonic()-started:.3f}",
          file=sys.stderr, flush=True)


def verify(report: dict, binary: Path | None = None, artifact: Path | None = None, *, legacy_offline: bool = False) -> None:
    require(isinstance(report, dict), "whole-game report must be an object")
    if legacy_offline:
        from legacy_offline import whole_game_report
        whole_game_report(report, binary, artifact)
        return
    require(report.get("score_contract") == SCORE_CONTRACT, "whole-game score contract mismatch; old reports require --legacy-offline")
    require(report.get("kind") in ("oracle", "cli", "cli-persistent"), "new whole-game report cannot claim legacy CLI semantics")
    require(report.get("schema_version") == 3, "unsupported whole-game report")
    if "identity" not in report:
        require(report == sealed(report), "report digest mismatch")
        compatible = sealed({**report, "schema_version": 1})
        _verify_complete(compatible, binary, artifact)
        return
    require(report.get("schema_version") == 3 and report.get("runner_version") == RESUMABLE_VERSION,
            "unsupported whole-game report")
    require(report.get("report_digest") == sealed(report)["report_digest"], "report digest mismatch")
    require(report.get("resource_scopes") == {
        "aggregate": "completed-game-checkpoints",
        "segment_aggregate": "seat-process-segments" if report["kind"] == "cli-persistent" else None},
        "resource scope mismatch")
    require(report.get("segment_aggregate") == segment_totals(report.get("segments", [])),
            "segment aggregate mismatch")
    identity = report.get("identity")
    require(isinstance(identity, dict) and report.get("condition_digest") == hashlib.sha256(canonical(identity)).hexdigest(),
            "condition identity mismatch")
    require(identity.get("score_contract") == SCORE_CONTRACT, "condition score contract mismatch")
    require(identity.get("cache_lifetime") == "one-game" and identity.get("reset_protocol") == (
            "gtp-clear-board" if report["kind"] == "oracle" else "new_game-v1"),
            "game cache/reset identity missing")
    require(re.fullmatch(r"[0-9a-f]{64}", report.get("manifest_digest", "")) is not None,
            "manifest identity missing")
    require(identity["settings"] == report["settings"] and identity["binary"] == report["binary"]
            and identity["artifact"] == report["artifact"] and identity["kind"] == report["kind"]
            and identity["host"] == report["environment"]["host"]
            and identity["openings_sha256"] == report["openings_sha256"], "report identity fields mismatch")
    require(report["settings"].get("process_lifetime") == (
        "segments-per-seat" if report["kind"] == "cli-persistent" else "one-game-per-seat"),
        "resumable process lifetime mismatch")
    require(report["kind"] == "cli-persistent" or report.get("segments") == [],
            "unexpected one-game process segments")
    # The v1 verifier remains the common independent legal-game/resource validator.
    compatible = dict(report)
    compatible["schema_version"] = 1
    compatible["runner_version"] = VERSION
    compatible["settings"] = dict(report["settings"])
    if report["kind"] == "cli-persistent":
        compatible["settings"]["process_lifetime"] = "all-games-per-seat"
        segments = report.get("segments")
        require(isinstance(segments, list) and segments, "persistent segments missing")
        for segment in segments:
            verify_segment_receipt(segment, report["settings"]["max_rss_kib"])
        by_id = {segment["segment_id"]: segment for segment in segments}
        require(len(by_id) == len(segments), "duplicate segment identity")
        totals_by_side = {}
        for side in ("B", "W"):
            items = [segment["process_totals"][side] for segment in segments]
            totals_by_side[side] = {key: (max(item[key] for item in items) if key == "peak_rss_kib"
                                        else sum(item[key] for item in items))
                                    for key in ("startup_ns", "shutdown_ns", "user_cpu_ns", "system_cpu_ns", "peak_rss_kib")}
        totals_by_side["B"]["shutdown_ns"] = max(1, totals_by_side["B"]["shutdown_ns"])
        totals_by_side["W"]["shutdown_ns"] = max(1, totals_by_side["W"]["shutdown_ns"])
        compatible["process_totals"] = totals_by_side
        for game_record in report["games"]:
            require(game_record["segment_id"] in by_id, "game segment missing")
            segment = by_id[game_record["segment_id"]]
            require(segment.get("report_digest") == sealed(segment)["report_digest"], "segment digest mismatch")
            require(segment.get("condition_digest") == report["condition_digest"]
                    and segment.get("manifest_digest") == report["manifest_digest"], "segment measurement identity mismatch")
            require(segment["session_id"] == game_record["session_id"], "segment session mismatch")
            require(segment["rss_scope"] == "segment-cumulative", "RSS scope mismatch")
            require(segment["status"] in ("closed", "process-lost"), "segment closure missing")
            require(segment.get("resource_observation") == ("wait4" if segment["status"] == "closed" else "proc-checkpoint"),
                    "segment resource observation mismatch")
            for usage in segment["process_totals"].values():
                require(type(usage.get("shutdown_ns")) is int and usage["shutdown_ns"] >= 0,
                        "segment shutdown invalid")
                require(usage["shutdown_ns"] > 0 if segment["status"] == "closed" else usage["shutdown_ns"] == 0,
                        "unobserved shutdown claimed")
            # Game VmHWM and segment wait4 peaks are independently capped;
            # neither observation is an upper bound for the other.
            for side in ("B", "W"):
                members = [item for item in report["games"] if item["segment_id"] == segment["segment_id"]]
                for key in ("user_cpu_ns", "system_cpu_ns"):
                    require(sum(item["seat_processes"][side][key] for item in members)
                            <= segment["process_totals"][side][key], "segment CPU mismatch")
    compatible = sealed(compatible)
    _verify_complete(compatible, binary, artifact, (16, 20, 24), require_decision_resources=True)
    for record in report["games"]:
        verify_boundary(record, report["kind"])
        require(type(record.get("started_at_ns")) is int and type(record.get("ended_at_ns")) is int
                and 0 < record["started_at_ns"] <= record["ended_at_ns"], "game lifecycle timestamps missing")
        require(record.get("condition_digest") == report["condition_digest"]
                and record.get("manifest_digest") == report["manifest_digest"], "game measurement identity mismatch")
        require(isinstance(record.get("session_id"), str) and isinstance(record.get("segment_id"), str),
                "game lifecycle identity missing")


def verify_boundary(record: dict, kind: str) -> None:
    require(type(record.get("started_at_ns")) is int and type(record.get("ended_at_ns")) is int
            and 0 < record["started_at_ns"] <= record["ended_at_ns"], "game lifecycle timestamps missing")
    events = record.get("reset_events")
    require(isinstance(events, dict) and set(events) == {"B", "W"}, "game reset events missing")
    for event in events.values():
        require(event.get("game_id") == f"{record['opening_id']}-seat{record['assignment']}"
                and event.get("acknowledged") is True and type(event.get("elapsed_ns")) is int
                and event["elapsed_ns"] >= 0
                and event.get("protocol") == ("gtp-clear-board" if kind == "oracle" else "new_game-v1"),
                "game reset acknowledgement mismatch")


def segment_totals(segments: list[dict]) -> dict | None:
    if not segments:
        return None
    usages = [usage for segment in segments for usage in segment["process_totals"].values()]
    return {"user_cpu_ns": sum(usage["user_cpu_ns"] for usage in usages),
            "system_cpu_ns": sum(usage["system_cpu_ns"] for usage in usages),
            "peak_rss_kib": max(usage["peak_rss_kib"] for usage in usages),
            "complete_process_observations": all(segment["status"] == "closed" for segment in segments)}


def verify_segment_receipt(segment: dict, max_rss_kib: int) -> None:
    require(segment.get("report_digest") == sealed(segment)["report_digest"], "segment digest mismatch")
    require(segment.get("status") in ("live", "closed", "process-lost")
            and segment.get("resource_observation") == ("wait4" if segment["status"] == "closed" else "proc-checkpoint")
            and segment.get("rss_scope") == "segment-cumulative", "segment observation invalid")
    require(isinstance(segment.get("segment_id"), str) and isinstance(segment.get("session_id"), str),
            "segment lifecycle identity missing")
    usages = segment.get("process_totals")
    require(isinstance(usages, dict) and set(usages) == {"B", "W"}, "segment seats missing")
    for usage in usages.values():
        require(all(type(usage.get(key)) is int and usage[key] >= 0
                    for key in ("startup_ns", "shutdown_ns", "user_cpu_ns", "system_cpu_ns", "peak_rss_kib"))
                and usage["startup_ns"] > 0 and 0 < usage["peak_rss_kib"] <= max_rss_kib,
                "segment resources invalid")
        require(type(usage.get("started_at_ns")) is int and usage["started_at_ns"] > 0,
                "segment startup timestamp missing")
        if segment["status"] == "closed":
            require(usage["shutdown_ns"] > 0 and type(usage.get("ended_at_ns")) is int
                    and usage["ended_at_ns"] >= usage["started_at_ns"], "segment shutdown timestamp missing")
        else:
            require(usage["shutdown_ns"] == 0 and usage.get("ended_at_ns") is None,
                    "unobserved shutdown claimed")


def require_execution_scope(kind: str, scope: str) -> None:
    require(kind == "oracle" or scope == "turn",
            "CLI game exact-cache scope is suspended until correctness repair (0044); use turn")


def measurement_identity(args) -> dict:
    require(args.kind in ("oracle", "cli", "cli-persistent"), "legacy CLI cannot measure reset conditions")
    require(getattr(args, "exact_empty", 16) in (16, 20, 24), "unsupported exact threshold")
    node_limit = getattr(args, "node_limit", None)
    require(node_limit is None or type(node_limit) is int and node_limit > 0, "invalid node limit")
    search_time_limit_ms = getattr(args, "search_time_limit_ms", None)
    require(search_time_limit_ms is None or type(search_time_limit_ms) is int and search_time_limit_ms > 0,
            "invalid search time limit")
    require(args.kind != "oracle" or args.cache_scope == "game", "Oracle has no CLI turn cache scope")
    opening_depth = getattr(args, "opening_depth", 12)
    endgame_depth = getattr(args, "endgame_depth", 12)
    require(all(type(depth) is int and 1 <= depth <= 64
                for depth in (opening_depth, args.midgame_depth, endgame_depth)), "invalid phase depth")
    game_sample = getattr(args, "game_sample", "full8")
    game_time_limit = getattr(args, "game_time_limit_seconds", None)
    rows = measurement_rows(game_sample)
    require(game_time_limit is None or isinstance(game_time_limit, (int, float))
            and game_time_limit > 0, "invalid whole-game wall limit")
    if args.kind == "oracle":
        require(opening_depth == 12 and endgame_depth == 12, "unsupported Oracle phase profile")
    if game_sample == "efficiency3":
        require(args.kind == "cli-persistent" and args.artifact is not None and args.artifact.is_file()
                and (opening_depth, args.midgame_depth, endgame_depth) == (8, 8, 8)
                and getattr(args, "exact_empty", 16) == 16 and args.cache_scope == "turn"
                and game_time_limit == 300 and len(rows) == 3
                and search_time_limit_ms is not None and node_limit is not None
                and args.timeout_seconds > search_time_limit_ms / 1000,
                "TrainedEvaluator efficiency sample requires 8/8/8 exact16 turn, fixed 3 games, "
                "a 300s game cap, and explicit production search limits")
    return {"score_contract": SCORE_CONTRACT, "kind": args.kind, "binary": {"path": str(args.binary.resolve()), "sha256": digest(args.binary)},
            "artifact": ({"path": str(args.artifact.resolve()), "sha256": digest(args.artifact)} if args.artifact else None),
            "openings_sha256": digest(OPENINGS), "source_revision": getattr(args, "source_revision", None),
            "host": platform.node(), "cache_lifetime": "one-game",
            "reset_protocol": "gtp-clear-board" if args.kind == "oracle" else "new_game-v1",
            "settings": {"opening_depth": opening_depth, "midgame_depth": args.midgame_depth,
                         "endgame_depth": endgame_depth,
                         "exact_empty": getattr(args, "exact_empty", 16), "timeout_seconds": args.timeout_seconds,
                         "search_time_limit_ms": search_time_limit_ms, "node_limit": node_limit,
                         "exact_cache_scope": args.cache_scope, "max_decisions": args.max_decisions,
                         "max_rss_kib": args.max_rss_kib,
                         "process_lifetime": "segments-per-seat" if args.kind == "cli-persistent" else "one-game-per-seat",
                         "game_sample": game_sample, "game_time_limit_seconds": game_time_limit}}


def measure_resumable(args, manifest_digest: str, condition_id: str, checkpoint_dir: Path,
                      conditions_done: int = 0, conditions_total: int = 1) -> dict:
    require_execution_scope(args.kind, args.cache_scope)
    started = time.monotonic()
    every = getattr(args, "progress_every", 1)
    require(type(every) is int and every > 0, "progress interval invalid")
    require(sys.platform == "linux" and args.timeout_seconds > 1 and args.max_rss_kib > 0
            and args.max_decisions >= 120, "invalid resource measurement settings")
    identity = measurement_identity(args)
    condition_digest = hashlib.sha256(canonical(identity)).hexdigest()
    rows = measurement_rows(identity["settings"]["game_sample"])
    game_total = len(rows)
    progress("inputs", condition_id, conditions_done, conditions_total, 0, "verified", started,
             game_total=game_total)
    with exclusive_lock(checkpoint_dir):
        if args.output.exists():
            report = read_canonical(args.output)
            verify(report, args.binary, args.artifact)
            require(report.get("identity") == identity and report.get("manifest_digest") == manifest_digest
                    and report.get("condition_id") == condition_id,
                    "completed report manifest identity mismatch")
            progress("verify", condition_id, conditions_done+1, conditions_total, game_total,
                     "skipped", started, game_total=game_total)
            return report
        games = {}
        known = {f"{row['id']}-seat{assignment}" for row, assignment in rows}
        for path in checkpoint_dir.iterdir():
            require(path.name == ".lock" or path.name.startswith(".unfinished-")
                    or path.name.startswith("game-") and path.suffix == ".json"
                    or path.name.startswith("failure-") and path.suffix == ".json"
                    or path.name.startswith("segment-") and path.suffix == ".json",
                    "unknown checkpoint file")
        for path in checkpoint_dir.glob("failure-*.json"):
            failure = read_canonical(path)
            game_id = failure.get("game_id")
            require(failure.get("report_digest") == sealed(failure)["report_digest"]
                    and game_id in known and path.name == f"failure-{game_id}.json"
                    and failure.get("condition_digest") == condition_digest
                    and failure.get("manifest_digest") == manifest_digest
                    and failure.get("status") == "wall-limit-exceeded"
                    and type(failure.get("elapsed_ns")) is int and failure["elapsed_ns"] > 0,
                    "invalid failed-game checkpoint")
            raise BenchmarkError(f"game {game_id} previously exceeded its wall limit; use a new measurement identity")
        prior_segments = {}
        for path in checkpoint_dir.glob("segment-*.json"):
            segment = read_canonical(path)
            verify_segment_receipt(segment, args.max_rss_kib)
            require(segment.get("report_digest") == sealed(segment)["report_digest"]
                    and segment.get("condition_digest") == condition_digest
                    and segment.get("manifest_digest") == manifest_digest, "segment identity mismatch")
            require(path.name == f"segment-{segment['segment_id']}.json"
                    and segment["segment_id"] not in prior_segments, "duplicate segment identity")
            require(segment.get("status") in ("live", "closed")
                    and segment.get("resource_observation") == ("wait4" if segment["status"] == "closed" else "proc-checkpoint"),
                    "segment observation invalid")
            prior_segments[segment["segment_id"]] = segment
        for path in checkpoint_dir.glob("game-*.json"):
            item = read_canonical(path)
            require(item.get("report_digest") == sealed(item)["report_digest"], "checkpoint digest mismatch")
            key = item.get("game_id")
            require(key in known and key not in games and path.name == f"game-{key}.json", "duplicate/unknown checkpoint game")
            require(item.get("condition_digest") == condition_digest and item.get("manifest_digest") == manifest_digest,
                    "checkpoint measurement identity mismatch")
            record = item["game"]
            row, assignment = next(pair for pair in rows if f"{pair[0]['id']}-seat{pair[1]}" == key)
            verify_game(record, row, assignment, args.kind, identity["settings"], require_decision_resources=True)
            require(identity["settings"]["game_time_limit_seconds"] is None
                    or record["wall_ns"] <= identity["settings"]["game_time_limit_seconds"] * 1_000_000_000,
                    "checkpoint game exceeded configured wall limit")
            verify_boundary(record, args.kind)
            require(record.get("condition_digest") == condition_digest and record.get("manifest_digest") == manifest_digest
                    and isinstance(record.get("session_id"), str) and isinstance(record.get("segment_id"), str),
                    "checkpoint lifecycle identity mismatch")
            if args.kind == "cli-persistent":
                require(record["segment_id"] in prior_segments, "checkpoint segment missing")
                segment = prior_segments[record["segment_id"]]
                require(segment.get("session_id") == record["session_id"], "checkpoint segment session mismatch")
                # Both receipts were independently checked against the RSS cap.
                # A later proc sample or final wait4 peak may be lower.
            games[key] = record
        session_id = uuid.uuid4().hex
        segment_id = uuid.uuid4().hex
        segment_path = checkpoint_dir / f"segment-{segment_id}.json"
        segments = []
        seats = {}
        active_game_key = None
        active_game_started_ns = None
        old_handler = signal.getsignal(signal.SIGTERM)
        def interrupted(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupted)
        try:
            for row, assignment in rows:
                key = f"{row['id']}-seat{assignment}"
                if key in games:
                    continue
                active_game_key = key
                active_game_started_ns = None
                progress("measure", condition_id, conditions_done, conditions_total, len(games),
                         "measuring", started, every, game_total)
                if not seats:
                    for side in ("B", "W"):
                        seats[side] = Seat("cli" if args.kind == "cli-persistent" else args.kind,
                                           args.binary, args.artifact, args.midgame_depth, args.timeout_seconds,
                                           side, getattr(args, "oracle_cwd", None), args.cache_scope,
                                           getattr(args, "exact_empty", 16), getattr(args, "node_limit", None),
                                           args.max_rss_kib, opening_depth=identity["settings"]["opening_depth"],
                                           endgame_depth=identity["settings"]["endgame_depth"],
                                           search_time_limit_ms=identity["settings"]["search_time_limit_ms"])
                game_started_at_ns = time.time_ns()
                game_started_monotonic_ns = time.monotonic_ns()
                active_game_started_ns = game_started_monotonic_ns
                configured_game_limit = identity["settings"]["game_time_limit_seconds"]
                game_deadline = (time.monotonic() + configured_game_limit
                                 if configured_game_limit is not None else None)
                before = {side: proc_usage(seat.process.pid) for side, seat in seats.items()}
                events = {side: seat.new_game(key, game_deadline) for side, seat in seats.items()}
                remaining_game_limit = (None if game_deadline is None
                                        else game_deadline - time.monotonic())
                require(remaining_game_limit is None or remaining_game_limit > 0,
                        f"whole-game wall limit exceeded during reset at {key}")
                record = game(row, assignment, seats, "cli" if args.kind == "cli-persistent" else args.kind,
                              args.timeout_seconds, args.max_decisions,
                              remaining_game_limit)
                if args.kind == "cli-persistent":
                    after = {side: proc_usage(seat.process.pid) for side, seat in seats.items()}
                    usages = {side: {"startup_ns": 0, "shutdown_ns": 0,
                                     "user_cpu_ns": after[side]["user_cpu_ns"]-before[side]["user_cpu_ns"],
                                     "system_cpu_ns": after[side]["system_cpu_ns"]-before[side]["system_cpu_ns"],
                                     "peak_rss_kib": after[side]["peak_rss_kib"]} for side in ("B", "W")}
                    for seat in seats.values():
                        seat.collect_diagnostics()
                else:
                    usages = {side: seat.close() for side, seat in seats.items()}
                attach_diagnostics(record, seats, args.kind)
                record.update({"seat_processes": usages,
                               "resources": {"user_cpu_ns": sum(item["user_cpu_ns"] for item in usages.values()),
                                             "system_cpu_ns": sum(item["system_cpu_ns"] for item in usages.values()),
                                             "peak_rss_kib": max_observed_rss(usages, record)},
                               "reset_events": events, "session_id": session_id, "segment_id": segment_id,
                               "started_at_ns": game_started_at_ns, "ended_at_ns": time.time_ns(),
                               "manifest_digest": manifest_digest, "condition_digest": condition_digest})
                verify_game(record, row, assignment, args.kind, identity["settings"], require_decision_resources=True)
                verify_boundary(record, args.kind)
                record["wall_ns"] += sum(event["elapsed_ns"] for event in events.values())
                require(identity["settings"]["game_time_limit_seconds"] is None
                        or record["wall_ns"] <= identity["settings"]["game_time_limit_seconds"] * 1_000_000_000,
                        f"whole-game wall limit exceeded at {key}")
                if args.kind == "cli-persistent":
                    # A live segment receipt survives SIGKILL; final wait4 reconciliation supersedes it.
                    atomic_write(segment_path, sealed({"segment_id": segment_id, "session_id": session_id,
                        "condition_digest": condition_digest, "manifest_digest": manifest_digest,
                        "status": "live", "resource_observation": "proc-checkpoint", "rss_scope": "segment-cumulative",
                        "process_totals": {side: {**after[side], "startup_ns": seats[side].startup_ns,
                                                   "shutdown_ns": 0, "started_at_ns": seats[side].started_at_ns,
                                                   "ended_at_ns": None} for side in ("B", "W")}}))
                atomic_write(checkpoint_dir / f"game-{key}.json", sealed({"game_id": key,
                    "condition_digest": condition_digest, "manifest_digest": manifest_digest, "game": record}))
                games[key] = record
                progress("measure", condition_id, conditions_done, conditions_total, len(games), "saved", started, every)
                if args.kind != "cli-persistent":
                    seats = {}
            if seats:
                process_totals = {side: seat.close() for side, seat in seats.items()}
                atomic_write(segment_path, sealed({"segment_id": segment_id, "session_id": session_id,
                    "condition_digest": condition_digest, "manifest_digest": manifest_digest,
                    "status": "closed", "resource_observation": "wait4", "rss_scope": "segment-cumulative", "process_totals": process_totals}))
                seats = {}
        except BaseException as exc:
            if (isinstance(exc, BenchmarkError) and "whole-game wall limit exceeded" in str(exc)
                    and active_game_key is not None and active_game_started_ns is not None):
                atomic_write(checkpoint_dir / f"failure-{active_game_key}.json", sealed({
                    "game_id": active_game_key, "condition_digest": condition_digest,
                    "manifest_digest": manifest_digest, "status": "wall-limit-exceeded",
                    "elapsed_ns": time.monotonic_ns() - active_game_started_ns,
                    "limit_seconds": identity["settings"]["game_time_limit_seconds"],
                    "reason": str(exc)}))
            if seats and args.kind == "cli-persistent":
                # On orderly interrupt, close idle or working seats with a bounded exit before aborting.
                interrupted_usages = {side: seat.abort() for side, seat in seats.items()}
                if segment_path.exists() and all(item is not None for item in interrupted_usages.values()):
                    atomic_write(segment_path, sealed({"segment_id": segment_id, "session_id": session_id,
                        "condition_digest": condition_digest, "manifest_digest": manifest_digest,
                        "status": "closed", "shutdown_reason": "interrupted", "resource_observation": "wait4",
                        "rss_scope": "segment-cumulative", "process_totals": interrupted_usages}))
                seats = {}
            progress("measure", condition_id, conditions_done, conditions_total, len(games),
                     "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", started,
                     game_total=game_total)
            raise
        finally:
            signal.signal(signal.SIGTERM, old_handler)
            for seat in seats.values():
                seat.abort()
        if args.kind == "cli-persistent":
            for path in checkpoint_dir.glob("segment-*.json"):
                segment = read_canonical(path)
                require(segment.get("report_digest") == sealed(segment)["report_digest"]
                        and segment.get("condition_digest") == condition_digest
                        and segment.get("manifest_digest") == manifest_digest, "segment identity mismatch")
                if any(record["segment_id"] == segment["segment_id"] for record in games.values()):
                    segments.append(segment)
            # A killed process has no wait4 receipt in the resumed parent. Keep checkpoint cumulative
            # CPU/RSS and explicitly classify this segment as process-lost rather than claiming closure.
            for segment in segments:
                if segment["status"] == "live":
                    segment["status"] = "process-lost"
                    segment["resource_observation"] = "proc-checkpoint"
                segment.update(sealed(segment))
        progress("aggregate", condition_id, conditions_done, conditions_total, game_total,
                 "measuring", started, game_total=game_total)
        ordered = [games[f"{row['id']}-seat{assignment}"] for row, assignment in rows]
        report = sealed({"schema_version": 3, "score_contract": SCORE_CONTRACT, "runner_version": RESUMABLE_VERSION,
            "kind": args.kind, "binary": identity["binary"], "artifact": identity["artifact"],
            "openings_sha256": identity["openings_sha256"], "identity": identity,
            "condition_id": condition_id, "condition_digest": condition_digest, "manifest_digest": manifest_digest,
            "settings": identity["settings"], "environment": {"host": platform.node(), "cpu_model": platform.processor(),
                "os": platform.platform(), "measurement": "linux-wait4"},
            "oracle_profile": oracle.profile_metadata(profile(args.midgame_depth, getattr(args, "exact_empty", 16))) if args.kind == "oracle" else None,
            "games": ordered, "aggregate": totals(ordered), "process_totals": None, "segments": segments,
            "performance_gate": (efficiency_performance_gate(ordered)
                                 if identity["settings"]["game_sample"] == "efficiency3" else None),
            "segment_aggregate": segment_totals(segments),
            "resource_scopes": {"aggregate": "completed-game-checkpoints",
                                "segment_aggregate": "seat-process-segments" if args.kind == "cli-persistent" else None}})
        verify(report, args.binary, args.artifact)
        atomic_write(args.output, report)
        progress("verify", condition_id, conditions_done+1, conditions_total, game_total,
                 "verified", started, game_total=game_total)
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    measure = sub.add_parser("measure")
    measure.add_argument("--kind", choices=("oracle", "cli", "cli-persistent"), required=True)
    measure.add_argument("--binary", type=Path, required=True)
    measure.add_argument("--artifact", type=Path)
    measure.add_argument("--oracle-cwd", type=Path)
    measure.add_argument("--opening-depth", type=int, default=12)
    measure.add_argument("--midgame-depth", type=int, choices=(8, 12), required=True)
    measure.add_argument("--endgame-depth", type=int, default=12)
    measure.add_argument("--exact-empty", type=int, choices=(16, 20, 24), default=16)
    measure.add_argument("--cache-scope", choices=("game", "turn"),
                         help="CLI defaults to turn; Oracle uses game")
    measure.add_argument("--timeout-seconds", type=float, default=310)
    measure.add_argument("--search-time-limit-ms", type=int)
    measure.add_argument("--node-limit", type=int)
    measure.add_argument("--max-rss-kib", type=int, required=True)
    measure.add_argument("--max-decisions", type=int, default=120)
    measure.add_argument("--game-sample", choices=("full8", "efficiency3"), default="full8")
    measure.add_argument("--game-time-limit-seconds", type=float)
    measure.add_argument("--output", type=Path, required=True)
    measure.add_argument("--checkpoint-dir", type=Path)
    measure.add_argument("--progress-every", type=int, default=1)
    measure.add_argument("--source-revision")
    check = sub.add_parser("verify")
    check.add_argument("--legacy-offline", action="store_true")
    check.add_argument("--report", type=Path, required=True)
    check.add_argument("--binary", type=Path)
    check.add_argument("--artifact", type=Path)
    for name in ("compare", "verify-comparison"):
        operation = sub.add_parser(name)
        operation.add_argument("--baseline-report", type=Path, required=True)
        operation.add_argument("--candidate-report", type=Path, required=True)
        operation.add_argument("--output", type=Path, required=True)
    for name in ("oracle-check", "verify-oracle-check"):
        operation = sub.add_parser(name)
        operation.add_argument("--report", type=Path, required=True)
        if name == "verify-oracle-check":
            operation.add_argument("--legacy-offline", action="store_true")
        operation.add_argument("--oracle-binary", type=Path)
        operation.add_argument("--oracle-cwd", type=Path)
        operation.add_argument("--timeout-seconds", type=float, default=310)
        operation.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "measure":
            if args.cache_scope is None:
                args.cache_scope = "game" if args.kind == "oracle" else "turn"
            identity = measurement_identity(args)
            measure_resumable(args, hashlib.sha256(canonical(identity)).hexdigest(),
                              args.output.stem, args.checkpoint_dir or Path(str(args.output)+".checkpoints"))
        elif args.command == "verify":
            raw = args.report.read_bytes()
            decoded = json.loads(raw)
            require(raw == canonical(decoded), "report must be canonical JSON")
            verify(decoded, args.binary, args.artifact, legacy_offline=args.legacy_offline)
        elif args.command in ("compare", "verify-comparison"):
            baseline_raw = args.baseline_report.read_bytes()
            candidate_raw = args.candidate_report.read_bytes()
            baseline = json.loads(baseline_raw)
            candidate = json.loads(candidate_raw)
            require(baseline_raw == canonical(baseline) and candidate_raw == canonical(candidate),
                    "comparison inputs must be canonical JSON")
            result = comparison(baseline, candidate)
            if args.command == "compare":
                require(not args.output.exists(), "comparison output already exists")
                args.output.write_bytes(canonical(result))
            else:
                require(args.output.read_bytes() == canonical(result), "comparison report mismatch")
        else:
            raw = args.report.read_bytes()
            decoded = json.loads(raw)
            require(raw == canonical(decoded), "CLI report must be canonical JSON")
            if args.command == "oracle-check":
                require(args.oracle_binary is not None and not args.output.exists(),
                        "oracle binary required and output must be new")
                result = oracle_evidence(decoded, args.oracle_binary,
                                         args.oracle_cwd or args.oracle_binary.parent,
                                         args.timeout_seconds)
                args.output.write_bytes(canonical(result))
            else:
                evidence_raw = args.output.read_bytes()
                evidence = json.loads(evidence_raw)
                require(evidence_raw == canonical(evidence), "oracle evidence must be canonical JSON")
                if args.legacy_offline:
                    from legacy_offline import whole_game_report
                    whole_game_report(decoded, evidence=evidence, oracle_binary=args.oracle_binary)
                else:
                    verify_oracle_evidence(decoded, evidence, args.oracle_binary)
    except (BenchmarkError, oracle.OracleError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"whole-game benchmark error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
