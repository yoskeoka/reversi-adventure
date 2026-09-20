# Child plan: define the pattern evaluator contract

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Specify a project-owned, phase-aware pattern evaluator that can later consume
trained weights without importing Egaroucid code, weights, or runtime assets.
Completion defines feature extraction, symmetry, phase interpolation, artifact
identity, score scale, and the explanation boundary. It does not train weights
or change the runtime evaluator.

## Existing references

- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:1-143` --
  profile and held-out measurement prerequisite.
- `docs/specs/reversi-ai.md:9-80` -- `BoardEvaluator`, `EvalResult`, factors,
  and context fingerprint contract.
- `rust/reversi-ai/src/eval/mod.rs` -- evaluator public surface.
- `rust/reversi-ai/src/eval/strategic.rs` -- current explainable baseline.
- `docs/issues/0005-trained-evaluator.md:1-31` -- original trained-evaluator
  need and external reference boundary.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- pattern feature, artifact, score, and
  explanation compatibility contract.
- (MODIFY) `docs/design-decisions/2026-03-02-reversi-ai-design.md` -- record
  the project-owned representation decision.
- (NEW) `rust/reversi-ai/src/eval/pattern.rs` and focused tests -- feature
  encoding, canonical symmetries, and fixture vectors.
- (MODIFY) `rust/reversi-ai/src/eval/mod.rs` -- internal types only if needed;
  preserve the public `BoardEvaluator` contract.

## Black-box contract and work

1. Declare a finite pattern catalog and one canonical orientation for every
   board symmetry. Equivalent symmetric positions must produce equal features.
2. Define phase buckets or interpolation from occupied-disc count. This is
   independent of the exact-solver start threshold in child 0011.
3. Define an immutable weight-artifact schema containing format version,
   catalog digest, phase definition, score scale, source provenance, and weight
   digest. All score-affecting fields enter `context_fingerprint()`.
4. Keep educational factors available: a trained scalar may be reported beside
   existing factors, but fabricated factor attribution is forbidden.
5. Add golden feature vectors, color-perspective antisymmetry tests, symmetry
   tests, corrupt-artifact rejection, and a score-range/overflow test.

Depends on 0011. Child 0013 depends on this contract; child 0015 may proceed
in parallel after 0011.

## Verification

- Focused `reversi-ai` evaluator tests and workspace Clippy.
- Fixture vectors cover corners, edges, passes, all eight symmetries, and each
  phase boundary.
- `git diff --check` and the repository workflow lint.

## Addresses

- `docs/issues/0005-trained-evaluator.md`
