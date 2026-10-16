"""Deterministic, score-blind independent Oracle corpus selection."""

import hashlib
import sys
from pathlib import Path

import random_inputs
import reinforcement
import training

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reversi-ai-oracle"))
import oracle

VERSION = "reversi-ai-independent-corpus-v1"
STONES = (20, 40, 48)


def select(seed, excluded_keys, reserved_keys=(), *, progress_every=1):
    training.require_int(seed, "corpus seed", 0, random_inputs.MASK)
    training.require_int(progress_every, "progress interval", 1)
    excluded, reserved = set(excluded_keys), set(reserved_keys)
    seen, records, games, decisions = set(), [], [], []
    counts = {stone: 0 for stone in STONES}
    for game_id in range(256):
        game_seed = int.from_bytes(hashlib.sha256(f"{VERSION}:game:{seed}:{game_id}".encode()).digest()[:8], "big")
        stream = random_inputs.Stream(game_seed)
        board, side, turns = reinforcement.INITIAL, "B", []
        for turn in range(128):
            moves = sorted(reinforcement.legal_moves(board, side))
            if not moves and not reinforcement.legal_moves(board, reinforcement.other(side)):
                break
            stones = 64 - board.count(".")
            if stones in STONES:
                root_key = training.canonical_position_key(board, side)
                children = [reinforcement.apply_move(board, side, move) for move in moves]
                child_keys = {training.canonical_position_key(child, reinforcement.other(side)) for child in children}
                reason = "selected"
                if counts[stones] == 4:
                    reason = "quota"
                elif not 2 <= len(moves) <= 16:
                    reason = "legal-count"
                elif not any(reinforcement.legal_moves(child, "B") or reinforcement.legal_moves(child, "W") for child in children):
                    reason = "terminal-children"
                elif root_key in seen:
                    reason = "duplicate"
                elif ({root_key} | child_keys) & excluded:
                    reason = "split-exposure"
                elif ({root_key} | child_keys) & reserved:
                    reason = "acceptance-reservation"
                decisions.append({"game_id": game_id, "turn": turn, "stone_count": stones,
                                  "key": root_key, "reason": reason})
                if reason == "selected":
                    records.append(oracle.make_corpus_record(f"independent-game-{game_id}-turn-{turn}", board, side,
                                                            [item["move"] for item in turns], VERSION))
                    seen.add(root_key)
                    counts[stones] += 1
            move = moves[stream.index(len(moves))] if moves else "pass"
            turns.append({"side": side, "move": move})
            if move != "pass":
                board = reinforcement.apply_move(board, side, move)
            side = reinforcement.other(side)
        if reinforcement.legal_moves(board, "B") or reinforcement.legal_moves(board, "W"):
            raise training.TrainingError("independent candidate game did not complete")
        games.append({"game_id": game_id, "seed": game_seed, "turns": turns, "terminal_board": board})
        if (game_id + 1) % progress_every == 0 or all(value == 4 for value in counts.values()):
            print(f"progress independent-corpus games={game_id + 1}/256 roots={len(records)}/12", file=sys.stderr, flush=True)
        if all(value == 4 for value in counts.values()):
            break
    evidence = {"version": VERSION, "seed": seed, "max_games": 256, "stone_counts": list(STONES),
                "roots_per_stone": 4, "excluded_keys": sorted(excluded), "reserved_keys": sorted(reserved),
                "decisions": decisions, "complete": len(records) == 12}
    return records, games, evidence


def blobs(seed, excluded_keys, reserved_keys=(), *, progress_every=1):
    records, games, selection = select(seed, excluded_keys, reserved_keys, progress_every=progress_every)
    return {"corpus.jsonl": b"".join(random_inputs.canonical(row) for row in records),
            "games.jsonl": b"".join(random_inputs.canonical(row) for row in games),
            "selection.json": random_inputs.canonical(selection)}, selection


def generate(seed, excluded_keys, output, reserved_keys=(), *, progress_every=1):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise training.TrainingError("corpus output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    outputs, selection = blobs(seed, excluded_keys, reserved_keys, progress_every=progress_every)
    for name, data in outputs.items():
        (output / name).write_bytes(data)
    if not selection["complete"]:
        raise training.TrainingError("independent corpus exhausted 256 candidate games")


def verify(output, excluded_keys, reserved_keys=()):
    output = Path(output)
    if {path.name for path in output.iterdir()} != {"corpus.jsonl", "games.jsonl", "selection.json"}:
        raise training.TrainingError("missing or extra corpus evidence")
    saved = training.read_json(output / "selection.json")
    expected, selection = blobs(saved["seed"], excluded_keys, reserved_keys, progress_every=256)
    if not selection["complete"] or any((output / name).read_bytes() != data for name, data in expected.items()):
        raise training.TrainingError("independent corpus differs from deterministic replay")
    rows = oracle.load_jsonl(output / "corpus.jsonl")
    oracle.validate_corpus(rows)
    roots = {training.canonical_position_key(row["board"], row["side_to_move"]) for row in rows}
    children = {training.canonical_position_key(oracle.apply_move(row["board"], row["side_to_move"], move),
                                               oracle.other(row["side_to_move"])) for row in rows for move in row["legal_moves"]}
    return {"seed": saved["seed"], "count": len(rows),
            "exposure_keys": {"oracle_root": sorted(roots), "oracle_child": sorted(children)}}
