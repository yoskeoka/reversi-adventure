"""Immutable, chained unit receipts shared by execution and offline replay."""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

import training

VERSION = "reversi-ai-table32-pilot-v1"
PHASES = ("input-verification", "teacher-preflight", "generation", "early-labels",
          "extraction", "phase-training", "export", "diagnostics", "match20",
          "explicit-match200", "offline-verification")
LIMITS = {"games": 128, "early_labels": 256, "preflight_decisions": 12,
          "oracle_queries": 24, "training_steps_per_phase": 1000,
          "export_proposals_per_phase": 1000, "matches": 200,
          "wall_seconds": 72 * 3600, "producer_rss_kib": 262144,
          "child_rss_kib": 1572864}
BASELINE_SHA = "13e8bdf59553746ba32ce47b53a09c011eb79223cabf4ddefb224b2640d283de"


def require(condition, message):
    if not condition:
        raise training.TrainingError(message)


def blob(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode() + b"\n"


def digest(value):
    import hashlib
    return hashlib.sha256(blob(value)).hexdigest()


def read(path):
    def invalid(value):
        raise ValueError(f"non-finite JSON: {value}")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"duplicate JSON key {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), parse_constant=invalid, object_pairs_hook=pairs)


def atomic(path, value, *, once=False):
    atomic_bytes(path, blob(value), once=once)


def atomic_bytes(path, data, *, once=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and once:
        require(path.read_bytes() == data, f"immutable output differs: {path}")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+".tmp-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def pin(path):
    path = Path(path).resolve(strict=True)
    require(path.is_file(), f"not a file: {path}")
    return {"path": str(path), "sha256": training.sha256_file(path)}


def check_pin(value):
    require(pin(value["path"]) == value, f"input digest changed: {value['path']}")
    return Path(value["path"])


def inventory(root):
    root = Path(root).resolve(strict=True)
    files = []
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), f"source contains symlink: {path}")
        if path.is_file():
            files.append({"path": path.relative_to(root).as_posix(),
                          "sha256": training.sha256_file(path)})
    require(files, f"source is empty: {root}")
    return {"path": str(root), "files": files, "digest": digest(files)}


def seal(value):
    value = {key: item for key, item in value.items() if key != "digest"}
    return {**value, "digest": digest(value)}


class Journal:
    def __init__(self, root, manifest, every=1):
        require(type(every) is int and every > 0, "progress-every must be positive")
        self.root, self.manifest, self.every = Path(root), manifest, every
        self.started = time.monotonic()
        self.previous = digest(manifest)
        self.cursor = 0
        self.phase = "input-verification"
        self.unit = "start"

    def entries(self):
        folder = self.root / "units"
        paths = sorted(folder.glob("*.json"))
        for index, path in enumerate(paths):
            require(path.name == f"{index:07d}.json", "non-contiguous completed unit prefix")
            entry = read(path)
            require(entry == seal(entry) and entry.get("index") == index
                    and entry.get("manifest_digest") == digest(self.manifest)
                    and entry.get("previous") == self.previous,
                    f"unit receipt chain differs: {path}")
            self.previous = entry["digest"]
            self.cursor = index + 1
            yield entry

    def save(self, phase, unit, value, completed, total):
        require(phase in PHASES, "unknown phase")
        entry = seal({"version": VERSION, "manifest_digest": digest(self.manifest),
                      "index": self.cursor, "previous": self.previous,
                      "phase": phase, "unit": unit, "value": value})
        atomic(self.root / "units" / f"{self.cursor:07d}.json", entry, once=True)
        self.previous, self.cursor = entry["digest"], self.cursor + 1
        self.progress(phase, unit, completed, total, "saved")
        return entry

    def progress(self, phase, unit, completed, total, status):
        import sys
        self.phase, self.unit = phase, unit
        if completed % self.every == 0 or status != "saved" or completed == total:
            print(f"table32 phase={phase} unit={unit} completed={completed} total={total} "
                  f"elapsed_seconds={time.monotonic()-self.started:.3f} status={status}",
                  file=sys.stderr, flush=True)


def match_outcome(points, count):
    require(type(points) in (int, float) and math.isfinite(points)
            and type(count) is int and count in (20, 200)
            and 0 <= points <= count and points * 2 == int(points * 2), "invalid match points")
    if count == 20:
        return "not-improved-at-pilot-scale" if points < 10 else "awaiting-explicit-continue"
    return "promising-at-pilot-scale" if points > 100 else "not-improved-at-pilot-scale"
