# Child plan: establish the Reversi search performance benchmark

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Create a reproducible performance suite of exactly eight legal decision
positions from four pinned Egaroucid-versus-Egaroucid games: four distinct
midgame positions for complete heuristic depth-12 search and four distinct
positions with exactly 16 empty squares for exact solving. Completion checks in
the immutable suite, provenance and correctness metadata, a release benchmark
runner, a baseline report for current `main`, and a comparator used unchanged
by plans 0022--0028.

This plan measures performance; it does not optimize search, use benchmark
positions for evaluator training or 0018 strength acceptance, change the
public move-only CLI, or make wall-clock assertions in CI.

## Existing references

- `docs/specs/reversi-ai.md:302-316` defines the diagnostics-only fixed-node
  profiler and separates deterministic output from supplemental elapsed time.
- `rust/reversi-ai/src/bin/reversi-ai-search-profile.rs:11-80,125-177` requires
  a node ceiling and emits one elapsed value per corpus position.
- `tools/reversi-ai-oracle/oracle.py:1268-1366` plays candidate/oracle games;
  it does not yet run two isolated pinned oracle sides or extract benchmark
  positions.
- `tools/reversi-ai-oracle/oracle.py:1388-1503` owns the external-tool CLI and
  its fail-closed profile/corpus handling.
- `tools/reversi-ai-oracle/tests/test_oracle.py:29-42,258-275` exercises corpus
  validation and the fake external protocol.
- `rust/reversi-ai/tests/search_profile.rs:10-74` preserves fixed-node
  profiler determinism.
- `rust/reversi-ai/src/search/endgame.rs:344-391` contains independent
  oracle-checked 13--16-empty exact fixtures.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- define performance-suite identity,
  workload semantics, raw/summary report fields, and the non-CI timing rule.
- (MODIFY) `tools/reversi-ai-oracle/oracle.py`, tests, README, and `Makefile` --
  add explicit benchmark-corpus generation and validation.
- (NEW) `tools/reversi-ai-benchmark/positions-v1.jsonl` -- eight immutable
  oracle-self-play positions with source-game transcripts and digests.
- (NEW) `tools/reversi-ai-benchmark/README.md` and comparison runner -- build,
  warm-up, alternating-run, environment, raw-sample, and summary contract.
- (MODIFY) `rust/reversi-ai/src/bin/reversi-ai-search-profile.rs` and focused
  integration tests -- retain fixed-node mode and add full configured-depth
  completion for one or more selected suite positions.
- (NEW) `docs/references/reversi-ai-search-performance-v1.md` -- immutable
  current-main baseline commit, environment, raw report digest, and summary.

## Black-box contract and work

1. Pin Egaroucid v7.8.1, its existing verified source digest,
   `strong-engine-hcap-v1`, one thread, bookless mode, and four checked-in legal
   opening prefixes. Start an isolated oracle session for each color, replay
   each prefix, and let the two oracles play the remainder. Fail closed on an
   illegal move, pass mismatch, timeout, profile mismatch, incomplete game, or
   non-reproducible transcript.
2. Select one 21--44-stone position and the 48-stone decision position from
   each game. Require eight unique boards with no D4-symmetry duplicates,
   legal side-to-move metadata, source game/prefix/transcript digest, occupied
   count, phase, and suite schema/profile digest. Regeneration must reproduce
   identical canonical JSONL bytes.
3. Analyze all exact positions with the pinned oracle at complete depth 16 and
   store final root-side score and optimal move set as correctness metadata.
   Store the oracle depth-12 analysis for midgame positions as reference only;
   the benchmark measures the project strategic evaluator, not imitation.
4. Define `midgame-depth-12` as `AiConfig(12,12,12)` with exact threshold zero,
   and `exact-16` as the same depths with exact threshold 16. Each measured
   invocation uses a fresh `SearchEngine`, completes the configured search
   without a node truncation, and reports a timeout as failure rather than a
   partial timing sample.
5. The comparator accepts explicit baseline and candidate release binaries,
   alternates their order for each board, performs one warm-up and at least
   five measured repetitions, and emits canonical JSON with raw nanoseconds,
   per-position medians/ratios, workload geometric means, nodes, outcome,
   score, PV, completed depth, exactness, commits, rustc/build flags, OS,
   architecture, CPU model, and runner version.
6. CI validates corpus/report schemas, digests, replay legality, exact oracle
   metadata, deterministic non-time fields, and comparison arithmetic with a
   fake clock. It never fails on elapsed speed. The human-run release command
   is the only source of performance evidence.

## Dependencies and sequencing

- Depends on merged 0015 search profiling and 0016 exact-16 work, now present
  on `main` through PRs #191 and #190.
- Blocks every optimization child in parent 0020.
- The suite is performance-only and must remain disjoint from 0018 held-out
  openings and 0019 training/validation records.

## Verification

- Oracle-tool unit tests for two-session self-play, fixed prefixes, legal
  replay, pass/game-over, extraction counts, uniqueness including D4 symmetry,
  digest/profile mismatch, timeout, and byte-identical regeneration.
- Rust integration tests for both workload configurations, exact metadata,
  fresh-engine isolation, timeout failure, and unchanged fixed-node mode.
- Comparator tests with synthetic timings for alternation, medians, geometric
  means, thresholds, environment mismatch, and malformed/missing samples.
- Generate twice and compare the eight-position corpus byte-for-byte; replay
  every transcript and verify all four exact scores with the pinned oracle.
- Run the documented same-host release baseline and store its raw report and
  digest; run Rust/Python tests, Clippy, GDExtension build, workflow lint, and
  `git diff --check`.

## Addresses

- N/A; parent 0020 owns `docs/issues/0011-exact-solver-20-performance.md`.
