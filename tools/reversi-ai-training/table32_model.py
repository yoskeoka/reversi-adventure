"""Independent CPU implementation of the pinned table32 mathematical catalog.

The JSON catalog contains geometry, not upstream executable code or weights.
Sparse global parameter indices preserve the full shared table address space.
"""
from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from pathlib import Path

IDENTITY = "reversi-ai-pattern-table32-v1"
PARTIAL_IDENTITY = "reversi-ai-pattern-table32-partial-v1"
TRAINER = "reversi-ai-table32-training-v1"
OPTIMIZER = "table32_full_batch_adam_v1"
COMBINE_VERSION = "table32-combine-v1"
SCORE_CONTRACT = "winner-empty-v1"
PHASE_COUNT = 60
FEATURE_COUNT = 65
LIMIT = 4091
CATALOG = json.loads((Path(__file__).resolve().parents[2] / "rust/reversi-ai/data/table32-catalog.json").read_text())


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


CATALOG_DIGEST = digest(CATALOG)
SIZES = [3 ** len(t["placements"][0]) for t in CATALOG["tables"]] + [65]
OFFSETS = []
PARAMETER_COUNT = 0
for _size in SIZES:
    OFFSETS.append(PARAMETER_COUNT)
    PARAMETER_COUNT += _size
PLACEMENTS = [[(int(c[1]) - 1) * 8 + ord(c[0]) - ord("a") for c in p]
              for t in CATALOG["tables"] for p in t["placements"]]


def _board(board: str, side: str = "B") -> None:
    if not isinstance(board, str) or len(board) != 64 or set(board) - set("BW.") or side not in ("B", "W"):
        raise ValueError("invalid table32 board/side")
    if not 4 <= 64 - board.count(".") <= 64:
        raise ValueError("table32 board must contain 4..64 discs")


def phase(board: str) -> int:
    _board(board)
    return min(59, 60 - board.count("."))


