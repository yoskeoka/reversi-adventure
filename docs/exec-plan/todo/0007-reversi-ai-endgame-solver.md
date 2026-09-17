# Implement a shared exact Reversi endgame solver

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Add evaluator-independent exact endgame solving. Below a configured empty-square
threshold, every AI evaluator uses the same pass-aware solver to return final
disc differential and an exact move; heuristic board evaluation is not used for
that completed result. The initial target is up to 16 empty squares subject to
the time-budget evidence from the oracle corpus.

## Existing references

- `docs/issues/0004-endgame-solver.md:1-28` defines the 16-empty target,
  parity ordering, and 1--4-empty special cases.
- `rust/reversi-ai/src/search/negascout.rs:147-164` calls the evaluator at
  terminal nodes and handles passes.
- `rust/reversi-ai/src/search/ordering.rs:22-78` provides current ordering.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- define exact-result semantics and the
  configured endgame threshold.
- (NEW) `rust/reversi-ai/src/search/endgame.rs` -- exact pass-aware negamax/PVS,
  parity-region ordering, and specialized 1--4-empty solvers.
- (MODIFY) `search/mod.rs`, `search/negascout.rs`, and tests -- route all
  evaluators through the solver and mark supported results exact.
- (DELETE) `docs/issues/0004-endgame-solver.md` and this plan after scoped
  implementation verification and PR preparation.

## Execution steps

1. Solve final disc differential exactly, including pass and game-over cases.
2. Implement empty-region parity ordering and specialized small-empty paths.
3. Make the solver a common search component, not an evaluator feature.
4. Configure the maximum threshold per time preset; lower it rather than label
   a heuristic result exact when the budget cannot complete.

## Verification

- Exact fixtures for 1--4, pass, and representative 5--16-empty positions.
- Compare supported results with the pinned oracle corpus.
- Confirm all evaluator variants receive the same exact result.

## Addresses

- `docs/issues/0004-endgame-solver.md`
