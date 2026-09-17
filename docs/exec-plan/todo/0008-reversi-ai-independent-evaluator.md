# Parent plan: improve and optimize the independent Reversi evaluator

> **Execution**: Do not implement from this parent. Create and approve detailed child plans, then use `/execute-task` for each child and `/review-task` for its PR.

## Objective and completion boundary

Guide the incremental improvement of the project-owned, explainable evaluator.
It will remain distinct from the strongest pattern-learning engine and will be
assessed through the common TT, oracle, time-budget, and endgame foundations.
It remains active until its approved child plans have completed; implementation
detail is intentionally deferred.

## Existing references

- `rust/reversi-ai/src/eval/strategic.rs:8-231` contains current hand-tuned
  corner, stability, mobility, edge, parity, and disc features.
- `rust/reversi-ai/src/eval/mod.rs:1-60` exposes explanation factors.
- `docs/design-decisions/2026-03-02-reversi-ai-design.md:131-158` defines the
  present hand-tuned strategic evaluator.

## Change map

- (MODIFY) future `docs/specs/reversi-ai.md` and design decision record --
  specify each accepted feature and user-visible explanation behavior.
- (NEW) detailed child plans for feature definitions, parameter artifacts, and
  balanced self-play/GA optimization.
- (MODIFY) future evaluator, training/tournament tools, and fixtures -- exact
  paths are N/A - detail required before execution.
- (DELETE) this parent only after its approved child plans have completed.

## Intended child work

- Reassess independent features such as corner/X/C exposure, mobility/potential
  mobility, frontier discs, stable discs, edge patterns, disc differential,
  and empty-region parity.
- Specify phase behavior and explanation mapping for every accepted feature.
- Make weights and phase cutoffs reproducible parameter vectors.
- Run balanced, color-swapped, opening-rotated self-play; use genetic search or
  another approved optimizer and retain seeds, raw games, and acceptance gates.

## Verification

N/A - detail required before execution. Each child must use common oracle
regret and reproducible self-play reports.

## Addresses

N/A
