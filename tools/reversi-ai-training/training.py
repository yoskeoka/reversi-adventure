#!/usr/bin/env python3
"""Deterministically train and validate a sparse Reversi pattern artifact.

This intentionally uses only the Python standard library.  It is an offline
producer: the JSON artifact is validated here but is not a game runtime input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1
TRAINER_VERSION = "reversi-ai-pattern-training-v1"
FEATURE_COUNT = 64
PHASE_COUNT = 60
SCORE_SCALE = "final_disc_difference"
TARGET_SEMANTICS = "final_disc_difference_for_side"
SPLITS = {"train", "validation", "held_out"}
BASE_PATTERNS = (
    (0, 1, 2, 8, 9, 16, 17, 18),
    (0, 1, 2, 3, 8, 9, 10, 16, 17, 24),
    (0, 1, 2, 3, 4, 5, 6, 7),
    (1, 2, 3, 9, 10, 11, 17, 18, 19, 25),
    (2, 3, 4, 10, 11, 12, 18, 19, 20, 26),
    (9, 10, 11, 12, 13, 17, 18, 19, 20, 21),
    (18, 19, 20, 21, 26, 27, 28, 29, 34, 35),
    (3, 4, 11, 12, 19, 20, 27, 28, 35, 36),
)


class TrainingError(ValueError):
    """A malformed input or unsafe artifact.  All callers fail closed."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(), parse_constant=lambda value: (_ for _ in ()).throw(TrainingError(f"non-finite JSON value {value}")))
    except (OSError, json.JSONDecodeError) as error:
        raise TrainingError(f"cannot read {path}: {error}") from error


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text().splitlines()
    except OSError as error:
        raise TrainingError(f"cannot read {path}: {error}") from error
    records = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(TrainingError(f"non-finite JSON value {value}")))
        except (TrainingError, json.JSONDecodeError) as error:
            raise TrainingError(f"{path}:{line_number}: invalid JSON: {error}") from error
        if not isinstance(record, dict):
            raise TrainingError(f"{path}:{line_number}: record must be an object")
        records.append(record)
    return records


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transform(square: int, symmetry: int) -> int:
    row, col = divmod(square, 8)
    transforms = ((row, col), (col, 7-row), (7-row, 7-col), (7-col, row),
                  (row, 7-col), (7-row, col), (col, row), (7-col, 7-row))
    out_row, out_col = transforms[symmetry]
    return out_row * 8 + out_col


def inverse(symmetry: int) -> int:
    return (0, 3, 2, 1, 4, 5, 6, 7)[symmetry]


def catalog() -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(transform(square, symmetry) for square in pattern)
                 for pattern in BASE_PATTERNS for symmetry in range(8))


CATALOG = catalog()


