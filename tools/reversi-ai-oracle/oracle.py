#!/usr/bin/env python3
"""Run the pinned Egaroucid oracle without making it a Rust dependency."""

from __future__ import annotations

import argparse
import copy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
import re
import select
import signal
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import NamedTuple, NoReturn


ORACLE_VERSION = "7.8.1"
SOURCE_URL = (
    "https://github.com/Nyanyan/Egaroucid/archive/refs/tags/"
    f"v{ORACLE_VERSION}.tar.gz"
)
SOURCE_SHA256 = "173af642276216a284498f8d7e32de23dbb9dc6611686c370b0de3eddbc1238b"
DEFAULT_TIMEOUT_SECONDS = 300.0
HEADER = ["Level", "Depth", "Move", "Score", "Time", "Nodes", "NPS"]
SUMMARY_RE = re.compile(
    r"^total (?P<nodes>\d+) nodes in (?P<seconds>\d+(?:\.\d+)?)s NPS (?P<nps>\d+)$"
)
MAX_PROTOCOL_LINE_BYTES = 64 * 1024
MAX_GTP_RESPONSE_LINES = 1024
COORDINATE_RE = re.compile(r"^[a-h][1-8]$")
BOARD_RE = re.compile(r"^[BW.]{64}$")


class OracleError(RuntimeError):
    """A fail-closed adapter error suitable for command-line reporting."""


class DepthProbabilityRange(NamedTuple):
    move_start: int
    move_end: int
    depth: int
    probability: str


class OracleProfile(NamedTuple):
    name: str
    hash_level: int
    depth_ranges: tuple[DepthProbabilityRange, ...]
    candidate_depth: int
    candidate_exact_solver_empty_squares: int
    legacy_level: int | None = None


CI_SMOKE_V1 = OracleProfile(
    name="ci-smoke-v1",
    hash_level=25,
    depth_ranges=(),
    candidate_depth=2,
    candidate_exact_solver_empty_squares=12,
    legacy_level=8,
)
STRONG_ENGINE_HCAP_V1 = OracleProfile(
    name="strong-engine-hcap-v1",
    hash_level=25,
    depth_ranges=(
        DepthProbabilityRange(1, 41, 8, "100"),
        DepthProbabilityRange(42, 60, 12, "100"),
    ),
    candidate_depth=12,
    candidate_exact_solver_empty_squares=16,
)
SEARCH_PERFORMANCE_SELF_PLAY_V1 = OracleProfile(
    name="search-performance-self-play-v1",
    hash_level=25,
    depth_ranges=(),
    candidate_depth=6,
    candidate_exact_solver_empty_squares=0,
    legacy_level=6,
)
PROFILES = {
    profile.name: profile
    for profile in (
        CI_SMOKE_V1,
        STRONG_ENGINE_HCAP_V1,
        SEARCH_PERFORMANCE_SELF_PLAY_V1,
    )
}


def validate_profile(profile: OracleProfile) -> None:
    if profile.name not in PROFILES or PROFILES[profile.name] != profile:
        die(f"unknown or modified oracle profile: {profile.name!r}")
    if profile.hash_level != 25 or profile.candidate_depth < 1:
        die(f"invalid oracle profile: {profile.name!r}")
    if profile.legacy_level is not None:
        if profile.depth_ranges or not (1 <= profile.legacy_level <= 60):
            die(f"invalid legacy oracle profile: {profile.name!r}")
        return
    previous_end = 0
    for item in profile.depth_ranges:
        if not (1 <= item.move_start <= item.move_end <= 60):
            die(f"invalid depth range in profile {profile.name!r}")
        if item.move_start <= previous_end or not (1 <= item.depth <= 60):
            die(f"overlapping or invalid depth range in profile {profile.name!r}")
        if item.probability != "100":
            die(f"profile {profile.name!r} must use 100% probability")
        previous_end = item.move_end


def profile_from_name(name: str) -> OracleProfile:
    profile = PROFILES.get(name)
    if profile is None:
        die(f"unknown oracle profile: {name!r}")
    validate_profile(profile)
    return profile


def profile_metadata(profile: OracleProfile) -> dict[str, object]:
    validate_profile(profile)
    return {
        "name": profile.name,
        "oracle": {
            "name": "Egaroucid for Console",
            "version": ORACLE_VERSION,
            "source_url": SOURCE_URL,
            "source_sha256": SOURCE_SHA256,
            "book": False,
            "threads": 1,
            "hash_level": profile.hash_level,
            "evaluation_override": False,
            "depth_probability_ranges": [
                {"move_start": item.move_start, "move_end": item.move_end,
                 "depth": item.depth, "probability": item.probability}
                for item in profile.depth_ranges
            ],
            "legacy_level": profile.legacy_level,
        },
        "candidate": {
            "heuristic_depth": profile.candidate_depth,
            "exact_solver_empty_squares": profile.candidate_exact_solver_empty_squares,
        },
    }


def profile_depth_at(profile: OracleProfile, occupied_discs: int) -> int:
    validate_profile(profile)
    if profile.legacy_level is not None:
        return 60
    move_number = occupied_discs - 3
    for item in profile.depth_ranges:
        if item.move_start <= move_number <= item.move_end:
            return item.depth
    die(f"profile {profile.name!r} has no depth for decision move {move_number}")


def oracle_argv(binary: Path, profile: OracleProfile, *, solve_path: Path | None = None,
               child_query: bool = False, gtp: bool = False) -> list[str]:
    validate_profile(profile)
    argv = [str(binary), "-nobook", "-thread", "1", "-hash", str(profile.hash_level)]
    if profile.legacy_level is not None:
        argv.extend(["-level", str(profile.legacy_level)])
    for item in profile.depth_ranges:
        start = item.move_start + (1 if child_query else 0)
        end = min(item.move_end + (1 if child_query else 0), 60)
        if start <= end:
            argv.extend(["-depthprobrange", str(start), str(end), str(item.depth), item.probability])
    if gtp:
        argv.extend(["-gtp", "-quiet"])
    if solve_path is not None:
        argv.extend(["-solve", str(solve_path)])
    return argv


def die(message: str) -> NoReturn:
    raise OracleError(message)


def coordinate(row: int, col: int) -> str:
    return f"{chr(ord('a') + col)}{row + 1}"


def parse_coordinate(value: str) -> tuple[int, int]:
    if not COORDINATE_RE.fullmatch(value):
        die(f"invalid coordinate: {value!r}")
    return ord(value[1]) - ord("1"), ord(value[0]) - ord("a")


def other(side: str) -> str:
    if side == "B":
        return "W"
    if side == "W":
        return "B"
    die(f"invalid side_to_move: {side!r}")


