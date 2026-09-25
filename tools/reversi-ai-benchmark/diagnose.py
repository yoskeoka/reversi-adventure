#!/usr/bin/env python3
"""Validate cost-only fixed-node traces and summarize diagnostic counters."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from compare import ComparisonError, canonical_json, load_corpus, sha256_file


FIELDS = ("position_id", "board_digest", "outcome", "score", "pv",
          "completed_depth", "exact", "nodes_searched")


def load_diagnostics(path: Path, expected_ids: list[str]) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if [row.get("position_id") for row in rows] != expected_ids:
        raise ComparisonError(f"diagnostic positions are incomplete or out of order: {path}")
    for row in rows:
        diagnostic = row.get("cost_diagnostics")
        if (not isinstance(diagnostic, dict)
                or not isinstance(diagnostic.get("trace_sha256"), str)
                or len(diagnostic["trace_sha256"]) != 64
                or type(diagnostic.get("trace_events")) is not int
                or diagnostic["trace_events"] <= 0):
            raise ComparisonError(f"missing ordered trace: {path}")
        if not all(field in row for field in FIELDS):
            raise ComparisonError(f"missing result projection: {path}")
    return rows


def summarize(rows: list[dict]) -> dict:
    counters: dict[str, dict[str, int]] = {}
    for row in rows:
        for name, values in row["cost_diagnostics"]["counters"].items():
            entry = counters.setdefault(name, {"calls": 0, "inclusive_ns": 0})
            entry["calls"] += values["calls"]
            entry["inclusive_ns"] += values["inclusive_ns"]
    return counters


def report(corpus: Path, original: Path, tuned: Path, trained: Path) -> dict:
    records = load_corpus(corpus)
    ids = [row["position_id"] for row in records]
    stone_counts = {row["position_id"]: row["stone_count"] for row in records}
    before = load_diagnostics(original, ids)
    after = load_diagnostics(tuned, ids)
    trained_rows = load_diagnostics(trained, ids)
    node_limit = before[0].get("node_limit")
    if type(node_limit) is not int or node_limit <= 0 or any(
        row.get("node_limit") != node_limit for row in before + after + trained_rows
    ):
        raise ComparisonError("diagnostic node-only budgets differ")
    for left, right in zip(before, after):
        if any(left[field] != right[field] for field in FIELDS):
            raise ComparisonError(f"cost-only result or node mismatch: {left['position_id']}")
        if left["cost_diagnostics"]["trace_sha256"] != right["cost_diagnostics"]["trace_sha256"]:
            raise ComparisonError(f"ordered trace mismatch: {left['position_id']}")
    for row in trained_rows:
        if row.get("evaluator") != "trained" or not row.get("artifact_sha256"):
            raise ComparisonError("trained diagnostic lacks a fixed artifact")
        if stone_counts[row["position_id"]] == 48 and any(
            row["cost_diagnostics"]["counters"].get(name, {}).get("calls", 0)
            for name in ("heuristic_leaf_eval", "trained_feature_extract", "trained_lookup")
        ):
            raise ComparisonError(f"exact solver called evaluator: {row['position_id']}")
    if len({row["artifact_sha256"] for row in trained_rows}) != 1:
        raise ComparisonError("trained artifact changed between positions")
    return {
        "schema_version": 1,
        "node_limit": node_limit,
        "corpus_sha256": sha256_file(corpus),
        "original": {"jsonl_sha256": sha256_file(original), "counters": summarize(before)},
        "tuned": {"jsonl_sha256": sha256_file(tuned), "counters": summarize(after)},
        "trained": {"jsonl_sha256": sha256_file(trained),
                    "artifact_sha256": trained_rows[0]["artifact_sha256"],
                    "evaluator_context": trained_rows[0]["evaluator_context"],
                    "counters": summarize(trained_rows)},
        "positions": [{"position_id": row["position_id"],
                       "trace_sha256": row["cost_diagnostics"]["trace_sha256"],
                       "nodes_searched": row["nodes_searched"]} for row in before],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("corpus", "original", "tuned", "trained", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = report(args.corpus, args.original, args.tuned, args.trained)
        args.output.write_text(canonical_json(result) + "\n", encoding="utf-8")
    except (ComparisonError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
