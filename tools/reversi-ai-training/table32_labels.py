#!/usr/bin/env python3
"""Produce or read immutable Egaroucid labels for the fixed table32 corpus."""
from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import gzip
import hashlib
import io
import json
import math
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import table32_corpus as corpus
import table32_store as st
import training
from pilot import oracle

VERSION = "table32-opening-labels-v1"
DEFAULT_BATCH_SIZE = 16
MAX_BATCH_SIZE = 128
MAX_RECORD_BYTES = 2 * 1024 * 1024
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SHA256 = re.compile(r"[0-9a-f]{64}")
# The first two boards each have one legal move and end with one empty square.
# The first has 61 black and 2 white after a6; the second has 53 black and
# 10 white after h2. The other side must pass in both cases.
CALIBRATION_BOARDS = (
    "B" * 31 + "W." + "B" * 7 + "." + "B" * 8 + "W" + "B" * 3 + "W" + "B" * 10,
    "BWBBBBBBBBBBBBB.BBBBBBBBBWBBWBBBBBBBBBBBBWBBBBBBBBBBBB.WBBBBBBBB",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _file_digest(path):
    return training.sha256_file(path)


def _corpus(root):
    manifest = corpus.read_manifest(root)
    return manifest, _file_digest(Path(root) / "manifest.json")


def _settings(level, threads, hash_level, timeout, batch_size, measure_per_phase):
    require(type(level) is int and 1 <= level <= 60, "level must be 1..60")
    require(type(threads) is int and 1 <= threads <= 32, "threads must be 1..32")
    require(type(hash_level) is int and 16 <= hash_level <= 28, "hash-level must be 16..28")
    require(type(timeout) is int and timeout > 0, "timeout-seconds must be positive")
    require(type(batch_size) is int and 1 <= batch_size <= MAX_BATCH_SIZE,
            f"batch-size must be 1..{MAX_BATCH_SIZE}")
    require(type(measure_per_phase) is int and 0 <= measure_per_phase <= 32,
            "measure-per-phase must be 0..32")
    return {
        "level": level, "threads": threads, "hash_level": hash_level,
        "timeout_seconds": timeout, "batch_size": batch_size,
        "measure_per_phase": measure_per_phase, "book": False,
        "search": "console-solve-level", "seed": None, "evaluation_override": False,
        "perspective": "side-to-move", "unit": "discs",
        "score_contract": oracle.SCORE_CONTRACT,
    }


def _source_metadata(version, url, archive, receipt):
    require(isinstance(version, str) and SEMVER.fullmatch(version), "invalid teacher version")
    require(isinstance(url, str) and urlsplit(url).scheme == "https" and urlsplit(url).hostname,
            "source URL must use HTTPS")
    for pin in (archive,) if receipt is None else (archive, receipt):
        require(isinstance(pin, dict) and set(pin) == {"path", "sha256"}
                and isinstance(pin["path"], str) and Path(pin["path"]).is_absolute()
                and isinstance(pin["sha256"], str) and SHA256.fullmatch(pin["sha256"]),
                "invalid teacher source pin")
    if version == oracle.ORACLE_VERSION:
        require(archive["sha256"] == oracle.SOURCE_SHA256,
                "source archive does not match the published Egaroucid checksum")
    return {"version": version, "url": url, "archive": archive, "runtime_receipt": receipt}


def prepare(args):
    validate = (args.binary, args.cwd, args.source_url, args.source_archive, args.source_sha256)
    receipt = args.runtime_receipt
    if receipt:
        require(all(item is None for item in validate),
                "--runtime-receipt cannot be combined with manual source/runtime options")
        record = oracle.verify_runtime_receipt(receipt, require_current_source=False)
        require(record["oracle_version"] == args.version, "receipt teacher version differs")
        source = _source_metadata(args.version, record["source_url"], record["source_archive"], st.pin(receipt))
        runtime = record["runtime"]
        _check_runtime(runtime)
    else:
        require(all(item is not None for item in validate),
                "provide --runtime-receipt or all manual source/runtime options")
        archive = st.pin(args.source_archive)
        require(archive["sha256"] == args.source_sha256, "teacher source archive checksum differs")
        source = _source_metadata(args.version, args.source_url, archive, None)
        runtime = oracle.runtime_identity(args.binary, args.cwd)
    _, corpus_digest = _corpus(args.corpus_root)
    settings = _settings(args.level, args.threads, args.hash_level, args.timeout_seconds,
                         args.batch_size, args.measure_per_phase)
    manifest = st.seal({"version": VERSION, "corpus_sha256": corpus_digest,
                        "source": source, "runtime": runtime, "settings": settings})
    label_root, corpus_root = args.label_root.resolve(), args.corpus_root.resolve()
    require(label_root != corpus_root and corpus_root not in label_root.parents,
            "label root must be separate from the corpus")
    label_root.mkdir(parents=True)
    st.atomic(label_root / "manifest.json", manifest, once=True)
    return manifest


def _manifest(label_root, corpus_digest):
    manifest = st.read(Path(label_root) / "manifest.json")
    require(isinstance(manifest, dict)
            and set(manifest) == {"version", "corpus_sha256", "source", "runtime", "settings", "digest"}
            and manifest == st.seal(manifest) and manifest["version"] == VERSION
            and manifest["corpus_sha256"] == corpus_digest,
            "label manifest or corpus digest differs")
    settings = manifest["settings"]
    expected = _settings(settings["level"], settings["threads"], settings["hash_level"],
                         settings["timeout_seconds"], settings["batch_size"], settings["measure_per_phase"])
    require(st.blob(expected) == st.blob(settings), "invalid label settings")
    source = manifest["source"]
    expected = _source_metadata(source["version"], source["url"], source["archive"], source["runtime_receipt"])
    require(expected == source, "invalid label source")
    oracle.validate_saved_runtime(manifest["runtime"])
    return manifest


def _check_runtime(runtime):
    oracle.validate_saved_runtime(runtime)
    current = oracle.runtime_identity(runtime["binary"]["path"], runtime["working_directory"])
    require(current == runtime, "teacher binary or runtime resources changed")


def _batches(corpus_manifest, settings):
    sample_count = settings["measure_per_phase"]
    counts = defaultdict(int)
    for shard in corpus_manifest["shards"]:
        counts[shard["phase"]] += shard["count"]
    offsets = defaultdict(int)
    for shard in corpus_manifest["shards"]:
        phase = shard["phase"]
        offset = offsets[phase]
        if sample_count:
            count = counts[phase]
            n = min(count, sample_count)
            ranks = [(2 * index + 1) * count // (2 * n) for index in range(n)]
            ranges = ((rank - offset, 1) for rank in ranks if offset <= rank < offset + shard["count"])
        else:
            size = settings["batch_size"]
            ranges = ((start, min(size, shard["count"] - start))
                      for start in range(0, shard["count"], size))
        for start, count in ranges:
            yield shard, {"phase": phase, "start": offset + start, "count": count, "offset": start,
                          "corpus_shard": shard["path"], "corpus_shard_sha256": shard["sha256"]}
        offsets[phase] += shard["count"]


def _batch_path(root, batch):
    return Path(root) / "batches" / f'p{batch["phase"]:02d}-{batch["start"]:06d}.json.gz'


def _profile(level):
    # Existing Oracle solve parser handles the Console level, depth, and summary.
    name = f"{VERSION}-level-{level}"
    profile = oracle.OracleProfile(name, 25, (), 1, 0, level)
    oracle.PROFILES[name] = profile
    return profile


def _query(board, side):
    moves = oracle.legal_moves(board, side)
    if moves:
        return side, 1, moves
    other = oracle.other(side)
    moves = oracle.legal_moves(board, other)
    if moves:
        return other, -1, moves
    return None, 0, []


def _queries(positions):
    return [(identifier, board, side, *_query(board, side)) for identifier, board, side in positions]


def _labels(queries, stdout, settings, *, minimum_depth=None):
    required = [board.count(".") for _, board, _, effective, _, _ in queries if effective]
    rows = iter(oracle.parse_solve_output(stdout, required, _profile(settings["level"]))) if required else iter(())
    require(required or not stdout, "terminal-only batch has external solve output")
    labels = []
    for identifier, board, side, effective, sign, moves in queries:
        if effective is None:
            labels.append({"id": identifier, "score": oracle.terminal_score(board, side),
                           "kind": "terminal", "move": None, "depth": 0, "search_ms": 0})
            continue
        row = next(rows)
        require(row["move"] in moves, f"illegal teacher move for {identifier}")
        require(-64 <= row["value"] <= 64 and 1 <= row["completed_depth"] <= board.count("."),
                f"invalid teacher score or depth for {identifier}")
        if minimum_depth is not None:
            require(row["completed_depth"] >= min(minimum_depth, board.count(".")),
                    f"teacher depth below requested level for {identifier}")
        labels.append({"id": identifier, "score": sign * row["value"],
                       "kind": "search" if sign == 1 else "forced-pass",
                       "move": row["move"], "depth": row["completed_depth"],
                       "search_ms": row["elapsed_ms"]})
    return labels


def _console_args(manifest, problem):
    settings = manifest["settings"]
    return [manifest["runtime"]["binary"]["path"], "-nobook", "-thread", str(settings["threads"]),
            "-hash", str(settings["hash_level"]), "-level", str(settings["level"]), "-solve", str(problem)]


def _solve(queries, manifest):
    problems = [oracle.to_egaroucid_problem(board, effective)
                for _, board, _, effective, _, _ in queries if effective]
    if not problems:
        return ""
    with tempfile.TemporaryDirectory(prefix="table32-label-") as temporary:
        problem = Path(temporary) / "positions.txt"
        problem.write_text("\n".join(problems) + "\n", encoding="ascii")
        result = oracle.run_external(_console_args(manifest, problem),
                                     cwd=Path(manifest["runtime"]["working_directory"]),
                                     timeout=manifest["settings"]["timeout_seconds"])
        require(not re.search(r"\[(?:ERROR|FATAL)\]", result.stderr), "teacher reported a console error")
        return result.stdout


def _calibration_queries():
    positive, negative = CALIBRATION_BOARDS
    terminal = oracle.apply_move(positive, "B", "a6")
    return _queries((("winning-black", positive, "B"), ("losing-white", negative, "W"),
                     ("forced-pass-white", positive, "W"), ("terminal-white", terminal, "W")))


def _check_calibration(manifest, evidence):
    version = re.escape(manifest["source"]["version"])
    require(isinstance(evidence, dict)
            and set(evidence) == {"manifest_digest", "version_output", "stdout", "digest"}
            and evidence == st.seal(evidence) and evidence["manifest_digest"] == manifest["digest"],
            "label calibration identity differs")
    require(re.search(rf"^Egaroucid for Console {version}(?:\.[0-9]+)?(?:[ \t]|$)",
                      evidence["version_output"], re.MULTILINE), "teacher run reported a different version")
    labels = _labels(_calibration_queries(), evidence["stdout"], manifest["settings"])
    projection = [(row["score"], row["kind"], row["move"]) for row in labels]
    require(projection == [(60, "search", "a6"), (-44, "search", "h2"),
                           (-60, "forced-pass", "a6"), (-60, "terminal", None)],
            "teacher calibration failed: score perspective or winner-empty contract differs")


def _calibrate(root, manifest, *, execute=False):
    path = Path(root) / "calibration.json"
    if not path.exists() and execute:
        runtime = manifest["runtime"]
        version = oracle.run_external([runtime["binary"]["path"], "-version"],
                                      cwd=Path(runtime["working_directory"]),
                                      timeout=min(manifest["settings"]["timeout_seconds"], 30))
        evidence = st.seal({"manifest_digest": manifest["digest"],
                            "version_output": version.stdout + "\n" + version.stderr,
                            "stdout": _solve(_calibration_queries(), manifest)})
        _check_calibration(manifest, evidence)
        st.atomic(path, evidence, once=True)
    require(path.is_file(), "missing label calibration; run table32_labels.py run")
    evidence = st.read(path)
    _check_calibration(manifest, evidence)
    return evidence["digest"]


def _positions(records):
    return _queries((row["id"], *corpus.decode_position(row)) for row in records)


def _position_labels(records, stdout, manifest, *, queries=None):
    if queries is None:
        queries = _positions(records)
    level = manifest["settings"]["level"] if manifest["source"]["version"] == "7.8.1" else None
    labels = _labels(queries, stdout, manifest["settings"], minimum_depth=level)
    require(all(row["terminal"] == (label["kind"] == "terminal") for row, label in zip(records, labels)),
            "label and corpus terminal status differ")
    return labels


def _read_batch(path, batch, manifest):
    require(path.is_file(), f"missing labels: {path}")
    require(not path.is_symlink(), f"label batch is a symlink: {path}")
    require(path.stat().st_size <= MAX_RECORD_BYTES, f"oversize compressed label batch: {path}")
    raw = path.read_bytes()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            expanded = stream.read(MAX_RECORD_BYTES + 1)
    except (EOFError, OSError) as error:
        raise ValueError(f"invalid compressed label batch: {path}: {error}") from error
    require(len(expanded) <= MAX_RECORD_BYTES, f"oversize label batch: {path}")
    evidence = json.loads(expanded)
    require(isinstance(evidence, dict)
            and set(evidence) == {"manifest_digest", "batch", "stdout", "labels", "wall_seconds", "digest"}
            and evidence == st.seal(evidence) and expanded == st.blob(evidence)
            and evidence["manifest_digest"] == manifest["digest"]
            and st.blob(evidence["batch"]) == st.blob(batch),
            f"label batch digest or binding differs: {path}")
    wall = evidence["wall_seconds"]
    require(type(wall) in (int, float) and math.isfinite(wall) and wall > 0,
            f"label batch wall time is invalid: {path}")
    return evidence, hashlib.sha256(raw).hexdigest()


def _verify_batch(evidence, records, manifest):
    expected = _position_labels(records, evidence["stdout"], manifest)
    require(st.blob(expected) == st.blob(evidence["labels"]), "label IDs or scores differ from raw solver output")
    return expected


def _write_batch(path, batch, records, manifest):
    started = time.monotonic()
    queries = _positions(records)
    stdout = _solve(queries, manifest)
    labels = _position_labels(records, stdout, manifest, queries=queries)
    evidence = st.seal({"manifest_digest": manifest["digest"], "batch": batch, "stdout": stdout,
                        "labels": labels, "wall_seconds": time.monotonic() - started})
    st.atomic_bytes(path, gzip.compress(st.blob(evidence), mtime=0), once=True)


def _selected(corpus_root, label_root, phases, limit_per_phase, exclude_ids):
    corpus_manifest, digest = _corpus(corpus_root)
    manifest = _manifest(label_root, digest)
    require(manifest["settings"]["measure_per_phase"] == 0, "measurement labels cannot be imported")
    phases = set(phases)
    allowed = {shard["phase"] for shard in corpus_manifest["shards"]}
    require(phases and all(type(phase) is int and phase in allowed for phase in phases),
            "invalid label phase selection")
    require(limit_per_phase is None or type(limit_per_phase) is int and limit_per_phase > 0,
            "label limit per phase must be positive")
    counts = defaultdict(int)
    last_shard, records = None, []
    for shard, batch in _batches(corpus_manifest, manifest["settings"]):
        phase = batch["phase"]
        if phase not in phases or (limit_per_phase is not None and counts[phase] >= limit_per_phase):
            continue
        if shard != last_shard:
            records = list(corpus.iter_shard(corpus_root, shard))
            last_shard = shard
        offset = batch["offset"]
        group = records[offset:offset + batch["count"]]
        selected = [index for index, row in enumerate(group) if row["id"] not in exclude_ids]
        if limit_per_phase is not None:
            selected = selected[:limit_per_phase - counts[phase]]
        if not selected:
            continue
        counts[phase] += len(selected)
        path = _batch_path(label_root, batch)
        evidence, file_digest = _read_batch(path, batch, manifest)
        yield phase, group, selected, evidence, file_digest, manifest, path.name
    require(all(counts[phase] > 0 for phase in phases), "no eligible labels for a selected phase")


def iter_labeled(corpus_root, label_root, phases, limit_per_phase=None, *, exclude_ids=()):
    """Yield selected examples after exact corpus ID and raw solve validation."""
    _, digest = _corpus(corpus_root)
    _calibrate(label_root, _manifest(label_root, digest))
    for phase, group, selected, evidence, _, manifest, _ in _selected(
            corpus_root, label_root, phases, limit_per_phase, frozenset(exclude_ids)):
        labels = _verify_batch(evidence, group, manifest)
        for index in selected:
            yield {**group[index], "phase": phase, "score": labels[index]["score"]}


def dataset_identity(corpus_root, label_root, phases, limit_per_phase=None, *, exclude_ids=(), verify_scores=False):
    """Pin required batch bytes without depending on engine availability."""
    _, digest = _corpus(corpus_root)
    manifest = _manifest(label_root, digest)
    calibration = _calibrate(label_root, manifest)
    pins = {}
    for _, group, _, evidence, pin, _, name in _selected(
            corpus_root, label_root, phases, limit_per_phase, frozenset(exclude_ids)):
        if verify_scores:
            _verify_batch(evidence, group, manifest)
        pins[name] = pin
    return {**manifest, "calibration_digest": calibration, "batch_sha256": pins}


def _progress(started, batch, completed, total, status):
    print(f'table32 phase={batch["phase"]:02d} unit={batch["start"]:06d} '
          f"completed={completed} total={total} elapsed_seconds={time.monotonic() - started:.3f} "
          f"status={status}", file=sys.stderr, flush=True)


def _group_batches(batches, corpus_root):
    from itertools import groupby

    for _, units in groupby(batches, key=lambda item: item[0]["path"]):
        units = list(units)
        shard = units[0][0]
        records = list(corpus.iter_shard(corpus_root, shard))
        yield [(batch, records[batch["offset"]:batch["offset"] + batch["count"]])
               for _, batch in units]


def run(args):
    from table32_process import supervise

    root = args.label_root
    corpus_manifest, corpus_digest = _corpus(args.corpus_root)
    manifest = _manifest(root, corpus_digest)
    require(0 <= args.phase_start <= args.phase_end <= 9, "label phase range must be within 0..9")
    all_batches = [(shard, batch) for shard, batch in _batches(corpus_manifest, manifest["settings"])
                   if args.phase_start <= batch["phase"] <= args.phase_end]
    stop = len(all_batches) if args.batch_stop is None else args.batch_stop
    require(0 <= args.batch_start < stop <= len(all_batches), "invalid label batch range")
    require(1 <= args.jobs <= 32, "jobs must be 1..32")
    require(args.attempt_wall_seconds > 0 and args.max_rss_kib > 0 and args.progress_every > 0,
            "attempt wall, RSS and progress cadence must be positive")
    chosen = all_batches[args.batch_start:stop]
    total = sum(batch["count"] for _, batch in chosen)
    attempt_manifest = {
        "producer_commit": None,
        "settings": {"label_manifest_digest": manifest["digest"], "jobs": args.jobs,
                     "phase_start": args.phase_start, "phase_end": args.phase_end,
                     "batch_start": args.batch_start, "batch_stop": stop,
                     "total_positions": total, "total_batches": len(chosen), "resume": args.resume},
        "limits": {"wall_seconds": args.attempt_wall_seconds,
                   "producer_rss_kib": args.max_rss_kib, "child_rss_kib": args.max_rss_kib},
    }
    def worker(attempt):
        started = time.monotonic()
        completed = 0
        last_report = 0
        last_batch = chosen[0][1]
        try:
            _progress(started, last_batch, 0, total, "start")
            for pin in (manifest["source"]["archive"], manifest["source"]["runtime_receipt"]):
                if pin:
                    st.check_pin(pin)
            _check_runtime(manifest["runtime"])
            st.atomic(attempt / "progress.json", {"phase": "label-calibration", "unit": "console",
                                                 "completed": 0, "total": total})
            _calibrate(root, manifest, execute=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
                for group in _group_batches(chosen, args.corpus_root):
                    for head in range(0, len(group), args.jobs):
                        active = group[head:head + args.jobs]
                        last_batch = active[0][0]
                        st.atomic(attempt / "progress.json", {
                            "phase": f'{last_batch["phase"]:02d}', "unit": f'{last_batch["start"]:06d}',
                            "completed": completed, "total": total})
                        pending = []
                        for batch, records in active:
                            path = _batch_path(root, batch)
                            if path.exists():
                                evidence, _ = _read_batch(path, batch, manifest)
                                _verify_batch(evidence, records, manifest)
                                pending.append((batch, None))
                            else:
                                pending.append((batch, pool.submit(_write_batch, path, batch, records, manifest)))
                        for last_batch, future in pending:
                            if future is not None:
                                future.result()
                            completed += last_batch["count"]
                            if completed - last_report >= args.progress_every or completed == total:
                                _progress(started, last_batch, completed, total, "saved" if future else "verified")
                                last_report = completed
                        st.atomic(attempt / "progress.json", {
                            "phase": f'{last_batch["phase"]:02d}', "unit": f'{last_batch["start"]:06d}',
                            "completed": completed, "total": total})
            _progress(started, last_batch, completed, total, "complete")
        except BaseException:
            _progress(started, last_batch, completed, total, "failed")
            raise

    # The shared supervisor fixes settings and limits across its attempts.
    # Give each independently configured operator slice its own supervisor
    # root, and serialize publication to their shared batch directory.
    with (root / "run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another label invocation owns this run root") from error
        slices = root / "slices"
        prior = sorted(slices.glob("[0-9]*"))
        require(args.resume or not prior, "existing run requires --resume")
        slice_root = slices / f"{len(prior):04d}"
        slice_root.mkdir(parents=True)
        st.atomic(slice_root / "manifest.json", attempt_manifest, once=True)
        supervise(slice_root, attempt_manifest, worker, progress_every=args.progress_every,
                  attempt_wall_seconds=args.attempt_wall_seconds)


def inventory(corpus_root, label_root, *, require_complete=False):
    """Replay every saved batch offline and report the uncovered positions."""
    corpus_manifest, corpus_digest = _corpus(corpus_root)
    manifest = _manifest(label_root, corpus_digest)
    all_batches = list(_batches(corpus_manifest, manifest["settings"]))
    expected = {_batch_path(label_root, batch): (shard, batch) for shard, batch in all_batches}
    actual = set((Path(label_root) / "batches").glob("*.json.gz"))
    require(actual <= expected.keys(), "unexpected label batch in output root")
    calibration_path = Path(label_root) / "calibration.json"
    calibration = _calibrate(label_root, manifest) if actual or calibration_path.exists() else None
    require(not require_complete or (actual == expected.keys() and calibration),
            "label run has missing batches")
    phases = {}
    for _, batch in all_batches:
        phase = phases.setdefault(batch["phase"], {"expected": 0, "completed": 0, "samples": []})
        phase["expected"] += batch["count"]
    available = (pair for path, pair in expected.items() if path in actual)
    for group in _group_batches(available, corpus_root):
        for batch, records in group:
            evidence, _ = _read_batch(_batch_path(label_root, batch), batch, manifest)
            labels = _verify_batch(evidence, records, manifest)
            phase = phases[batch["phase"]]
            phase["completed"] += len(labels)
            if manifest["settings"]["measure_per_phase"]:
                phase["samples"].append({"id": labels[0]["id"], "search_ms": labels[0]["search_ms"],
                                         "batch_wall_seconds": evidence["wall_seconds"]})
    return manifest, corpus_manifest, calibration, phases


def estimate(corpus_root, label_root):
    manifest, corpus_manifest, calibration, phases = inventory(corpus_root, label_root)
    require(manifest["settings"]["measure_per_phase"] > 0, "estimate requires a measurement-only label root")
    populations = defaultdict(int)
    for shard in corpus_manifest["shards"]:
        populations[shard["phase"]] += shard["count"]
    bounds, complete = [], calibration is not None
    for phase, results in phases.items():
        samples = results["samples"]
        has_all = results["completed"] == results["expected"]
        complete &= has_all
        population = populations[phase]
        times = [row["batch_wall_seconds"] for row in samples]
        bounds.append({
            **results, "phase": phase, "population": population,
            "sample_min_seconds": min(times) if samples else None,
            "sample_max_seconds": max(times) if samples else None,
            "serial_projection_seconds": sum(times) * population / len(times) if has_all else None,
            "serial_projection_min_seconds": min(times) * population if has_all else None,
            "serial_projection_max_seconds": max(times) * population if has_all else None,
        })
    attempts = []
    for path in sorted((Path(label_root) / "slices").glob("[0-9]*")):
        receipt = path / "attempts/0000"
        recorded = st.read(path / "manifest.json") if (path / "manifest.json").exists() else None
        report = {"id": path.name, "completion": None, "failure": None, "resources": None}
        for key in ("completion", "failure", "resources"):
            saved = receipt / f"{key}.json"
            if saved.exists():
                entry = st.read(saved)
                if key != "resources":
                    require(recorded and recorded["settings"]["label_manifest_digest"] == manifest["digest"]
                            and entry == st.seal(entry) and entry["manifest_digest"] == st.digest(recorded),
                            f"measurement attempt evidence differs: {saved}")
                report[key] = entry
        attempts.append(report)
    return {
        "manifest_digest": manifest["digest"], "complete": complete, "phases": bounds,
        "attempts": attempts,
        "serial_projection_seconds": sum(phase["serial_projection_seconds"] for phase in bounds) if complete else None,
        "serial_projection_min_seconds": sum(phase["serial_projection_min_seconds"] for phase in bounds) if complete else None,
        "serial_projection_max_seconds": sum(phase["serial_projection_max_seconds"] for phase in bounds) if complete else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run", "verify", "estimate"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--corpus-root", type=Path, required=True)
        cmd.add_argument("--label-root", type=Path, required=True)
    prepare_parser = commands.choices["prepare"]
    for arg in ("runtime-receipt", "binary", "cwd", "source-archive"):
        prepare_parser.add_argument("--" + arg, type=Path)
    prepare_parser.add_argument("--source-url")
    prepare_parser.add_argument("--source-sha256")
    prepare_parser.add_argument("--version", default=oracle.ORACLE_VERSION)
    prepare_parser.add_argument("--level", type=int, default=21)
    prepare_parser.add_argument("--threads", type=int, default=1)
    prepare_parser.add_argument("--hash-level", type=int, default=25)
    prepare_parser.add_argument("--timeout-seconds", type=int, default=1800)
    prepare_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    prepare_parser.add_argument("--measure-per-phase", type=int, default=0)
    run_parser = commands.choices["run"]
    run_parser.add_argument("--phase-start", type=int, default=0)
    run_parser.add_argument("--phase-end", type=int, default=9)
    run_parser.add_argument("--batch-start", type=int, default=0)
    run_parser.add_argument("--batch-stop", type=int)
    run_parser.add_argument("--jobs", type=int, default=1)
    run_parser.add_argument("--max-rss-kib", type=int, default=1572864)
    run_parser.add_argument("--attempt-wall-seconds", type=int, default=12 * 3600)
    run_parser.add_argument("--progress-every", type=int, default=1)
    run_parser.add_argument("--resume", action="store_true")
    commands.choices["verify"].add_argument("--complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args)
        elif args.command == "run":
            run(args)
            return 0
        elif args.command == "verify":
            manifest, _, calibration, phases = inventory(args.corpus_root, args.label_root,
                                                          require_complete=args.complete)
            result = {"manifest_digest": manifest["digest"], "calibration_digest": calibration,
                      "phases": {str(phase): data for phase, data in phases.items()}}
        else:
            result = estimate(args.corpus_root, args.label_root)
        sys.stdout.buffer.write(st.blob(result))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, oracle.OracleError,
            training.TrainingError) as error:
        print(f"table32-label: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