def features(board: str, side: str) -> list[int]:
    _board(board, side)
    digits = [2 if c == "." else 0 if c == side else 1 for c in board]
    result = []
    for i, placement in enumerate(PLACEMENTS):
        code = 0
        for cell in placement:
            code = code * 3 + digits[cell]
        result.append(OFFSETS[i // 4] + code)
    result.append(OFFSETS[16] + board.count(side))
    return result


def reverse_index(index: int) -> int:
    if type(index) is not int or not 0 <= index < PARAMETER_COUNT:
        raise ValueError("invalid table32 parameter index")
    table = bisect_right(OFFSETS, index) - 1
    if table == 16:
        return index
    code = index - OFFSETS[table]
    digits = []
    for _ in CATALOG["tables"][table]["reverse"]:
        digits.append(code % 3)
        code //= 3
    digits.reverse()
    reverse = 0
    for d in CATALOG["tables"][table]["reverse"]:
        reverse = reverse * 3 + digits[d]
    return OFFSETS[table] + reverse


def runtime_score(raw: int) -> int:
    if type(raw) is not int:
        raise ValueError("table32 raw sum must be integer")
    value = (abs(raw) + 16) // 32
    return max(-64, min(64, -value if raw < 0 else value))


def feature_contract() -> dict:
    return {"catalog_digest": CATALOG_DIGEST, "phase_count": PHASE_COUNT,
            "feature_count": FEATURE_COUNT, "parameter_count": PARAMETER_COUNT,
            "scale": 32, "parameter_limit": LIMIT, "phase": CATALOG["phase"]}


def _sha(value, size=64):
    return isinstance(value, str) and len(value) == size and not set(value) - set("0123456789abcdef")


def make_artifact(phases, provenance: dict) -> dict:
    return _make_artifact(phases, provenance, partial=False)


def make_partial_artifact(phases, provenance: dict) -> dict:
    return _make_artifact(phases, provenance, partial=True)


def _make_artifact(phases, provenance: dict, *, partial: bool) -> dict:
    if isinstance(phases, list):
        phases = dict(enumerate(phases))
    weights = {str(p): {str(i): v for i, v in sorted(rows.items(), key=lambda x: int(x[0])) if v != 0}
               for p, rows in sorted(phases.items(), key=lambda x: int(x[0]))}
    artifact = {"identity": PARTIAL_IDENTITY if partial else IDENTITY, "score_contract": SCORE_CONTRACT,
                "feature_contract": feature_contract(), "provenance": provenance,
                "weights": weights, "weight_digest": digest(weights)}
    artifact["artifact_digest"] = digest(artifact)
    return _validate_artifact(artifact, partial=partial)


def validate_artifact(artifact: dict) -> dict:
    return _validate_artifact(artifact, partial=False)


def validate_partial_artifact(artifact: dict) -> dict:
    return _validate_artifact(artifact, partial=True)


def _validate_artifact(artifact: dict, *, partial: bool) -> dict:
    if not isinstance(artifact, dict):
        raise ValueError("table32 artifact must be an object")
    if artifact.get("identity") != (PARTIAL_IDENTITY if partial else IDENTITY) or artifact.get("score_contract") != SCORE_CONTRACT:
        raise ValueError("table32 identity/score contract mismatch")
    if artifact.get("feature_contract") != feature_contract():
        raise ValueError("table32 feature contract mismatch")
    provenance = artifact.get("provenance", {})
    common = (isinstance(provenance, dict) and _sha(provenance.get("input_manifest_digest"))
              and _sha(provenance.get("producer_commit"), 40))
    trained = (common and provenance.get("trainer_version") == TRAINER and provenance.get("optimizer") == OPTIMIZER
               and provenance.get("source_kind") == "project-owned" and type(provenance.get("seed")) is int
               and 0 <= provenance["seed"] < 2**64)
    combined = (common and set(provenance) == {"source_kind", "combine_version", "input_manifest_digest", "producer_commit"}
                and provenance.get("source_kind") == "combined-project-owned"
                and provenance.get("combine_version") == COMBINE_VERSION)
    if not (trained or combined):
        raise ValueError("invalid table32 provenance")
    weights = artifact.get("weights")
    valid_phases = {str(x) for x in range(60)}
    if not isinstance(weights, dict) or (not weights if partial else set(weights) != valid_phases) or not set(weights) <= valid_phases:
        raise ValueError("table32 requires all 60 learned phases")
    for table in weights.values():
        if not isinstance(table, dict):
            raise ValueError("invalid table32 phase table")
        for key, value in table.items():
            if not key.isascii() or not key.isdecimal() or str(int(key)) != key or not 0 <= int(key) < PARAMETER_COUNT:
                raise ValueError("invalid table32 parameter key")
            if type(value) is not int or not -LIMIT <= value <= LIMIT or value == 0:
                raise ValueError("invalid table32 weight")
            if table.get(str(reverse_index(int(key))), 0) != value:
                raise ValueError("table32 reverse sharing mismatch")
    if artifact.get("weight_digest") != digest(weights):
        raise ValueError("table32 weight digest mismatch")
    content = {k: v for k, v in artifact.items() if k != "artifact_digest"}
    if artifact.get("artifact_digest") != digest(content):
        raise ValueError("table32 artifact digest mismatch")
    return artifact


def predict(artifact: dict, board: str, side: str) -> int:
    table = artifact["weights"][str(phase(board))]
    return runtime_score(sum(table.get(str(i), 0) for i in features(board, side)))


def predict_partial(artifact: dict, board: str, side: str, fallback) -> int:
    current = phase(board)
    selected = next((p for p in range(current, PHASE_COUNT)
                     if str(p) in artifact["weights"]), None)
    if selected is None:
        return fallback(board, side)
    table = artifact["weights"][str(selected)]
    return runtime_score(sum(table.get(str(i), 0) for i in features(board, side)))