def legal_moves(board: str, side: str) -> list[str]:
    if not BOARD_RE.fullmatch(board):
        die("board must contain exactly 64 characters from B, W, and .")
    opponent = other(side)
    found: list[str] = []
    directions = (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    )
    for row in range(8):
        for col in range(8):
            index = row * 8 + col
            if board[index] != ".":
                continue
            captures = False
            for row_delta, col_delta in directions:
                next_row, next_col = row + row_delta, col + col_delta
                saw_opponent = False
                while 0 <= next_row < 8 and 0 <= next_col < 8:
                    cell = board[next_row * 8 + next_col]
                    if cell != opponent:
                        if saw_opponent and cell == side:
                            captures = True
                        break
                    saw_opponent = True
                    next_row += row_delta
                    next_col += col_delta
                if captures:
                    break
            if captures:
                found.append(coordinate(row, col))
    return sorted(found)


def apply_move(board: str, side: str, move: str) -> str:
    row, col = parse_coordinate(move)
    index = row * 8 + col
    if board[index] != ".":
        die(f"move {move} is not empty")
    opponent = other(side)
    directions = (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    )
    flips: list[int] = []
    for row_delta, col_delta in directions:
        next_row, next_col = row + row_delta, col + col_delta
        line: list[int] = []
        while 0 <= next_row < 8 and 0 <= next_col < 8:
            next_index = next_row * 8 + next_col
            cell = board[next_index]
            if cell != opponent:
                if line and cell == side:
                    flips.extend(line)
                break
            line.append(next_index)
            next_row += row_delta
            next_col += col_delta
    if not flips:
        die(f"move {move} is illegal for {side}")
    cells = list(board)
    cells[index] = side
    for flip_index in flips:
        cells[flip_index] = side
    return "".join(cells)


def phase_for(board: str) -> str:
    stones = sum(cell != "." for cell in board)
    if stones < 4:
        die(f"phase requires at least four stones, got {stones}")
    if stones <= 20:
        return "opening"
    if stones <= 44:
        return "midgame"
    return "endgame"


def outcome_for(board: str, side: str) -> dict[str, object]:
    moves = legal_moves(board, side)
    if moves:
        return {"kind": "MoveSet", "moves": moves}
    if legal_moves(board, other(side)):
        return {"kind": "Pass"}
    return {"kind": "GameOver"}


def make_corpus_record(
    position_id: str, board: str, side: str, game_record: list[str], source: str
) -> dict[str, object]:
    moves = legal_moves(board, side)
    return {
        "schema_version": 1,
        "position_id": position_id,
        "board": board,
        "side_to_move": side,
        "stone_count": sum(cell != "." for cell in board),
        "phase": phase_for(board),
        "legal_moves": moves,
        "outcome": outcome_for(board, side),
        "provenance": {
            "source": source,
            "game_record": "".join(game_record),
            "generator": "tools/reversi-ai-oracle/oracle.py",
        },
    }


def generate_corpus() -> list[dict[str, object]]:
    board = "".join(
        "........" for _ in range(8)
    )
    cells = list(board)
    cells[3 * 8 + 3] = "W"
    cells[3 * 8 + 4] = "B"
    cells[4 * 8 + 3] = "B"
    cells[4 * 8 + 4] = "W"
    board = "".join(cells)
    side = "B"
    game_record: list[str] = []
    targets = (4, 12, 20, 28, 40, 48, 56, 60)
    captured: set[int] = set()
    records: list[dict[str, object]] = []
    pass_count = 0
    pass_recorded = False

    while True:
        stones = sum(cell != "." for cell in board)
        if stones in targets and stones not in captured:
            records.append(
                make_corpus_record(
                    f"stones-{stones}",
                    board,
                    side,
                    game_record,
                    "deterministic-first-legal-self-play",
                )
            )
            captured.add(stones)

        moves = legal_moves(board, side)
        if not moves:
            opponent_moves = legal_moves(board, other(side))
            if not opponent_moves:
                records.append(
                    make_corpus_record(
                        "game-over",
                        board,
                        side,
                        game_record,
                        "deterministic-first-legal-self-play",
                    )
                )
                break
            if not pass_recorded:
                records.append(
                    make_corpus_record(
                        "forced-pass",
                        board,
                        side,
                        game_record,
                        "deterministic-first-legal-self-play",
                    )
                )
                pass_recorded = True
            game_record.append("PS")
            side = other(side)
            pass_count += 1
            if pass_count == 2:
                die("deterministic corpus generator reached two consecutive passes")
            continue

        pass_count = 0
        move = moves[0]
        board = apply_move(board, side, move)
        game_record.append(move.upper())
        side = other(side)

    missing = set(targets) - captured
    if missing:
        die(f"deterministic corpus generator missed stone counts: {sorted(missing)}")
    return records


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(canonical_json(record) + "\n" for record in records), encoding="utf-8"
    )


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        die(f"file not found: {path}")
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            die(f"{path}:{line_number}: invalid JSON: {exc}")
        if not isinstance(value, dict):
            die(f"{path}:{line_number}: record must be an object")
        records.append(value)
    if not records:
        die(f"corpus is empty: {path}")
    return records


