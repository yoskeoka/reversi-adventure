# Child plan: define the pattern evaluator contract

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Specify a project-owned pattern-evaluation contract modelled on Egaroucid's
publicly documented Logistello/Edax-class approach, without importing
Egaroucid code, weights, file formats, or runtime assets. Completion defines a
64-feature catalog, 60 discrete phases, feature extraction, symmetry,
artifact identity, and final-disc-difference score scale. It does not train
weights, create a runtime `TrainedEvaluator`, or couple to an independent
explanatory evaluator.

## Existing references

- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:1-143` --
  profile and held-out measurement prerequisite.
- `docs/specs/reversi-ai.md:9-80` -- `BoardEvaluator`, `EvalResult`, and
  context fingerprint contract.
- `rust/reversi-ai/src/eval/mod.rs` -- evaluator public surface.
- `docs/issues/0005-trained-evaluator.md:1-31` -- original trained-evaluator
  need and external reference boundary.
- `docs/references/egaroucid-technology-llms.txt` -- external technical
  reference boundary and publicly described pattern-evaluation approach.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- pattern feature, artifact, and score
  contract, with no explanatory-evaluator integration.
- (MODIFY) `docs/design-decisions/2026-03-02-reversi-ai-design.md` -- record
  the project-owned representation decision.
- (NEW) `rust/reversi-ai/src/eval/pattern.rs` and focused tests -- feature
  encoding, canonical symmetries, and fixture vectors.
- (MODIFY) `rust/reversi-ai/src/eval/mod.rs` -- internal types only if needed;
  preserve the public `BoardEvaluator` contract.

## Black-box contract and work

1. Declare the project-owned coordinates for the publicly described pattern
   family: 64 symmetry-expanded features, each containing at most 10 squares.
   Use ternary square encoding and one canonical orientation per board
   symmetry. Equivalent symmetric positions must produce equal features.
2. Define exactly 60 discrete phase tables, indexed by total occupied-disc
   count from the initial four discs through the last non-terminal position;
   do not interpolate. This is independent of the exact-solver start threshold
   in child 0011.
3. Define the evaluator score as the requested color's predicted final disc
   differential, in inclusive range `-64..=64`. Define deterministic integer
   accumulation and reject an artifact whose values or aggregate cannot meet
   that range without overflow.
4. Define an immutable weight-artifact schema containing format version,
   catalog digest, phase definition, score scale, safe source-provenance
   metadata, and weight digest. Provenance records reproducible trainer/input
   manifest identities and licenses, not private input data. All
   score-affecting fields enter the future evaluator's `context_fingerprint()`.
5. The trained pattern score has no human-factor attribution. This plan does
   not change, invoke, combine with, or specify an independent/strategic
   evaluator or explanation path.
6. Add golden feature vectors, color-perspective antisymmetry tests, symmetry
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
