# Child plan: try aspiration windows for iterative deepening

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Reduce completed midgame depth-12 work by searching each iterative-deepening
iteration after the first around the previous completed score, widening
deterministically on fail-low or fail-high. Accept only if the final full-depth
result is identical and the 0021 midgame timing gate passes. Exact solving is
unchanged.

Record both workload ratios, report digest, and the accepted/rejected outcome
in parent 0020. Retain the change when either workload improves by at least 5%.

## Existing references

- `rust/reversi-ai/src/search/negascout.rs:48-114` starts every iteration with
  the full integer score window.
- `rust/reversi-ai/src/search/negascout.rs:116-291` implements the existing PVS
  recursion and TT bound storage.
- `rust/reversi-ai/src/search/mod.rs:34-103` defines deadline, node-limit, and
  cancellation behavior that every retry must poll.
- `docs/specs/reversi-ai.md:318-383` requires deterministic node-limited
  results and publication of only wholly completed iterations.
- Edax's iterative PVS implementation is an algorithmic comparison point in
  `src/root.c` and `src/midgame.c`:
  <https://github.com/abulmo/edax-reversi>.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` and performance evidence -- window,
  widening, interruption, node-accounting, and accepted/rejected contract.
- (MODIFY) `rust/reversi-ai/src/search/negascout.rs` -- deterministic initial
  aspiration delta, fail-low/high widening, and full-window terminal fallback.
- (MODIFY) `rust/reversi-ai/src/search/mod.rs` search-semantics identity if the
  accepted node traversal changes retained-TT behavior.
- (MODIFY) focused heuristic search and profiler tests.

## Black-box contract and work

1. Depth 1 uses the full window. Later iterations center a checked integer
   window on the last wholly completed score and widen geometrically and
   symmetrically until the result falls strictly inside or the full score range
   is reached. Overflow must be impossible.
2. A failed window and every retry count their nodes and obey the same budget.
   Interruption during a retry discards the whole current iteration and returns
   the previous completed result; it never publishes a bound as an exact
   heuristic score.
3. TT bound reads/writes remain valid for the searched window. Pass, game-over,
   leaf-evaluation, tie-breaking, and exact-solver dispatch remain unchanged.
4. Tune no per-position window. Freeze one delta/widening rule before the
   candidate timing run and include it in the search-semantics fingerprint.
5. Require identical fully completed outcome, score, PV, depth, and exact flag
   for all 0021 positions; node counts may decrease. Apply the midgame gate and
   reject on an exact-workload regression above the shared allowance.

## Dependencies and sequencing

- Depends on completed 0023.
- Precedes 0025. It may run in parallel with exact-track plan 0026 after 0023.

## Verification

- Unit tests for in-window success, repeated fail-low/high, score-limit
  widening, TT bounds, pass/game-over, and cancellation at each retry.
- Differential full-depth tests against an explicit full-window mode across
  the benchmark and a deterministic reachable-position corpus.
- Fixed-node repeatability is a non-gating diagnostic: candidate runs must
  match each other, while a baseline/candidate completed-depth difference may
  be recorded as changed node use. It cannot waive the acceptance requirement
  that every full-depth 0021 outcome, score, PV, configured depth, and exact
  flag match.
- Apply the 0021 timing gate; run Rust AI tests, Clippy, GDExtension build,
  workflow lint, and `git diff --check`.

## Addresses

- N/A; parent 0020 owns `docs/issues/0011-exact-solver-20-performance.md`.
