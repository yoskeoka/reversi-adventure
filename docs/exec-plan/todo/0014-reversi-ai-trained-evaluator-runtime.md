# Child plan: integrate the trained evaluator at runtime

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Make a validated project-owned pattern artifact available to `reversi-ai` as a
fast `BoardEvaluator`, while preserving the existing explanation and search
contracts. Completion includes safe loading or build-owned embedding, CLI
selection, and regressions. It excludes training changes and search tuning.

## Existing references

- `docs/exec-plan/todo/0012-reversi-ai-pattern-evaluator-contract.md:1-58`.
- `docs/exec-plan/todo/0013-reversi-ai-pattern-training.md:1-55`.
- `docs/specs/reversi-ai.md:9-80,109-145,273-331` -- evaluator identity, TT,
  explanations, and `AiPlayer`.
- `rust/reversi-ai/src/eval/mod.rs`, `player.rs`, `bin/reversi-ai-cli.rs`.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- artifact loading/embedding and error
  behavior.
- (NEW) `rust/reversi-ai/src/eval/trained.rs` and tests.
- (MODIFY) `rust/reversi-ai/src/eval/mod.rs`, `lib.rs`, `player.rs`, and CLI --
  select the evaluator without changing default difficulty behavior.
- (NEW) build-owned generated/embed path only if artifact loading cannot meet
  release packaging constraints; never hand-edit generated output.

## Black-box contract and work

1. Validate artifact version, feature digest, length, score scale, provenance,
   and checksum before use. A bad artifact produces a clear startup/CLI error;
   it never silently falls back to another evaluator.
2. Include artifact identity in `context_fingerprint()` so TT entries never
   cross weights or phase definitions.
3. Keep the default strategic/novice evaluators stable. Expose trained mode
   only when the verified artifact is available.
4. Return a truthful explanation: retain search/PV and existing factors; label
   trained-pattern evaluation distinctly where no human factor is derivable.
5. Measure memory, allocation, and single-thread evaluator speed before making
   it the high-strength preset.

Depends on 0012 and 0013. Child 0018 consumes its reports.

## Verification

- `cargo test -p reversi-ai`, CLI selection/error tests, and Clippy.
- Artifact tamper/version/context-fingerprint/TT-isolation regressions.
- Corpus regret report under the 0011 profile, recorded as evidence only.
- Godot bridge build and `git diff --check`.

## Addresses

- `docs/issues/0005-trained-evaluator.md`
