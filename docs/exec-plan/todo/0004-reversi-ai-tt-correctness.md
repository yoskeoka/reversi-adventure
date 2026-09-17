# Correct Reversi AI transposition-table identity

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Make cached search results valid only in the context that produced them. A TT
probe must never reuse a score, bound, or best move from the other side to move
or from a different evaluator/parameter/search-semantics context. This plan
does not add search strength features or alter the current public difficulty
presets.

## Existing references

- `rust/reversi-ai/src/search/tt.rs:20-62` hashes board discs only.
- `rust/reversi-ai/src/search/negascout.rs:80-144` probes and stores
  side-dependent scores and best moves; `:147-164` permits a pass without
  changing the board.
- `rust/reversi-ai/src/search/mod.rs:28-62` retains one TT while accepting an
  evaluator for each search call.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- define a TT entry as scoped to board,
  side to move, and evaluator/search-context identity.
- (MODIFY) `rust/reversi-ai/src/search/tt.rs`, `search/negascout.rs`, and
  `search/mod.rs` -- add a side-to-move Zobrist key and evaluator/context
  fingerprint, or explicitly clear the TT whenever that context changes.
- (MODIFY) search tests -- cover a pass position and distinct evaluator
  fingerprints.
- (DELETE) this plan after implementation verification and PR preparation.

## Execution steps

1. Extend the TT key with side to move.
2. Define a stable context fingerprint covering evaluator identity, parameter
   vector/version, and semantics that change score meaning; namespace entries
   by it or clear the table before it changes.
3. Keep board color-inversion symmetry reuse out of scope: it needs explicit
   board, perspective, score, and move transformation and must not be inferred
   from an omitted side key.
4. Add regressions proving that the same discs with the other player to move,
   and the same position searched by distinct evaluator contexts, cannot reuse
   the old entry.

## Verification

- `cargo test -p reversi-ai`
- `cargo clippy --workspace -- -D warnings`
- Pass-position and evaluator-context TT regressions.

## Addresses

N/A
