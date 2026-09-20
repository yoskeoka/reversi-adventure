# Child plan: decide opening-book policy and provenance

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Decide whether the product's strong engine needs a project-owned opening book.
Completion is a documented accept/reject decision with measured benefit and
license/provenance evidence. It does not import Egaroucid's book or make an
external oracle book a product dependency.

## Existing references

- `docs/exec-plan/todo/0009-reversi-ai-strong-engine.md:38-57`.
- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:118-128` --
  bookless comparison profile.
- `docs/specs/reversi-ai.md:333-345` -- external oracle boundary.
- `tools/reversi-ai-oracle/README.md:1-49` -- external-only oracle assets.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` and design decision record -- policy,
  provenance, packaging, fallback, and explanation rules.
- (NEW) a decision report with measured opening-suite evidence.
- (NEW) implementation plan only if the decision accepts a book; otherwise no
  product code or artifact is added.

## Black-box contract and work

1. Compare bookless strong-engine results with a proposed project-owned book
   against a fixed opening suite. State whether the gain changes the 0018
   acceptance outcome rather than assuming it does.
2. A candidate book needs a creator/source license, reproducible generation,
   content digest, format version, legal-move validation, maximum coverage,
   update policy, and release-size budget.
3. No book may be copied from or loaded through Egaroucid. The oracle's
   `-book` option is whole-artifact selection, not a basic/detailed level; its
   profile remains bookless.
4. If accepted, book choice must be deterministic, legal, explainable as a
   book move, and fall back to the search engine on a miss or invalid record.

Depends on 0011. It may investigate alongside 0012--0016, but any integration
is a new child plan. Child 0018 uses the bookless profile regardless.

## Verification

- License/provenance review and reproducible digest check.
- Opening suite legality, symmetry, miss/fallback, and deterministic-choice
  tests for any accepted artifact.
- Record rejection evidence if no compliant book provides material value.
