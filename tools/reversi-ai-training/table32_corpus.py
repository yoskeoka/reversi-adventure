#!/usr/bin/env python3
"""Build and independently verify the scored-input-free 0–9 placement corpus."""
from __future__ import annotations

import argparse
import gzip
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import table32_store as st
import training


VERSION = "reversi-table32-opening-corpus-v1"
PHASE_COUNTS = (1, 1, 3, 14, 60, 322, 1773, 10649, 67245, 434029)
SHARD_SIZE = 4096
ENGINE_LINE_BYTES = 38
DEFAULT_RSS_KIB = 262144
BITBOARD = re.compile(r"[0-9a-f]{16}")
SHA256 = re.compile(r"[0-9a-f]{64}")
RULES = {
    "board": "absolute black and white, a1 bit 0, row-major",
    "canonical": "minimum numeric (black, white) of eight D4 images, side retained",
    "placement": "occupied stone count minus four",
    "pass": "automatic forced pass before recording, no extra placement",
    "terminal": "neither side can move, last mover retained, no descendants",
    "record": "sorted JSON lines, gzip mtime 0, zero-based phase-wide IDs",
}


def decode_position(row: dict) -> tuple[str, str]:
    black, white = int(row["black"], 16), int(row["white"], 16)
    board = "".join("B" if black & (1 << i) else "W" if white & (1 << i) else "."
                    for i in range(64))
    return board, {"black": "B", "white": "W"}[row["turn"]]


def _canonical_masks(board):
    images = []
    for symmetry in range(8):
        image = training.board_key(board, symmetry)
        black = sum(1 << square for square, stone in enumerate(image) if stone == "B")
        white = sum(1 << square for square, stone in enumerate(image) if stone == "W")
        images.append((black, white))
    return min(images)


def find_position_ids(root, position_keys):
    """Map matching training canonical board-and-side keys to fixed corpus IDs."""
    manifest = read_manifest(root)
    wanted = {}
    for key in position_keys:
        st.require(isinstance(key, str) and key.count(":") == 1, "invalid corpus position key")
        board, side = key.split(":")
        st.require(len(board) == 64 and set(board) <= {"B", "W", "."} and side in ("B", "W")
                   and training.canonical_position_key(board, side) == key, "invalid canonical position key")
        phase = 60 - board.count(".")
        turn = {"B": "black", "W": "white"}[side]
        wanted.setdefault(phase, {})[(*_canonical_masks(board), turn)] = key
    matches = {}
    for shard in manifest["shards"]:
        targets = wanted.get(shard["phase"])
        if not targets:
            continue
        for row in iter_shard(root, shard):
            position = (int(row["black"], 16), int(row["white"], 16), row["turn"])
            if position in targets:
                matches[targets.pop(position)] = row["id"]
    return matches


def _position_id(phase, offset):
    return f"p{phase:02d}-{offset:06d}"


def _shards_through(last_phase):
    for phase, count in enumerate(PHASE_COUNTS[:last_phase + 1]):
        for offset in range(0, count, SHARD_SIZE):
            length = min(SHARD_SIZE, count - offset)
            yield {
                "phase": phase,
                "path": f"shards/p{phase:02d}-{offset // SHARD_SIZE:03d}.jsonl.gz",
                "count": length,
                "first_id": _position_id(phase, offset),
                "last_id": _position_id(phase, offset + length - 1),
            }


