#!/usr/bin/env python3
"""Run or verify one frozen, bounded, project-owned pattern self-play cycle."""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import re
import select
import shlex
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import training

VERSION = "reversi-ai-pattern-reinforcement-v2"
PAIRING = "color_swap_d4_v1"
OUTPUTS = ("candidate-artifact.json", "selected-artifact.json", "games.jsonl", "checkpoint.json", "report.json")


def positive_interval(value: str) -> int:
    try:
        interval = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if interval < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return interval


class Progress:
    def __init__(self, interval: int):
        if interval < 1:
            fail("progress interval must be a positive integer")
        self.interval = interval
        self.started = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def stage_start(self, name: str) -> float:
        print(f"stage {name} start elapsed={self.elapsed():.1f}s", file=sys.stderr, flush=True)
        return time.monotonic()

    def stage_done(self, name: str, started: float) -> None:
        print(f"stage {name} done stage={time.monotonic() - started:.1f}s elapsed={self.elapsed():.1f}s", file=sys.stderr, flush=True)

    def game(self, pair: int, member: int, completed: int, total: int, started: float) -> None:
        if completed % self.interval == 0 or completed == total:
            print(f"progress self-play pair={pair} member={member} {completed}/{total} game={time.monotonic() - started:.1f}s elapsed={self.elapsed():.1f}s", file=sys.stderr, flush=True)
INITIAL = "...........................WB......BW..........................."
HEX = re.compile(r"[0-9a-f]{64}\Z")
MOVE = re.compile(r"[a-h][1-8]\Z")
DIRECTIONS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1),
              (1, -1), (1, 0), (1, 1))


def fail(message: str) -> None:
    raise training.TrainingError(message)


