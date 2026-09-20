# Child plan: integrate the trained evaluator at runtime

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Make a validated project-owned pattern artifact available to `reversi-ai` as a
fast, independently applicable `TrainedEvaluator`. Completion includes safe
loading or build-owned embedding, plus selection from the existing oracle
candidate CLI protocol. Its caller-selected reading depths and exact-solver
threshold remain adjustable through `AiConfig`. It excludes training changes,
search tuning, Godot/product selection, opening-book integration, and every
explanatory or independent/strategic-evaluator integration.

## Existing references

- `docs/exec-plan/todo/0012-reversi-ai-pattern-evaluator-contract.md:1-75`.
- `docs/exec-plan/todo/0013-reversi-ai-pattern-training.md:1-62`.
- `docs/specs/reversi-ai.md:9-80,109-145` -- evaluator identity and TT.
- `rust/reversi-ai/src/eval/mod.rs`, search context consumers, and
  `rust/reversi-ai/src/bin/reversi-ai-cli.rs`.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- artifact loading/embedding and error
  behavior.
- (NEW) `rust/reversi-ai/src/eval/trained.rs` and tests.
- (MODIFY) `rust/reversi-ai/src/eval/mod.rs`, `lib.rs`, and
  `bin/reversi-ai-cli.rs` -- expose the evaluator as a library capability and
  select it with an explicit artifact path for oracle evaluation. The trained
  CLI path uses `SearchEngine` directly rather than `AiPlayer`, whose generic
  explanation method is outside this plan. Preserve the existing long-lived
  stdin/stdout move protocol and expose the normal `AiConfig` depth and
  exact-solver controls.
- (NEW) build-owned generated/embed path only if artifact loading cannot meet
  release packaging constraints; never hand-edit generated output.

## Black-box contract and work

1. Validate artifact version, feature digest, length, score scale, provenance,
   and checksum before use. A bad artifact returns a clear library/CLI load
   error; it never silently falls back to another evaluator.
2. Include artifact identity in `context_fingerprint()` so TT entries never
   cross weights or phase definitions.
3. Add `--evaluator trained --trained-artifact PATH` to the existing candidate
   CLI so the external oracle harness can run matches. The CLI does not invoke
   or combine any independent/strategic evaluator, and trained mode never
   constructs or exposes `AiPlayer::explain`. The trained evaluator supplies no
   human-factor attribution; product-facing explanation integration is deferred
   to game development through a separate plan.
4. In trained CLI mode, preserve adjustable `--opening-depth`,
   `--midgame-depth`, `--endgame-depth`, and `--exact-solver-empty-squares`.
   A named profile either supplies all of these values or rejects conflicting
   explicit values; it never silently ignores a requested setting. The final
   acceptance plan freezes and reports the chosen values.
5. Opening-book selection is a separate, optional move-selection policy, not a
   weight-artifact or evaluator parameter. The conditional 0017 integration
   plan adds the trained CLI's explicit `--book off|PATH` control after an
   accepted artifact exists. Until then, trained CLI mode is explicitly
   bookless.
6. Measure memory, allocation, and single-thread evaluator speed before making
   it eligible for a later high-strength preset.

Depends on 0012 and 0013. Child 0018 consumes its reports.

## Verification

- `cargo test -p reversi-ai`, library and CLI load/error/protocol tests, and
  Clippy.
- Artifact tamper/version/context-fingerprint/TT-isolation regressions.
- Regression that trained CLI mode uses the evaluation-only search path and
  cannot emit a `MoveExplanation` or an `ExplainTag`.
- CLI regressions for every adjustable `AiConfig` field and for profile/explicit
  setting conflicts.
- Corpus regret report under the 0011 profile, recorded as evidence only.
- `git diff --check`.

## Addresses

- `docs/issues/0005-trained-evaluator.md`
