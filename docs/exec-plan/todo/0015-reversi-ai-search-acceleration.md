# Child plan: accelerate strong-engine search safely

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Increase completed search depth within the candidate budget through measured,
conventional search improvements. Completion accepts only changes that preserve
legal moves, score semantics, TT isolation, last-completed iteration behavior,
and exact-solver separation. It does not tune to imitate an external engine.

## Existing references

- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:65-97`.
- `docs/specs/reversi-ai.md:109-271` -- TT, ordering, budgets, and exactness.
- `rust/reversi-ai/src/search/negascout.rs`, `ordering.rs`, `tt.rs`, and
  `endgame.rs`.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- any new ordering/cache/reduction
  semantics and performance counters.
- (MODIFY) `rust/reversi-ai/src/search/{negascout,ordering,tt}.rs` plus focused
  tests and benchmark fixtures.
- (NEW) deterministic profiling/benchmark scripts under `tools/` if existing
  corpus reports cannot state nodes, completed depth, and elapsed time.

## Black-box contract and work

1. Establish a repeatable baseline before optimization: fixed board suite,
   evaluator/context, node ceiling, completed depth, selected move, and nodes.
2. Consider one measured technique at a time (ordering, TT replacement/key
   use, aspiration windows, safe reductions, or move-generation cost). Each
   technique needs a soundness argument and a rollbackable benchmark result.
3. Do not store partial iterations, mix heuristic/exact entries, or bypass
   deadline/node/cancellation polling. A speed gain with a changed result is a
   correctness investigation, not an acceptance result.
4. Preserve single-thread product behavior for this plan; parallel search is a
   separate design decision because it changes cancellation and determinism.

Depends on 0011 and may run alongside 0012--0014. Child 0018 consumes only
measured accepted changes.

## Verification

- Focused engine/AI tests, fixed-node reproducibility, and forced-pass cases.
- Benchmark before/after report with no regression in legal result/PV/exactness.
- Time-limited cancellation and 16-empty fixture compatibility tests.
- Clippy, GDExtension build, and `git diff --check`.