def require_keys(value: object, keys: set[str], name: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        fail(f"{name} must contain exactly {sorted(keys)}")
    return value


def sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        fail(f"cannot read {path}: {error}")


def checked_file(root: Path, entry: dict, name: str) -> Path:
    require_keys(entry, {"path", "sha256"}, name)
    if not isinstance(entry["path"], str) or not entry["path"] or not isinstance(entry["sha256"], str) or not HEX.fullmatch(entry["sha256"]):
        fail(f"{name} path or digest is invalid")
    path = (root / entry["path"]).resolve()
    if not path.is_file() or sha(path) != entry["sha256"]:
        fail(f"{name} digest mismatch")
    return path


def other(side: str) -> str:
    return "W" if side == "B" else "B"


def legal_moves(board: str, side: str) -> list[str]:
    moves = []
    for index, cell in enumerate(board):
        if cell != ".":
            continue
        row, col = divmod(index, 8)
        for dr, dc in DIRECTIONS:
            r, c = row + dr, col + dc
            seen = False
            while 0 <= r < 8 and 0 <= c < 8 and board[r * 8 + c] == other(side):
                seen = True
                r, c = r + dr, c + dc
            if seen and 0 <= r < 8 and 0 <= c < 8 and board[r * 8 + c] == side:
                moves.append(f"{chr(97 + col)}{row + 1}")
                break
    return moves


def apply_move(board: str, side: str, move: str) -> str:
    if not MOVE.fullmatch(move) or move not in legal_moves(board, side):
        fail(f"illegal {side} move {move!r}")
    row, col = int(move[1]) - 1, ord(move[0]) - 97
    cells = list(board)
    cells[row * 8 + col] = side
    for dr, dc in DIRECTIONS:
        r, c = row + dr, col + dc
        line = []
        while 0 <= r < 8 and 0 <= c < 8 and cells[r * 8 + c] == other(side):
            line.append(r * 8 + c)
            r, c = r + dr, c + dc
        if line and 0 <= r < 8 and 0 <= c < 8 and cells[r * 8 + c] == side:
            for index in line:
                cells[index] = side
    return "".join(cells)


def rotated_pair(board: str, side: str, symmetry: int) -> tuple[str, str]:
    transformed = ["."] * 64
    for index, cell in enumerate(board):
        transformed[training.transform(index, symmetry)] = other(cell) if cell != "." else "."
    return "".join(transformed), other(side)


def openings(seed: int, count: int, plies: int) -> list[tuple[str, str, list[str], int]]:
    rng = random.Random(seed)
    result = []
    for pair in range(count // 2):
        board, side, moves = INITIAL, "B", []
        for _ in range(plies):
            legal = legal_moves(board, side)
            if not legal:
                side = other(side)
                legal = legal_moves(board, side)
            if not legal:
                fail("opening ended before requested plies")
            move = legal[rng.randrange(len(legal))]
            board = apply_move(board, side, move)
            moves.append(move)
            side = other(side)
        rotation = (pair + 1) % 8
        result.append((board, side, moves, rotation))
    return result


def validate_manifest(path: Path) -> tuple[dict, Path, Path, Path]:
    manifest = training.read_json(path)
    require_keys(manifest, {"schema_version", "producer_version", "baseline_artifact", "candidate", "seed", "game_count", "opening_plies", "pairing", "decision_timeout_seconds", "max_decisions", "update_rule", "validation", "match"}, "manifest")
    if manifest["schema_version"] != 2 or manifest["producer_version"] != VERSION:
        fail("unsupported reinforcement manifest")
    root = path.parent
    baseline_entry = require_keys(manifest["baseline_artifact"], {"path", "sha256", "artifact_digest"}, "baseline_artifact")
    baseline = checked_file(root, {key: baseline_entry[key] for key in ("path", "sha256")}, "baseline artifact")
    artifact = training.read_json(baseline)
    training.validate_artifact(artifact)
    if artifact["artifact_digest"] != baseline_entry["artifact_digest"]:
        fail("baseline artifact identity mismatch")
    candidate = require_keys(manifest["candidate"], {"path", "sha256", "evaluator", "profile", "opening_depth", "midgame_depth", "endgame_depth", "exact_solver_empty_squares", "time_limit_ms", "node_limit", "book"}, "candidate")
    executable = checked_file(root, {key: candidate[key] for key in ("path", "sha256")}, "candidate executable")
    if candidate["evaluator"] != "trained" or candidate["profile"] != "strong-engine-hcap-v1" or candidate["book"] != "off":
        fail("candidate must use trained strong-engine profile with book off")
    for key in ("opening_depth", "midgame_depth", "endgame_depth"):
        if training.require_int(candidate[key], key, 1, 64) != 12:
            fail("strong-engine-hcap-v1 requires 12/12/12 search depths")
    if training.require_int(candidate["exact_solver_empty_squares"], "exact threshold", 0, 16) != 16:
        fail("strong-engine-hcap-v1 requires exact threshold 16")
    training.require_int(candidate["time_limit_ms"], "time limit", 1)
    training.require_int(candidate["node_limit"], "node limit", 1)
    training.require_int(manifest["seed"], "seed", 0, 2**64 - 1)
    games = training.require_int(manifest["game_count"], "game_count", 2)
    if games % 2 or games > 256:
        fail("game_count must be even and at most 256")
    training.require_int(manifest["opening_plies"], "opening_plies", 1, 20)
    timeout = training.require_int(manifest["decision_timeout_seconds"], "decision_timeout_seconds", 1, 3600)
    if timeout * 1000 <= candidate["time_limit_ms"]:
        fail("decision timeout must exceed candidate time limit")
    training.require_int(manifest["max_decisions"], "max_decisions", 1, 256 * 120)
    if manifest["pairing"] != PAIRING or manifest["update_rule"] != {"name": "bounded_td_v1", "normalization_divisor": 64}:
        fail("unsupported pairing or update rule")
    match = require_keys(manifest["match"], {"first_pairs", "continuation_pairs", "max_opening_attempts"}, "match")
    if training.require_int(match["first_pairs"], "first match pairs", 1) != 25 or training.require_int(match["continuation_pairs"], "continuation match pairs", 0) != 75:
        fail("match requires 25 initial and 75 continuation pairs")
    training.require_int(match["max_opening_attempts"], "match opening attempts", 25)
    validation_entry = require_keys(manifest["validation"], {"path", "sha256", "source"}, "validation")
    if not isinstance(validation_entry["source"], str) or not validation_entry["source"]:
        fail("validation source must be named")
    validation = checked_file(root, {key: validation_entry[key] for key in ("path", "sha256")}, "validation input")
    return manifest, baseline, executable, validation


class Candidate:
    def __init__(self, executable: Path, artifact: Path, config: dict, timeout: int):
        argv = [str(executable), "--evaluator", "trained", "--trained-artifact", str(artifact),
                "--opening-depth", str(config["opening_depth"]), "--midgame-depth", str(config["midgame_depth"]),
                "--endgame-depth", str(config["endgame_depth"]),
                "--exact-solver-empty-squares", str(config["exact_solver_empty_squares"]),
                "--time-limit-ms", str(config["time_limit_ms"]),
                "--node-limit", str(config["node_limit"])]
        try:
            self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        except OSError as error:
            fail(f"cannot start candidate executable: {error}")
        self.timeout = timeout
        self.buffer = bytearray()

    def choose(self, identifier: str, board: str, side: str) -> str:
        assert self.process.stdin and self.process.stdout
        try:
            self.process.stdin.write(f"{identifier}\t{board}\t{side}\n".encode("ascii"))
            self.process.stdin.flush()
            deadline = time.monotonic() + self.timeout
            while b"\n" not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    fail(f"candidate timed out at {identifier}")
                ready, _, _ = select.select([self.process.stdout], [], [], remaining)
                if not ready:
                    fail(f"candidate timed out at {identifier}")
                chunk = os.read(self.process.stdout.fileno(), 4096)
                if not chunk:
                    fail(f"candidate exited before answering {identifier}")
                self.buffer.extend(chunk)
                if len(self.buffer) > 4096:
                    fail(f"candidate response too long at {identifier}")
            line, _, remainder = self.buffer.partition(b"\n")
            self.buffer = bytearray(remainder)
            answer = (line + b"\n").decode("ascii")
        except (BrokenPipeError, OSError) as error:
            fail(f"candidate failed at {identifier}: {error}")
        except UnicodeDecodeError:
            fail(f"candidate response is not ASCII at {identifier}")
        if not answer or answer.count("\t") != 1 or not answer.endswith("\n"):
            fail(f"candidate response malformed at {identifier}")
        response_id, move = answer.rstrip("\n").split("\t")
        if response_id != identifier or (move != "pass" and not MOVE.fullmatch(move)):
            fail(f"candidate response malformed at {identifier}")
        return move

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.communicate()


def play(kind: str, pair: int, member: int, board: str, side: str, opening: list[str], rotation: int,
         players: dict[str, Candidate], sides: dict[str, str], remaining: list[int]) -> dict:
    start_board, start_side = board, side
    decisions = []
    for turn in range(121):
        legal = legal_moves(board, side)
        if not legal and not legal_moves(board, other(side)):
            break
        if remaining[0] == 0:
            fail("maximum decision count exceeded")
        remaining[0] -= 1
        player = sides[side]
        identifier = f"{kind}-p{pair}-m{member}-t{turn}"
        move = players[player].choose(identifier, board, side) if legal else "pass"
        if legal and move not in legal or not legal and move != "pass":
            fail(f"illegal candidate response at {identifier}: {move}")
        decisions.append({"id": identifier, "board": board, "side": side, "move": move})
        if legal:
            board = apply_move(board, side, move)
        side = other(side)
    else:
        fail("game exceeded 120 turns")
    counts = {"B": board.count("B"), "W": board.count("W")}
    game = {"kind": kind, "pair": pair, "member": member, "players": sides, "opening": opening, "rotation": rotation,
            "start_board": start_board, "start_side": start_side, "decisions": decisions,
            "terminal_board": board, "disc_counts": counts, "final_score_black": counts["B"] - counts["W"], "failure": None}
    game["game_digest"] = training.digest(game)
    return game


def replay(game: dict) -> list[dict]:
    expected = dict(game)
    actual = expected.pop("game_digest", None)
    if actual != training.digest(expected):
        fail("game digest mismatch")
    board, side = game["start_board"], game["start_side"]
    tuning = []
    for decision in game["decisions"]:
        if decision["board"] != board or decision["side"] != side:
            fail("game decision state mismatch")
        legal = legal_moves(board, side)
        move = decision["move"]
        if legal:
            board = apply_move(board, side, move)
        elif move != "pass" or not legal_moves(board, other(side)):
            fail("invalid pass")
        tuning.append({"board": decision["board"], "side": side,
                       "target": game["final_score_black"] if side == "B" else -game["final_score_black"]})
        side = other(side)
    if legal_moves(board, side) or legal_moves(board, other(side)) or board != game["terminal_board"]:
        fail("game terminal state mismatch")
    if game["disc_counts"] != {"B": board.count("B"), "W": board.count("W")} or game["final_score_black"] != board.count("B") - board.count("W"):
        fail("terminal score mismatch")
    return tuning


def validate_positions(path: Path, tuning: list[dict], source: str) -> tuple[list[dict], list[str]]:
    records = training.read_jsonl(path)
    if not records:
        fail("validation input is empty")
    seen = {training.canonical_position_key(row["board"], row["side"]) for row in tuning}
    validated, excluded = [], []
    for row in records:
        if row.get("schema_version") != 1 or row.get("split") != "validation" or not isinstance(row.get("record_id"), str):
            fail("validation record schema or split mismatch")
        if row.get("source") != source or not isinstance(row.get("license"), str) or not row["license"] or not isinstance(row.get("source_digest"), str) or not row["source_digest"]:
            fail("validation record provenance mismatch")
        board, side, target = training.parse_position(row, f"validation {row['record_id']}")
        key = training.canonical_position_key(board, side)
        if key in seen:
            excluded.append(row["record_id"])
            continue
        seen.add(key)
        validated.append({"id": row["record_id"], "board": board, "side": side, "target": target})
    return validated, sorted(excluded)


def validation_keys(rows: list[dict]) -> list[str]:
    return sorted(training.canonical_position_key(row["board"], row["side"]) for row in rows)


def updated_artifact(baseline: dict, tuning: list[dict], manifest: dict) -> dict:
    sums = defaultdict(lambda: [0, 0])
    base = baseline["weights"]
    for row in tuning:
        prediction = training.predict(base, row["board"], row["side"])
        phase, values = training.extract_features(row["board"], row["side"])
        for feature, code in enumerate(values):
            bucket = sums[(phase, feature, code)]
            bucket[0] += row["target"] - prediction
            bucket[1] += 1
    weights = {phase: [dict(table) for table in tables] for phase, tables in base.items()}
    for (phase, feature, code), (total, count) in sorted(sums.items()):
        table = weights.setdefault(str(phase), [{} for _ in range(training.FEATURE_COUNT)])[feature]
        value = max(-1, min(1, table.get(str(code), 0) + training.round_division(total, count * 64)))
        if value:
            table[str(code)] = value
        else:
            table.pop(str(code), None)
    weights = {phase: tables for phase, tables in weights.items() if any(tables)}
    bounds = [max((abs(value) for tables in weights.values() for value in tables[feature].values()), default=0)
              for feature in range(training.FEATURE_COUNT)]
    artifact = {"format_version": 1, "feature_contract": baseline["feature_contract"],
                "provenance": {"trainer_version": VERSION, "input_manifest_digest": training.digest(manifest),
                               "seed": manifest["seed"], "optimizer": manifest["update_rule"],
                               "licenses": baseline["provenance"]["licenses"]},
                "feature_max_abs": bounds, "weights": weights, "weight_digest": training.digest(weights)}
    artifact["artifact_digest"] = training.digest(artifact)
    return artifact


def mse(artifact: dict, rows: list[dict]) -> dict:
    if not rows:
        return {"records": 0, "status": "unavailable"}
    errors = [training.predict(artifact["weights"], row["board"], row["side"]) - row["target"] for row in rows]
    return {"records": len(rows), "status": "available", "sum_squared_error": sum(error * error for error in errors),
            "mean_squared_error": sum(error * error for error in errors) / len(rows)}


def output_bytes(artifact: dict, selected: dict, games: list[dict], checkpoint: dict, report: dict) -> dict[str, bytes]:
    return {"candidate-artifact.json": training.canonical_json(artifact) + b"\n",
            "selected-artifact.json": training.canonical_json(selected) + b"\n",
            "games.jsonl": b"".join(training.canonical_json(game) + b"\n" for game in games),
            "checkpoint.json": training.canonical_json(checkpoint) + b"\n",
            "report.json": training.canonical_json(report) + b"\n"}


def match_summary(games: list[dict]) -> dict:
    wins = losses = draws = 0
    for game in games:
        score = game["final_score_black"] * (1 if game["players"]["B"] == "candidate" else -1)
        if score > 0:
            wins += 1
        elif score < 0:
            losses += 1
        else:
            draws += 1
    return {"games": len(games), "wins": wins, "losses": losses, "draws": draws,
            "match_points": wins + draws * 0.5}


def selected_from_match(summary: dict, continued: bool) -> str:
    return "candidate" if continued and summary["match_points"] > 100 else "baseline"


def match_openings(manifest: dict, tuning: list[dict]) -> tuple[list[tuple[str, str, list[str], int]], int, int]:
    needed = manifest["match"]["first_pairs"] + manifest["match"]["continuation_pairs"]
    attempts = manifest["match"]["max_opening_attempts"]
    forbidden = {training.canonical_position_key(row["board"], row["side"]) for row in tuning}
    pool, excluded = [], 0
    # This stream is deliberately independent of self-play. Recorded openings,
    # not seed regeneration, are verifier input.
    for opening in openings(manifest["seed"] ^ 0x9E3779B97F4A7C15, attempts * 2, manifest["opening_plies"]):
        if training.canonical_position_key(opening[0], opening[1]) in forbidden:
            excluded += 1
        else:
            pool.append(opening)
        if len(pool) == needed:
            return pool, attempts, excluded
    fail("match opening pool could not provide complete disjoint pairs")


def atomic_write(directory: Path, name: str, data: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix=f".{name}.", delete=False) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, directory / name)


def cycle(manifest_path: Path, progress: Progress | None = None, checkpoint_callback=None) -> dict[str, bytes]:
    manifest, baseline_path, executable, validation_path = validate_manifest(manifest_path)
    progress = progress or Progress(1)
    baseline = training.read_json(baseline_path)
    generated = openings(manifest["seed"], manifest["game_count"], manifest["opening_plies"])
    games = []
    remaining = [manifest["max_decisions"]]
    candidate = Candidate(executable, baseline_path, manifest["candidate"], manifest["decision_timeout_seconds"])
    stage = progress.stage_start("self-play")
    try:
        for pair, (board, side, opening, rotation) in enumerate(generated):
            game_started = time.monotonic()
            games.append(play("self-play", pair, 0, board, side, opening, 0, {"baseline": candidate}, {"B": "baseline", "W": "baseline"}, remaining))
            progress.game(pair, 0, len(games), manifest["game_count"], game_started)
            paired_board, paired_side = rotated_pair(board, side, rotation)
            game_started = time.monotonic()
            games.append(play("self-play", pair, 1, paired_board, paired_side, opening, rotation, {"baseline": candidate}, {"B": "baseline", "W": "baseline"}, remaining))
            progress.game(pair, 1, len(games), manifest["game_count"], game_started)
    finally:
        candidate.close()
    progress.stage_done("self-play", stage)
    stage = progress.stage_start("replay-tuning-extraction")
    tuning = [row for game in games for row in replay(game)]
    progress.stage_done("replay-tuning-extraction", stage)
    stage = progress.stage_start("validation")
    validation, excluded_validation_ids = validate_positions(validation_path, tuning, manifest["validation"]["source"])
    progress.stage_done("validation", stage)
    stage = progress.stage_start("artifact-update")
    artifact = updated_artifact(baseline, tuning, manifest)
    training.validate_artifact(artifact)
    progress.stage_done("artifact-update", stage)
    stage = progress.stage_start("metrics")
    base_metrics, candidate_metrics = mse(baseline, validation), mse(artifact, validation)
    progress.stage_done("metrics", stage)
    match_pool, attempts, excluded_openings = match_openings(manifest, tuning)
    with tempfile.NamedTemporaryFile(prefix="reversi-ai-candidate-", suffix=".json", delete=False) as handle:
        handle.write(training.canonical_json(artifact) + b"\n")
        candidate_path = Path(handle.name)
    match_games = []
    stage = progress.stage_start("candidate-match")
    baseline_player = Candidate(executable, baseline_path, manifest["candidate"], manifest["decision_timeout_seconds"])
    candidate_player = Candidate(executable, candidate_path, manifest["candidate"], manifest["decision_timeout_seconds"])
    try:
        for pair, (board, side, opening, rotation) in enumerate(match_pool):
            for member, (match_board, match_side, match_rotation, sides) in enumerate(((board, side, 0, {"B": "candidate", "W": "baseline"}), (rotated_pair(board, side, rotation)[0], rotated_pair(board, side, rotation)[1], rotation, {"B": "baseline", "W": "candidate"}))):
                started = time.monotonic()
                match_games.append(play("candidate-match", pair, member, match_board, match_side, opening, match_rotation, {"baseline": baseline_player, "candidate": candidate_player}, sides, remaining))
                progress.game(pair, member, len(match_games), 200, started)
            if pair + 1 == 25:
                first = match_summary(match_games)
                continued = first["match_points"] > 25
                checkpoint = {"schema_version": 2, "producer_version": VERSION, "manifest_digest": training.digest(manifest), "game_digests": [game["game_digest"] for game in match_games], "match": first, "continued": continued}
                checkpoint["checkpoint_digest"] = training.digest(checkpoint)
                if checkpoint_callback:
                    checkpoint_callback(training.canonical_json(checkpoint) + b"\n")
                if not continued:
                    break
    finally:
        baseline_player.close()
        candidate_player.close()
        candidate_path.unlink(missing_ok=True)
    progress.stage_done("candidate-match", stage)
    first = match_summary(match_games[:50])
    continued = first["match_points"] > 25
    checkpoint = {"schema_version": 2, "producer_version": VERSION, "manifest_digest": training.digest(manifest), "game_digests": [game["game_digest"] for game in match_games[:50]], "match": first, "continued": continued}
    checkpoint["checkpoint_digest"] = training.digest(checkpoint)
    final_match = match_summary(match_games)
    selected_name = selected_from_match(final_match, continued)
    selected = artifact if selected_name == "candidate" else baseline
    stage = progress.stage_start("report-serialization")
    report = {"schema_version": 2, "producer_version": VERSION, "manifest_digest": training.digest(manifest), "baseline_sha256": sha(baseline_path),
              "baseline_artifact_digest": baseline["artifact_digest"], "candidate_artifact_digest": artifact["artifact_digest"],
              "selected_artifact_digest": selected["artifact_digest"], "selected": selected_name,
              "validation_sha256": sha(validation_path), "validation": {"baseline": base_metrics, "candidate": candidate_metrics, "excluded_ids": excluded_validation_ids, "remaining_records": len(validation)},
              "validation_position_keys": validation_keys(validation),
              "self_play_game_count": len(games), "self_play_game_digests": [game["game_digest"] for game in games],
              "match": final_match, "first_match": first, "continued": continued, "match_opening_attempts": attempts, "match_opening_excluded": excluded_openings,
              "game_digests": [game["game_digest"] for game in games + match_games], "decisions": manifest["max_decisions"] - remaining[0], "failures": [], "output_sha256": {}}
    all_games = games + match_games
    partial = output_bytes(artifact, selected, all_games, checkpoint, report)
    report["output_sha256"] = {name: hashlib.sha256(partial[name]).hexdigest() for name in OUTPUTS[:-1]}
    report["report_digest"] = training.digest(report)
    data = output_bytes(artifact, selected, all_games, checkpoint, report)
    progress.stage_done("report-serialization", stage)
    return data


def run(manifest: Path, directory: Path, progress_every: int = 1) -> None:
    if directory.exists() and any(directory.iterdir()):
        fail("output directory must be nonexistent or empty; refusing resume or overwrite")
    progress = Progress(progress_every)
    data = cycle(manifest, progress, lambda checkpoint: atomic_write(directory, "checkpoint.json", checkpoint))
    temporary = {}
    stage = progress.stage_start("atomic-output-publication")
    try:
        for name in OUTPUTS:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=f".{name}.", delete=False) as handle:
                handle.write(data[name]); handle.flush(); os.fsync(handle.fileno()); temporary[name] = Path(handle.name)
        for name in OUTPUTS:
            os.replace(temporary[name], directory / name)
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)
    progress.stage_done("atomic-output-publication", stage)


