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

VERSION = "reversi-ai-pattern-reinforcement-v1"
PAIRING = "color_swap_d4_v1"
OUTPUTS = ("candidate-artifact.json", "selected-artifact.json", "games.jsonl", "report.json")
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
    require_keys(manifest, {"schema_version", "producer_version", "source_commit", "producer_sources", "baseline_artifact", "candidate", "seed", "game_count", "opening_plies", "pairing", "decision_timeout_seconds", "max_decisions", "update_rule", "validation"}, "manifest")
    if manifest["schema_version"] != 1 or manifest["producer_version"] != VERSION:
        fail("unsupported reinforcement manifest")
    if not isinstance(manifest["source_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"]):
        fail("source_commit must be a complete commit SHA")
    root_repo = Path(__file__).resolve().parents[2]
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root_repo, capture_output=True, text=True, check=True).stdout
    if status:
        fail("source worktree is dirty; frozen source is required")
    source = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root_repo, capture_output=True, text=True, check=True).stdout.strip()
    if source != manifest["source_commit"]:
        fail("source commit mismatch")
    sources = require_keys(manifest["producer_sources"], {"reinforcement.py", "training.py"}, "producer_sources")
    for name, path_source in (("reinforcement.py", Path(__file__)), ("training.py", Path(training.__file__))):
        if not isinstance(sources[name], str) or not HEX.fullmatch(sources[name]) or sources[name] != sha(path_source):
            fail(f"producer source digest mismatch: {name}")
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
        training.require_int(candidate[key], key, 1, 64)
    training.require_int(candidate["exact_solver_empty_squares"], "exact threshold", 0, 16)
    training.require_int(candidate["time_limit_ms"], "time limit", 1)
    training.require_int(candidate["node_limit"], "node limit", 1)
    training.require_int(manifest["seed"], "seed", 0, 2**64 - 1)
    games = training.require_int(manifest["game_count"], "game_count", 2)
    if games % 2 or games > 256:
        fail("game_count must be even and at most 256")
    training.require_int(manifest["opening_plies"], "opening_plies", 1, 20)
    training.require_int(manifest["decision_timeout_seconds"], "decision_timeout_seconds", 1, 3600)
    training.require_int(manifest["max_decisions"], "max_decisions", 1, 256 * 120)
    if manifest["pairing"] != PAIRING or manifest["update_rule"] != {"name": "bounded_td_v1", "normalization_divisor": 64}:
        fail("unsupported pairing or update rule")
    validation_entry = require_keys(manifest["validation"], {"path", "sha256", "source"}, "validation")
    if not isinstance(validation_entry["source"], str) or not validation_entry["source"] or "0018" in validation_entry["source"]:
        fail("validation source must be named and separate from 0018")
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


