# Child plan: make move generation a portable bitboard hot path

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Replace candidate-by-candidate board scanning with architecture-neutral `u64`
bitboard propagation and carry each already computed flip mask into successor
construction. Accept the implementation only if it preserves exhaustive move
semantics and improves the combined 0021 benchmark according to parent 0020's
gate. A candidate that is correct but does not clear the timing gate is removed
and recorded as rejected.

No SIMD, target-feature dispatch, unsafe code, mutable/unmake board API, public
game-rule change, or search-tree pruning belongs to this plan.

## Existing references

- `rust/reversi-engine/src/moves.rs:17-105` scans every empty square through
  eight row/column walks, then `make_move` recomputes the same flips.
- `rust/reversi-ai/src/search/ordering.rs:22-108` already retains successor
  boards when mobility ordering had to construct them.
- `rust/reversi-ai/src/search/negascout.rs:182-220` and
  `rust/reversi-ai/src/search/endgame.rs:147-190` consume legal masks and build
  successors at every node.
- Edax describes a portable Kogge--Stone-style partial move generator and a
  move object that carries flipped discs in `src/board.c:679-780` and
  `src/move.h:11-39`: <https://github.com/abulmo/edax-reversi>.
- Egaroucid keeps a non-AVX implementation in
  `src/engine/mobility_generic.hpp`:
  <https://github.com/Nyanyan/Egaroucid/blob/main/src/engine/mobility_generic.hpp>.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` and
  `docs/references/reversi-ai-search-performance-v1.md` -- record unchanged
  semantics, portable constraints, and accepted/rejected benchmark evidence.
- (MODIFY) `rust/reversi-engine/src/moves.rs` -- scalar directional bitboard
  legal-move/flip primitives and an internal move descriptor containing
  position plus flips.
- (MODIFY) engine callers and tests -- apply a validated descriptor without
  recalculating flips while retaining the existing public checked APIs.
- (MODIFY) `rust/reversi-ai/src/search/{ordering,negascout,endgame}.rs` -- use
  generated descriptors/successors without changing ordering or pruning.

## Black-box contract and work

1. Implement legal-move propagation only with portable stable-Rust integer
   operations and explicit file-edge masks. Retain a test-only straightforward
   reference implementation independent of the optimized code.
2. Represent a generated legal move with its position and exact flip mask.
   Search may construct the child board directly from that descriptor; public
   `make_move`, legality errors, `Game`, GDExtension, board orientation, and
   notation remain unchanged.
3. Preserve canonical legal-mask bits, every flipped disc, deterministic move
   order, pass/game-over detection, node counts, outcome, score, PV, completed
   depth, exact flag, and interruption polling. This experiment changes cost
   per node only.
4. Do not translate or copy GPL source. Document the algorithmic references
   and independently implement the project's board orientation and masks.
5. Compare the immediate pre-change commit and candidate with the 0021 runner.
   Accept only the shared-gate result; otherwise revert production changes and
   record the rejected report/digest.

## Dependencies and sequencing

- Depends on completed 0021 and is the first optimization child.
- Blocks 0023--0028 so later experiments inherit one move primitive and do not
  confound their baselines.

## Verification

- Exhaustively compare optimized and reference legal masks/flips for all moves
  across a large deterministic corpus of reachable boards, both colors,
  corners/edges, multi-direction flips, passes, and terminal states.
- Replay the oracle benchmark game transcripts and existing engine fixtures
  through both implementations with byte-identical final boards/results.
- Require identical 0021 non-time fields and node counts, then apply the
  timing gate to both workload classes.
- Rust engine/AI tests, Clippy, GDExtension build, Miri or sanitizer checks if
  available without weakening the required gates, workflow lint, and
  `git diff --check`.

## Addresses

- N/A; parent 0020 owns `docs/issues/0011-exact-solver-20-performance.md`.
