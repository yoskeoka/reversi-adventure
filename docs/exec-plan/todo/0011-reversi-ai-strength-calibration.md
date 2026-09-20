# Child plan: calibrate the strong-engine resource profile

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Make the parent plan's intended handicap reproducible and unambiguous before
improving the engine. The acceptance profile initially gives the project AI a
midgame search depth of 12 and starts its exact solver at 16 remaining empty
squares. It compares it with pinned Egaroucid v7.8.1 at midgame search depth 8
and exact solving from 12 remaining empty squares.

"Midgame search depth" is a placement-search limit. "Exact-solver start
threshold" is the number of empty squares at or below which the evaluator is
bypassed and a final-disc proof is attempted. Neither phrase means the usual
opening (turns 1--20), midgame (21--40), and late game (41--60) turn ranges;
the plan must not describe the threshold as an "endgame depth".

This child delivers profile/configuration support, documented black-box
contracts, and evidence suitable for later strength work. It does not add a
trained evaluator, search optimization, a product opening book, or claim the
final 50% strength result. The parent may revise the handicap only through a
new versioned profile with comparative evidence.

## Existing references

- `docs/exec-plan/todo/0009-reversi-ai-strong-engine.md:5-48` -- parent
  objective, external-oracle boundary, and child-plan dependency.
- `docs/specs/reversi-ai.md:82-96` and `254-271` -- `AiConfig`, the current
  12-empty-square exact-solver threshold, and interruption semantics.
- `docs/specs/reversi-ai.md:333-388` -- external oracle, normalized-report,
  determinism, and no-oracle-time-limit contracts.
- `tools/reversi-ai-oracle/oracle.py:731-770` and `1065-1079` -- current
  bookless, single-thread Egaroucid invocation and output assumptions.
- `Makefile:1-51` and `tools/reversi-ai-oracle/README.md:33-49` -- current
  level-only Make variables and bounded CI defaults.
- `rust/reversi-ai/src/search/negascout.rs:39-164` and its `SearchBudget`
  callers -- project search baseline to which candidate budgets apply.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- define a versioned external-oracle
  strength profile, its report/match metadata, the distinct midgame-depth and
  exact-solver-threshold terms, and the held-out match acceptance vocabulary.
- (MODIFY) `docs/design-decisions/2026-03-02-reversi-ai-design.md` -- replace
  the ambiguous `endgame_depth` terminology where it means exact-solver start.
- (MODIFY) `tools/reversi-ai-oracle/oracle.py` -- accept and validate a
  structured profile rather than raw option fragments; construct and parse the
  Egaroucid custom-depth invocation safely.
- (MODIFY) `tools/reversi-ai-oracle/tests/test_oracle.py` -- cover profile
  validation, generated argv, custom-level output, metadata, malformed
  profiles, and phase boundaries.
- (MODIFY) `tools/reversi-ai-oracle/README.md` and `Makefile` -- expose named
  reproducible profiles; retain small CI defaults separately from strength
  evaluation runs.
- (MODIFY) `rust/reversi-ai/src/**`, `rust/reversi-ai/tests/**`, and the CLI
  budget flags -- expose the candidate's declared midgame depth and exact
  solver threshold without weakening last-completed-iteration semantics.
- (NEW) versioned held-out opening-suite fixture/report paths under
  `tools/reversi-ai-oracle/` -- only after the implementation chooses their
  exact format and validates symmetry, legality, and color alternation.
- (DELETE) N/A -- retain the parent and the trained-evaluator issue until the
  later children meet their own completion boundaries.

## Black-box contract

1. Define `strong-engine-hcap-v1` as all of the following, and serialize the
   entire profile in analysis and match reports:

   - Egaroucid Console v7.8.1 and the pinned source digest;
   - no opening book, one thread, fixed hash level 25, and no external eval
     override;
   - fixed-depth, 100%-probability ranges: Egaroucid move numbers 1--41 at
     depth 8 and 42--60 at depth 12; and
   - no Egaroucid `-time`; process timeout remains a safety failure boundary,
     never a fairness budget.

