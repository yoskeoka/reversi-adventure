#!/usr/bin/env python3
"""Compare two release search-profiler binaries on the canonical corpus.

This is deliberately a human-operated measurement tool.  Tests exercise its
schema and arithmetic with synthetic samples; they never assert an elapsed
time or a speedup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


RUNNER_VERSION = "reversi-ai-search-comparator-v1"
CORPUS_V1_SHA256 = "5831839527b433b4b92c314331b9f0e613d98e0f82b9b6edb725f8bd6cb97ff8"


class ComparisonError(RuntimeError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_corpus(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise ComparisonError(f"corpus is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != CORPUS_V1_SHA256:
        raise ComparisonError("comparison requires the pinned positions-v1 corpus digest")
    if not text.endswith("\n"):
        raise ComparisonError("corpus must end with a newline")
    records = []
    for line_number, line in enumerate(text.splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ComparisonError(f"corpus line {line_number} is not JSON: {exc}") from exc
        if not isinstance(record, dict) or not isinstance(record.get("position_id"), str):
            raise ComparisonError(f"corpus line {line_number} has no position_id")
        if type(record.get("stone_count")) is not int:
            raise ComparisonError(f"corpus line {line_number} has no stone_count")
        if line != canonical_json(record):
            raise ComparisonError(f"corpus line {line_number} is not canonical")
        records.append(record)
    if len(records) != 16:
        raise ComparisonError("comparison requires the sixteen-position corpus")
    return records


def workload(record: dict[str, object]) -> str:
    return "exact-16" if record["stone_count"] == 48 else "heuristic-depth-12"


def median(samples: list[int]) -> int:
    if not samples:
        raise ComparisonError("cannot calculate a median without samples")
    ordered = sorted(samples)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) // 2


def geometric_mean(values: list[float]) -> float:
    if not values or any(value <= 0 or not math.isfinite(value) for value in values):
        raise ComparisonError("geometric mean requires finite positive values")
    return math.exp(sum(math.log(value) for value in values) / len(values))


def environment() -> dict[str, str]:
    cpu_model = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {
        "architecture": platform.machine(),
        "cpu_model": cpu_model,
        "os": platform.platform(),
        "rustc": subprocess.run(["rustc", "--version"], check=True, capture_output=True, text=True).stdout.strip(),
        "rustflags": os.environ.get("RUSTFLAGS", ""),
    }


def invoke(binary: Path, record: dict[str, object], time_limit_ms: int,
           run: Callable[..., subprocess.CompletedProcess[str]]) -> dict[str, object]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", encoding="utf-8", delete=False) as corpus:
        corpus.write(canonical_json(record) + "\n")
        corpus_path = Path(corpus.name)
    try:
        result = run(
            [str(binary), "--corpus", str(corpus_path), "--time-limit-ms", str(time_limit_ms),
             "--opening-depth", "12", "--midgame-depth", "12", "--endgame-depth", "12",
             "--exact-solver-empty-squares", "16"],
            check=False, capture_output=True, text=True,
        )
    finally:
        corpus_path.unlink(missing_ok=True)
    if result.returncode:
        raise ComparisonError(f"{binary} failed for {record['position_id']}: {result.stderr.strip()}")
    lines = [line for line in result.stdout.splitlines() if line]
    if len(lines) != 1:
        raise ComparisonError(f"{binary} returned {len(lines)} records for {record['position_id']}")
    try:
        sample = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ComparisonError(f"{binary} returned invalid JSON: {exc}") from exc
    required = ("position_id", "elapsed_ns", "nodes_searched", "outcome", "score", "pv", "completed_depth", "exact", "timing_success")
    if not isinstance(sample, dict) or any(key not in sample for key in required):
        raise ComparisonError(f"{binary} returned an incomplete profiler sample")
    if sample["position_id"] != record["position_id"] or type(sample["elapsed_ns"]) is not int or sample["elapsed_ns"] <= 0:
        raise ComparisonError(f"{binary} returned an invalid profiler sample")
    if sample["timing_success"] is not True:
        raise ComparisonError(f"{binary} did not complete {record['position_id']}: {sample.get('timing_failure_reason')}")
    return sample


def compare(baseline: Path, candidate: Path, records: list[dict[str, object]], repetitions: int,
            time_limit_ms: int, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
            start_repetition: int = 1, warmup: bool = True) -> dict[str, object]:
    if repetitions < 1 or start_repetition < 1:
        raise ComparisonError("repetitions and start repetition must be positive")
    if time_limit_ms <= 0:
        raise ComparisonError("time limit must be positive")
    if not baseline.is_file() or not candidate.is_file():
        raise ComparisonError("baseline and candidate must be explicit executable files")
    raw: list[dict[str, object]] = []
    # One unrecorded warm-up per binary and board prevents first-use effects from
    # entering samples, while alternating the recorded order controls drift.
    for record in records:
        if warmup:
            invoke(baseline, record, time_limit_ms, run)
            invoke(candidate, record, time_limit_ms, run)
        for repetition in range(start_repetition, start_repetition + repetitions):
            order = (("baseline", baseline), ("candidate", candidate)) if repetition % 2 else (("candidate", candidate), ("baseline", baseline))
            for label, binary in order:
                sample = invoke(binary, record, time_limit_ms, run)
                raw.append({"binary": label, "position_id": record["position_id"], "repetition": repetition, "workload": workload(record), "sample": sample})
    positions = []
    for record in records:
        samples = {label: [int(item["sample"]["elapsed_ns"]) for item in raw if item["position_id"] == record["position_id"] and item["binary"] == label] for label in ("baseline", "candidate")}
        baseline_median, candidate_median = median(samples["baseline"]), median(samples["candidate"])
        positions.append({"position_id": record["position_id"], "workload": workload(record), "baseline_median_ns": baseline_median, "candidate_median_ns": candidate_median, "ratio": candidate_median / baseline_median})
    workloads = []
    for name in ("heuristic-depth-12", "exact-16"):
        ratios = [float(item["ratio"]) for item in positions if item["workload"] == name]
        workloads.append({"name": name, "positions": len(ratios), "geometric_mean_ratio": geometric_mean(ratios)})
    return {"schema_version": 1, "runner_version": RUNNER_VERSION, "repetitions": repetitions, "start_repetition": start_repetition, "time_limit_ms": time_limit_ms, "binaries": {"baseline": {"path": str(baseline), "sha256": sha256_file(baseline)}, "candidate": {"path": str(candidate), "sha256": sha256_file(candidate)}}, "environment": environment(), "raw_samples": raw, "positions": positions, "workloads": workloads}


def merge_fragments(fragments: list[dict[str, object]]) -> dict[str, object]:
    if len(fragments) != 5:
        raise ComparisonError("exactly five comparison fragments are required")
    first = fragments[0]
    required = ("schema_version", "runner_version", "time_limit_ms", "binaries", "environment")
    if any(first.get(key) is None for key in required):
        raise ComparisonError("comparison fragment has an incomplete schema")
    if any(any(fragment.get(key) != first[key] for key in required) for fragment in fragments[1:]):
        raise ComparisonError("comparison fragments were not measured in the same environment")
    if sorted(fragment.get("start_repetition") for fragment in fragments) != [1, 2, 3, 4, 5] or any(fragment.get("repetitions") != 1 for fragment in fragments):
        raise ComparisonError("comparison fragments must cover repetitions one through five exactly once")
    raw = [sample for fragment in fragments for sample in fragment.get("raw_samples", [])]
    if len(raw) != 160:
        raise ComparisonError("comparison fragments do not contain 160 raw samples")
    positions = []
    for position_id in sorted({str(item["position_id"]) for item in raw}):
        for item in (item for item in raw if item["position_id"] == position_id):
            sample = item.get("sample")
            if not isinstance(sample, dict) or type(sample.get("elapsed_ns")) is not int or sample["elapsed_ns"] <= 0 or sample.get("timing_success") is not True:
                raise ComparisonError(f"comparison fragments have an invalid timing sample for {position_id}")
        samples = {label: [int(item["sample"]["elapsed_ns"]) for item in raw if item["position_id"] == position_id and item["binary"] == label] for label in ("baseline", "candidate")}
        if any(len(values) != 5 for values in samples.values()):
            raise ComparisonError(f"comparison fragments have missing samples for {position_id}")
        source = next(item for item in raw if item["position_id"] == position_id)
        baseline_median, candidate_median = median(samples["baseline"]), median(samples["candidate"])
        positions.append({"position_id": position_id, "workload": source["workload"], "baseline_median_ns": baseline_median, "candidate_median_ns": candidate_median, "ratio": candidate_median / baseline_median})
    workloads = [{"name": name, "positions": len(ratios), "geometric_mean_ratio": geometric_mean(ratios)} for name in ("heuristic-depth-12", "exact-16") for ratios in [[float(item["ratio"]) for item in positions if item["workload"] == name]]]
    return {"schema_version": 1, "runner_version": RUNNER_VERSION, "repetitions": 5, "time_limit_ms": first["time_limit_ms"], "binaries": first["binaries"], "environment": first["environment"], "raw_samples": raw, "positions": positions, "workloads": workloads}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--start-repetition", type=int, default=1)
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--fragments", type=Path, nargs="+")
    parser.add_argument("--time-limit-ms", type=int, default=300000)
    args = parser.parse_args(argv)
    try:
        if args.fragments:
            report = merge_fragments([json.loads(path.read_text(encoding="utf-8")) for path in args.fragments])
        else:
            if not args.baseline or not args.candidate or not args.corpus:
                raise ComparisonError("--baseline, --candidate, and --corpus are required without --fragments")
            report = compare(args.baseline, args.candidate, load_corpus(args.corpus), args.repetitions, args.time_limit_ms, start_repetition=args.start_repetition, warmup=not args.no_warmup)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    except ComparisonError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