def play(pair: int, member: int, board: str, side: str, opening: list[str], rotation: int,
         candidate: Candidate, remaining: list[int]) -> dict:
    start_board, start_side = board, side
    decisions = []
    for turn in range(121):
        legal = legal_moves(board, side)
        if not legal and not legal_moves(board, other(side)):
            break
        if remaining[0] == 0:
            fail("maximum decision count exceeded")
        remaining[0] -= 1
        identifier = f"p{pair}-m{member}-t{turn}"
        move = candidate.choose(identifier, board, side) if legal else "pass"
        if legal and move not in legal or not legal and move != "pass":
            fail(f"illegal candidate response at {identifier}: {move}")
        decisions.append({"id": identifier, "board": board, "side": side, "move": move})
        if legal:
            board = apply_move(board, side, move)
        side = other(side)
    else:
        fail("game exceeded 120 turns")
    counts = {"B": board.count("B"), "W": board.count("W")}
    game = {"pair": pair, "member": member, "opening": opening, "rotation": rotation,
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


def validate_positions(path: Path, tuning: list[dict], source: str) -> list[dict]:
    records = training.read_jsonl(path)
    if not records:
        fail("validation input is empty")
    seen = {training.canonical_position_key(row["board"], row["side"]) for row in tuning}
    validated = []
    for row in records:
        if row.get("schema_version") != 1 or row.get("split") != "validation" or not isinstance(row.get("record_id"), str):
            fail("validation record schema or split mismatch")
        if row.get("source") != source or not isinstance(row.get("license"), str) or not row["license"] or not isinstance(row.get("source_digest"), str) or not row["source_digest"]:
            fail("validation record provenance mismatch")
        board, side, target = training.parse_position(row, f"validation {row['record_id']}")
        key = training.canonical_position_key(board, side)
        if key in seen:
            fail("validation position overlaps tuning records")
        seen.add(key)
        validated.append({"id": row["record_id"], "board": board, "side": side, "target": target})
    return validated


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
    errors = [training.predict(artifact["weights"], row["board"], row["side"]) - row["target"] for row in rows]
    return {"records": len(rows), "sum_squared_error": sum(error * error for error in errors),
            "mean_squared_error": sum(error * error for error in errors) / len(rows)}


def select_artifact(baseline: dict, candidate: dict, base_metrics: dict, candidate_metrics: dict) -> dict:
    return candidate if candidate_metrics["sum_squared_error"] < base_metrics["sum_squared_error"] else baseline


def output_bytes(artifact: dict, selected: dict, games: list[dict], report: dict) -> dict[str, bytes]:
    return {"candidate-artifact.json": training.canonical_json(artifact) + b"\n",
            "selected-artifact.json": training.canonical_json(selected) + b"\n",
            "games.jsonl": b"".join(training.canonical_json(game) + b"\n" for game in games),
            "report.json": training.canonical_json(report) + b"\n"}


def cycle(manifest_path: Path) -> dict[str, bytes]:
    manifest, baseline_path, executable, validation_path = validate_manifest(manifest_path)
    baseline = training.read_json(baseline_path)
    generated = openings(manifest["seed"], manifest["game_count"], manifest["opening_plies"])
    games = []
    remaining = [manifest["max_decisions"]]
    candidate = Candidate(executable, baseline_path, manifest["candidate"], manifest["decision_timeout_seconds"])
    try:
        for pair, (board, side, opening, rotation) in enumerate(generated):
            games.append(play(pair, 0, board, side, opening, 0, candidate, remaining))
            paired_board, paired_side = rotated_pair(board, side, rotation)
            games.append(play(pair, 1, paired_board, paired_side, opening, rotation, candidate, remaining))
    finally:
        candidate.close()
    tuning = [row for game in games for row in replay(game)]
    validation = validate_positions(validation_path, tuning, manifest["validation"]["source"])
    artifact = updated_artifact(baseline, tuning, manifest)
    training.validate_artifact(artifact)
    base_metrics, candidate_metrics = mse(baseline, validation), mse(artifact, validation)
    selected = select_artifact(baseline, artifact, base_metrics, candidate_metrics)
    report = {"schema_version": 1, "producer_version": VERSION, "source_commit": manifest["source_commit"],
              "manifest_digest": training.digest(manifest), "baseline_sha256": sha(baseline_path),
              "baseline_artifact_digest": baseline["artifact_digest"], "candidate_artifact_digest": artifact["artifact_digest"],
              "selected_artifact_digest": selected["artifact_digest"], "selected": "candidate" if selected is artifact else "baseline",
              "validation_sha256": sha(validation_path), "validation": {"baseline": base_metrics, "candidate": candidate_metrics},
              "game_count": len(games), "pair_count": len(games) // 2, "game_digests": [game["game_digest"] for game in games],
              "decisions": manifest["max_decisions"] - remaining[0], "failures": [], "output_sha256": {}}
    partial = output_bytes(artifact, selected, games, report)
    report["output_sha256"] = {name: hashlib.sha256(partial[name]).hexdigest() for name in OUTPUTS[:-1]}
    report["report_digest"] = training.digest(report)
    return output_bytes(artifact, selected, games, report)


def run(manifest: Path, directory: Path) -> None:
    if any((directory / name).exists() for name in OUTPUTS):
        fail("output paths already exist; choose a fresh directory")
    data = cycle(manifest)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = {}
    try:
        for name in OUTPUTS:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=f".{name}.", delete=False) as handle:
                handle.write(data[name])
                handle.flush()
                os.fsync(handle.fileno())
                temporary[name] = Path(handle.name)
        for name in OUTPUTS:
            os.replace(temporary[name], directory / name)
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)


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
    if len(games) != manifest["game_count"] or report.get("game_count") != len(games) or report.get("pair_count") != len(games) // 2:
        fail("incomplete game set")
    generated = openings(manifest["seed"], manifest["game_count"], manifest["opening_plies"])
    for pair, (board, side, opening, rotation) in enumerate(generated):
        for member in (0, 1):
            game = games[2 * pair + member]
            expected_board, expected_side = (board, side) if member == 0 else rotated_pair(board, side, rotation)
            if game["pair"] != pair or game["member"] != member or game["start_board"] != expected_board or game["start_side"] != expected_side or game["opening"] != opening or game["rotation"] != (rotation if member else 0) or game["failure"] is not None:
                fail("game pairing or opening mismatch")
    tuning = [row for game in games for row in replay(game)]
    if report.get("game_digests") != [game["game_digest"] for game in games] or report.get("decisions") != len(tuning) or len(tuning) > manifest["max_decisions"] or report.get("failures") != []:
        fail("game record or resource metadata mismatch")
    validation = validate_positions(validation_path, tuning, manifest["validation"]["source"])
    baseline = training.read_json(baseline_path)
    candidate = training.read_json(directory / "candidate-artifact.json")
    training.validate_artifact(candidate)
    expected = updated_artifact(baseline, tuning, manifest)
    if candidate != expected:
        fail("candidate update mismatch")
    base_metrics, candidate_metrics = mse(baseline, validation), mse(candidate, validation)
    selected = select_artifact(baseline, candidate, base_metrics, candidate_metrics)
    if training.read_json(directory / "selected-artifact.json") != selected:
        fail("selected artifact mismatch")
    checks = {"schema_version": 1, "producer_version": VERSION, "source_commit": manifest["source_commit"],
              "manifest_digest": training.digest(manifest), "baseline_sha256": sha(baseline_path),
              "baseline_artifact_digest": baseline["artifact_digest"], "candidate_artifact_digest": candidate["artifact_digest"],
              "selected_artifact_digest": selected["artifact_digest"], "selected": "candidate" if selected is candidate else "baseline",
              "validation_sha256": sha(validation_path), "validation": {"baseline": base_metrics, "candidate": candidate_metrics}}
    if any(report.get(key) != value for key, value in checks.items()):
        fail("report metadata or selection mismatch")


