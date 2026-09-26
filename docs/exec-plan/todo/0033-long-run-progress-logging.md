# Long-running job progress logging

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

An operator can see the reinforcement runner move forward while it runs.
By default, each completed game writes a flushed progress line. The line has a
short activity summary, `N/total`, that game's elapsed time, and total elapsed
time. The runner also writes short start and finish lines for its later replay,
validation, update, selection, and publish stages.

`make pattern-reinforcement-run` accepts an opt-in game interval for an agent
or another log-limited caller. An interval of `N` writes each `N`th completed
game and the final game. The default is `1`. Logging changes no game result,
artifact bytes, manifest identity, or fail-closed completion.

Agents planning a future long-running batch command must define equivalent
visible progress for its own completed work units. They must also state how a
log-limited caller can reduce per-unit output when that command needs it.

The already frozen 0019 manifest at source commit `77e6fa6` and its human-run
process keep their original producer. This plan applies to future runs from a
new source commit; it does not restart, attach to, or monitor the current run.

## Existing references

- `AGENTS.md:9-35` -- repository-wide planning and spec-first work rules.
- `docs/specs/reversi-ai.md:182-235` -- bounded reinforcement observable
  contract and human-operated run boundary.
- `Makefile:42-49, 90-91` -- 64-game run defaults and the current run target.
- `tools/reversi-ai-training/reinforcement.py:196-258` -- candidate timeout
  and one complete, digested game; `:361-412` -- pair loop, learning stages,
  and atomic output publication; `:512-537` -- run CLI.
- `tools/reversi-ai-training/tests/test_reinforcement.py:29-70` -- fixture and
  byte-reproducibility checks.
- `tools/reversi-ai-training/README.md:72-140` -- operator run and verification
  instructions.

## Change map

- (MODIFY) `AGENTS.md` -- require plans for long-running batch commands to
  define completed-unit progress, stage visibility, and a log-rate control.
- (MODIFY) `docs/specs/reversi-ai.md` -- state the reinforcement run's visible
  progress contract before code changes.
- (MODIFY) `Makefile` -- expose the default-one-game `REINFORCEMENT_PROGRESS_EVERY`
  setting through `pattern-reinforcement-run`.
- (MODIFY) `tools/reversi-ai-training/reinforcement.py` -- emit and flush
  completed-game progress and named learning-stage boundaries to stderr.
- (MODIFY) `tools/reversi-ai-training/tests/test_reinforcement.py` -- assert
  default per-game lines, interval suppression, stage lines, and unchanged
  canonical outputs.
- (MODIFY) `tools/reversi-ai-training/README.md` -- explain what the human sees
  and how progress relates to final verification.

## Black-box contract and work

1. A game counts after `play()` has produced its terminal record and game
   digest. For the default interval of `1`, print exactly one completed-game
   line after every game, including both members of each color-swapped pair.
   Its summary is at most 50 characters and identifies the self-play pair and
   member. The line includes completed and total games as `N/total`, elapsed
   time for that game, and elapsed time for the whole run. Use a monotonic
   clock and flush stderr after each line. Use the stable form
   `progress self-play pair=P member=M N/total game=S.s elapsed=S.s`.
2. Add `--progress-every POSITIVE_INTEGER` to the `run` CLI and map Make's
   `REINFORCEMENT_PROGRESS_EVERY`, defaulting to `1`, to that flag. For a value
   greater than one, emit a completed-game line when `N` is a multiple of the
   interval and always at `total/total`. Reject zero and invalid values before
   the run starts. Keep the total as the manifest's individual `game_count`,
   not its pair count.
3. Write concise, flushed stderr lines at the start and finish of self-play,
   replay/tuning extraction, validation, artifact update, metrics and
   selection, report serialization, and atomic output publication. Each line
   identifies the stage and has its stage elapsed and total elapsed times. A
   stage line has no `N/total` unless it represents a completed game. Use
   `stage NAME start elapsed=S.s` and `stage NAME done stage=S.s elapsed=S.s`.
4. Progress and stage lines are diagnostics. Keep them out of stdout, the
   candidate CLI protocol, manifest, game records, report, digests, and output
   bytes. A failure stays a failure even after a line has been printed; lines
   do not establish valid candidate evidence.
5. State this concrete behavior and the interval override in the AI spec and
   operator README. Preserve the frozen 0019 source worktree, manifest, CLI,
   and output path.
   Any later production run with new logging needs a newly frozen manifest and
   its own human-operated command. No AI-started or AI-monitored production run
   is introduced.
6. Add a repository rule in `AGENTS.md`: when an Agent plans a long-running
   batch command, its plan states the completed unit, total when known, live
   progress fields, meaningful stage lines, and a rate-control option when
   per-unit logs can overwhelm a consumer. The command's black-box spec fixes
   the exact format and default. This plan applies that rule to reinforcement.

## Dependencies and sequencing

- Implement after this plan PR merges, on a fresh `feat/long-run-progress-logging`
  worktree. Update the black-box spec before the runner.
- The 0019 run and its independent output verification do not depend on this
  logging change. Do not rebase or modify its frozen source checkout.

## Verification

- Test the default emits each completed game, with increasing `N/total`, the
  required timing fields, a summary of at most 50 characters, and the final
  `total/total` line.
- Test interval `N` emits only multiples of `N` plus the final game, including
  a non-divisible total; reject zero and invalid interval values.
- With the tiny fixture, capture stderr and assert self-play and every later
  stage has start and finish visibility. Assert logging remains outside
  stdout/protocol and canonical files, and output artifacts/reports remain
  byte-identical across two runs.
- Assert an interrupted or failed cycle cannot publish `report.json` merely
  because it emitted progress.
- Run `make pattern-training-test`, workflow lint, and `git diff --check`; run
  other applicable non-AI gates if implementation scope expands.

## Addresses

- N/A
