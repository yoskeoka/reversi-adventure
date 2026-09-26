#!/usr/bin/env python3
"""Prepare, generate, and verify project-owned random-game training inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import reinforcement
import training

VERSION = "reversi-ai-random-inputs-v1"
SOURCE = "project-owned-random-games-v1"
COUNTS = {"train": 2048, "validation": 256, "held_out": 256}
SPLITS = ("train", "validation", "held_out")
MASK = (1 << 64) - 1


def reject(message: str) -> None:
    raise training.TrainingError(message)


def canonical(value: object) -> bytes:
    return training.canonical_json(value) + b"\n"


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def seed_for(master: int, game_id: int) -> int:
    return int.from_bytes(hashlib.sha256(f"{VERSION}:game:{master}:{game_id}".encode()).digest()[:8], "big")


class Stream:
    """SplitMix64 with rejection sampling for an unbiased bounded index."""

    def __init__(self, seed: int):
        self.state = seed

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK
        return value ^ (value >> 31)

    def index(self, size: int) -> int:
        if size < 1:
            reject("cannot choose from an empty move list")
        limit = (1 << 64) - ((1 << 64) % size)
        while True:
            value = self.next()
            if value < limit:
                return value % size


def assignment(master: int, counts: dict[str, int]) -> dict[str, list[int]]:
    ids = list(range(sum(counts.values())))
    stream = Stream(int.from_bytes(hashlib.sha256(f"{VERSION}:split:{master}".encode()).digest()[:8], "big"))
    for i in range(len(ids) - 1, 0, -1):
        j = stream.index(i + 1)
        ids[i], ids[j] = ids[j], ids[i]
    offset = 0
    result = {}
    for split in SPLITS:
        result[split] = sorted(ids[offset:offset + counts[split]])
        offset += counts[split]
    return result


def prepare(path: Path, master: int, counts: dict[str, int], start: int, max_turns: int,
            require_clean: bool = True) -> None:
    training.require_int(master, "seed", 0, MASK)
    training.require_int(start, "record start", 8, 59)
    training.require_int(max_turns, "maximum turns", 60, 128)
    for split in SPLITS:
        training.require_int(counts[split], split, 1, 2048)
    total = sum(counts.values())
    if total > 2560:
        reject("game count exceeds production bound")
    seeds = [seed_for(master, game_id) for game_id in range(total)]
    if len(set(seeds)) != total:
        reject("per-game seed collision")
    root = Path(__file__).resolve().parents[2]
    if require_clean and subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True,
                                        capture_output=True, text=True).stdout:
        reject("source checkout must be clean before freezing production inputs")
    source = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    base = subprocess.run(["git", "rev-parse", "origin/main"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    manifest = {"schema_version": 1, "generator_version": VERSION,
                "source_commit": source, "base_commit": base,
                "generator_sha256": training.sha256_file(Path(__file__)),
                "producer_sources": {"reinforcement.py": training.sha256_file(Path(reinforcement.__file__)),
                                     "training.py": training.sha256_file(Path(training.__file__))},
                "license": "CC0-1.0", "source": SOURCE, "seed": master,
                "seed_derivation": "sha256-prefix64-v1", "random_rule": "splitmix64-rejection-sorted-legal-v1",
                "split_rule": "splitmix64-fisher-yates-v1", "counts": counts,
                "game_ids": assignment(master, counts), "record_start_placements": start,
                "max_turns": max_turns, "output_schema": 1}
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        reject("frozen manifest already exists")
    path.write_bytes(canonical(manifest))


def check_manifest(path: Path) -> dict:
    manifest = training.read_json(path)
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "generator_version", "source_commit", "base_commit", "generator_sha256", "producer_sources", "license", "source", "seed", "seed_derivation", "random_rule", "split_rule", "counts", "game_ids", "record_start_placements", "max_turns", "output_schema"}:
        reject("invalid generator manifest shape")
    if manifest["schema_version"] != 1 or manifest["output_schema"] != 1 or manifest["generator_version"] != VERSION or manifest["license"] != "CC0-1.0" or manifest["source"] != SOURCE:
        reject("unsupported generator manifest")
    if manifest["seed_derivation"] != "sha256-prefix64-v1" or manifest["random_rule"] != "splitmix64-rejection-sorted-legal-v1" or manifest["split_rule"] != "splitmix64-fisher-yates-v1":
        reject("unsupported random stream rule")
    if manifest["generator_sha256"] != training.sha256_file(Path(__file__)):
        reject("generator source digest mismatch")
    sources = manifest["producer_sources"]
    if not isinstance(sources, dict) or set(sources) != {"reinforcement.py", "training.py"}:
        reject("invalid producer source digests")
    for name, module in (("reinforcement.py", reinforcement), ("training.py", training)):
        if sources[name] != training.sha256_file(Path(module.__file__)):
            reject(f"producer source digest mismatch: {name}")
    source = manifest["source_commit"]
    if not isinstance(source, str) or len(source) != 40 or any(c not in "0123456789abcdef" for c in source):
        reject("invalid source commit")
    base = manifest["base_commit"]
    if not isinstance(base, str) or len(base) != 40 or any(c not in "0123456789abcdef" for c in base):
        reject("invalid merged base commit")
    root = Path(__file__).resolve().parents[2]
    if (subprocess.run(["git", "merge-base", "--is-ancestor", source, "HEAD"], cwd=root).returncode
            or subprocess.run(["git", "merge-base", "--is-ancestor", base, source], cwd=root).returncode):
        reject("source checkout or merged base commit mismatch")
    master = training.require_int(manifest["seed"], "seed", 0, MASK)
    counts = manifest["counts"]
    if not isinstance(counts, dict) or set(counts) != set(SPLITS):
        reject("invalid split counts")
    for split in SPLITS:
        training.require_int(counts[split], split, 1, 2048)
    if sum(counts.values()) > 2560 or manifest["game_ids"] != assignment(master, counts):
        reject("game assignment mismatch")
    if len({seed_for(master, game_id) for game_id in range(sum(counts.values()))}) != sum(counts.values()):
        reject("per-game seed collision")
    training.require_int(manifest["record_start_placements"], "record start", 8, 59)
    training.require_int(manifest["max_turns"], "maximum turns", 60, 128)
    return manifest


def phase(placements: int) -> str:
    return "opening" if placements <= 20 else "midgame" if placements <= 44 else "endgame"


def play(game_id: int, split: str, manifest: dict) -> tuple[dict, list[dict], int]:
    seed = seed_for(manifest["seed"], game_id)
    stream = Stream(seed)
    board, side, turns, positions = reinforcement.INITIAL, "B", [], []
    placements = 0
    for _ in range(manifest["max_turns"]):
        legal = sorted(reinforcement.legal_moves(board, side))
        if not legal and not reinforcement.legal_moves(board, reinforcement.other(side)):
            break
        if placements >= manifest["record_start_placements"] and placements <= 59:
            positions.append((board, side, placements, len(legal), len(turns)))
        move = legal[stream.index(len(legal))] if legal else "pass"
        turns.append({"side": side, "move": move})
        if move != "pass":
            board = reinforcement.apply_move(board, side, move)
            placements += 1
        side = reinforcement.other(side)
    if reinforcement.legal_moves(board, side) or reinforcement.legal_moves(board, reinforcement.other(side)):
        reject(f"game {game_id} is incomplete at turn cap")
    black, white = board.count("B"), board.count("W")
    game = {"schema_version": 1, "game_id": game_id, "split": split, "seed": seed,
            "turns": turns, "terminal_board": board, "black": black, "white": white}
    game["game_digest"] = training.digest(game)
    rows = []
    for position, turn_side, ply, legal_count, turn_index in positions:
        rows.append({"schema_version": 1, "record_id": f"game-{game_id}-turn-{turn_index}",
                     "split": split, "source": SOURCE, "license": "CC0-1.0",
                     "source_digest": manifest["generator_sha256"], "board": position,
                     "side": turn_side, "target": {"semantics": training.TARGET_SEMANTICS,
                                                     "value": (black - white) * (1 if turn_side == "B" else -1)},
                     "game_id": game_id, "turn_index": turn_index, "placements": ply,
                     "phase": phase(ply), "legal_moves": legal_count,
                     "game_digest": game["game_digest"]})
    return game, rows, placements


def build(manifest: dict) -> tuple[dict[str, bytes], dict]:
    mapping = {game_id: split for split in SPLITS for game_id in manifest["game_ids"][split]}
    games, records = [], {split: [] for split in SPLITS}
    seen = set()
    duplicates = Counter()
    phases = {split: Counter() for split in SPLITS}
    legal_counts = {split: Counter() for split in SPLITS}
    turns = {split: 0 for split in SPLITS}
    targets = {split: [] for split in SPLITS}
    for game_id in range(sum(manifest["counts"].values())):
        split = mapping[game_id]
        game, candidates, _ = play(game_id, split, manifest)
        games.append(game)
        turns[split] += len(game["turns"])
        for row in candidates:
            key = training.canonical_position_key(row["board"], row["side"])
            if key in seen:
                duplicates[split] += 1
                continue
            seen.add(key)
            records[split].append(row)
            phases[split][row["phase"]] += 1
            legal_counts[split][str(row["legal_moves"])] += 1
            targets[split].append(row["target"]["value"])
    for split in SPLITS:
        if set(phases[split]) != {"opening", "midgame", "endgame"}:
            reject(f"missing phase coverage in {split}")
    blobs = {"games.jsonl": b"".join(canonical(game) for game in games)}
    for split in SPLITS:
        blobs[f"{split}.jsonl"] = b"".join(canonical(row) for row in records[split])
    trainer = {"schema_version": 1, "trainer_version": training.TRAINER_VERSION,
               "seed": manifest["seed"], "feature_contract": {"format_version": 1,
               "catalog_digest": training.catalog_digest(), "phase_count": 60,
               "score_scale": training.SCORE_SCALE},
               "optimizer": {"name": "sparse_mean_v1", "normalization_divisor": 64},
               "inputs": [{"path": f"{split}.jsonl", "sha256": hash_bytes(blobs[f"{split}.jsonl"]),
                           "source": SOURCE, "license": "CC0-1.0",
                           "source_digest": manifest["generator_sha256"]} for split in SPLITS]}
    blobs["trainer-manifest.json"] = canonical(trainer)
    report = {"schema_version": 1, "generator_version": VERSION,
              "manifest_sha256": None,
              "games": [{"game_id": game["game_id"], "split": game["split"],
                         "seed": game["seed"], "turns": len(game["turns"]),
                         "passes": sum(turn["move"] == "pass" for turn in game["turns"]),
                         "game_digest": game["game_digest"]} for game in games],
              "splits": {split: {"games": manifest["counts"][split], "turns": turns[split],
                       "records": len(records[split]), "duplicates": duplicates[split],
                       "phases": dict(sorted(phases[split].items())),
                       "legal_moves": dict(sorted(legal_counts[split].items())),
                       "target_range": [min(targets[split]), max(targets[split])]} for split in SPLITS},
              "outputs": {name: hash_bytes(data) for name, data in sorted(blobs.items())}}
    return blobs, report


def verify_game(game: dict, manifest: dict) -> None:
    expected = dict(game)
    digest = expected.pop("game_digest", None)
    if digest != training.digest(expected):
        reject("game digest mismatch")
    board, side = reinforcement.INITIAL, "B"
    for turn in game["turns"]:
        if turn["side"] != side:
            reject("game side mismatch")
        legal = reinforcement.legal_moves(board, side)
        if turn["move"] == "pass":
            if legal or not reinforcement.legal_moves(board, reinforcement.other(side)):
                reject("illegal pass")
        else:
            if turn["move"] not in legal:
                reject("illegal move in game log")
            board = reinforcement.apply_move(board, side, turn["move"])
        side = reinforcement.other(side)
    if len(game["turns"]) > manifest["max_turns"] or board != game["terminal_board"] or board.count("B") != game["black"] or board.count("W") != game["white"]:
        reject("terminal game mismatch")
    if reinforcement.legal_moves(board, side) or reinforcement.legal_moves(board, reinforcement.other(side)):
        reject("nonterminal game log")


def generate(manifest_path: Path, output: Path) -> None:
    manifest = check_manifest(manifest_path)
    if output.exists() and any(output.iterdir()):
        reject("output directory must be empty")
    blobs, report = build(manifest)
    report["manifest_sha256"] = training.sha256_file(manifest_path)
    output.mkdir(parents=True, exist_ok=True)
    for name, data in blobs.items():
        (output / name).write_bytes(data)
    (output / "report.json").write_bytes(canonical(report))


def verify(manifest_path: Path, output: Path) -> dict:
    manifest = check_manifest(manifest_path)
    expected_names = {"games.jsonl", "train.jsonl", "validation.jsonl", "held_out.jsonl", "trainer-manifest.json", "report.json"}
    if not output.is_dir() or {path.name for path in output.iterdir()} != expected_names:
        reject("missing or extra generator output")
    games = training.read_jsonl(output / "games.jsonl")
    if len(games) != sum(manifest["counts"].values()):
        reject("incomplete game set")
    for game in games:
        verify_game(game, manifest)
    blobs, report = build(manifest)
    report["manifest_sha256"] = training.sha256_file(manifest_path)
    for name, data in blobs.items():
        if (output / name).read_bytes() != data:
            reject(f"{name} differs from replay")
    if (output / "report.json").read_bytes() != canonical(report):
        reject("report differs from replay")
    trainer = training.read_json(output / "trainer-manifest.json")
    training.validate_records(training.validate_manifest(trainer, output))
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--manifest", type=Path, required=True)
    prep.add_argument("--seed", type=int, default=20260926)
    for split in SPLITS:
        prep.add_argument(f"--{split.replace('_', '-')}-games", type=int, default=COUNTS[split])
    prep.add_argument("--record-start-placements", type=int, default=8)
    prep.add_argument("--max-turns", type=int, default=128)
    for name in ("generate", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            counts = {split: getattr(args, f"{split}_games") for split in SPLITS}
            prepare(args.manifest, args.seed, counts, args.record_start_placements, args.max_turns)
        elif args.command == "generate":
            generate(args.manifest, args.output_dir)
        else:
            verify(args.manifest, args.output_dir)
    except (training.TrainingError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"random inputs error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
