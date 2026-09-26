# Child plan: run one bounded pattern-reinforcement cycle

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Produce exactly one reproducible, project-owned candidate pattern artifact by
running bounded self-play and updating the existing sparse pattern tables from
game outcomes. Completion records the frozen self-play configuration, inputs,
seed, update rule, candidate and baseline artifact digests, held-out metrics,
and an oracle corpus-regret report. It establishes evidence for a candidate;
it does not tune on 0018's held-out openings, claim the 50% win line, alter
runtime search semantics, or add human-facing explanations.

The reinforcement cycle is a human-operated long-running job. A human starts
it in a separate terminal from the generated frozen manifest; an AI agent does
not start, wait for, poll, monitor, or claim completion of that job. A later
task receives only its immutable artifact/report paths and digests, validates
them, and then decides whether 0018 may freeze the candidate.

## Existing references

- `docs/specs/reversi-ai.md:56-145` -- pattern contract and offline trainer.
- `tools/reversi-ai-training/training.py:162-309` -- manifest validation,
  sparse artifact serialization, digesting, and held-out report.
- `tools/reversi-ai-oracle/oracle.py:1161-1275` -- external corpus evaluation.
- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:65-97` --
  candidate profile and vocabulary.
- `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md:1-61` --
  later frozen held-out acceptance boundary.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- self-play input provenance, one-cycle
  update/selection rules, and separation of tuning from acceptance openings.
- (MODIFY) `tools/reversi-ai-training/training.py` and tests -- deterministic
  self-play generation, bounded TD-style outcome update, artifact selection,
  and fail-closed manifest/report validation.
- (NEW) versioned tiny self-play fixture, immutable candidate report schema,
  and Make targets/scripts for the bounded cycle and corpus-regret evidence.
- (MODIFY) `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md`
  -- depend on this candidate-production evidence before freezing acceptance.

## Black-box contract and work

1. Freeze a self-play manifest before any game: source commit, baseline
   artifact digest, evaluator/search profile, exact-solver threshold, book
   mode, game count, pairing/rotation policy, seed, resource cap, and update
   rule. Self-play must use only project-owned binaries and artifacts.
   Document the exact human-run command, output directory, and stop/restart
   behavior. The command writes its report atomically only after a complete
   cycle; partial output is not candidate evidence.
2. Generate legal games with color-swapped and symmetry-rotated pairs. Record
   every game input, terminal score, failure, and digest; a timeout, malformed
   record, or incomplete pair fails the cycle rather than being omitted.
3. Update sparse phase/feature weights from final-disc outcomes with a bounded,
   deterministic TD-style rule. Preserve the 64-feature, 60-phase, `-64..=64`,
   integer-bound, and canonical-artifact contracts. Identical frozen inputs
   reproduce candidate and report digests exactly.
4. Select at most one candidate against the baseline using a validation split
   that is disjoint from self-play tuning records and 0018 openings. The report
   must retain both results and choose the baseline on a tie or failed gate.
5. Run corpus regret under the frozen 0011 profile as evidence only. The 0018
   held-out suite remains unread and unused until it freezes the selected
   artifact and configuration for its own win-rate test.

## Dependencies and sequencing

- Requires the verified project-owned random-game inputs from 0032. Freeze the
  production manifest only after its baseline artifact and separate validation
  JSONL have passed their digest and complete-game verification. Pin their
  exact paths and SHA-256 values; never substitute the tiny fixtures. Keep the
  trainer-held-out set separate from the 0019 validation set.
- Depends on merged 0013/0014 and the 0011 calibration profile.
- Before the human-operated long run, use the completed 0020 series and its
  `docs/references/reversi-ai-search-performance-0020-closeout.md` report. The
  manifest freezes only merged, accepted optimizations; it never runs against
  an experiment branch.
- It may use completed 0017 changes when available, but freezes whichever
  accepted candidate configuration exists at execution time.
- 0018 depends on this plan's recorded selected artifact; it performs the
  separate 50%-win acceptance measurement and triggers a new calibration or
  reinforcement plan if the line is missed.
- The long-running command is explicitly handed to a human. An AI may prepare
  its manifest and validate completed immutable outputs, but must not monitor
  an in-progress reinforcement run.

## Verification

- Unit tests for deterministic pair generation, legal replay, update bounds,
  seed reproducibility, split isolation, and baseline-on-tie selection.
- Run the bounded fixture twice and require byte-identical artifacts/reports.
- Verify that the human-run command documents its output digest and that a
  partial or missing report fails closed without any monitoring loop.
- Validate the selected artifact through `TrainedEvaluator` and run the
  evaluation-only candidate CLI with the frozen configuration.
- Generate the corpus-regret report; confirm it is not an 0018 opening suite.
- Applicable Rust/Python tests, Clippy, workflow lint, and `git diff --check`.

## Addresses

- N/A