def prepare(args: argparse.Namespace) -> None:
    if args.manifest.exists():
        fail("manifest already exists; choose a fresh immutable path")
    root = Path(__file__).resolve().parents[2]
    source = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    baseline = training.read_json(args.baseline_artifact)
    training.validate_artifact(baseline)
    manifest = {"schema_version": 1, "producer_version": VERSION, "source_commit": source,
                "producer_sources": {"reinforcement.py": sha(Path(__file__)), "training.py": sha(Path(training.__file__))},
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
                               "source": args.validation_source}}
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


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    creation = commands.add_parser("prepare")
    for option in ("manifest", "baseline-artifact", "candidate-executable", "validation-input"):
        creation.add_argument(f"--{option}", type=Path, required=True)
    creation.add_argument("--validation-source", required=True)
    for option in ("seed", "game-count", "opening-plies", "opening-depth", "midgame-depth", "endgame-depth", "exact-solver-empty-squares", "time-limit-ms", "node-limit", "decision-timeout-seconds", "max-decisions"):
        creation.add_argument(f"--{option}", type=int, required=True)
    for name in ("run", "verify", "regret-command"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "regret-command":
            print(regret_command(args.manifest, args.output_dir))
        else:
            (run if args.command == "run" else verify)(args.manifest, args.output_dir)
    except (training.TrainingError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as error:
        print(f"reinforcement error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
