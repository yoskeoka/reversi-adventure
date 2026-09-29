#!/usr/bin/env python3
"""Human-operated, serial whole-game self-play measurement and offline verifier."""

from __future__ import annotations

import argparse
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

VERSION = "reversi-ai-whole-game-v1"
OPENINGS = Path(__file__).with_name("whole-game-openings-v1.json")
DIAGNOSTIC = re.compile(
    r"search_diagnostic_v1\tposition_id=([^\t]+)\telapsed_us=(\d+)\tnodes=(\d+)"
    r"\texact=(true|false)\tscore=(-?\d+|none)\tcompleted_depth=(\d+)"
    r"\toutcome=(move|pass|game_over)\tcache_probes=(\d+)\tcache_hits=(\d+)\tcache_stores=(\d+)"
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


def profile(midgame_depth: int) -> oracle.OracleProfile:
    return oracle.profile_from_name(f"whole-game-depth-{midgame_depth}-exact-16")


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
                 cache_scope: str = "game"):
        self.kind, self.timeout, self.label, self.depth = kind, timeout, label, depth
        self.stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        started = time.monotonic_ns()
        if kind == "oracle":
            self.gtp = oracle.GtpSession(binary, cwd or binary.parent, profile(depth), timeout)
            self.process = self.gtp.process
            self.buffer = bytearray()
        else:
            require(artifact is not None, "CLI requires a trained artifact")
            argv = [str(binary), "--evaluator", "trained", "--trained-artifact", str(artifact),
                    "--opening-depth", "12", "--midgame-depth", str(depth),
                    "--endgame-depth", "12", "--exact-solver-empty-squares", "16",
                    "--time-limit-ms", str(int(timeout * 1000) - 1000)]
            if kind != "cli-legacy":
                argv.extend(["--exact-cache-scope", cache_scope])
            self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=self.stderr, bufsize=0)
            self.gtp = None
            self.buffer = bytearray()
        self.startup_ns = time.monotonic_ns() - started
        self.diagnostics: dict[str, dict] = {}

    def gtp_command(self, command: str) -> list[str]:
        require(self.gtp is not None, "GTP command sent to CLI")
        return self.gtp.command(command)

    def choose(self, identifier: str, board: str, side: str) -> tuple[str, int]:
        started = time.monotonic_ns()
        if self.gtp:
            command = f"genmove {'black' if side == 'B' else 'white'}"
            move = oracle.gtp_move_from_response(self.gtp.command(command), command)
        else:
            assert self.process.stdin and self.process.stdout
            self.process.stdin.write(f"{identifier}\t{board}\t{side}\n".encode("ascii"))
            self.process.stdin.flush()
            deadline = time.monotonic() + self.timeout
            while b"\n" not in self.buffer:
                remaining = deadline - time.monotonic()
                require(remaining > 0, f"CLI timed out at {identifier}")
                ready, _, _ = select.select([self.process.stdout], [], [], remaining)
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
        self.stderr.seek(0)
        for line in self.stderr.read().splitlines():
            match = DIAGNOSTIC.fullmatch(line)
            if match:
                identifier, elapsed, nodes, exact, score, completed_depth, outcome, probes, hits, stores = match.groups()
                require(identifier not in self.diagnostics, "duplicate CLI diagnostic id")
                self.diagnostics[identifier] = {
                    "elapsed_us": int(elapsed), "nodes": int(nodes), "exact": exact == "true",
                    "score": None if score == "none" else int(score),
                    "completed_depth": int(completed_depth), "outcome": outcome,
                    "cache_probes": int(probes), "cache_hits": int(hits), "cache_stores": int(stores),
                }
        self.stderr.close()
        return {"startup_ns": self.startup_ns, "shutdown_ns": shutdown_ns, **usage}

    def abort(self) -> None:
        if self.process.returncode is None:
            self.process.kill()
            try:
                os.wait4(self.process.pid, 0)
            except ChildProcessError:
                pass
        self.stderr.close()


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
         timeout: float, max_decisions: int) -> dict:
    board, side = row["board"], row["side"]
    if kind == "oracle":
        replay_opening_on_oracle(seats, row["moves"])
    steps = []
    started = time.monotonic_ns()
    for turn in range(max_decisions):
        legal = oracle.legal_moves(board, side)
        if not legal and not oracle.legal_moves(board, oracle.other(side)):
            break
        seat_label = side if assignment == 0 else oracle.other(side)
        identifier = f"{row['id']}-seat{assignment}-turn{turn}"
        if legal or kind != "oracle":
            move, elapsed = seats[seat_label].choose(identifier, board, side)
        else:
            move, elapsed = "pass", 0
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


