# Child plan: make pattern-weight training reproducible

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Build a reproducible offline pipeline that produces the artifact specified by
child 0012 and reports held-out quality. Completion is a repeatable training
run with pinned inputs and validation evidence; it is not runtime integration
or a claim that the final engine meets the match target.

## Existing references

- `docs/exec-plan/todo/0012-reversi-ai-pattern-evaluator-contract.md:1-75` --
  artifact and feature contract.
- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:83-97` --
  held-out evidence and profile identity.
- `docs/issues/0005-trained-evaluator.md:19-30` -- data/training scope.
- `tools/reversi-ai-oracle/corpus.jsonl` -- small oracle fixture, not training
  data.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- training input, split, seed,
  provenance, and validation-report contract.
- (NEW) `tools/reversi-ai-training/` -- manifest-driven extraction, trainer,
  artifact validation, and tests.
- (NEW) versioned dataset manifests and small legal test fixtures -- no opaque
  unlicensed game database in the repository.
- (NEW) retained validation report/artifact metadata path -- actual large
  datasets and mutable caches remain outside the checkout.

## Black-box contract and work

1. Require every input record to state source, license, digest, board encoding,
   side, target semantics, and split assignment. Reject duplicates across
   train/validation/held-out splits, including symmetry-equivalent positions.
2. Pin trainer version, random seed, feature-contract digest, optimizer and
   hyperparameters. A rerun from identical inputs must reproduce artifact
   digest or have an explicit documented numeric tolerance.
3. Train the 64-feature, 60-discrete-phase, final-disc-difference contract
   from 0012. Report loss and move-quality metrics by phase, with the
   calibration corpus held out from tuning. Never derive product provenance
   from private data.
4. Fail closed on missing licenses, schema/digest mismatch, leakage, NaN,
   overflow, or an artifact outside the 0012 score contract.
5. Provide a small CPU test fixture; large-scale training is manual or CI
   artifact work with caches outside the checkout.

Depends on 0012. Child 0014 depends on its validated artifact. Child 0015 can
run in parallel.

## Verification

- Unit tests for parsing, split leakage, deterministic seed, and corruption.
- Run the tiny end-to-end fixture twice and compare its declared output.
- Validate the generated artifact with the 0012 feature vectors and run
  `git diff --check`.

## Addresses

- `docs/issues/0005-trained-evaluator.md`
