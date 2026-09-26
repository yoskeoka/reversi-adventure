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
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, NamedTuple


RUNNER_VERSION = "reversi-ai-rust-cost-comparator-v1"
CORPUS_V1_SHA256 = "5831839527b433b4b92c314331b9f0e613d98e0f82b9b6edb725f8bd6cb97ff8"


class ComparisonError(RuntimeError):
    pass


def positive_interval(value: str) -> int:
    try:
        interval = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if interval < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return interval


class Progress:
    def __init__(self, interval: int):
        self.interval = interval
        self.started = time.monotonic()

    def stage(self, name: str, start: float | None = None) -> float | None:
        elapsed = time.monotonic() - self.started
        if start is None:
            print(f"stage benchmark-{name} start elapsed={elapsed:.1f}s", file=sys.stderr, flush=True)
            return time.monotonic()
        print(f"stage benchmark-{name} done stage={time.monotonic() - start:.1f}s elapsed={elapsed:.1f}s", file=sys.stderr, flush=True)
        return None

    def unit(self, position: str, repetition: int, completed: int, total: int, start: float) -> None:
        if completed % self.interval == 0 or completed == total:
            print(f"progress benchmark position={position} repetition={repetition} {completed}/{total} pair={time.monotonic() - start:.1f}s elapsed={time.monotonic() - self.started:.1f}s", file=sys.stderr, flush=True)


class MeasuredProcess(NamedTuple):
    returncode: int
    stdout: str
    stderr: str
    process_elapsed_ns: int
    user_cpu_ns: int
    system_cpu_ns: int
    peak_rss_kib: int


def run_measured(argv: list[str]) -> MeasuredProcess:
    if sys.platform != "linux":
        raise ComparisonError("per-child resource measurement requires Linux")
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout, tempfile.TemporaryFile(
        mode="w+t", encoding="utf-8"
    ) as stderr:
        started = time.monotonic_ns()
        process = subprocess.Popen(argv, stdout=stdout, stderr=stderr)
        try:
            _, status, usage = os.wait4(process.pid, 0)
        except BaseException:
            process.kill()
            os.waitpid(process.pid, 0)
            raise
        elapsed = time.monotonic_ns() - started
        process.returncode = os.waitstatus_to_exitcode(status)
        stdout.seek(0)
        stderr.seek(0)
        return MeasuredProcess(
            process.returncode, stdout.read(), stderr.read(), elapsed,
            round(usage.ru_utime * 1_000_000_000),
            round(usage.ru_stime * 1_000_000_000), usage.ru_maxrss,
        )


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
        "host": platform.node(),
        "measurement_method": "linux-wait4",
        "os": platform.platform(),
        "rustc": subprocess.run(["rustc", "+1.98.1", "--version"], check=True, capture_output=True, text=True).stdout.strip(),
        "rustflags": os.environ.get("RUSTFLAGS", ""),
    }


