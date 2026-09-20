# Parent plan: build a strong conventional Reversi engine

> **Execution**: Do not implement from this parent. Create and approve detailed child plans, then use `/execute-task` for each child and `/review-task` for its PR.

## Objective and completion boundary

Plan a project-owned conventional engine whose configurable reading time can
reach a level at which human players should not be expected to win routinely.
It draws on public Egaroucid/Edax-class ideas without importing their code,
weights, binaries, or runtime dependencies into the product or release
artifacts. The pinned Egaroucid development/CI oracle remains permitted. Its
detailed architecture and acceptance thresholds will be decided through later
child plans and measured by the shared oracle and endgame foundations.

## Existing references

- `docs/issues/0005-trained-evaluator.md:1-36` calls for an Egaroucid/Logistello
  style trained evaluator.
- `rust/reversi-ai/src/search/negascout.rs:39-164` is the current common search
  baseline.
- `docs/exec-plan/todo/0005-reversi-ai-oracle-corpus.md` and
  `0007-reversi-ai-endgame-solver.md` define shared measurement/solver work.

## Change map

- (MODIFY) future `docs/specs/reversi-ai.md` and design decision record --
  define engine mode, midgame search depth, exact-solver start threshold in
  remaining empty squares, analysis/explanation contract, and measurable
  strength target. Do not call the latter "endgame depth": it is the point at
  which complete solving starts, not a heuristic search depth.
- (NEW) detailed child plans for pattern evaluation/training, search
  acceleration, optional book policy, artifact provenance, and benchmarks.
- (MODIFY) `docs/design-decisions/2026-03-02-reversi-ai-design.md` and
  `docs/references/egaroucid-technology-llms.txt` -- replace links to the
  trained-evaluator issue when it is removed.
- (MODIFY) future Rust engine/evaluator/tooling paths -- N/A - detail required
  before execution.
- (DELETE) `docs/issues/0005-trained-evaluator.md` and this parent only after
  the approved child implementation satisfies its acceptance contract.

## Intended child work

- `0011-reversi-ai-strength-calibration.md` first fixes the versioned oracle
  and candidate resource profiles. Its initial target is oracle midgame search
  depth 8 with complete solving beginning at 12 empty squares, versus project
  midgame search depth 12 with complete solving beginning at 16 empty squares.
  It deliberately distinguishes those terms from the ordinary opening,
  midgame, and late-game turn ranges.
- `0012-reversi-ai-pattern-evaluator-contract.md` defines the project-owned
  feature, phase, symmetry, artifact-identity, and explanation boundary.
- `0013-reversi-ai-pattern-training.md` makes the data, split, optimizer, and
  validation evidence reproducible before runtime integration.
- `0014-reversi-ai-trained-evaluator-runtime.md` integrates only validated
  project-owned artifacts into the Rust evaluator and its TT identity.
- `0015-reversi-ai-search-acceleration.md` improves conventional search from a
  fixed baseline while preserving every budget and exactness guarantee.
- `0016-reversi-ai-exact-solver-16.md` separately proves the 16-empty-square
  exact-solver threshold or retains 12 with evidence.
- `0017-reversi-ai-opening-book-policy.md` decides book adoption, provenance,
  and licensing; it does not make the bookless acceptance profile conditional.
- `0018-reversi-ai-strong-engine-acceptance.md` freezes the profile, runs the
  held-out color-balanced suite, and decides the `wins / all games >= 0.50`
  target without tuning on its fixtures.

## Verification

N/A - detail required before execution. Every child must compare its declared
time budget against the pinned oracle corpus and avoid external runtime assets.

## Addresses

- `docs/issues/0005-trained-evaluator.md`
