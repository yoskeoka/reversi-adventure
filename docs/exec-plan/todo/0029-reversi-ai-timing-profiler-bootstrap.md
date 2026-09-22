# Child plan: land the full-depth timing profiler before performance baselines

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Land the minimal, release-build-only full-depth timing capability in `main` so
that the subsequent performance-benchmark execution can build a true `main`
baseline binary. The change preserves the existing deterministic fixed-node
diagnostic mode, adds no corpus, oracle, comparator, or performance claim, and
does not change the public move-only CLI.

## Existing references

- `docs/specs/reversi-ai.md:302-316` defines the existing fixed-node profiler.
- `rust/reversi-ai/src/bin/reversi-ai-search-profile.rs:11-177` parses the
  fixed-node CLI and creates a fresh engine per input record.
- `rust/reversi-ai/tests/search_profile.rs:10-74` fixes node-mode output
  determinism.
- `rust/reversi-ai/src/search/mod.rs:145-175` already accepts a monotonic
  `SearchBudget` and dispatches exact solving by configured threshold.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- distinguish fixed-node diagnostics
  from full-depth same-host timing samples and their completion predicate.
- (MODIFY) `rust/reversi-ai/src/bin/reversi-ai-search-profile.rs` -- require
  exactly one of `--node-limit` and `--time-limit-ms`; construct a time-only
  monotonic budget for the latter and emit stable timing completion metadata.
- (MODIFY) `rust/reversi-ai/tests/search_profile.rs` -- preserve node-mode
  projection and cover missing/both budget modes plus timing success/failure
  metadata.

## Black-box contract and work

1. Keep `--node-limit` mandatory for legacy diagnostics and preserve its JSON
   fields and deterministic projection.
2. Add `--time-limit-ms` as the mutually exclusive full-depth mode. It needs a
   positive per-position timeout, must not set a node cap, and uses a fresh
   `SearchEngine` per corpus input.
3. A time-mode record identifies its timeout and declares success only when
   the configured phase depth completes with the expected exactness. A timeout,
   cancellation, or partial depth emits a failed sample with a stable reason.
4. Tests use the existing 16-empty fixture for exact completion and avoid
   elapsed-speed assertions.

## Dependencies and sequencing

- This is the prerequisite split from 0021. Merge it before measuring the
  `main` baseline in the benchmark execution branch.
- It depends only on the merged SearchBudget and exact-solver work.

## Verification

- `cargo +1.98.1 test -p reversi-ai --test search_profile`
- `cargo +1.98.1 test -p reversi-ai`
- `cargo +1.98.1 clippy -p reversi-ai --all-targets -- -D warnings`
- `git diff --check`

## Addresses

- N/A; this is a dependency split required to produce a true `main` timing
  baseline.
