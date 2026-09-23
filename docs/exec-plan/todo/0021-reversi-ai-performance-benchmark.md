# Child plan: finish the Reversi search performance benchmark

> **Execution**: Use `/execute-task` for this plan. After the work is complete,
> use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Finish the work left after the profiler foundation in PR #195
(`bc3ece052154f5fa591922870adedf50a69a7ee7`) and the corpus foundation in
PR #196 (`f1255fe5d863f110029c75c87e631e780f98de36`).

The checked-in corpus has sixteen positions. Each of its four pinned self-play
games supplies positions at 20, 40, 44, and 48 occupied discs. The remaining
work is a reference-analysis profile and report, a same-host release
comparator, a true-current-`main` baseline, CI schema and arithmetic coverage,
and documentation that later optimization plans can use unchanged.

This plan adds performance evidence only. Search optimization, evaluator
training, 0018 strength acceptance, the public move-only CLI, and CI speed
assertions stay unchanged.

## Existing references

- `docs/specs/reversi-ai.md` defines the completed fixed-node and full-depth
  timing modes plus the immutable sixteen-position corpus; it still needs the
  reference-analysis, release-comparison, and non-CI timing contract.
- `rust/reversi-ai/src/bin/reversi-ai-search-profile.rs` and
  `rust/reversi-ai/tests/search_profile.rs` provide the completed fresh-engine,
  time-only profiling foundation.
- `tools/reversi-ai-benchmark/positions-v1.jsonl` and its `README.md` provide
  the completed canonical corpus and its generation/validation entry points.
- `tools/reversi-ai-oracle/oracle.py` and
  `tools/reversi-ai-oracle/tests/test_oracle.py` own corpus validation and are
  the boundary for the new pinned reference analysis.
- `Makefile` exposes the completed corpus setup, generation, and verification
  commands and is the entry point for the remaining reference and comparison
  commands.
- `rust/reversi-ai/src/search/endgame.rs:344-391` contains independent
  oracle-checked 13--16-empty exact fixtures.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- define reference-analysis identity,
  workload semantics, raw/summary report fields, and the non-CI timing rule.
- (MODIFY) `tools/reversi-ai-oracle/oracle.py`, its tests, `Makefile`, and the
  benchmark README -- add pinned reference analysis and its validation.
- (NEW) `tools/reversi-ai-benchmark` comparison runner and focused tests --
  build, warm-up, alternating-run, environment, raw-sample, and summary
  contract over the existing corpus.
- (NEW) `docs/references/reversi-ai-search-performance-v1.md` -- immutable
  current-main baseline commit, environment, raw report digest, and summary.

## Black-box contract and work

1. Define a separate versioned `search-performance-reference-v1` oracle
   analysis profile: the same pinned source digest, one thread, hash level 25,
   bookless/default evaluation, fixed 100%-probability depth 12 for every
   midgame root, and complete depth 16 for the exact roots. Serialize the full
   configuration and its digest in every report. This profile is not the
   `strong-engine-hcap-v1` self-play profile, whose depth ranges remain
   unchanged. Store final root-side score and optimal move set for exact roots,
   and store depth-12 midgame analysis as reference only; the benchmark
   measures the project strategic evaluator directly.
2. The comparator accepts explicit baseline and candidate release binaries,
   alternates their order for each board, performs one warm-up and at least
   five measured repetitions, and emits canonical JSON with raw nanoseconds,
   per-position medians/ratios, workload geometric means, nodes, outcome,
   score, PV, completed depth, exactness, commits, rustc/build flags, OS,
   architecture, CPU model, and runner version.
3. CI validates reference/report schemas and digests, exact oracle metadata,
   deterministic non-time fields, and comparison arithmetic with a fake clock.
   It never fails on elapsed speed. The human-run release command is the only
   source of performance evidence.

## Dependencies and sequencing

- Depends on merged 0015 search profiling and 0016 exact-16 work, now present
  on `main` through PRs #191 and #190.
- Blocks every optimization child in parent 0020.
- The suite is performance-only and must remain disjoint from 0018 held-out
  openings and 0019 training/validation records.

## Verification

- Oracle-tool unit tests for the distinct reference profile, depth-12 range
  enforcement, exact metadata, digest/profile mismatch, timeout, and malformed
  reference reports.
- Comparator tests with synthetic timings for alternation, medians, geometric
  means, thresholds, environment mismatch, and malformed/missing samples.
- Run the documented same-host release baseline and store its raw report and
  digest; run Rust/Python tests, Clippy, GDExtension build, workflow lint, and
  `git diff --check`.

## Addresses

- N/A; parent 0020 owns `docs/issues/0011-exact-solver-20-performance.md`.
