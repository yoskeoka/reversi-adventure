# Child plan: specialize exact parity and last-empty search

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Remove repeated heap-backed region discovery, generic move sorting, and generic
recursion from the final exact plies by maintaining empty-region parity and
using scalar last-empty routines. Accept only if exact results are unchanged
and the 0021 exact timing gate passes.

The implementation remains portable stable Rust. It may specialize by number
of empty squares, not by CPU architecture or instruction set.

Record both workload ratios and the report digest in parent 0020. The user
decides whether to retain the experiment; CPU comparison is wall-clock based,
with peak memory and the configured wall-clock deadline as resource limits.

## Existing references

- `rust/reversi-ai/src/search/endgame.rs:219-262` sorts every node by calling
  general ordering and recomputes one connected region per candidate using a
  heap-backed frontier.
- `rust/reversi-ai/src/search/endgame.rs:108-218` keeps only board/color in its
  recursive state and uses the generic path through terminal positions.
- `rust/reversi-engine/src/moves.rs:46-99` supplies flip and successor
  primitives inherited from 0022.
- Egaroucid has generic scalar specialized last-four search and parity ordering
  in `src/engine/endsearch_nws_last_generic.hpp`:
  <https://github.com/Nyanyan/Egaroucid/blob/main/src/engine/endsearch_nws_last_generic.hpp>.
- Edax maintains an empty-square list/parity state and specialized last-four
  solver in `src/search.c:883-916` and `src/endgame.c:279-430`:
  <https://github.com/abulmo/edax-reversi>.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` and performance evidence -- maintained
  empties/parity semantics, specialization boundary, and experiment result.
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs` -- bounded empty-square
  state, allocation-free region parity, deterministic move selection, and
  specialized final one-through-four-empty routines.
- (MODIFY) engine move helpers only if a portable flip-mask primitive from
  0022 needs internal reuse; public rules remain unchanged.
- (MODIFY) exact differential, parity, pass, and profiler tests.

## Black-box contract and work

1. Build the empty-square list and orthogonal connected components at the exact
   root. Removing a played square may split its old component, so recompute the
   affected remaining component(s) with an allocation-free bitset flood fill
   after every placement and restore the prior masks from bounded per-ply
   state. A pass is the only transition that leaves empties and component
   membership unchanged.
2. Replace `Vec` region traversal and general sorting with fixed arrays/bitsets.
   Preserve TT move first, odd-region preference, existing secondary order,
   and deterministic equal-score tie-breaking.
3. Dispatch the final one through four empty squares to dedicated scalar
   routines that enumerate only legal placements, handle intervening passes,
   compute the final root-side disc differential, and obey the same alpha-beta
   window and budget. Fall back to the generic exact path above the frozen
   specialization boundary.
4. The fast path must update node counters and cancellation/deadline checks
   according to one documented definition so it cannot appear faster by
   undercounting or becoming uninterruptible.
5. Require identical exact outcome, score, full PV, depth, tie-break, and flag.
   Apply the exact timing gate and shared midgame allowance.

## Dependencies and sequencing

- Depends on the accepted/rejected outcome of 0026 and its latest `main`.
- Blocks 0028 and is required before 0019's long-running manifest is frozen.

## Verification

- Exhaustively compare specialized and generic solvers for every reachable
  position in a bounded one-through-four-empty corpus, both sides to move,
  including pass and game-over cases.
- Property tests for empty-list update/restore, bridge-square removal that
  splits one region into two or more components, component masks, parity after
  a move/pass, ordering stability, and node/budget accounting.
- Differential oracle-checked 13--16-empty fixtures and all 0021 exact boards;
  apply the timing gate and rerun the 20-empty `+26` fixture for five minutes.
- Rust tests, Clippy, GDExtension build, workflow lint, and `git diff --check`.

## Addresses

- N/A; parent 0020 owns `docs/issues/0011-exact-solver-20-performance.md`.