2. Define every threshold against the decision position before its move. Map
   Egaroucid's move number (`occupied discs - 3`) against that board: the
   second range begins at 45 occupied discs. The profile's 12 means complete
   solving starts when the decision position has at most 12 empty squares.
   This is a threshold, not a 12-ply heuristic search.

3. Define the candidate profile independently: heuristic depth 12 for every
   non-exact decision position, including opening and the 17--19-empty-square
   late-game interval; exact solver starts at at most 16 empty squares; caller
   owned monotonic deadline is the production budget; fixed node ceilings are
   optional deterministic tuning/CI limits. The profile calls out its
   midgame-depth target while fully declaring match behavior. A later child may
   improve either implementation, but it must preserve this profile's identity
   or publish a new version.

4. A run must fail closed when its profile, source digest, book/eval artifact,
   hash/thread setting, custom-depth response, corpus, or report metadata does
   not match. Custom Egaroucid depth output must not be misread as the legacy
   numeric `--level` output.

5. The first profile is a calibration baseline, not proof of final strength.
   The final child must use held-out, color-swapped, opening-rotated games and
   define `wins / all games >= 0.50` separately from match points where a draw
   is worth 0.5. It must also declare sample size and a confidence rule before
   asserting the target.

## Sub-tasks and dependencies

1. Update the spec and design-decision record first with the vocabulary and
   profile schema above. Add a regression boundary that rejects the old,
   ambiguous `endgame_depth` label where it denotes an empty-square threshold.
2. Implement typed profile parsing and validation in the external-only Python
   harness. Keep arbitrary Egaroucid argv, external book/eval files, multiple
   threads, and time-control modes outside the profile contract.
3. Extend `-solve` and GTP match process construction to use the profile's
   fixed-depth ranges. Bind each range to the decision position before a move.
   Because `-solve` receives child positions for root-move analysis, batch or
   dispatch its calls with the corresponding shifted profile; for GTP, restart
   and replay legal history when a profile transition is needed. Cover forced
   passes. Adapt parsing for Egaroucid's custom-depth response and include the
   profile in golden/report projections without admitting machine-time drift.
4. Add project CLI/config support necessary to run the candidate profile and
   prove that its 16-empty-square exact solver obeys its `SearchBudget`. Do
   not silently convert a timeout into a partial exact result.
5. Add deterministic fixture and report tests, then a bounded calibration
   command that records baseline regret and alternating-color results. It may
   report results but must not make the final 50% assertion.
6. Record the artifact/provenance decision: `strong-engine-hcap-v1` is
   bookless. A basic or detailed book is a separate later policy child because
   Egaroucid Console only selects a whole book artifact and its fixed-depth
   mode does not use it.

Steps 1--3 are sequential. Step 4 may proceed in parallel after step 1.
Step 5 depends on steps 2--4. Later evaluator and search children depend on
the published profile; the independent exact-solver-to-16 child may begin
after step 1 but cannot claim this profile until its verification passes.

## Verification

- Run the oracle unit suite and its focused profile/parser tests.
- Run the existing corpus/golden verification and prove that legacy level-only
  profiles remain compatible or are explicitly versioned/migrated.
- Run profile fixture tests at occupied-disc boundaries 4, 20, 21, 40, 41,
  44, 45, 63, and terminal 64, including a forced-pass position and the
  decision-position versus child-query boundary.
- Run focused `reversi-ai` tests for the 16-empty-square exact-solver start,
  deadline/node-limit interruption, and legal last-completed fallback.
- Run a bounded, alternating-color calibration match and retain its profile
  metadata; do not treat the existing two-game CI smoke match as acceptance
  evidence.
- Run the repository's applicable lint/build checks and `git diff --check`.

## Addresses

- `docs/issues/0005-trained-evaluator.md`