def _has_sha256(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _check_shard(shard, expected):
    st.require(isinstance(shard, dict) and set(shard) == set(expected) | {"sha256", "terminal_count"}
               and all(type(shard[key]) is type(value) and shard[key] == value
                       for key, value in expected.items())
               and _has_sha256(shard["sha256"])
               and type(shard["terminal_count"]) is int
               and 0 <= shard["terminal_count"] <= shard["count"], "invalid corpus shard metadata")


def read_manifest(root):
    manifest = st.read(Path(root) / "manifest.json")
    st.require(isinstance(manifest, dict) and manifest == st.seal(manifest)
               and manifest.get("version") == VERSION and manifest.get("rules") == RULES
               and manifest.get("shard_size") == SHARD_SIZE, "invalid corpus manifest")
    phases = manifest.get("phases")
    st.require(isinstance(phases, list) and 1 <= len(phases) <= len(PHASE_COUNTS),
               "invalid corpus phase inventory")
    expected_shards = list(_shards_through(len(phases) - 1))
    shards = manifest.get("shards")
    st.require(isinstance(shards, list) and len(shards) == len(expected_shards),
               "invalid corpus shard inventory")
    for shard, expected in zip(shards, expected_shards):
        _check_shard(shard, expected)
    st.require(st.blob(manifest) == st.blob(_manifest(len(phases) - 1, shards)), "invalid corpus phase totals")
    return manifest


def _row_key(row, expected_id, phase):
    st.require(isinstance(row, dict)
               and set(row) == {"id", "black", "white", "turn", "terminal"}
               and row["id"] == expected_id
               and all(isinstance(row[color], str) and BITBOARD.fullmatch(row[color])
                       for color in ("black", "white"))
               and row["turn"] in ("black", "white") and type(row["terminal"]) is bool,
               f"invalid corpus row {expected_id}")
    black, white = int(row["black"], 16), int(row["white"], 16)
    st.require(black & white == 0 and (black | white).bit_count() == phase + 4,
               f"invalid corpus board {expected_id}")
    return black, white, row["turn"]


def iter_shard(root, shard):
    """Return checked rows in order. No row leaves a failed shard."""
    phase = shard["phase"]
    st.require(type(phase) is int and 0 <= phase < len(PHASE_COUNTS), "invalid shard phase")
    expected = next((s for s in _shards_through(phase) if s["path"] == shard["path"]), None)
    st.require(expected is not None, "unknown corpus shard path")
    _check_shard(shard, expected)
    path = Path(root) / shard["path"]
    st.require(not path.is_symlink() and not path.parent.is_symlink()
               and path.is_file() and path.stat().st_size < 50 * 1024 * 1024
               and training.sha256_file(path) == shard["sha256"], f"corpus shard digest differs: {path}")
    rows = []
    previous = (-1, -1, "")
    terminals = 0
    offset = int(shard["first_id"].split("-")[-1])
    with gzip.open(path, "rb") as stream:
        for index in range(shard["count"]):
            line = stream.readline(160)
            expected_id = _position_id(phase, offset + index)
            st.require(line.endswith(b"\n"), f"missing or truncated corpus row {expected_id}")
            row = json.loads(line)
            key = _row_key(row, expected_id, phase)
            st.require(key > previous and line == st.blob(row), f"corpus row order/encoding differs: {expected_id}")
            previous = key
            terminals += row["terminal"]
            rows.append(row)
        st.require(not stream.read(1) and terminals == shard["terminal_count"],
                   f"corpus shard counts differ: {path}")
    return iter(rows)


def _manifest(last_phase, shards):
    return st.seal({
        "version": VERSION,
        "rules": RULES,
        "shard_size": SHARD_SIZE,
        "phases": [
            {"phase": phase, "count": count,
             "terminal_count": sum(s["terminal_count"] for s in shards if s["phase"] == phase)}
            for phase, count in enumerate(PHASE_COUNTS[:last_phase + 1])
        ],
        "total_count": sum(PHASE_COUNTS[:last_phase + 1]),
        "shards": shards,
    })


def _frontier(enumerator, mode, phase, prior):
    process = subprocess.run([str(enumerator), mode, str(phase)], input=prior,
                             capture_output=True, check=True)
    output = process.stdout
    if len(output) != ENGINE_LINE_BYTES * PHASE_COUNTS[phase]:
        count = output.count(b"\n")
        raise training.TrainingError(f"{mode} phase {phase}: expected {PHASE_COUNTS[phase]} positions, got {count}")
    return output


def _engine_line(row):
    turn = "B" if row["turn"] == "black" else "W"
    return f"{row['black']} {row['white']} {turn} {int(row['terminal'])}\n".encode("ascii")


def _row(phase, index, line):
    black, white, turn, terminal = line.decode("ascii").split()
    st.require(turn in ("B", "W") and terminal in ("0", "1"), "invalid corpus enumerator output")
    return {"id": _position_id(phase, index), "black": black, "white": white,
            "turn": "black" if turn == "B" else "white", "terminal": terminal == "1"}


def _write_shard(root, shard, rows):
    buffer = io.BytesIO()
    terminal_count = 0
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0) as stream:
        for row in rows:
            terminal_count += row["terminal"]
            stream.write(st.blob(row))
    path = root / shard["path"]
    st.atomic_bytes(path, buffer.getvalue(), once=True)
    result = {**shard, "sha256": training.sha256_file(path), "terminal_count": terminal_count}
    st.atomic(_checkpoint(root, shard), result, once=True)
    return result


def _checkpoint(root, shard):
    return root / "checkpoints" / (Path(shard["path"]).name + ".json")


def _saved(root, shards):
    saved = []
    missing = False
    for shard in shards:
        checkpoint = _checkpoint(root, shard)
        if not checkpoint.exists():
            missing = True
            continue
        st.require(not missing, "corpus checkpoint is outside completed shard prefix")
        previous = st.read(checkpoint)
        _check_shard(previous, shard)
        saved.append(previous)
    return saved


def _progress(start, phase, unit, completed, total, status, every=1):
    if status != "saved" or completed % every == 0 or completed == total:
        print(f"table32 phase={phase} unit={unit} completed={completed} total={total} "
              f"elapsed_seconds={time.monotonic() - start:.3f} status={status}",
              file=sys.stderr, flush=True)


def _attempt_progress(attempt, phase, completed, total):
    st.atomic(attempt / "progress.json", {"phase": phase, "unit": "shard",
                                          "completed": completed, "total": total})