def verify(manifest_path: Path, directory: Path) -> None:
    manifest, baseline_path, _, validation_path = validate_manifest(manifest_path)
    try:
        raw = {name: (directory / name).read_bytes() for name in OUTPUTS}
    except OSError as error:
        fail(f"incomplete cycle output: {error}")
    report = training.read_json(directory / "report.json")
    if report.get("report_digest") != training.digest({key: value for key, value in report.items() if key != "report_digest"}):
        fail("report digest mismatch")
    for name in OUTPUTS[:-1]:
        if report.get("output_sha256", {}).get(name) != hashlib.sha256(raw[name]).hexdigest():
            fail(f"{name} digest mismatch")
    games = training.read_jsonl(directory / "games.jsonl")
    self_games, match_games = games[:manifest["game_count"]], games[manifest["game_count"]:]
    if len(self_games) != manifest["game_count"] or len(match_games) not in (50, 200):
        fail("incomplete game set")
    for index, game in enumerate(games):
        if game.get("failure") is not None or game.get("kind") not in ("self-play", "candidate-match") or not isinstance(game.get("players"), dict):
            fail("game metadata mismatch")
        replay(game)
        if index < len(self_games) and (game["kind"] != "self-play" or set(game["players"].values()) != {"baseline"}):
            fail("self-play game metadata mismatch")
        if index >= len(self_games) and (game["kind"] != "candidate-match" or set(game["players"].values()) != {"baseline", "candidate"}):
            fail("match game metadata mismatch")
    tuning = [row for game in self_games for row in replay(game)]
    if report.get("game_digests") != [game["game_digest"] for game in games] or report.get("decisions") < len(tuning) or report.get("decisions") > manifest["max_decisions"] or report.get("failures") != []:
        fail("game record or resource metadata mismatch")
    validation, excluded_ids = validate_positions(validation_path, tuning, manifest["validation"]["source"])
    baseline = training.read_json(baseline_path)
    candidate = training.read_json(directory / "candidate-artifact.json")
    training.validate_artifact(candidate)
    expected = updated_artifact(baseline, tuning, manifest)
    if candidate != expected:
        fail("candidate update mismatch")
    base_metrics, candidate_metrics = mse(baseline, validation), mse(candidate, validation)
    first = match_summary(match_games[:50])
    continued = first["match_points"] > 25
    if continued != (len(match_games) == 200):
        fail("match continuation mismatch")
    final_match = match_summary(match_games)
    selected_name = selected_from_match(final_match, continued)
    selected = candidate if selected_name == "candidate" else baseline
    if training.read_json(directory / "selected-artifact.json") != selected:
        fail("selected artifact mismatch")
    checkpoint = training.read_json(directory / "checkpoint.json")
    expected_checkpoint = {"schema_version": 2, "producer_version": VERSION, "manifest_digest": training.digest(manifest), "game_digests": [game["game_digest"] for game in match_games[:50]], "match": first, "continued": continued}
    expected_checkpoint["checkpoint_digest"] = training.digest(expected_checkpoint)
    if checkpoint != expected_checkpoint:
        fail("checkpoint metadata or decision mismatch")
    checks = {"schema_version": 2, "producer_version": VERSION,
              "manifest_digest": training.digest(manifest), "baseline_sha256": sha(baseline_path),
              "baseline_artifact_digest": baseline["artifact_digest"], "candidate_artifact_digest": candidate["artifact_digest"],
              "selected_artifact_digest": selected["artifact_digest"], "selected": selected_name,
              "validation_sha256": sha(validation_path), "validation": {"baseline": base_metrics, "candidate": candidate_metrics, "excluded_ids": excluded_ids, "remaining_records": len(validation)},
              "self_play_game_count": len(self_games), "self_play_game_digests": [game["game_digest"] for game in self_games], "match": final_match, "first_match": first, "continued": continued}
    checks["validation_position_keys"] = validation_keys(validation)
    if any(report.get(key) != value for key, value in checks.items()):
        fail("report metadata or selection mismatch")