def invoke(binary: Path, record: dict[str, object], time_limit_ms: int,
           run: Callable[[list[str]], MeasuredProcess]) -> dict[str, object]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", encoding="utf-8", delete=False) as corpus:
        corpus.write(canonical_json(record) + "\n")
        corpus_path = Path(corpus.name)
    try:
        result = run(
            [str(binary), "--corpus", str(corpus_path), "--time-limit-ms", str(time_limit_ms),
             "--opening-depth", "12", "--midgame-depth", "12", "--endgame-depth", "12",
             "--exact-solver-empty-squares", "16"],
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
    resources = {
        "process_elapsed_ns": result.process_elapsed_ns,
        "user_cpu_ns": result.user_cpu_ns,
        "system_cpu_ns": result.system_cpu_ns,
        "peak_rss_kib": result.peak_rss_kib,
    }
    validate_resources(resources)
    sample.update(resources)
    return sample


def validate_resources(sample: dict[str, object]) -> None:
    for key in ("process_elapsed_ns", "user_cpu_ns", "system_cpu_ns", "peak_rss_kib"):
        value = sample.get(key)
        if type(value) is not int or value < (1 if key in ("process_elapsed_ns", "peak_rss_kib") else 0):
            raise ComparisonError(f"missing or invalid {key}")


SEMANTIC_FIELDS = ("board_digest", "outcome", "score", "pv", "completed_depth", "exact", "nodes_searched")


def aggregate(raw: list[dict[str, object]], records: list[dict[str, object]],
              repetitions: list[int]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    expected = {(record["position_id"], repetition, label) for record in records
                for repetition in repetitions for label in ("baseline", "candidate")}
    actual = [(item.get("position_id"), item.get("repetition"), item.get("binary")) for item in raw]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ComparisonError("comparison has missing or duplicate position/repetition/binary samples")
    positions = []
    for record in records:
        position_id = record["position_id"]
        if any(item.get("workload") != workload(record) for item in raw if item["position_id"] == position_id):
            raise ComparisonError(f"workload mismatch for {position_id}")
        by_key = {(item["repetition"], item["binary"]): item for item in raw
                  if item["position_id"] == position_id}
        for repetition in repetitions:
            baseline = by_key[(repetition, "baseline")]["sample"]
            candidate = by_key[(repetition, "candidate")]["sample"]
            for label, sample in (("baseline", baseline), ("candidate", candidate)):
                item = by_key[(repetition, label)]
                if not isinstance(sample, dict) or sample.get("position_id") != position_id or sample.get("timing_success") is not True:
                    raise ComparisonError(f"invalid timing sample for {position_id} {repetition} {label}")
                if not isinstance(item.get("resource_usage"), dict):
                    raise ComparisonError(f"missing resource usage for {position_id}")
                validate_resources(item["resource_usage"])
                if type(sample.get("elapsed_ns")) is not int or sample["elapsed_ns"] <= 0:
                    raise ComparisonError(f"invalid search elapsed for {position_id}")
                if type(sample.get("nodes_searched")) is not int or sample["nodes_searched"] < 0:
                    raise ComparisonError(f"invalid node count for {position_id}")
                if not all(field in sample for field in SEMANTIC_FIELDS):
                    raise ComparisonError(f"missing result field for {position_id}")
                expected_board_digest = hashlib.sha256(record["board"].encode("ascii")).hexdigest()
                if sample["board_digest"] != expected_board_digest:
                    raise ComparisonError(f"board digest mismatch for {position_id}")
                if (type(sample.get("score")) is not int
                        or not isinstance(sample.get("outcome"), dict)
                        or not isinstance(sample.get("pv"), list)):
                    raise ComparisonError(f"invalid completed result for {position_id}")
                expected_exact = record["stone_count"] == 48
                expected_depth = 16 if expected_exact else 12
                if sample.get("exact") is not expected_exact or sample.get("completed_depth") != expected_depth:
                    raise ComparisonError(f"incomplete or unexpected search for {position_id}")
            if any(baseline.get(field) != candidate.get(field) for field in SEMANTIC_FIELDS):
                raise ComparisonError(f"result or node mismatch for {position_id} repetition {repetition}")
            if "cost_diagnostics" in baseline or "cost_diagnostics" in candidate:
                left = baseline.get("cost_diagnostics", {}).get("trace_sha256")
                right = candidate.get("cost_diagnostics", {}).get("trace_sha256")
                if not left or left != right:
                    raise ComparisonError(f"trace mismatch for {position_id} repetition {repetition}")
        # Repetitions must also be deterministic within each binary.
        reference = by_key[(repetitions[0], "baseline")]["sample"]
        for item in by_key.values():
            sample = item["sample"]
            if any(reference.get(field) != sample.get(field) for field in SEMANTIC_FIELDS):
                raise ComparisonError(f"result or node mismatch across repetitions for {position_id}")
        samples = {label: [by_key[(repetition, label)] for repetition in repetitions]
                   for label in ("baseline", "candidate")}
        medians = {}
        for label in ("baseline", "candidate"):
            medians[label] = {"elapsed_ns": median([item["sample"]["elapsed_ns"] for item in samples[label]])}
            medians[label].update({key: median([item["resource_usage"][key] for item in samples[label]])
                                   for key in ("process_elapsed_ns", "user_cpu_ns", "system_cpu_ns")})
            medians[label]["cpu_ns"] = median([item["resource_usage"]["user_cpu_ns"] +
                                                item["resource_usage"]["system_cpu_ns"]
                                                for item in samples[label]])
            medians[label]["peak_rss_kib"] = max(item["resource_usage"]["peak_rss_kib"]
                                                for item in samples[label])
        base, cand = medians["baseline"], medians["candidate"]
        if base["cpu_ns"] <= 0 or cand["cpu_ns"] <= 0:
            raise ComparisonError(f"CPU median is zero for {position_id}")
        positions.append({"position_id": position_id, "workload": workload(record),
                          "baseline_median_ns": base["elapsed_ns"],
                          "candidate_median_ns": cand["elapsed_ns"],
                          "ratio": cand["elapsed_ns"] / base["elapsed_ns"],
                          "baseline": medians["baseline"], "candidate": medians["candidate"],
                          "cpu_ratio": cand["cpu_ns"] / base["cpu_ns"],
                          "process_elapsed_ratio": cand["process_elapsed_ns"] / base["process_elapsed_ns"]})
    workloads = []
    for name in ("heuristic-depth-12", "exact-16"):
        subset = [item for item in positions if item["workload"] == name]
        if not subset:
            raise ComparisonError(f"missing workload {name}")
        workloads.append({"name": name, "positions": len(subset),
                          "geometric_mean_ratio": geometric_mean([item["ratio"] for item in subset]),
                          "cpu_geometric_mean_ratio": geometric_mean([item["cpu_ratio"] for item in subset]),
                          "process_elapsed_geometric_mean_ratio": geometric_mean([item["process_elapsed_ratio"] for item in subset]),
                          "baseline_peak_rss_kib": max(item["baseline"]["peak_rss_kib"] for item in subset),
                          "candidate_peak_rss_kib": max(item["candidate"]["peak_rss_kib"] for item in subset)})
    return positions, workloads


def compare(baseline: Path, candidate: Path, records: list[dict[str, object]], repetitions: int,
            time_limit_ms: int, run: Callable[[list[str]], MeasuredProcess] = run_measured,
            start_repetition: int = 1, warmup: bool = True, progress_every: int = 1,
            progress: Progress | None = None) -> dict[str, object]:
    if repetitions < 1 or start_repetition < 1:
        raise ComparisonError("repetitions and start repetition must be positive")
    if time_limit_ms <= 0:
        raise ComparisonError("time limit must be positive")
    if progress_every < 1:
        raise ComparisonError("progress interval must be positive")
    if not baseline.is_file() or not candidate.is_file():
        raise ComparisonError("baseline and candidate must be explicit executable files")
    raw: list[dict[str, object]] = []
    progress = progress or Progress(progress_every)
    stage = progress.stage("measurement")
    completed, total = 0, len(records) * repetitions
    # One unrecorded warm-up per binary and board prevents first-use effects from
    # entering samples, while alternating the recorded order controls drift.
    for record in records:
        if warmup:
            invoke(baseline, record, time_limit_ms, run)
            invoke(candidate, record, time_limit_ms, run)
        for repetition in range(start_repetition, start_repetition + repetitions):
            pair_started = time.monotonic()
            order = (("baseline", baseline), ("candidate", candidate)) if repetition % 2 else (("candidate", candidate), ("baseline", baseline))
            for label, binary in order:
                sample = invoke(binary, record, time_limit_ms, run)
                resources = {key: sample.pop(key) for key in
                             ("process_elapsed_ns", "user_cpu_ns", "system_cpu_ns", "peak_rss_kib")}
                raw.append({"binary": label, "position_id": record["position_id"],
                            "repetition": repetition, "workload": workload(record),
                            "sample": sample, "resource_usage": resources})
            completed += 1
            progress.unit(str(record["position_id"]), repetition, completed, total, pair_started)
    progress.stage("measurement", stage)
    stage = progress.stage("aggregation")
    positions, workloads = aggregate(raw, records, list(range(start_repetition, start_repetition + repetitions)))
    progress.stage("aggregation", stage)
    return {"schema_version": 2, "runner_version": RUNNER_VERSION, "repetitions": repetitions, "start_repetition": start_repetition, "time_limit_ms": time_limit_ms, "binaries": {"baseline": {"path": str(baseline), "sha256": sha256_file(baseline)}, "candidate": {"path": str(candidate), "sha256": sha256_file(candidate)}}, "environment": environment(), "raw_samples": raw, "positions": positions, "workloads": workloads}


def merge_fragments(fragments: list[dict[str, object]]) -> dict[str, object]:
    if len(fragments) != 5:
        raise ComparisonError("exactly five comparison fragments are required")
    first = fragments[0]
    required = ("schema_version", "runner_version", "time_limit_ms", "binaries", "environment")
    if any(first.get(key) is None for key in required):
        raise ComparisonError("comparison fragment has an incomplete schema")
    if first["schema_version"] != 2 or first["runner_version"] != RUNNER_VERSION:
        raise ComparisonError("comparison fragment has an unsupported schema or runner")
    if (not isinstance(first["environment"], dict)
            or first["environment"].get("measurement_method") != "linux-wait4"
            or not first["environment"].get("host")
            or not first["environment"].get("cpu_model")):
        raise ComparisonError("comparison fragment lacks a Linux host or measurement method")
    if any(any(fragment.get(key) != first[key] for key in required) for fragment in fragments[1:]):
        raise ComparisonError("comparison fragments were not measured in the same environment")
    if sorted(fragment.get("start_repetition") for fragment in fragments) != [1, 2, 3, 4, 5] or any(fragment.get("repetitions") != 1 for fragment in fragments):
        raise ComparisonError("comparison fragments must cover repetitions one through five exactly once")
    raw = [sample for fragment in fragments for sample in fragment.get("raw_samples", [])]
    records = load_corpus(Path(__file__).with_name("positions-v1.jsonl"))
    positions, workloads = aggregate(raw, records, [1, 2, 3, 4, 5])
    return {"schema_version": 2, "runner_version": RUNNER_VERSION, "repetitions": 5, "time_limit_ms": first["time_limit_ms"], "binaries": first["binaries"], "environment": first["environment"], "raw_samples": raw, "positions": positions, "workloads": workloads}


def verify_report(report: dict[str, object], records: list[dict[str, object]],
                  baseline_binary: Path | None = None,
                  candidate_binary: Path | None = None) -> bool:
    if report.get("schema_version") != 2 or report.get("runner_version") != RUNNER_VERSION:
        raise ComparisonError("unsupported report schema or runner")
    repetitions = report.get("repetitions")
    if type(repetitions) is not int or repetitions < 5 or report.get("start_repetition", 1) != 1:
        raise ComparisonError("final report requires at least five repetitions from one")
    environment = report.get("environment")
    if (not isinstance(environment, dict)
            or environment.get("measurement_method") != "linux-wait4"
            or not environment.get("host") or not environment.get("cpu_model")):
        raise ComparisonError("final report lacks Linux host and measurement method")
    binaries = report.get("binaries")
    if not isinstance(binaries, dict):
        raise ComparisonError("final report lacks binary digests")
    if (baseline_binary is None) != (candidate_binary is None):
        raise ComparisonError("binary rehash requires both baseline and candidate")
    for label in ("baseline", "candidate"):
        identity = binaries.get(label)
        if (not isinstance(identity, dict)
                or not isinstance(identity.get("path"), str) or not identity["path"]
                or not isinstance(identity.get("sha256"), str)
                or len(identity["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in identity["sha256"])):
            raise ComparisonError(f"final report lacks {label} identity")
        path = baseline_binary if label == "baseline" else candidate_binary
        if path is not None and (not path.is_file() or sha256_file(path) != identity["sha256"]):
            raise ComparisonError(f"{label} binary digest changed")
    raw = report.get("raw_samples")
    if not isinstance(raw, list):
        raise ComparisonError("final report lacks raw samples")
    positions, workloads = aggregate(raw, records, list(range(1, repetitions + 1)))
    if (canonical_json(report.get("positions")) != canonical_json(positions)
            or canonical_json(report.get("workloads")) != canonical_json(workloads)):
        raise ComparisonError("final report aggregates do not match raw samples")
    return baseline_binary is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--start-repetition", type=int, default=1)
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--fragments", type=Path, nargs="+")
    parser.add_argument("--time-limit-ms", type=int, default=300000)
    parser.add_argument("--progress-every", type=positive_interval, default=1)
    args = parser.parse_args(argv)
    try:
        if args.verify_report:
            if not args.corpus:
                raise ComparisonError("--verify-report requires --corpus")
            rehashed = verify_report(json.loads(args.verify_report.read_text(encoding="utf-8")),
                                     load_corpus(args.corpus), args.baseline, args.candidate)
            print("verified comparison report data" +
                  (" and supplied binary digests" if rehashed else
                   "; recorded binary digests were not rehashed"))
            return 0
        if args.output is None:
            raise ComparisonError("--output is required for comparison or fragment merge")
        if args.fragments:
            report = merge_fragments([json.loads(path.read_text(encoding="utf-8")) for path in args.fragments])
        else:
            if not args.baseline or not args.candidate or not args.corpus:
                raise ComparisonError("--baseline, --candidate, and --corpus are required without --fragments")
            progress = Progress(args.progress_every)
            report = compare(args.baseline, args.candidate, load_corpus(args.corpus), args.repetitions, args.time_limit_ms, start_repetition=args.start_repetition, warmup=not args.no_warmup, progress_every=args.progress_every, progress=progress)
        if args.fragments:
            progress = Progress(args.progress_every)
        stage = progress.stage("output-publication")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(canonical_json(report) + "\n", encoding="utf-8")
        progress.stage("output-publication", stage)
    except ComparisonError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
