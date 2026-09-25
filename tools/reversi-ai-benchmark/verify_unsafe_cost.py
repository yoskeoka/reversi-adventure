#!/usr/bin/env python3
"""Verify fixed-node equivalence for the three 0032 strategic binaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from compare import ComparisonError, canonical_json, load_corpus, sha256_file
from diagnose import FIELDS, load_diagnostics, summarize


def report(corpus: Path, binaries: dict[str, Path], traces: dict[str, Path]) -> dict:
    records = load_corpus(corpus)
    ids = [row["position_id"] for row in records]
    rows = {name: load_diagnostics(path, ids) for name, path in traces.items()}
    node_limits = {row.get("node_limit") for group in rows.values() for row in group}
    if len(node_limits) != 1 or type(next(iter(node_limits))) is not int or next(iter(node_limits)) <= 0:
        raise ComparisonError("fixed-node budgets differ or are missing")
    for name in binaries:
        if name not in rows or not binaries[name].is_file():
            raise ComparisonError(f"missing binary or trace for {name}")
    for triples in zip(*(rows[name] for name in ("main", "safe", "unsafe"))):
        original = triples[0]
        for other in triples[1:]:
            if any(original[key] != other[key] for key in FIELDS):
                raise ComparisonError(f"result or node mismatch: {original['position_id']}")
            if original["cost_diagnostics"]["trace_sha256"] != other["cost_diagnostics"]["trace_sha256"]:
                raise ComparisonError(f"ordered trace mismatch: {original['position_id']}")
    return {
        "schema_version": 1,
        "corpus_sha256": sha256_file(corpus),
        "node_limit": next(iter(node_limits)),
        "binaries": {name: {
            "binary_sha256": sha256_file(binaries[name]),
            "trace_jsonl_sha256": sha256_file(traces[name]),
            "counters": summarize(rows[name]),
        } for name in ("main", "safe", "unsafe")},
        "positions": [{
            "position_id": row["position_id"],
            "nodes_searched": row["nodes_searched"],
            "trace_sha256": row["cost_diagnostics"]["trace_sha256"],
        } for row in rows["main"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path)
    destination.add_argument("--verify-report", type=Path)
    for name in ("main", "safe", "unsafe"):
        parser.add_argument(f"--{name}-binary", type=Path, required=True)
        parser.add_argument(f"--{name}-trace", type=Path, required=True)
    args = parser.parse_args()
    binaries = {name: getattr(args, f"{name}_binary") for name in ("main", "safe", "unsafe")}
    traces = {name: getattr(args, f"{name}_trace") for name in ("main", "safe", "unsafe")}
    try:
        result = report(args.corpus, binaries, traces)
        canonical = canonical_json(result) + "\n"
        if args.verify_report:
            if args.verify_report.read_text(encoding="utf-8") != canonical:
                raise ComparisonError("saved diagnostic report differs from inputs")
        else:
            args.output.write_text(canonical, encoding="utf-8")
    except (ComparisonError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