def prepare(args: argparse.Namespace) -> None:
    if args.manifest.exists():
        fail("manifest already exists; choose a fresh immutable path")
    baseline = training.read_json(args.baseline_artifact)
    training.validate_artifact(baseline)
    manifest = {"schema_version": 2, "producer_version": VERSION,
                "baseline_artifact": {"path": str(args.baseline_artifact.resolve()), "sha256": sha(args.baseline_artifact),
                                      "artifact_digest": baseline["artifact_digest"]},
                "candidate": {"path": str(args.candidate_executable.resolve()), "sha256": sha(args.candidate_executable),
                              "evaluator": "trained", "profile": "strong-engine-hcap-v1", "book": "off",
                              "opening_depth": args.opening_depth, "midgame_depth": args.midgame_depth,
                              "endgame_depth": args.endgame_depth, "exact_solver_empty_squares": args.exact_solver_empty_squares,
                              "time_limit_ms": args.time_limit_ms, "node_limit": args.node_limit},
                "seed": args.seed, "game_count": args.game_count, "opening_plies": args.opening_plies,
                "pairing": PAIRING, "decision_timeout_seconds": args.decision_timeout_seconds,
                "max_decisions": args.max_decisions,
                "update_rule": {"name": "bounded_td_v1", "normalization_divisor": 64},
                "validation": {"path": str(args.validation_input.resolve()), "sha256": sha(args.validation_input),
                               "source": args.validation_source},
                "match": {"first_pairs": args.match_first_pairs, "continuation_pairs": args.match_continuation_pairs, "max_opening_attempts": args.match_max_opening_attempts}}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_bytes(training.canonical_json(manifest) + b"\n")
    try:
        validate_manifest(args.manifest)
    except Exception:
        args.manifest.unlink(missing_ok=True)
        raise


