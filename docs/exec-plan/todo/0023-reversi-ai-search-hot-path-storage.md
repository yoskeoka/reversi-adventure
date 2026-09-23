# Child plan: remove recursive search heap allocation

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Remove heap-backed principal-variation and exact-cache work from recursive
search nodes using bounded search-owned storage. Preserve the complete public
search output, bound peak memory, and report the parent 0020 timing result for
the user to decide whether to retain the experiment.

This plan does not change move ordering, alpha-beta windows, evaluator calls,
TT context identity, or the heuristic/exact cache boundary. Exact PV
reconstruction may add deterministic proof work, which is counted explicitly.

Before PR preparation, record both workload ratios and the report digest in
parent 0020. The user decides whether to retain an experiment; no node-count
threshold makes that decision. CPU comparison is wall-clock based, while peak
memory and the configured wall-clock deadline are the resource constraints.

## Existing references

- `rust/reversi-ai/src/search/negascout.rs:18-23,131-173,204-268` creates and
  extends `Vec<Position>` values throughout heuristic recursion, including TT
  cutoffs.
- `rust/reversi-ai/src/search/endgame.rs:8-34,108-210` stores a PV `Vec` in
  every `HashMap` exact entry and clones it on cache hits.
- `rust/reversi-ai/src/search/tt.rs:78-124` is the existing fixed-capacity
  heuristic table and replacement precedent.
- `docs/specs/reversi-ai.md:384-402` requires a complete exact PV while
  prohibiting partial PV/score exposure on interruption.
- Edax keeps bounded search/result lines in search-owned structures rather
  than a heap object per node (`src/search.h` and `src/search.c`):
  <https://github.com/abulmo/edax-reversi>.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` and the performance evidence -- internal
  storage limits, cache identity/replacement, and accepted/rejected result.
- (MODIFY) `rust/reversi-ai/src/search/negascout.rs` -- per-ply bounded PV and
  leaf-result storage owned by one search invocation.
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs` -- score/bound/best-move
  entries without PV vectors plus bounded preallocated exact cache/storage.
- (MODIFY) focused search, cache-collision, pass, interruption, and profiler
  tests.

## Black-box contract and work

1. Allocate bounded heuristic PV scratch storage once per root search, indexed
   by ply. Recursive heuristic nodes return compact score/status data and
   update the caller's line only when a new best move is accepted. Copy the
   completed heuristic root line into the public `Vec` only once.
2. Replace the solve-local `HashMap<u64, ExactEntry>` with a bounded,
   preallocated table. Each hit must verify complete board plus side-to-move
   identity (not hash alone); replacement is deterministic and prefers the
   more valuable remaining-depth/exact-bound entry.
3. Exact cache hits are score/bound evidence only and never supply a completed
   PV from the current recursion scratch. After the root score is proven, run
   a deterministic reconstruction pass from the root: at each node follow the
   first move in the established order whose identity-checked child score
   proves the parent score, recurse across passes without appending a sentinel,
   and verify the terminal disc difference. Re-search a missing/evicted child
   with cache cutoffs disabled as needed. The reconstruction uses the same
   budget; if it is interrupted or cannot prove every ply, return the existing
   non-exact fallback with no score/PV rather than a truncated exact line.
4. Bound entries never manufacture a principal variation. Cache entries retain
   score, bound, and best move only; reconstruction must not trust a best-move
   chain without revalidating board identity, legality, and score consistency.
5. Preserve the existing heuristic TT, evaluator/search-context invalidation,
   solver-local lifetime, cache separation, and budget polling cadence. Public
   `nodes_searched` includes all search work. Memory use must be explicitly
   bounded and reported; no implementation-specific node split is required.
6. Require identical 0021 outcomes, scores, PVs, depths, and exact flags before
   considering the timing gate. Node counts are diagnostic only and need not be
   split by implementation technique.

## Dependencies and sequencing

- Depends on accepted or rejected 0022; run from the resulting latest `main`.
- Blocks both the midgame track (0024--0025) and exact track (0026--0028).

## Verification

- Unit tests for maximum PV length, pass-without-placement, exact-cache hits
  from another branch, evicted reconstruction entries, score-inconsistent
  best moves, cache collisions, deterministic replacement, and
  exact/heuristic cache isolation.
- Interruption at each representative ply must return only the old legal
  fallback or last wholly completed iteration, never scratch/PV residue.
- Differential results against the pre-change engine on the 0021 suite and a
  deterministic reachable-position corpus; require semantic non-time fields to
  match. Record node totals as diagnostics, not an acceptance limit.
- Apply the timing gate and report bounded peak storage; run Rust tests,
  Clippy, GDExtension build, workflow lint, and `git diff --check`.

## Addresses

- N/A; parent 0020 owns `docs/issues/0011-exact-solver-20-performance.md`.
