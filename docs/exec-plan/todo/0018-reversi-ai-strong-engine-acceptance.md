# Child plan: accept the strong-engine target

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Run the final held-out evidence suite for the project-owned strong engine under
the calibrated external-oracle handicap profile. Completion establishes whether
the engine wins at least 50% of games against the restricted oracle. The frozen
candidate includes a completed, accepted project-owned opening book when one
exists; otherwise it is explicitly bookless. It does not retune the engine
during the held-out run or claim parity with unrestricted world-class engines.

## Existing references

- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:83-97` --
  profile, metric vocabulary, and fixture prerequisite.
- `docs/exec-plan/todo/0014-reversi-ai-trained-evaluator-runtime.md:1-54`.
- `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md:1-71`.
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

1. Freeze source commit, candidate weight artifact, all `AiConfig` reading
   depths and exact-solver threshold, accepted book artifact and `--book` mode
   (or an explicit bookless declaration), `strong-engine-hcap-v1`, opening
   suite digest, suite seed, hardware/resource declaration, and report schema
   before the first held-out game.
2. Use legal, diverse opening prefixes; pair each with reversed colors and
   symmetry rotations where applicable. No opening or position used for 0019
   self-play tuning or artifact selection may enter this suite; check its
   canonical board-and-side keys against the frozen 0019 report's validation
   keys and its replayed game positions before the first acceptance game.
3. Define primary success as `candidate wins / all games >= 0.50`. Report draws
   and match points separately. Declare sample size and a one-sided confidence
   rule before execution; passing point estimate alone is insufficient.
4. Report corpus regret by position phase plus every game record, profile,
   side, result, failure, and aggregate. Fail closed on a missing game or
   metadata mismatch.
5. If the target misses, preserve evidence and revise the profile only through
   a new calibration plan. Do not tune on the held-out fixtures.

## If the acceptance gate misses

Keep the frozen 0018 result as evidence. Diagnose the miss using the 0019
validation metrics, its selected-artifact decision, the corpus-regret report,
and the 0018 game records. The 0018 opening suite remains held out: do not use
its positions or outcomes to choose new weights, cycle counts, or search
settings. Write a separate executable plan before the next candidate run.

Candidate directions for that plan, subject to the diagnosis:

- If the 0019 update changes few weights or selects the baseline, examine its
  integer residual rounding and the quality of the starting artifact. Define
  a bounded update rule and an independent validation gate before retrying.
- If more self-play data is warranted, predeclare the game count, maximum
  learning cycles, seeds, resource caps, and a stop rule. Keep color and D4
  pairing; evaluate every cycle against the same disjoint validation source
  and retain baseline-on-tie selection. The current 0019 tool runs one cycle
  with 64 games by default; it has no automatic multi-cycle schedule.
- If move quality near the end of games is the limiting factor, profile an
  exact-solver threshold near 20 empty squares as a separate experiment.
  Adopt it only after independent oracle agreement and bounded time/memory
  evidence. Search-depth or book changes likewise need their own calibrated
  plan and evidence.

Depends on completed 0011, 0014, 0015, 0016, 0017, 0019, and the completed
0020 search performance series recorded in
`docs/references/reversi-ai-search-performance-0020-closeout.md`. The frozen
candidate may contain only merged optimizations accepted by that series. If
0017 accepts a book, its dedicated integration child plan must also complete
before this plan freezes the candidate.
For 0019, completion means the human-operated cycle has finished and a later
task has independently verified the immutable manifest, game records, candidate
and selected artifacts, validation metrics, and corpus-regret report. This plan
does not freeze a candidate from a prepared manifest or a partial cycle report.

## Verification

- Harness unit tests for suite expansion, color pairing, metadata, and failure
  handling.
- Independent replay of every stored game and aggregate recomputation.
- Held-out run under frozen inputs, then report digest verification.
- Applicable Rust tests, Clippy, GDExtension build, workflow lint, and diff
  check before PR handoff.
