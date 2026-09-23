# Child plan: try enhanced transposition cutoffs

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Reduce heuristic depth-12 CPU time by probing already generated child positions
for sound transposition-table cutoffs before recursive search. Preserve the
full-depth result, report the 0021 timing result, and leave retention to the
user; node totals are diagnostic only.

This plan does not add selective pruning, new evaluation, a second TT, exact-
solver cache sharing, or prefetch/CPU-specific instructions.

Record both workload ratios and the report digest in parent 0020. The user
decides whether to retain the experiment; CPU comparison is wall-clock based,
with peak memory and the configured wall-clock deadline as resource limits.

## Existing references

- `rust/reversi-ai/src/search/negascout.rs:141-180` applies current-node TT
  bounds; `204-220` already owns ordered successor boards.
- `rust/reversi-ai/src/search/tt.rs:9-30,87-124` defines entry depth, bounds,
  direct indexing, and deterministic replacement.
- `rust/reversi-ai/src/search/mod.rs:105-178` scopes TT contents to evaluator,
  configuration, and search-semantics identity.
- Egaroucid describes Enhanced Transposition Cutoff separately from its
  selective search in `src/engine/transposition_cutoff.hpp`:
  <https://github.com/Nyanyan/Egaroucid/blob/main/src/engine/transposition_cutoff.hpp>.
- Edax's PVS path documents hash and enhanced cutoff use in
  `src/midgame.c`: <https://github.com/abulmo/edax-reversi>.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` and performance evidence -- qualifying
  child-bound proof, probe counters, semantics identity, and result.
- (MODIFY) `rust/reversi-ai/src/search/{negascout,ordering,tt}.rs` -- store and
  verify complete board/side identity for all heuristic TT probes, expose child
  depth/bound data, and perform the bounded ETC pass.
- (MODIFY) `rust/reversi-ai/src/search/mod.rs` -- bump search semantics for an
  accepted traversal change.
- (MODIFY) TT/search/profiler tests.

## Black-box contract and work

1. Extend each heuristic TT entry with the complete black bitboard, white
   bitboard, and side to move. Every existing current-node probe and every new
   child probe must compare that identity after indexing by Zobrist hash;
   context remains protected by table invalidation. Hash equality alone is
   never sufficient for a score, bound, or best-move hit.
2. At a configured minimum remaining depth, inspect each legal successor that
   ordering already constructed. A child entry may cut off only when its
   collision-safe identity, stored remaining depth, and bound prove the parent
   null/full-window result after negation. A best-move hint alone is not a
   cutoff.
3. Probe in the existing deterministic move order. Count ETC probes, hits, and
   cutoffs separately in diagnostics without changing public game APIs.
4. If no child proves a cutoff, continue the existing PVS path unchanged. The
   plan may order a proven-best child first only when doing so preserves the
   established tie-break rule.
5. Do not apply ETC to the exact solver in this experiment. Preserve context
   invalidation, collision checks, interruption polling, and completed-
   iteration publication.
6. Freeze the minimum-depth rule before performance measurement. Require
   identical 0021 completed outputs; node counts may decrease. Apply the
   midgame gate and shared exact-regression allowance.

## Dependencies and sequencing

- Depends on the accepted/rejected outcome of 0024 and uses that latest
  `main` as its immediate baseline.
- Completes the nonselective midgame track before 0019's manifest is frozen.

## Verification

- Construct exact/lower/upper child entries at shallower/equal/deeper depths
  and prove that only qualifying bounds cut off after correct sign/window
  conversion. Inject identical-hash entries for different boards/sides and
  require misses in both legacy current-node probes and ETC child probes.
- Collision, changed evaluator/config/search semantics, pass, cancellation,
  and no-hit tests must take the old path.
- Differential full-depth search over the 0021 suite and deterministic random
  reachable boards; require identical outcomes, scores, PVs, depths, and
  exactness.
- Apply the timing gate and report ETC counters; run Rust tests, Clippy,
  GDExtension build, workflow lint, and `git diff --check`.

## Addresses

- N/A; parent 0020 owns `docs/issues/0011-exact-solver-20-performance.md`.