def catalog_digest() -> str:
    value = 0xCBF29CE484222325
    for pattern in CATALOG:
        value = (value ^ len(pattern)) * 0x100000001B3 & 0xFFFFFFFFFFFFFFFF
        for square in pattern:
            value = (value ^ square) * 0x100000001B3 & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def require_int(value: Any, name: str, lower: int | None = None, upper: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrainingError(f"{name} must be an integer")
    if lower is not None and value < lower or upper is not None and value > upper:
        raise TrainingError(f"{name} is outside its allowed range")
    return value


def require_decimal_key(value: Any, name: str, lower: int | None = None, upper: int | None = None) -> int:
    if not isinstance(value, str) or not value.isdecimal() or (len(value) > 1 and value.startswith("0")):
        raise TrainingError(f"{name} must be a canonical decimal integer key")
    return require_int(int(value), name, lower, upper)


def parse_position(value: dict[str, Any], context: str) -> tuple[str, str, int]:
    board, side = value.get("board"), value.get("side")
    if not isinstance(board, str) or len(board) != 64 or any(cell not in "BW." for cell in board):
        raise TrainingError(f"{context}.board must be a 64-character B/W/. board")
    if side not in ("B", "W"):
        raise TrainingError(f"{context}.side must be B or W")
    occupied = sum(cell != "." for cell in board)
    if not 4 <= occupied <= 63:
        raise TrainingError(f"{context}.board must have 4 through 63 occupied discs")
    target = value.get("target")
    if not isinstance(target, dict) or target.get("semantics") != TARGET_SEMANTICS:
        raise TrainingError(f"{context}.target semantics are unsupported")
    return board, side, require_int(target.get("value"), f"{context}.target.value", -64, 64)


def board_key(board: str, symmetry: int) -> str:
    inv = inverse(symmetry)
    return "".join(board[transform(square, inv)] for square in range(64))


def canonical_position_key(board: str, side: str) -> str:
    return min(board_key(board, symmetry) for symmetry in range(8)) + ":" + side


def extract_features(board: str, side: str) -> tuple[int, list[int]]:
    symmetry = min(range(8), key=lambda candidate: board_key(board, candidate))
    inv = inverse(symmetry)
    values = []
    for pattern in CATALOG:
        code = 0
        for square in pattern:
            cell = board[transform(square, inv)]
            code = code * 3 + (0 if cell == "." else 1 if cell == side else 2)
        values.append(code)
    return sum(cell != "." for cell in board) - 4, values


def validate_manifest(manifest: dict[str, Any], root: Path) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    if manifest.get("schema_version") != FORMAT_VERSION or manifest.get("trainer_version") != TRAINER_VERSION:
        raise TrainingError("unsupported manifest schema or trainer version")
    require_int(manifest.get("seed"), "manifest.seed", 0)
    feature = manifest.get("feature_contract")
    if feature != {"format_version": FORMAT_VERSION, "catalog_digest": catalog_digest(), "phase_count": PHASE_COUNT, "score_scale": SCORE_SCALE}:
        raise TrainingError("manifest feature contract does not match the project contract")
    optimizer = manifest.get("optimizer")
    if optimizer != {"name": "sparse_mean_v1", "normalization_divisor": FEATURE_COUNT}:
        raise TrainingError("unsupported optimizer configuration")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise TrainingError("manifest.inputs must be a non-empty list")
    loaded = []
    for entry in inputs:
        if not isinstance(entry, dict):
            raise TrainingError("manifest input must be an object")
        path_text, expected = entry.get("path"), entry.get("sha256")
        if not isinstance(path_text, str) or not isinstance(expected, str) or len(expected) != 64:
            raise TrainingError("manifest input requires path and SHA-256")
        if not all(isinstance(entry.get(field), str) and entry[field] for field in ("source", "license", "source_digest")):
            raise TrainingError("manifest input requires source, license, and source_digest")
        path = root / path_text
        if not path.is_file() or sha256_file(path) != expected:
            raise TrainingError(f"input digest mismatch: {path_text}")
        loaded.append((entry, read_jsonl(path)))
    return loaded


def validate_records(loaded: list[tuple[dict[str, Any], list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    result, seen = [], set()
    for input_entry, records in loaded:
        for record in records:
            if record.get("schema_version") != FORMAT_VERSION or not isinstance(record.get("record_id"), str):
                raise TrainingError("record schema_version and record_id are required")
            if any(record.get(key) != input_entry[key] for key in ("source", "license", "source_digest")):
                raise TrainingError(f"record {record.get('record_id')} provenance differs from its manifest input")
            split = record.get("split")
            if split not in SPLITS:
                raise TrainingError(f"record {record['record_id']} has invalid split")
            board, side, target = parse_position(record, f"record {record['record_id']}")
            key = canonical_position_key(board, side)
            if key in seen:
                raise TrainingError(f"duplicate or symmetry-leaking position: {record['record_id']}")
            seen.add(key)
            candidates = record.get("candidates", [])
            if not isinstance(candidates, list):
                raise TrainingError(f"record {record['record_id']}.candidates must be a list")
            parsed_candidates = []
            for candidate in candidates:
                if not isinstance(candidate, dict) or not isinstance(candidate.get("move"), str):
                    raise TrainingError(f"record {record['record_id']} has invalid candidate")
                parsed_candidates.append(parse_position(candidate, f"record {record['record_id']}.candidate"))
            result.append({"id": record["record_id"], "split": split, "board": board, "side": side,
                           "target": target, "candidates": parsed_candidates})
    if not any(record["split"] == "train" for record in result):
        raise TrainingError("inputs contain no training records")
    return result


def round_division(total: int, divisor: int) -> int:
    return (total + divisor // 2) // divisor if total >= 0 else -((-total + divisor // 2) // divisor)


def train_weights(records: list[dict[str, Any]]) -> dict[str, list[dict[str, int]]]:
    sums: dict[tuple[int, int, int], list[int]] = defaultdict(lambda: [0, 0])
    for record in records:
        if record["split"] != "train":
            continue
        phase, values = extract_features(record["board"], record["side"])
        for feature, code in enumerate(values):
            aggregate = sums[(phase, feature, code)]
            aggregate[0] += record["target"]
            aggregate[1] += 1
    tables: dict[str, list[dict[str, int]]] = {}
    for (phase, feature, code), (total, count) in sorted(sums.items()):
        weight = max(-1, min(1, round_division(total, count * FEATURE_COUNT)))
        if weight:
            phase_table = tables.setdefault(str(phase), [dict() for _ in range(FEATURE_COUNT)])
            phase_table[feature][str(code)] = weight
    return tables


def predict(weights: dict[str, list[dict[str, int]]], board: str, side: str) -> int:
    phase, values = extract_features(board, side)
    score = sum(weights.get(str(phase), [{} for _ in range(FEATURE_COUNT)])[feature].get(str(code), 0)
                for feature, code in enumerate(values))
    if not -64 <= score <= 64:
        raise TrainingError("artifact prediction exceeds final-disc-difference score range")
    return score


def artifact_from(manifest: dict[str, Any], records: list[dict[str, Any]], manifest_digest: str) -> dict[str, Any]:
    random.Random(manifest["seed"])  # pins the stochastic boundary for future optimizer versions.
    weights = train_weights(records)
    bounds = [0] * FEATURE_COUNT
    for tables in weights.values():
        for index, table in enumerate(tables):
            if table:
                bounds[index] = max(abs(value) for value in table.values())
    artifact = {"format_version": FORMAT_VERSION, "feature_contract": manifest["feature_contract"],
                "provenance": {"trainer_version": TRAINER_VERSION, "input_manifest_digest": manifest_digest,
                               "licenses": sorted({entry["license"] for entry in manifest["inputs"]}),
                               "seed": manifest["seed"], "optimizer": manifest["optimizer"]},
                "feature_max_abs": bounds, "weights": weights, "weight_digest": digest(weights)}
    artifact["artifact_digest"] = digest(artifact)
    return artifact


def validate_artifact(artifact: dict[str, Any]) -> None:
    if artifact.get("format_version") != FORMAT_VERSION or artifact.get("feature_contract") != {"format_version": FORMAT_VERSION, "catalog_digest": catalog_digest(), "phase_count": PHASE_COUNT, "score_scale": SCORE_SCALE}:
        raise TrainingError("artifact feature contract mismatch")
    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("trainer_version") != TRAINER_VERSION:
        raise TrainingError("artifact provenance is incomplete")
    manifest_digest = provenance.get("input_manifest_digest")
    if not isinstance(manifest_digest, str) or len(manifest_digest) != 64 or any(character not in "0123456789abcdef" for character in manifest_digest):
        raise TrainingError("artifact provenance has an invalid input manifest digest")
    require_int(provenance.get("seed"), "artifact provenance seed", 0)
    if provenance.get("optimizer") != {"name": "sparse_mean_v1", "normalization_divisor": FEATURE_COUNT}:
        raise TrainingError("artifact provenance has an unsupported optimizer")
    licenses = provenance.get("licenses")
    if not isinstance(licenses, list) or not licenses or any(not isinstance(license_name, str) or not license_name for license_name in licenses):
        raise TrainingError("artifact provenance has invalid licenses")
    bounds, weights = artifact.get("feature_max_abs"), artifact.get("weights")
    if not isinstance(bounds, list) or len(bounds) != FEATURE_COUNT or any(require_int(value, "feature bound", 0, 1) != value for value in bounds) or sum(bounds) > 64:
        raise TrainingError("artifact feature bounds are unsafe")
    if not isinstance(weights, dict) or artifact.get("weight_digest") != digest(weights):
        raise TrainingError("artifact weight digest mismatch")
    for phase, tables in weights.items():
        require_decimal_key(phase, "weight phase", 0, PHASE_COUNT - 1)
        if not isinstance(tables, list) or len(tables) != FEATURE_COUNT:
            raise TrainingError("artifact tables have an invalid feature count")
        for feature, table in enumerate(tables):
            if not isinstance(table, dict):
                raise TrainingError("artifact feature table is invalid")
            for code, value in table.items():
                require_decimal_key(code, "feature code", 0)
                require_int(value, "weight", -bounds[feature], bounds[feature])
    expected = dict(artifact)
    actual = expected.pop("artifact_digest", None)
    if actual != digest(expected):
        raise TrainingError("artifact digest mismatch")


def validation_report(artifact: dict[str, Any], records: list[dict[str, Any]], manifest_digest: str) -> dict[str, Any]:
    weights = artifact["weights"]
    phases: dict[str, dict[str, float | int | None]] = {}
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["split"] == "held_out":
            buckets[extract_features(record["board"], record["side"])[0]].append(record)
    for phase, rows in sorted(buckets.items()):
        errors, agreements, candidates = [], 0, 0
        for row in rows:
            predicted = predict(weights, row["board"], row["side"])
            errors.append(predicted - row["target"])
            if row["candidates"]:
                selected = max(((predict(weights, board, side), index) for index, (board, side, _) in enumerate(row["candidates"])), key=lambda item: (item[0], -item[1]))[1]
                best = max(range(len(row["candidates"])), key=lambda index: (row["candidates"][index][2], -index))
                candidates += 1
                agreements += selected == best
        phases[str(phase)] = {"records": len(rows), "mse": sum(error * error for error in errors) / len(errors),
                               "mae": sum(abs(error) for error in errors) / len(errors),
                               "candidate_top_target_agreement": agreements / candidates if candidates else None}
    report = {"format_version": FORMAT_VERSION, "artifact_digest": artifact["artifact_digest"],
              "input_manifest_digest": manifest_digest, "phase_metrics": phases}
    report["report_digest"] = digest(report)
    return report


def run(manifest_path: Path, artifact_path: Path, report_path: Path) -> None:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise TrainingError("manifest must be an object")
    loaded = validate_manifest(manifest, manifest_path.parent)
    records = validate_records(loaded)
    manifest_digest = digest(manifest)
    artifact = artifact_from(manifest, records, manifest_digest)
    validate_artifact(artifact)
    for record in records:
        predict(artifact["weights"], record["board"], record["side"])
    report = validation_report(artifact, records, manifest_digest)
    artifact_path.write_bytes(canonical_json(artifact) + b"\n")
    report_path.write_bytes(canonical_json(report) + b"\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    train = subcommands.add_parser("train")
    train.add_argument("--manifest", type=Path, required=True)
    train.add_argument("--artifact", type=Path, required=True)
    train.add_argument("--report", type=Path, required=True)
    validate = subcommands.add_parser("validate")
    validate.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "train":
            run(args.manifest, args.artifact, args.report)
        else:
            artifact = read_json(args.artifact)
            if not isinstance(artifact, dict):
                raise TrainingError("artifact must be an object")
            validate_artifact(artifact)
    except TrainingError as error:
        print(f"training error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