def load_canonical_jsonl(path: Path) -> list[dict[str, object]]:
    """Load JSON Lines only when its serialized representation is canonical."""
    if not path.is_file():
        die(f"file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        die(f"canonical JSON Lines file must end with a newline: {path}")
    lines = text.splitlines()
    if not lines or any(not line for line in lines):
        die(f"canonical JSON Lines file must contain no blank records: {path}")
    records = load_jsonl(path)
    if len(records) != len(lines) or any(
        line != canonical_json(record) for line, record in zip(lines, records)
    ):
        die(f"JSON Lines file is not canonical: {path}")
    return records


def validate_corpus_record(record: dict[str, object]) -> None:
    required = {
        "schema_version",
        "position_id",
        "board",
        "side_to_move",
        "stone_count",
        "phase",
        "legal_moves",
        "outcome",
        "provenance",
    }
    missing = sorted(required - record.keys())
    if missing:
        die(f"corpus record is missing fields: {', '.join(missing)}")
    board = record["board"]
    side = record["side_to_move"]
    position_id = record["position_id"]
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        die(f"unsupported schema_version in corpus record {position_id!r}")
    if not isinstance(position_id, str) or not position_id:
        die("corpus position_id must be a non-empty string")
    if any(character in position_id for character in "\t\r\n"):
        die(f"corpus position_id contains a protocol delimiter: {position_id!r}")
    if not isinstance(board, str) or not BOARD_RE.fullmatch(board):
        die(f"invalid board in corpus record {position_id!r}")
    if side not in ("B", "W"):
        die(f"invalid side_to_move in corpus record {position_id!r}")
    expected_count = sum(cell != "." for cell in board)
    if type(record["stone_count"]) is not int or record["stone_count"] != expected_count:
        die(f"stone_count mismatch in corpus record {position_id!r}")
    if record["phase"] != phase_for(board):
        die(f"phase mismatch in corpus record {position_id!r}")
    actual_moves = legal_moves(board, side)
    if not isinstance(record["legal_moves"], list):
        die(f"legal_moves must be a list in corpus record {position_id!r}")
    if record["legal_moves"] != actual_moves:
        die(f"legal_moves mismatch in corpus record {position_id!r}")
    outcome = record["outcome"]
    if not isinstance(outcome, dict):
        die(f"outcome must be an object in corpus record {position_id!r}")
    if record["outcome"] != outcome_for(board, side):
        die(f"outcome mismatch in corpus record {position_id!r}")
    provenance = record["provenance"]
    if not isinstance(provenance, dict):
        die(f"provenance must be an object in corpus record {position_id!r}")
    if not all(isinstance(provenance.get(key), str) for key in ("source", "game_record", "generator")):
        die(f"provenance is incomplete in corpus record {position_id!r}")


def validate_corpus(records: list[dict[str, object]]) -> None:
    ids: set[object] = set()
    for record in records:
        validate_corpus_record(record)
        position_id = record["position_id"]
        if position_id in ids:
            die(f"duplicate corpus position_id: {position_id!r}")
        ids.add(position_id)


def d4_canonical(board: str) -> str:
    """Return the lexicographically least of the eight square symmetries."""
    rows = [board[index:index + 8] for index in range(0, 64, 8)]

    def rotate(square: list[str]) -> list[str]:
        return ["".join(square[7 - col][row] for col in range(8)) for row in range(8)]

    def reflect(square: list[str]) -> list[str]:
        return [row[::-1] for row in square]

    variants: list[str] = []
    square = rows
    for _ in range(4):
        variants.append("".join(square))
        variants.append("".join(reflect(square)))
        square = rotate(square)
    return min(variants)


def validate_benchmark_corpus(records: list[dict[str, object]]) -> None:
    if len(records) != 16:
        die("benchmark corpus must contain exactly sixteen records")
    expected = {(game, stones) for game in range(1, 5) for stones in (20, 40, 44, 48)}
    observed: set[tuple[int, int]] = set()
    symmetries: set[str] = set()
    transcripts: dict[int, str] = {}
    for record in records:
        validate_corpus_record(record)
        provenance = record["provenance"]
        if not isinstance(provenance, dict) or type(provenance.get("source_game")) is not int:
            die("benchmark corpus provenance requires integer source_game")
        identity = (provenance["source_game"], record["stone_count"])
        if identity in observed:
            die(f"duplicate benchmark root {identity!r}")
        observed.add(identity)
        transcript = provenance.get("transcript")
        if not isinstance(transcript, str) or provenance.get("game_record") != transcript:
            die(f"benchmark corpus has invalid transcript provenance: {record['position_id']!r}")
        source_game = provenance["source_game"]
        previous = transcripts.setdefault(source_game, transcript)
        if previous != transcript:
            die(f"benchmark corpus has inconsistent transcript provenance for game {source_game}")
        symmetry = d4_canonical(str(record["board"]))
        if symmetry in symmetries:
            die(f"benchmark corpus has a D4-equivalent duplicate: {record['position_id']!r}")
        symmetries.add(symmetry)
    if observed != expected:
        die(f"benchmark corpus roots differ from expected set: {sorted(observed)!r}")
    replayed = {
        (game, record["stone_count"]): record
        for game, transcript in transcripts.items()
        for record in benchmark_records_from_transcript(transcript, game)
    }
    actual = {(record["provenance"]["source_game"], record["stone_count"]): record for record in records}
    if {key: canonical_json(value) for key, value in actual.items()} != {
        key: canonical_json(value) for key, value in replayed.items()
    }:
        die("benchmark corpus records do not match their replayed transcripts")


def cache_root() -> Path:
    configured = os.environ.get("REVERSI_ADVENTURE_ORACLE_CACHE")
    if configured:
        return Path(configured).expanduser().resolve()
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
    return (base / "reversi-adventure" / "egaroucid" / ORACLE_VERSION).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_symlink():
            die(f"oracle source contains an unexpected symlink: {path}")
        if path.is_dir():
            digest.update(b"d\0" + relative + b"\0")
        elif path.is_file():
            digest.update(b"f\0" + relative + b"\0")
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        else:
            die(f"oracle source contains an unexpected special file: {path}")
    return digest.hexdigest()


def safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if member.issym() or member.islnk():
                die(f"refusing archive link: {member.name}")
            if not (member.isdir() or member.isfile()):
                die(f"refusing archive special file: {member.name}")
            target = (destination / member.name).resolve()
            if target != destination and destination not in target.parents:
                die(f"refusing archive path outside cache: {member.name}")
        tar.extractall(destination)


def run_external(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: float,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        die(f"required external command is unavailable: {command[0]}: {exc}")
    except subprocess.TimeoutExpired as exc:
        die(f"oracle process timed out after {timeout:g}s: {' '.join(command)}")
    except OSError as exc:
        die(f"unable to execute external command {command[0]}: {exc}")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        die(f"oracle process failed with exit {result.returncode}: {detail}")
    return result


def validate_budget(level: int, timeout: float) -> None:
    if not 1 <= level <= 60:
        die(f"oracle level must be between 1 and 60: {level}")
    if not math.isfinite(timeout) or timeout <= 0:
        die(f"oracle timeout must be positive: {timeout}")


def find_oracle_binary(root: Path) -> Path:
    candidates = [
        root / "bin" / "Egaroucid_for_Console.out",
        root / "bin" / "Egaroucid_for_console.out",
        root / "source" / "bin" / "Egaroucid_for_Console.out",
        root / "source" / "bin" / "Egaroucid_for_console.out",
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    die("built Egaroucid Console executable was not found in the pinned cache")


def validate_source_directory(source: Path) -> None:
    if source.is_symlink():
        die(f"pinned oracle source path must not be a symlink: {source}")
    if source.exists() and not source.is_dir():
        die(f"pinned oracle source path is not a directory: {source}")


def archive_source_tree_sha256(archive: Path) -> str:
    with tempfile.TemporaryDirectory(prefix=".source-check-", dir=archive.parent) as temporary:
        destination = Path(temporary)
        safe_extract(archive, destination)
        extracted = [path for path in destination.iterdir() if path.is_dir()]
        if len(extracted) != 1:
            die("pinned Egaroucid source archive has an unexpected layout")
        return sha256_tree(extracted[0])


def write_cache_integrity(path: Path, source: Path, binary: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "archive_sha256": SOURCE_SHA256,
                "binary_sha256": sha256_file(binary),
                "source_sha256": sha256_tree(source),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
    )


def validate_cache_integrity(
    path: Path, source: Path, binary: Path
) -> None:
    if not path.is_file():
        die(f"oracle cache integrity manifest is missing: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        die(f"oracle cache integrity manifest is invalid: {path}: {exc}")
    if not isinstance(manifest, dict) or not all(
        isinstance(manifest.get(key), str)
        for key in ("archive_sha256", "binary_sha256", "source_sha256")
    ):
        die(f"oracle cache integrity manifest has an invalid schema: {path}")
    if manifest["archive_sha256"] != SOURCE_SHA256:
        die(f"oracle cache integrity manifest targets a different archive: {path}")
    if manifest["source_sha256"] != sha256_tree(source):
        die(f"pinned Egaroucid source integrity mismatch: {source}")
    if manifest["binary_sha256"] != sha256_file(binary):
        die(f"pinned Egaroucid binary integrity mismatch: {binary}")


def ensure_oracle(timeout: float) -> tuple[Path, Path]:
    if not math.isfinite(timeout) or timeout <= 0:
        die(f"oracle timeout must be positive: {timeout}")
    if sys.platform != "linux":
        die("the oracle adapter supports Linux and WSL2 only")
    root = cache_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        die(f"oracle cache is not writable: {root}: {exc}")
    archive = root / f"egaroucid-v{ORACLE_VERSION}.tar.gz"
    source = root / "source"
    integrity_manifest = root / ".integrity.json"

    if not archive.is_file():
        temporary = root / f"{archive.name}.download"
        try:
            with urllib.request.urlopen(SOURCE_URL, timeout=60) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            actual = sha256_file(temporary)
            if actual != SOURCE_SHA256:
                die(f"Egaroucid source SHA-256 mismatch: expected {SOURCE_SHA256}, got {actual}")
            os.replace(temporary, archive)
        except OracleError:
            raise
        except Exception as exc:
            die(f"unable to download pinned Egaroucid source: {exc}")
        finally:
            temporary.unlink(missing_ok=True)
    elif sha256_file(archive) != SOURCE_SHA256:
        die(f"cached Egaroucid source SHA-256 mismatch: {archive}")

    expected_source_sha256 = archive_source_tree_sha256(archive)
    validate_source_directory(source)
    if not source.is_dir():
        with tempfile.TemporaryDirectory(prefix=".extract-", dir=root) as temporary:
            extract_root = Path(temporary)
            safe_extract(archive, extract_root)
            extracted = [path for path in extract_root.iterdir() if path.is_dir()]
            if len(extracted) != 1:
                die("pinned Egaroucid source archive has an unexpected layout")
            os.replace(extracted[0], source)
    if sha256_tree(source) != expected_source_sha256:
        die(f"pinned Egaroucid source integrity mismatch: {source}")

    built_binary = source / "bin" / "Egaroucid_for_Console.out"
    if not built_binary.is_file():
        built_binary = source / "bin" / "Egaroucid_for_console.out"
    try:
        with tempfile.TemporaryDirectory(prefix=".build-", dir=root) as temporary:
            build_dir = Path(temporary)
            run_external(
                [
                    "cmake",
                    "-S",
                    str(source),
                    "-B",
                    str(build_dir),
                    "-DCMAKE_BUILD_TYPE=Release",
                    "-DHAS_NO_AVX2=ON",
                ],
                timeout=timeout,
            )
            run_external(
                ["cmake", "--build", str(build_dir), "--parallel", "2"],
                timeout=timeout,
            )
            built_binary = find_oracle_binary(source)
            binary_dir = root / "bin"
            binary_dir.mkdir(exist_ok=True)
            binary = binary_dir / built_binary.name
            shutil.copy2(built_binary, binary)
            binary.chmod(binary.stat().st_mode | 0o111)
            resources = binary_dir / "resources"
            shutil.rmtree(resources, ignore_errors=True)
            shutil.copytree(source / "bin" / "resources", resources)
    finally:
        built_binary.unlink(missing_ok=True)

    if not source.is_dir():
        die(f"pinned oracle source directory is missing: {source}")
    if sha256_tree(source) != expected_source_sha256:
        die(f"pinned Egaroucid source changed during build: {source}")
    write_cache_integrity(integrity_manifest, source, binary)
    validate_cache_integrity(integrity_manifest, source, binary)
    version = run_external([str(binary), "-version"], cwd=source, timeout=min(timeout, 30))
    if ORACLE_VERSION not in version.stdout and ORACLE_VERSION not in version.stderr:
        die("built Egaroucid executable did not report the pinned version")
    return binary, source


def parse_elapsed(value: str) -> int:
    match = re.fullmatch(r"(\d+):([0-5]\d):([0-5]\d)\.(\d{3})", value)
    if not match:
        die(f"unexpected Egaroucid elapsed time: {value!r}")
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_depth(value: str) -> tuple[int, float]:
    if value == "-":
        return 0, 0.0
    match = re.fullmatch(r"(\d+)@(\d+(?:\.\d+)?)%", value)
    if not match:
        die(f"unexpected Egaroucid depth: {value!r}")
    percentage = float(match.group(2))
    if percentage > 100:
        die(f"unexpected Egaroucid MPC probability: {value!r}")
    return int(match.group(1)), percentage


def parse_solve_output(
    output: str, required_depths: list[int], expected_profile: OracleProfile
) -> list[dict[str, object]]:
    validate_profile(expected_profile)
    rows: list[dict[str, object]] = []
    header_seen = False
    summary_seen = False
    summary_nodes = 0
    summary_seconds = Decimal(0)
    summary_nps = 0
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if summary_seen:
            die("Egaroucid output has content after its total summary")
        if stripped.startswith("total "):
            summary = SUMMARY_RE.fullmatch(stripped)
            if summary is None:
                die(f"unexpected Egaroucid summary: {line!r}")
            try:
                summary_nodes = int(summary.group("nodes"))
                summary_seconds = Decimal(summary.group("seconds"))
                summary_nps = int(summary.group("nps"))
            except (InvalidOperation, ValueError) as exc:
                die(f"unexpected Egaroucid summary: {line!r}: {exc}")
            summary_seen = True
            continue
        if not stripped.startswith("|"):
            die(f"unexpected Egaroucid output: {line!r}")
        fields = [field.strip() for field in stripped.split("|")[1:-1]]
        if fields == HEADER:
            if header_seen:
                die("duplicate Egaroucid table header")
            header_seen = True
            continue
        if not header_seen:
            die("Egaroucid table row appeared before its header")
        if len(fields) != len(HEADER):
            die(f"unexpected Egaroucid table row: {line!r}")
        level, depth, move, score, elapsed, nodes, nps = fields
        if move == "ps":
            die("Egaroucid returned a pass row without a score")
        if not COORDINATE_RE.fullmatch(move.lower()):
            die(f"unexpected Egaroucid move: {move!r}")
        if not re.fullmatch(r"[+-]?\d+", score):
            die(f"unexpected Egaroucid score: {score!r}")
        if expected_profile.legacy_level is None and level != "custom":
            die(f"Egaroucid returned level {level!r}, expected custom profile output")
        if expected_profile.legacy_level is not None and level != str(expected_profile.legacy_level):
            die(f"Egaroucid returned level {level!r}, expected {expected_profile.legacy_level}")
        completed_depth, probability = parse_depth(depth)
        if expected_profile.legacy_level is None and probability != 100:
            die(f"Egaroucid custom profile did not report 100% probability: {depth!r}")
        if not re.fullmatch(r"\d+", nodes) or not re.fullmatch(r"\d+", nps):
            die(f"unexpected Egaroucid node count: {nodes!r}, {nps!r}")
        rows.append(
            {
                "move": move.lower(),
                "value": int(score),
                "completed_depth": completed_depth,
                "nodes": int(nodes),
                "elapsed_ms": parse_elapsed(elapsed),
                "nps": int(nps),
                "exact": False,
            }
        )
    if not summary_seen:
        die("Egaroucid output did not contain a total summary")
    if not header_seen:
        die("Egaroucid output did not contain its table header")
    if len(rows) != len(required_depths):
        die(f"Egaroucid returned {len(rows)} rows for {len(required_depths)} queries")
    row_nodes = sum(int(row["nodes"]) for row in rows)
    row_elapsed_ms = sum(int(row["elapsed_ms"]) for row in rows)
    if summary_nodes != row_nodes:
        die(f"Egaroucid summary node count {summary_nodes} does not match rows {row_nodes}")
    expected_seconds = Decimal(row_elapsed_ms) / Decimal(1000)
    if expected_seconds:
        # Egaroucid prints the total with C++'s default six significant digits.
        rounding_quantum = Decimal(1).scaleb(expected_seconds.adjusted() - 5)
        if abs(summary_seconds - expected_seconds) > rounding_quantum / 2:
            die(
                f"Egaroucid summary time {summary_seconds}s does not match rows "
                f"{expected_seconds}s"
            )
    elif summary_seconds != 0:
        die(f"Egaroucid summary time {summary_seconds}s does not match zero row time")
    expected_nps = row_nodes * 1000 // max(row_elapsed_ms, 1)
    if summary_nps != expected_nps:
        die(f"Egaroucid summary NPS {summary_nps} does not match rows {expected_nps}")
    for row, required_depth in zip(rows, required_depths):
        row["exact"] = row["completed_depth"] >= required_depth
    return rows


def effective_query(board: str, side: str) -> tuple[str, int]:
    if legal_moves(board, side):
        return side, 1
    if legal_moves(board, other(side)):
        return other(side), -1
    die("terminal positions must not be sent to Egaroucid")


def to_egaroucid_problem(board: str, side: str) -> str:
    if not BOARD_RE.fullmatch(board):
        die("board must contain exactly 64 characters from B, W, and .")
    opponent = other(side)
    cells = "".join("X" if cell == side else "O" if cell == opponent else "-" for cell in board)
    return cells + "X"


def run_solve(
    queries: list[tuple[str, str]],
    binary: Path,
    cwd: Path,
    profile: OracleProfile,
    timeout: float,
    *,
    child_query: bool,
) -> list[dict[str, object]]:
    validate_profile(profile)
    validate_budget(1, timeout)
    if not queries:
        return []
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="reversi-ai-oracle-", suffix=".txt", encoding="ascii", delete=False
    ) as problem:
        problem_path = Path(problem.name)
        for board, side in queries:
            # -solve consumes the same a1-through-h8 order as the public GTP
            # display; only the alphabet and side perspective need conversion.
            problem.write(to_egaroucid_problem(board, side) + "\n")
    try:
        result = run_external(
            oracle_argv(binary, profile, solve_path=problem_path, child_query=child_query),
            cwd=cwd,
            timeout=timeout,
        )
        # Egaroucid's pinned search decrements depth for placements but not
        # for a forced pass, so empty squares are its remaining exact depth.
        required_depths = [min(board.count("."), profile_depth_at(profile, board.count("B") + board.count("W") - (1 if child_query else 0))) for board, _ in queries]
        rows = parse_solve_output(result.stdout, required_depths, profile)
        for (board, side), row in zip(queries, rows):
            if str(row["move"]) not in legal_moves(board, side):
                die(f"Egaroucid returned an illegal continuation move for {side}: {row['move']!r}")
        return rows
    finally:
        problem_path.unlink(missing_ok=True)


def candidate_move_from_line(line: str, expected_id: str) -> str:
    fields = line.rstrip("\r\n").split("\t")
    if len(fields) != 2 or fields[0] != expected_id:
        die(f"candidate protocol response does not match {expected_id!r}: {line!r}")
    move = fields[1].lower()
    if move != "pass" and not COORDINATE_RE.fullmatch(move):
        die(f"candidate returned an invalid move: {move!r}")
    return move


class TimedLineReader:
    def __init__(self, stream: object) -> None:
        self.stream = stream
        self.buffer = bytearray()
        self.fd = stream.fileno()

    def read_line(self, timeout: float, timeout_message: str, eof_message: str) -> str:
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                die(timeout_message)
            ready, _, _ = select.select([self.fd], [], [], remaining)
            if not ready:
                die(timeout_message)
            try:
                chunk = os.read(self.fd, 4096)
            except OSError as exc:
                die(f"protocol pipe read failed: {exc}")
            if not chunk:
                die(eof_message)
            if len(self.buffer) + len(chunk) > MAX_PROTOCOL_LINE_BYTES:
                die(f"protocol response line exceeds {MAX_PROTOCOL_LINE_BYTES} bytes")
            self.buffer.extend(chunk)

        newline = self.buffer.index(b"\n")
        raw_line = bytes(self.buffer[:newline])
        del self.buffer[: newline + 1]
        try:
            return raw_line.rstrip(b"\r").decode("ascii")
        except UnicodeDecodeError:
            die("protocol response is not ASCII")


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def gtp_move_from_response(response: list[str], command: str) -> str:
    fields = response[0].split()
    if len(fields) != 2:
        die(f"oracle GTP response has no move token for {command!r}: {response!r}")
    move = fields[1].lower()
    if move != "pass" and not COORDINATE_RE.fullmatch(move):
        die(f"oracle GTP response has an invalid move for {command!r}: {response!r}")
    return move


class CandidateSession:
    def __init__(self, command: str, cwd: Path, timeout: float) -> None:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            die(f"invalid candidate command: {exc}")
        if not argv:
            die("candidate command is empty")
        try:
            self.process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                text=False,
                bufsize=0,
                start_new_session=True,
            )
        except OSError as exc:
            die(f"unable to start candidate command: {exc}")
        self.timeout = timeout
        assert self.process.stdout is not None
        self.reader = TimedLineReader(self.process.stdout)

    def move(self, position_id: str, board: str, side: str) -> str:
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(f"{position_id}\t{board}\t{side}\n".encode("ascii"))
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            die(f"candidate command pipe failed for {position_id!r}: {exc}")
        line = self.reader.read_line(
            self.timeout,
            f"candidate command timed out after {self.timeout:g}s",
            f"candidate command exited before answering {position_id!r}",
        )
        return candidate_move_from_line(line, position_id)

    def close(self) -> None:
        terminate_process_group(self.process)
        if self.process.stdin:
            self.process.stdin.close()
        if self.process.stdout:
            self.process.stdout.close()


def analyze_records(
    records: list[dict[str, object]],
    binary: Path,
    cwd: Path,
    profile: OracleProfile,
    timeout: float,
    candidate_command: str | None,
) -> list[dict[str, object]]:
    validate_profile(profile)
    candidate = (
        CandidateSession(candidate_command, repo_root(), timeout) if candidate_command else None
    )
    try:
        selected: dict[str, str] = {}
        if candidate:
            for record in records:
                position_id = str(record["position_id"])
                selected[position_id] = candidate.move(
                    position_id, str(record["board"]), str(record["side_to_move"])
                )

        child_queries: list[tuple[str, str]] = []
        child_meta: list[tuple[str, int, str, int]] = []
        pass_queries: list[tuple[str, str]] = []
        pass_meta: list[tuple[str, int, str, int]] = []
        evaluations_by_position: dict[str, list[dict[str, object] | None]] = {}
        for record in records:
            board = str(record["board"])
            side = str(record["side_to_move"])
            legal = list(record["legal_moves"])
            position_id = str(record["position_id"])
            evaluations_by_position[position_id] = [None] * (len(legal) or (1 if record["outcome"]["kind"] == "Pass" else 0))
            if legal:
                for move_index, move in enumerate(legal):
                    child = apply_move(board, side, str(move))
                    child_side = other(side)
                    if not legal_moves(child, child_side) and not legal_moves(child, other(child_side)):
                        black = child.count("B")
                        white = child.count("W")
                        terminal_value = black - white if side == "B" else white - black
                        evaluations_by_position[position_id][move_index] = {
                            "move": move,
                            "value": terminal_value,
                            "completed_depth": 0,
                            "nodes": 0,
                            "elapsed_ms": 0,
                            "exact": True,
                        }
                        continue
                    effective_side, sign = effective_query(child, child_side)
                    child_queries.append((child, effective_side))
                    child_meta.append((position_id, move_index, str(move), -sign))
            elif record["outcome"]["kind"] == "Pass":
                effective_side, sign = effective_query(board, side)
                pass_queries.append((board, effective_side))
                pass_meta.append((position_id, 0, "pass", sign))

        for query_meta, raw_results in (
            (child_meta, run_solve(child_queries, binary, cwd, profile, timeout, child_query=True)),
            (pass_meta, run_solve(pass_queries, binary, cwd, profile, timeout, child_query=False)),
        ):
            for (position_id, move_index, move, sign), raw in zip(query_meta, raw_results):
                evaluation = {
                    "move": move,
                    "value": sign * int(raw["value"]),
                    "completed_depth": raw["completed_depth"],
                    "nodes": raw["nodes"],
                    "elapsed_ms": raw["elapsed_ms"],
                    "exact": raw["exact"],
                }
                evaluations_by_position[position_id][move_index] = evaluation

        reports: list[dict[str, object]] = []
        for record in records:
            position_id = str(record["position_id"])
            board = str(record["board"])
            side = str(record["side_to_move"])
            legal = list(record["legal_moves"])
            evaluations = evaluations_by_position[position_id]
            if any(evaluation is None for evaluation in evaluations):
                die(f"missing oracle evaluation for {position_id!r}")
            evaluations = [evaluation for evaluation in evaluations if evaluation is not None]
            if legal:
                if len(evaluations) != len(legal):
                    die(f"incomplete root-move set for {position_id!r}")
                best_value = max(int(item["value"]) for item in evaluations)
                optimal_moves = [
                    str(item["move"]) for item in evaluations if int(item["value"]) == best_value
                ]
            elif record["outcome"]["kind"] == "Pass":
                if len(evaluations) != 1 or evaluations[0]["move"] != "pass":
                    die(f"missing pass evaluation for {position_id!r}")
                best_value = int(evaluations[0]["value"])
                optimal_moves = []
            else:
                black = board.count("B")
                white = board.count("W")
                best_value = black - white if side == "B" else white - black
                optimal_moves = []

            analysis: dict[str, object] = {
                "best_value": best_value,
                "optimal_moves": optimal_moves,
                "evaluations": evaluations,
            }
            if candidate:
                selected_move = selected[position_id]
                if legal and selected_move not in legal:
                    die(f"candidate selected illegal move {selected_move!r} at {position_id!r}")
                if not legal and record["outcome"]["kind"] == "Pass" and selected_move != "pass":
                    die(f"candidate did not pass at forced-pass position {position_id!r}")
                if legal:
                    selected_value = next(
                        int(item["value"]) for item in evaluations if item["move"] == selected_move
                    )
                    analysis.update(
                        {
                            "selected_move": selected_move,
                            "selected_value": selected_value,
                            "regret": best_value - selected_value,
                        }
                    )
                elif record["outcome"]["kind"] == "Pass":
                    analysis.update(
                        {
                            "selected_move": selected_move,
                            "selected_value": best_value,
                            "regret": 0,
                        }
                    )
                else:
                    if selected_move != "pass":
                        die(f"candidate did not pass at game-over position {position_id!r}")
                    analysis.update(
                        {
                            "selected_move": selected_move,
                            "selected_value": best_value,
                            "regret": 0,
                        }
                    )
            reports.append(
                {
                    "schema_version": 1,
                    "position_id": position_id,
                    "board": board,
                    "side_to_move": side,
                    "stone_count": record["stone_count"],
                    "phase": record["phase"],
                    "legal_moves": legal,
                    "outcome": record["outcome"],
                    "provenance": record["provenance"],
                    "profile": profile_metadata(profile),
                    "analysis": analysis,
                }
            )
        return reports
    finally:
        if candidate:
            candidate.close()


def golden_projection(reports: list[dict[str, object]]) -> list[dict[str, object]]:
    projected = copy.deepcopy(reports)
    for report in projected:
        analysis = report["analysis"]
        for evaluation in analysis["evaluations"]:
            evaluation.pop("elapsed_ms", None)
    return projected


def initial_board() -> str:
    cells = list("." * 64)
    cells[27], cells[28], cells[35], cells[36] = "W", "B", "B", "W"
    return "".join(cells)


def replay_console_move(board: str, side: str, move: str) -> tuple[str, str]:
    """Apply a coordinate while mirroring Console self-play's implicit pass."""
    legal = legal_moves(board, side)
    if move not in legal and not legal:
        if not legal_moves(board, other(side)):
            die("benchmark self-play transcript continues after game over")
        side = other(side)
    if move not in legal_moves(board, side):
        die(f"benchmark self-play transcript has illegal move {move!r}")
    return apply_move(board, side, move), other(side)


def benchmark_records_from_transcript(transcript: str, game_index: int) -> list[dict[str, object]]:
    """Replay one Console self-play transcript and retain the workload roots."""
    board, side = initial_board(), "B"
    records: list[dict[str, object]] = []
    if len(transcript) % 2:
        die(f"benchmark self-play transcript {game_index} has odd length")
    for offset in range(0, len(transcript), 2):
        move = transcript[offset:offset + 2].lower()
        try:
            board, side = replay_console_move(board, side, move)
        except OracleError as exc:
            die(f"benchmark self-play transcript {game_index}: {exc}")
        stones = sum(cell != "." for cell in board)
        if stones in (20, 40, 44, 48):
            records.append(
                {
                    "schema_version": 1,
                    "position_id": f"self-play-{game_index}-{stones}",
                    "board": board,
                    "side_to_move": side,
                    "stone_count": stones,
                    "phase": phase_for(board),
                    "legal_moves": legal_moves(board, side),
                    "outcome": outcome_for(board, side),
                    "provenance": {
                        "source": SEARCH_PERFORMANCE_SELF_PLAY_V1.name,
                        "source_game": game_index,
                        "game_record": transcript,
                        "transcript": transcript,
                        "generator": "tools/reversi-ai-oracle/oracle.py",
                    },
                }
            )
    if legal_moves(board, side) or legal_moves(board, other(side)):
        die(f"benchmark self-play transcript {game_index} ends before game over")
    if len(records) != 4:
        die(
            f"benchmark self-play transcript {game_index} did not reach all roots; "
            f"captured {[record['stone_count'] for record in records]!r}"
        )
    return records


def run_fast_self_play(binary: Path, cwd: Path, games: int, timeout: float) -> list[dict[str, object]]:
    """Use Console's reproducible transcript mode, rather than the GTP game loop."""
    profile = profile_from_name(SEARCH_PERFORMANCE_SELF_PLAY_V1.name)
    command = oracle_argv(binary, profile) + ["-quiet", "-selfplay", str(games), "6"]
    try:
        completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        die(f"benchmark self-play timed out after {timeout:g}s")
    if completed.returncode:
        die(f"benchmark self-play failed: {completed.stderr.strip()}")
    transcripts = [
        line.strip().upper()
        for line in completed.stdout.splitlines()
        if re.fullmatch(r"(?:[a-h][1-8])+", line.strip(), re.IGNORECASE)
    ]
    if len(transcripts) != games:
        die(
            f"benchmark self-play expected {games} transcripts, got {len(transcripts)}; "
            f"stdout={completed.stdout[:500]!r}; stderr={completed.stderr[:500]!r}"
        )
    return [
        record
        for index, transcript in enumerate(transcripts, 1)
        for record in benchmark_records_from_transcript(transcript, index)
    ]


class GtpSession:
    def __init__(self, binary: Path, cwd: Path, profile: OracleProfile, timeout: float) -> None:
        validate_profile(profile)
        try:
            self.process = subprocess.Popen(
                oracle_argv(binary, profile, gtp=True),
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                text=False,
                bufsize=0,
            )
        except OSError as exc:
            die(f"unable to start oracle GTP process: {exc}")
        self.timeout = timeout
        self.failed = False
        assert self.process.stdout is not None
        self.reader = TimedLineReader(self.process.stdout)

    def command(self, command: str) -> list[str]:
        assert self.process.stdin is not None
        try:
            self.process.stdin.write((command + "\n").encode("ascii"))
            self.process.stdin.flush()
            deadline = time.monotonic() + self.timeout
            timeout_message = f"oracle GTP command timed out after {self.timeout:g}s"

            def remaining_timeout() -> float:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    die(timeout_message)
                return remaining

            response = [
                self.reader.read_line(
                    remaining_timeout(),
                    timeout_message,
                    "oracle GTP process exited unexpectedly",
                )
            ]
            while True:
                # The GTP protocol terminates every response with a blank line.
                line = self.reader.read_line(
                    remaining_timeout(),
                    timeout_message,
                    "oracle GTP process exited before completing its response",
                )
                if not line:
                    break
                response.append(line)
                if len(response) >= MAX_GTP_RESPONSE_LINES:
                    die(f"oracle GTP response has too many lines for {command!r}")
            if not response or not response[0].startswith(("=", "?")):
                die(f"invalid oracle GTP response to {command!r}: {response!r}")
            if response[0].startswith("?"):
                die(f"oracle GTP command failed: {command!r}: {' '.join(response)}")
            return response
        except OracleError:
            self.failed = True
            raise
        except (OSError, ValueError) as exc:
            self.failed = True
            die(f"oracle GTP pipe failed for {command!r}: {exc}")

    def close(self) -> None:
        if not self.failed and self.process.poll() is None:
            try:
                self.command("quit")
            except OracleError:
                pass
        try:
            self.process.terminate()
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass


def run_match(
    binary: Path,
    cwd: Path,
    candidate_command: str,
    games: int,
    profile: OracleProfile,
    timeout: float,
) -> dict[str, object]:
    validate_profile(profile)
    validate_budget(1, timeout)
    if games < 1:
        die("match requires at least one game")
    candidate = CandidateSession(candidate_command, repo_root(), timeout)
    game_reports: list[dict[str, object]] = []
    try:
        for game_index in range(games):
            oracle = GtpSession(binary, cwd, profile, timeout)
            try:
                board = "".join("........" for _ in range(8))
                cells = list(board)
                cells[27], cells[28], cells[35], cells[36] = "W", "B", "B", "W"
                board = "".join(cells)
                side = "B"
                candidate_side = "B" if game_index % 2 == 0 else "W"
                passes = 0
                moves_played = 0
                history: list[str] = []
                while True:
                    moves = legal_moves(board, side)
                    oracle_pass = False
                    if not moves:
                        if not legal_moves(board, other(side)):
                            break
                        passes += 1
                        if passes == 2:
                            die("match reached two consecutive passes")
                        move = "pass"
                        oracle_pass = side != candidate_side
                    else:
                        passes = 0
                        if side == candidate_side:
                            move = candidate.move(
                                f"match-{game_index}-{moves_played}", board, side
                            )
                            if move not in moves:
                                die(f"candidate selected illegal move {move!r} in match")
                        else:
                            command = f"genmove {'black' if side == 'B' else 'white'}"
                            response = oracle.command(command)
                            move = gtp_move_from_response(response, command)
                            if move == "pass":
                                die("oracle passed despite having a legal move")
                            if move not in moves:
                                die(f"oracle selected illegal move {move!r} in match")

                    if side == candidate_side:
                        if move == "pass":
                            oracle.command(f"play {'black' if side == 'B' else 'white'} PASS")
                        else:
                            oracle.command(f"play {'black' if side == 'B' else 'white'} {move}")
                    elif oracle_pass:
                        # Egaroucid v7.8.1 does not advance its GTP state for a
                        # pass, so apply the oracle pass once.
                        oracle.command(f"play {'black' if side == 'B' else 'white'} PASS")
                    if move != "pass":
                        board = apply_move(board, side, move)
                        moves_played += 1
                        history.append(move)
                    else:
                        history.append("PS")
                    side = other(side)

                black = board.count("B")
                white = board.count("W")
                candidate_score = black if candidate_side == "B" else white
                oracle_score = white if candidate_side == "B" else black
                result = "draw" if candidate_score == oracle_score else (
                    "candidate_win" if candidate_score > oracle_score else "oracle_win"
                )
                game_reports.append(
                    {
                        "game": game_index + 1,
                        "candidate_side": candidate_side,
                        "oracle_side": other(candidate_side),
                        "black": black,
                        "white": white,
                        "candidate_score": candidate_score,
                        "oracle_score": oracle_score,
                        "result": result,
                        "moves": moves_played,
                        "game_record": "".join(history),
                    }
                )
            finally:
                oracle.close()
    finally:
        candidate.close()

    counts = {"candidate_win": 0, "oracle_win": 0, "draw": 0}
    for report in game_reports:
        counts[str(report["result"])] += 1
    return {
        "schema_version": 1,
        "profile": profile_metadata(profile),
        "games": games,
        "summary": counts,
        "results": game_reports,
    }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_paths() -> tuple[Path, Path]:
    tool_dir = Path(__file__).resolve().parent
    return tool_dir / "corpus.jsonl", tool_dir / "golden.jsonl"


def command_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate-corpus")
    generate.add_argument("--output", type=Path, default=default_paths()[0])

    benchmark = subparsers.add_parser("generate-benchmark-corpus")
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)

    setup = subparsers.add_parser("setup-oracle")
    setup.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)

    benchmark_verify = subparsers.add_parser("verify-benchmark-corpus")
    benchmark_verify.add_argument("--corpus", type=Path, required=True)

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--corpus", type=Path, default=default_paths()[0])
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--profile", choices=sorted(PROFILES), default=CI_SMOKE_V1.name)
    analyze.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    analyze.add_argument("--candidate-command")

    golden = subparsers.add_parser("generate-golden")
    golden.add_argument("--corpus", type=Path, default=default_paths()[0])
    golden.add_argument("--output", type=Path, default=default_paths()[1])
    golden.add_argument("--profile", choices=sorted(PROFILES), default=CI_SMOKE_V1.name)
    golden.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--corpus", type=Path, default=default_paths()[0])
    verify.add_argument("--golden", type=Path, default=default_paths()[1])
    verify.add_argument("--profile", choices=sorted(PROFILES), default=CI_SMOKE_V1.name)
    verify.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)

    match = subparsers.add_parser("match")
    match.add_argument("--candidate-command", required=True)
    match.add_argument("--games", type=int, default=2)
    match.add_argument("--profile", choices=sorted(PROFILES), default=CI_SMOKE_V1.name)
    match.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    match.add_argument("--output", type=Path)

    ci = subparsers.add_parser("ci")
    ci.add_argument("--corpus", type=Path, default=default_paths()[0])
    ci.add_argument("--golden", type=Path, default=default_paths()[1])
    ci.add_argument("--profile", choices=sorted(PROFILES), default=CI_SMOKE_V1.name)
    ci.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    ci.add_argument("--candidate-command", required=True)
    ci.add_argument("--games", type=int, default=2)
    ci.add_argument("--match-timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    ci.add_argument("--match-output", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "generate-corpus":
            records = generate_corpus()
            validate_corpus(records)
            write_jsonl(args.output, records)
            print(f"wrote {len(records)} corpus positions to {args.output}")
            return 0

        if args.command == "setup-oracle":
            validate_budget(1, args.timeout)
            binary, _ = ensure_oracle(args.timeout)
            print(f"verified pinned Egaroucid v{ORACLE_VERSION}: {binary}")
            return 0

        if args.command == "verify-benchmark-corpus":
            records = load_canonical_jsonl(args.corpus)
            validate_benchmark_corpus(records)
            print(f"verified {len(records)} benchmark positions")
            return 0

        if args.command == "generate-benchmark-corpus":
            validate_budget(1, args.timeout)
            binary, cwd = ensure_oracle(args.timeout)
            records = run_fast_self_play(binary, cwd, 4, args.timeout)
            validate_benchmark_corpus(records)
            write_jsonl(args.output, records)
            print(f"wrote {len(records)} benchmark positions to {args.output}")
            return 0

        if args.command == "verify":
            profile = profile_from_name(args.profile)
            validate_budget(1, args.timeout)
            records = load_jsonl(args.corpus)
            validate_corpus(records)
            binary, cwd = ensure_oracle(args.timeout)
            reports = analyze_records(records, binary, cwd, profile, args.timeout, None)
            actual = golden_projection(reports)
            expected = load_jsonl(args.golden)
            if [canonical_json(item) for item in actual] != [canonical_json(item) for item in expected]:
                die(f"normalized oracle report differs from golden: {args.golden}")
            print(f"verified {len(reports)} normalized oracle reports")
            return 0

        if args.command == "generate-golden":
            profile = profile_from_name(args.profile)
            validate_budget(1, args.timeout)
            records = load_jsonl(args.corpus)
            validate_corpus(records)
            binary, cwd = ensure_oracle(args.timeout)
            reports = analyze_records(records, binary, cwd, profile, args.timeout, None)
            write_jsonl(args.output, golden_projection(reports))
            print(f"wrote {len(reports)} golden oracle reports to {args.output}")
            return 0

        if args.command == "analyze":
            profile = profile_from_name(args.profile)
            validate_budget(1, args.timeout)
            records = load_jsonl(args.corpus)
            validate_corpus(records)
            binary, cwd = ensure_oracle(args.timeout)
            reports = analyze_records(
                records, binary, cwd, profile, args.timeout, args.candidate_command
            )
            write_jsonl(args.output, reports)
            print(f"wrote {len(reports)} oracle reports to {args.output}")
            return 0

        if args.command == "match":
            profile = profile_from_name(args.profile)
            validate_budget(1, args.timeout)
            binary, cwd = ensure_oracle(args.timeout)
            summary = run_match(
                binary, cwd, args.candidate_command, args.games, profile, args.timeout
            )
            output = canonical_json(summary)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(output + "\n", encoding="utf-8")
            print(output)
            return 0

        if args.command == "ci":
            profile = profile_from_name(args.profile)
            validate_budget(1, args.timeout)
            validate_budget(1, args.match_timeout)
            records = load_jsonl(args.corpus)
            validate_corpus(records)
            binary, cwd = ensure_oracle(max(args.timeout, args.match_timeout))
            reports = analyze_records(records, binary, cwd, profile, args.timeout, None)
            actual = golden_projection(reports)
            expected = load_jsonl(args.golden)
            if [canonical_json(item) for item in actual] != [canonical_json(item) for item in expected]:
                die(f"normalized oracle report differs from golden: {args.golden}")
            print(f"verified {len(reports)} normalized oracle reports")
            summary = run_match(
                binary,
                cwd,
                args.candidate_command,
                args.games,
                profile,
                args.match_timeout,
            )
            output = canonical_json(summary)
            if args.match_output:
                args.match_output.parent.mkdir(parents=True, exist_ok=True)
                args.match_output.write_text(output + "\n", encoding="utf-8")
            print(output)
            return 0
    except OracleError as exc:
        print(f"reversi-ai-oracle: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(command_main(sys.argv[1:]))
