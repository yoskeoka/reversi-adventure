#!/usr/bin/env python3
"""Compare two release search profilers on the immutable performance suite."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
from pathlib import Path

RUNNER_VERSION = "search-performance-v1"
WORKLOADS = {
    "midgame-depth-12": {"stones": {20, 40}, "exact_threshold": 0},
    "exact-16": {"stones": {48}, "exact_threshold": 16},
}


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def load_jsonl(path: Path) -> list[dict]:
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(records) != 16:
        raise ValueError("benchmark corpus must contain exactly sixteen records")
    return records


def run(binary: str, corpus: Path, workload: str, timeout_ms: int) -> list[dict]:
    configuration = WORKLOADS[workload]
    threshold = str(configuration["exact_threshold"])
    selected = [r for r in load_jsonl(corpus) if r["stone_count"] in configuration["stones"]]
    expected_count = 8 if workload == "midgame-depth-12" else 4
    if len(selected) != expected_count:
        raise ValueError(f"{workload} must contain exactly {expected_count} records")
    payload = "\n".join(canonical(r) for r in selected) + "\n"
    command = [binary, "--corpus", "-", "--time-limit-ms", str(timeout_ms),
               "--opening-depth", "12", "--midgame-depth", "12", "--endgame-depth", "12",
               "--exact-solver-empty-squares", threshold]
    completed = subprocess.run(command, input=payload, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"profiler failed: {completed.stderr.strip()}")
    samples = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    if len(samples) != expected_count or any(not sample.get("timing_success") for sample in samples):
        raise RuntimeError(f"{workload} produced an incomplete timing sample")
    return samples


def median_ratio(baseline: list[dict], candidate: list[dict]) -> dict:
    by_id = {sample["position_id"]: sample for sample in candidate}
    positions = []
    for old in baseline:
        new = by_id.get(old["position_id"])
        if new is None or old["elapsed_ns"] <= 0 or new["elapsed_ns"] <= 0:
            raise ValueError("missing or invalid timing sample")
        positions.append({"position_id": old["position_id"], "baseline_median_ns": old["elapsed_ns"],
                          "candidate_median_ns": new["elapsed_ns"],
                          "ratio": new["elapsed_ns"] / old["elapsed_ns"]})
    return {"positions": positions,
            "geometric_mean_ratio": math.prod(item["ratio"] for item in positions) ** (1 / len(positions))}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--timeout-ms", type=int, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.timeout_ms <= 0 or args.repetitions < 5:
        parser.error("--timeout-ms must be positive and --repetitions must be at least five")
    raw: dict[str, list[dict]] = {"baseline": [], "candidate": []}
    for repetition in range(args.repetitions + 1):  # first pass is warm-up
        for workload in WORKLOADS:
            order = ("baseline", "candidate") if repetition % 2 == 0 else ("candidate", "baseline")
            for name in order:
                samples = run(getattr(args, name), args.corpus, workload, args.timeout_ms)
                if repetition:
                    raw[name].extend([{**sample, "workload": workload, "repetition": repetition} for sample in samples])
    summaries = {}
    for workload in WORKLOADS:
        old = [s for s in raw["baseline"] if s["workload"] == workload]
        new = [s for s in raw["candidate"] if s["workload"] == workload]
        # Median each binary's repetitions before calculating the ratio.
        medians = []
        for position_id in sorted({s["position_id"] for s in old}):
            old_median = statistics.median(s["elapsed_ns"] for s in old if s["position_id"] == position_id)
            new_median = statistics.median(s["elapsed_ns"] for s in new if s["position_id"] == position_id)
            medians.append({"position_id": position_id, "baseline_median_ns": old_median,
                            "candidate_median_ns": new_median, "ratio": new_median / old_median})
        summaries[workload] = {"positions": medians,
            "geometric_mean_ratio": math.prod(s["ratio"] for s in medians) ** (1 / len(medians))}
    report = {"schema_version": 1, "runner_version": RUNNER_VERSION,
              "corpus_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
              "repetitions": args.repetitions, "timeout_ms": args.timeout_ms,
              "environment": {"os": platform.platform(), "architecture": platform.machine(), "python": platform.python_version()},
              "raw_samples": raw, "summary": summaries}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
