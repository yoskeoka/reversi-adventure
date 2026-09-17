# Implement a shared exact Reversi endgame solver

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Add evaluator-independent exact endgame solving. Below a configured empty-square
threshold, every AI evaluator uses the same pass-aware solver. Its score is the
final disc differential from the root side's perspective and its outcome is a
`Move`, `Pass`, or `GameOver`; no fake move is used. The initial target is up to
16 empty squares subject to the time-budget evidence from the oracle corpus.

## Existing references

- `docs/issues/0004-endgame-solver.md:1-28` defines the 16-empty target,
  parity ordering, and 1--4-empty special cases.
- `rust/reversi-ai/src/search/negascout.rs:147-164` calls the evaluator at
  terminal nodes and handles passes.
- `rust/reversi-ai/src/search/ordering.rs:22-78` provides current ordering.
- `rust/reversi-ai/src/explain.rs:50-108` derives heuristic factor deltas and
  needs an exact-result explanation path.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- define exact-result semantics and the
  configured endgame threshold.
- (NEW) `rust/reversi-ai/src/search/endgame.rs` -- exact pass-aware negamax/PVS,
  parity-region ordering, and specialized 1--4-empty solvers.
- (MODIFY) `search/mod.rs`, `search/negascout.rs`, `explain.rs`, and tests --
  route all evaluators through the solver; keep exact and heuristic TT entries
  separate or tagged; and describe exact results as final margin/PV rather than
  heuristic factor deltas.
- (MODIFY) `docs/design-decisions/2026-03-02-reversi-ai-design.md` and
  `docs/references/egaroucid-technology-llms.txt` -- replace links to the
  resolved endgame issue when it is removed.
- (DELETE) `docs/issues/0004-endgame-solver.md` and this plan after scoped
  implementation verification and PR preparation.

## Execution steps

1. Solve final disc differential from the root side's perspective, including
   `Pass` and `GameOver` outcomes.
2. Implement empty-region parity ordering and specialized small-empty paths.
3. Make the solver a common search component shared by all evaluators.
4. Keep exact entries separate from heuristic TT entries, or tag them and reject
   a heuristic hit before reporting `exact = true`.
5. Depend on `0006-reversi-ai-time-bounded-search.md`: an interrupted solve
   returns the last completed non-exact result with `exact = false`.
6. Show an exact result through final margin and PV; do not attribute it to
   heuristic factor deltas.

## Verification

- Exact fixtures for 1--4, pass, game-over, and representative 5--16-empty
  positions, including root-perspective score polarity.
- Deadline interruption of a supported endgame position returns `exact = false`.
- Compare supported results with the pinned oracle corpus.
- Confirm all evaluator variants receive the same exact result.

## Addresses

- `docs/issues/0004-endgame-solver.md`
