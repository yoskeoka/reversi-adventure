# Parent plan: make Reversi search performance measurable and improve it

> **Execution**: Do not implement from this parent. Approve and execute the detailed child plans in this series with `/execute-task`, then use `/review-task` for each PR.

## Objective and completion boundary

Reduce same-host release-build elapsed time for both project search workloads
that dominate matches and reinforcement: strategic midgame search through
depth 12 and evaluator-independent exact solving from 16 empty squares. Use a
versioned suite of sixteen positions. Four pinned self-play games each supply
positions at 20, 40, 44, and 48 occupied discs. Then try each
architecture-neutral technique in a separate, rollbackable child plan.

The series is complete only when all child experiments have an accepted or
rejected report, the accumulated accepted changes reduce the geometric mean of
per-position median time by at least 20% in both workload classes relative to
the 0021 baseline, and the existing 20-empty fixture completes with oracle
score `+26` inside five minutes. If the last condition is still missed, keep
this parent and `docs/issues/0011-exact-solver-20-performance.md` active and add
another measured child rather than raising the supported threshold. This
series does not itself change the default 16-empty threshold.

GPU execution, multithreaded search, SIMD, target-specific intrinsics,
`target-cpu=native`, and other optimizations that require a particular CPU
feature are out of scope. Egaroucid and Edax are algorithm references only:
their GPL code, weights, binaries, and formats are not copied into Rust,
GDExtension, or release artifacts.

## Existing references

- `docs/issues/0011-exact-solver-20-performance.md:1-37` records the legal
  20-empty fixture, oracle `+26` result, and current five-minute failure.
- `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md:5-64`
  defines the self-play workload whose cycle cost this work must reduce.
- `docs/specs/reversi-ai.md` defines the completed fixed-node and full-depth
  timing profiler plus the immutable sixteen-position corpus.
- `rust/reversi-engine/src/moves.rs:17-105` currently scans every empty square
  and recomputes flips when applying a move.
- `rust/reversi-ai/src/search/negascout.rs:18-291` and
  `rust/reversi-ai/src/search/endgame.rs:8-262` are the heuristic and exact
  hot paths.
- Edax documents portable bitboard generation, PVS, hash/ordering, and exact
  last-empty search in `src/board.c`, `src/midgame.c`, and `src/endgame.c`:
  <https://github.com/abulmo/edax-reversi>.
- Egaroucid documents generic mobility, transposition cutoffs, move ordering,
  and exact NWS in `src/engine/`:
  <https://github.com/Nyanyan/Egaroucid>.

## Change map

- (NEW) detailed executable plans `0021` through `0028`.
- (MODIFY) `docs/exec-plan/todo/0009-reversi-ai-strong-engine.md`,
  `0018-reversi-ai-strong-engine-acceptance.md`, and
  `0019-reversi-ai-pattern-reinforcement-cycle.md` -- make the performance
  series and its accepted outcomes explicit dependencies.
- (MODIFY) future `docs/specs/reversi-ai.md` and performance evidence -- N/A -
  detail is owned by each child plan.
- (MODIFY) future engine/search/tooling paths -- N/A - detail is owned by each
  child plan.
- (DELETE) this parent and `docs/issues/0011-exact-solver-20-performance.md`
  only after every completion condition above is satisfied.

## Child plans and sequencing

1. `0021-reversi-ai-performance-benchmark.md` completes the reference analysis,
   release comparator, and immutable baseline using the existing sixteen-
   position corpus and full-depth profiler. No optimization starts before it
   merges.
2. `0022-reversi-engine-portable-bitboard-moves.md` replaces per-empty-square
   move generation and carries computed flips into move application.
3. `0023-reversi-ai-search-hot-path-storage.md` removes recursive heap-backed
   PV/cache allocation while preserving public results and interruption.
4. `0024-reversi-ai-aspiration-windows.md` tries bounded iterative-deepening
   score windows for the midgame workload.
5. `0025-reversi-ai-enhanced-transposition-cutoff.md` tries sound child-TT
   cutoffs using already generated successors.
6. `0026-reversi-ai-exact-pvs.md` applies full-window-first/null-window exact
   search without selective pruning.
7. `0027-reversi-ai-exact-parity-last-empties.md` removes generic collection
   and region work from the final empties with maintained parity state.
8. `0028-reversi-ai-exact-stability-cutoff.md` adds only mathematically sound,
   conservative exact score bounds from proven stable discs.

Plans `0022` and `0023` are shared foundations and run serially. After them,
the midgame track (`0024` then `0025`) and exact track (`0026` then `0027` then
`0028`) may proceed in parallel, but each experiment starts from the latest
accepted `main` in its track and compares against its immediate parent. A child
merges production code only if its predeclared gate passes. A rejected child
records the report and removes the experiment code.

Multi-ProbCut is intentionally deferred: it is selective, evaluator-specific,
and can trade strength for speed, so it needs a separate calibration plan if
the exact, nonselective series is insufficient. Opening books, learned weights,
and parallel search remain owned by their existing plans.

## Shared acceptance rules

- Build both baseline and candidate in release mode with Rust 1.98.1, default
  portable target features, and the same host, power policy, and background
  load. Alternate baseline/candidate samples per position.
- Run one warm-up and at least five measured repetitions per binary/position.
  Report every raw elapsed sample, per-position median, workload geometric
  mean, node count, outcome, score, completed depth, PV, and exact flag.
- A child-specific speed win is at least 5% in its targeted workload geometric
  mean with no greater than 3% regression in the other workload. Noise or a
  smaller gain is rejection, not justification to loosen the gate afterward.
- Nonselective changes preserve legal outcome, score, completed depth,
  exactness, deterministic tie-breaking/PV, pass behavior, and the
  last-completed-iteration contract. Node counts may change only for a plan
  that deliberately changes the explored tree.
- Re-run the 20-empty issue fixture with a five-minute monotonic deadline after
  every accepted exact-search child and record completion, score, nodes, and
  elapsed time.

## Verification

N/A - detail is owned by the executable children. Parent closeout verifies the
checked-in reports and recomputes the accumulated before/after summary.

## Addresses

- `docs/issues/0011-exact-solver-20-performance.md`