def regret_command(manifest_path: Path, directory: Path) -> str:
    verify(manifest_path, directory)
    manifest = training.read_json(manifest_path)
    config = manifest["candidate"]
    executable = (manifest_path.parent / config["path"]).resolve()
    selected = (directory / "selected-artifact.json").resolve()
    argv = [str(executable), "--evaluator", "trained", "--trained-artifact", str(selected),
            "--opening-depth", str(config["opening_depth"]), "--midgame-depth", str(config["midgame_depth"]),
            "--endgame-depth", str(config["endgame_depth"]),
            "--exact-solver-empty-squares", str(config["exact_solver_empty_squares"]),
            "--time-limit-ms", str(config["time_limit_ms"]), "--node-limit", str(config["node_limit"])]
    return shlex.join(argv)


def regret_timeout(manifest_path: Path, directory: Path) -> int:
    verify(manifest_path, directory)
    manifest = training.read_json(manifest_path)
    return manifest["decision_timeout_seconds"]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    creation = commands.add_parser("prepare")
    for option in ("manifest", "baseline-artifact", "candidate-executable", "validation-input"):
        creation.add_argument(f"--{option}", type=Path, required=True)
    creation.add_argument("--validation-source", required=True)
    for option in ("seed", "game-count", "opening-plies", "opening-depth", "midgame-depth", "endgame-depth", "exact-solver-empty-squares", "time-limit-ms", "node-limit", "decision-timeout-seconds", "max-decisions"):
        creation.add_argument(f"--{option}", type=int, required=True)
    creation.add_argument("--match-first-pairs", type=int, default=25)
    creation.add_argument("--match-continuation-pairs", type=int, default=75)
    creation.add_argument("--match-max-opening-attempts", type=int, default=200)
    for name in ("run", "verify", "regret-command", "regret-timeout"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
        if name == "run":
            command.add_argument("--progress-every", type=positive_interval, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "regret-command":
            print(regret_command(args.manifest, args.output_dir))
        elif args.command == "regret-timeout":
            print(regret_timeout(args.manifest, args.output_dir))
        else:
            if args.command == "run":
                run(args.manifest, args.output_dir, args.progress_every)
            else:
                verify(args.manifest, args.output_dir)
    except (training.TrainingError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as error:
        print(f"reinforcement error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