def generate(root, enumerator, last_phase, *, attempt, progress_every=1):
    """Replay saved shard prefix and append immutable completed shards."""
    root, enumerator = Path(root), Path(enumerator).resolve(strict=True)
    started = time.monotonic()
    shards = list(_shards_through(last_phase))
    saved = _saved(root, shards)
    complete, prior = len(saved), b""
    phase = shards[complete]["phase"] if complete < len(shards) else last_phase
    _attempt_progress(attempt, phase, complete, len(shards))
    _progress(started, phase, "shard", complete, len(shards), "started")
    try:
        for phase in range(last_phase + 1):
            units = [shard for shard in shards if shard["phase"] == phase]
            _attempt_progress(attempt, phase, complete, len(shards))
            if all(_checkpoint(root, shard).exists() for shard in units):
                prior = b"".join(_engine_line(row) for unit in units
                                 for row in iter_shard(root, st.read(_checkpoint(root, unit))))
                continue
            frontier = _frontier(enumerator, "engine", phase, prior)
            for shard in units:
                offset = int(shard["first_id"].split("-")[-1])
                start = ENGINE_LINE_BYTES * offset
                stop = start + ENGINE_LINE_BYTES * shard["count"]
                lines = frontier[start:stop].splitlines()
                checkpoint = _checkpoint(root, shard)
                if checkpoint.exists():
                    previous = st.read(checkpoint)
                    actual = b"".join(_engine_line(row) for row in iter_shard(root, previous))
                    st.require(actual == b"\n".join(lines) + b"\n", f"saved corpus shard differs: {shard['path']}")
                    continue
                result = _write_shard(root, shard, (_row(phase, index, line)
                                                   for index, line in enumerate(lines, offset)))
                saved.append(result)
                complete += 1
                _attempt_progress(attempt, phase, complete, len(shards))
                _progress(started, phase, "shard", complete, len(shards), "saved", progress_every)
            prior = frontier
        manifest = _manifest(last_phase, saved)
        st.atomic(root / "manifest.json", manifest, once=True)
    except BaseException:
        _progress(started, phase, "shard", complete, len(shards), "stopped")
        raise
    return manifest


def verify(root, enumerator):
    manifest = read_manifest(root)
    root = Path(root)
    st.require({path.relative_to(root).as_posix() for path in (root / "shards").iterdir()}
               == {shard["path"] for shard in manifest["shards"]}, "corpus shard inventory differs")
    enumerator = Path(enumerator).resolve(strict=True)
    prior = b""
    for phase in range(len(manifest["phases"])):
        regenerated = _frontier(enumerator, "scalar", phase, prior)
        actual = b"".join(_engine_line(row) for shard in manifest["shards"] if shard["phase"] == phase
                          for row in iter_shard(root, shard))
        st.require(regenerated == actual, f"independent corpus replay differs at phase {phase}")
        prior = regenerated
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("generate")
    check = commands.add_parser("verify")
    for command in (build, check):
        command.add_argument("--root", required=True, type=Path)
        command.add_argument("--enumerator", required=True, type=Path)
    build.add_argument("--last-phase", type=int, choices=range(len(PHASE_COUNTS)), default=9)
    build.add_argument("--resume", action="store_true")
    build.add_argument("--progress-every", type=int, default=1)
    build.add_argument("--attempt-wall-seconds", type=int, default=43200)
    build.add_argument("--producer-rss-kib", type=int, default=DEFAULT_RSS_KIB)
    build.add_argument("--child-rss-kib", type=int, default=DEFAULT_RSS_KIB)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            manifest = verify(args.root, args.enumerator)
        else:
            from table32_process import supervise

            st.require(args.progress_every > 0 and args.attempt_wall_seconds >= 0
                       and args.producer_rss_kib > 0 and args.child_rss_kib > 0,
                       "invalid corpus attempt limit")
            enumerator = args.enumerator.resolve(strict=True)
            generation = {
                "producer_commit": None,
                "settings": {"version": VERSION, "enumerator": st.pin(enumerator), "last_phase": args.last_phase},
                "limits": {"wall_seconds": 43200, "producer_rss_kib": DEFAULT_RSS_KIB,
                           "child_rss_kib": DEFAULT_RSS_KIB},
            }
            if args.resume:
                actual = st.read(args.root / "generation.json")
                st.require(actual == generation, "corpus generation settings changed")
            else:
                args.root.mkdir(parents=True, exist_ok=False)
                st.atomic(args.root / "generation.json", generation, once=True)
            if not (args.root / "manifest.json").exists():
                supervise(args.root, generation,
                          lambda attempt: generate(args.root, enumerator, args.last_phase,
                                                   attempt=attempt, progress_every=args.progress_every),
                          progress_every=args.progress_every, attempt_wall_seconds=args.attempt_wall_seconds,
                          attempt_rss_limits={"producer_rss_kib": args.producer_rss_kib,
                                              "child_rss_kib": args.child_rss_kib})
            manifest = read_manifest(args.root)
        print(json.dumps({"digest": manifest["digest"], "phases": manifest["phases"],
                          "total_count": manifest["total_count"]}, sort_keys=True))
    except (OSError, ValueError, subprocess.CalledProcessError, training.TrainingError) as error:
        parser.exit(2, f"table32 corpus: {error}\n")


if __name__ == "__main__":
    main()
