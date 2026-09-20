# Child plan: accept the strong-engine target

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Run the final held-out evidence suite for the project-owned strong engine under
the calibrated bookless handicap profile. Completion establishes whether the
engine wins at least 50% of games against the restricted oracle. It does not
retune the engine during the held-out run or claim parity with unrestricted
world-class engines.

## Existing references

- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:83-97` --
  profile, metric vocabulary, and fixture prerequisite.
- `docs/exec-plan/todo/0014-reversi-ai-trained-evaluator-runtime.md:1-54`.
- `docs/exec-plan/todo/0015-reversi-ai-search-acceleration.md:1-46`.
- `docs/exec-plan/todo/0016-reversi-ai-exact-solver-16.md:1-40`.
- `tools/reversi-ai-oracle/oracle.py:1161-1275` -- current match behavior.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- final suite identity, lock/freeze
  rules, result schema, sample size, and confidence requirement.
- (MODIFY) `tools/reversi-ai-oracle/oracle.py`, tests, README, and Makefile --
  held-out suite selection, color-swapped opening matrix, and summary checks.
- (NEW) versioned held-out opening suite and immutable acceptance report.
- (DELETE) `docs/issues/0005-trained-evaluator.md` and parent 0009 only after
  the approved acceptance result and implementation closeout.

## Black-box contract and work

1. Freeze source commit, candidate artifact/config, `strong-engine-hcap-v1`,
   opening suite digest, suite seed, hardware/resource declaration, and report
   schema before the first held-out game.
2. Use legal, diverse opening prefixes; pair each with reversed colors and
   symmetry rotations where applicable. No opening used for tuning may enter
   this suite.
3. Define primary success as `candidate wins / all games >= 0.50`. Report draws
   and match points separately. Declare sample size and a one-sided confidence
   rule before execution; passing point estimate alone is insufficient.
4. Report corpus regret by position phase plus every game record, profile,
   side, result, failure, and aggregate. Fail closed on a missing game or
   metadata mismatch.
5. If the target misses, preserve evidence and revise the profile only through
   a new calibration plan. Do not tune on the held-out fixtures.

Depends on completed 0011, 0014, 0015, and 0016. It may consume 0017's policy
record, but its acceptance profile remains bookless.

## Verification

- Harness unit tests for suite expansion, color pairing, metadata, and failure
  handling.
- Independent replay of every stored game and aggregate recomputation.
- Held-out run under frozen inputs, then report digest verification.
- Applicable Rust tests, Clippy, GDExtension build, workflow lint, and diff
  check before PR handoff.
