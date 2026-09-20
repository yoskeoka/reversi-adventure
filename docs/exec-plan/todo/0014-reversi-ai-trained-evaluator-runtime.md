# Child plan: integrate the trained evaluator at runtime

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Make a validated project-owned pattern artifact available to `reversi-ai` as a
fast, independently applicable `TrainedEvaluator`. Completion includes safe
loading or build-owned embedding and regressions. It excludes training changes,
search tuning, CLI/Godot selection, and every explanatory or independent/
strategic-evaluator integration.

## Existing references

- `docs/exec-plan/todo/0012-reversi-ai-pattern-evaluator-contract.md:1-75`.
- `docs/exec-plan/todo/0013-reversi-ai-pattern-training.md:1-62`.
- `docs/specs/reversi-ai.md:9-80,109-145` -- evaluator identity and TT.
- `rust/reversi-ai/src/eval/mod.rs` and search context consumers.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- artifact loading/embedding and error
  behavior.
- (NEW) `rust/reversi-ai/src/eval/trained.rs` and tests.
- (MODIFY) `rust/reversi-ai/src/eval/mod.rs` and `lib.rs` -- expose the
  evaluator as a library capability without changing default difficulty
  behavior or selecting it from product-facing callers.
- (NEW) build-owned generated/embed path only if artifact loading cannot meet
  release packaging constraints; never hand-edit generated output.

## Black-box contract and work

1. Validate artifact version, feature digest, length, score scale, provenance,
   and checksum before use. A bad artifact returns a clear library load error;
   it never silently falls back to another evaluator.
2. Include artifact identity in `context_fingerprint()` so TT entries never
   cross weights or phase definitions.
3. Do not change, invoke, combine with, or select any independent/strategic
   evaluator. The trained evaluator supplies no human-factor attribution;
   product-facing explanation integration is deferred to game development.
4. Measure memory, allocation, and single-thread evaluator speed before making
   it eligible for a later high-strength preset.

Depends on 0012 and 0013. Child 0018 consumes its reports.

## Verification

- `cargo test -p reversi-ai`, library load/error tests, and Clippy.
- Artifact tamper/version/context-fingerprint/TT-isolation regressions.
- Corpus regret report under the 0011 profile, recorded as evidence only.
- `git diff --check`.

## Addresses

- `docs/issues/0005-trained-evaluator.md`
