# Parent plan: build a strong conventional Reversi engine

> **Execution**: Do not implement from this parent. Create and approve detailed child plans, then use `/execute-task` for each child and `/review-task` for its PR.

## Objective and completion boundary

Plan a project-owned conventional engine whose configurable reading time can
reach a level at which human players should not be expected to win routinely.
It draws on public Egaroucid/Edax-class ideas without importing their code,
weights, binaries, or runtime dependencies. Its detailed architecture and
acceptance thresholds will be decided through later child plans and measured by
the shared oracle and endgame foundations.

## Existing references

- `docs/issues/0005-trained-evaluator.md:1-36` calls for an Egaroucid/Logistello
  style trained evaluator.
- `rust/reversi-ai/src/search/negascout.rs:39-164` is the current common search
  baseline.
- `docs/exec-plan/todo/0005-reversi-ai-oracle-corpus.md` and
  `0007-reversi-ai-endgame-solver.md` define shared measurement/solver work.

## Change map

- (MODIFY) future `docs/specs/reversi-ai.md` and design decision record --
  define engine mode, budget presets, analysis/explanation contract, and
  measurable strength target.
- (NEW) detailed child plans for pattern evaluation/training, search
  acceleration, optional book policy, artifact provenance, and benchmarks.
- (MODIFY) future Rust engine/evaluator/tooling paths -- N/A - detail required
  before execution.
- (DELETE) `docs/issues/0005-trained-evaluator.md` and this parent only after
  the approved child implementation satisfies its acceptance contract.

## Intended child work

- Independently implement phase/pattern evaluation and reproducible training
  artifacts.
- Improve conventional-engine reading depth through time-bounded search,
  ordering, caching, and the shared exact endgame solver.
- Define whether an opening book is needed and, if so, its provenance and
  licensing before integration.
- Establish held-out oracle regret and balanced-game evidence for each strength
  preset, including a high-strength preset.

## Verification

N/A - detail required before execution. Every child must compare its declared
time budget against the pinned oracle corpus and avoid external runtime assets.

## Addresses

- `docs/issues/0005-trained-evaluator.md`