def validate_cli_diagnostic(step: dict, sample: dict, midgame_depth: int) -> None:
    require(isinstance(sample, dict) and type(sample.get("exact")) is bool
            and sample.get("outcome") in ("move", "pass", "game_over")
            and all(type(sample.get(key)) is int and sample[key] >= 0
                    for key in ("elapsed_us", "nodes", "completed_depth",
                                "cache_probes", "cache_hits", "cache_stores")),
            "CLI search diagnostic missing")
    occupied = 64 - step["board"].count(".")
    exact = occupied >= 48
    forced_pass = step["move"] == "pass"
    if exact:
        expected_depth = 64 - occupied
    elif forced_pass:
        expected_depth = 0
    else:
        expected_depth = 12 if occupied <= 20 or occupied >= 45 else midgame_depth
    expected_score = int if exact or not forced_pass else type(None)
    require(type(sample.get("score")) is expected_score
            and sample["completed_depth"] == expected_depth
            and sample["exact"] == exact
            and sample["outcome"] == ("pass" if forced_pass else "move"),
            "incomplete or inconsistent CLI search")


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
            validate_cli_diagnostic(step, diagnostic, seats[step["seat"]].depth)
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
                                       "peak_rss_kib": max(item["peak_rss_kib"] for item in usages.values())}
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
                               "peak_rss_kib": max(item["peak_rss_kib"] for item in usages.values())}
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
    report = {"schema_version": 1, "runner_version": VERSION, "kind": args.kind,
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


def verify(report: dict, binary: Path | None = None, artifact: Path | None = None) -> None:
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
    require(isinstance(settings, dict) and settings.get("opening_depth") == 12
            and settings.get("midgame_depth") in (8, 12) and settings.get("endgame_depth") == 12
            and settings.get("exact_empty") == 16
            and settings.get("exact_cache_scope") in ("game", "turn")
            and settings.get("process_lifetime") == ("all-games-per-seat" if kind == "cli-persistent"
                                                     else "one-game-per-seat"), "search settings mismatch")
    expected_oracle_profile = (oracle.profile_metadata(profile(settings["midgame_depth"]))
                               if kind == "oracle" else None)
    require(report.get("oracle_profile") == expected_oracle_profile, "oracle profile mismatch")
    require(report.get("environment", {}).get("measurement") == "linux-wait4", "missing CPU/RSS method")
    games = report.get("games")
    require(isinstance(games, list) and len(games) == 8, "incomplete eight-game sample")
    for index, (row, assignment) in enumerate((row, assignment) for row in opening_rows()
                                              for assignment in (0, 1)):
        record = games[index]
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
        expected = {"user_cpu_ns": sum(seat["user_cpu_ns"] for seat in processes.values()),
                    "system_cpu_ns": sum(seat["system_cpu_ns"] for seat in processes.values()),
                    "peak_rss_kib": max(seat["peak_rss_kib"] for seat in processes.values())}
        require(resources == expected and resources["peak_rss_kib"] <= settings["max_rss_kib"],
                "game resource totals mismatch")
        if kind in ("cli", "cli-persistent"):
            cache = {"probes": 0, "hits": 0, "stores": 0}
            for step in record["steps"]:
                sample = step.get("search")
                validate_cli_diagnostic(step, sample, settings["midgame_depth"])
                for key in cache:
                    cache[key] += sample[f"cache_{key}"]
            require(record.get("cache") == cache, "cache totals mismatch")
        else:
            require(record.get("cache") is None and all("search" not in step for step in record["steps"]),
                    "legacy/oracle workload has unexpected diagnostics")
    require(report.get("aggregate") == totals(games), "whole-game aggregate mismatch")
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
    result = {"schema_version": 1, "runner_version": VERSION,
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


def oracle_evidence(report: dict, binary: Path, cwd: Path, timeout: float) -> dict:
    """Human-operated independent solve of each exact decision and selected move."""
    verify(report)
    require(report["kind"] in ("cli", "cli-persistent"), "oracle check requires a diagnostic CLI report")
    require(binary.is_file() and timeout > 0, "oracle binary or timeout invalid")
    selected_profile = profile(report["settings"]["midgame_depth"])
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
                    selected_score = child.count(side) - child.count(oracle.other(side))
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
        print(f"progress whole-game-oracle-check {index}/{len(exact_steps)} "
              f"position={step['id']} elapsed={time.monotonic() - started:.1f}s",
              file=sys.stderr, flush=True)
    result = {"schema_version": 1, "runner_version": VERSION,
              "cli_report_digest": report["report_digest"],
              "oracle_binary_sha256": digest(binary),
              "oracle_profile": oracle.profile_metadata(selected_profile),
              "positions": rows}
    result["report_digest"] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def verify_oracle_evidence(report: dict, evidence: dict, binary: Path | None = None) -> None:
    verify(report)
    require(report["kind"] in ("cli", "cli-persistent"), "oracle evidence requires diagnostic CLI report")
    require(evidence.get("schema_version") == 1 and evidence.get("runner_version") == VERSION
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
    require(evidence.get("oracle_profile") == oracle.profile_metadata(profile(report["settings"]["midgame_depth"])),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    measure = sub.add_parser("measure")
    measure.add_argument("--kind", choices=("oracle", "cli", "cli-persistent", "cli-legacy"), required=True)
    measure.add_argument("--binary", type=Path, required=True)
    measure.add_argument("--artifact", type=Path)
    measure.add_argument("--oracle-cwd", type=Path)
    measure.add_argument("--midgame-depth", type=int, choices=(8, 12), required=True)
    measure.add_argument("--cache-scope", choices=("game", "turn"), default="game")
    measure.add_argument("--timeout-seconds", type=float, default=310)
    measure.add_argument("--max-rss-kib", type=int, required=True)
    measure.add_argument("--max-decisions", type=int, default=120)
    measure.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("verify")
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
        operation.add_argument("--oracle-binary", type=Path)
        operation.add_argument("--oracle-cwd", type=Path)
        operation.add_argument("--timeout-seconds", type=float, default=310)
        operation.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "measure":
            require(not args.output.exists(), "output already exists")
            result = run(args)
            verify(result, args.binary, args.artifact)
            args.output.write_bytes(canonical(result))
        elif args.command == "verify":
            raw = args.report.read_bytes()
            decoded = json.loads(raw)
            require(raw == canonical(decoded), "report must be canonical JSON")
            verify(decoded, args.binary, args.artifact)
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
                verify_oracle_evidence(decoded, evidence, args.oracle_binary)
    except (BenchmarkError, oracle.OracleError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"whole-game benchmark error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
