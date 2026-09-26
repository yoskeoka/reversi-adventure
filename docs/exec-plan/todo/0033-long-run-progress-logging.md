# Long-running job progress logging

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Operators of Reversi Adventure training and other long-running repository jobs
can tell from the job's own output how much work has completed. For a job with
a known total, print a flushed `N/total` progress line at about ten evenly
spaced completion points, including `total/total`. This repository policy and
the pattern-reinforcement runner implement that behavior without changing its
game results, artifact bytes, manifest identity, or fail-closed completion.

The already frozen 0019 manifest at source commit `77e6fa6` and its human-run
process keep their original producer. This plan applies to future runs from a
new source commit; it does not restart, attach to, or monitor the current run.

## Existing references

- `AGENTS.md:9-35` -- repository-wide work rules, with no long-job progress rule.
- `docs/specs/reversi-ai.md:182-235` -- bounded reinforcement observable
  contract and human-operated run boundary.
- `tools/reversi-ai-training/reinforcement.py:231-257` -- one game and its
  decisions; `:365-425` -- game-pair loop and atomic output publication.
- `tools/reversi-ai-training/tests/test_reinforcement.py:20-65` -- fixture and
  byte-reproducibility checks.
- `tools/reversi-ai-training/README.md:72-140` -- operator run and verification
  instructions.

## Change map

- (MODIFY) `AGENTS.md` -- require bounded, meaningful live progress from new
  long-running repo jobs; keep logging separate from evidence artifacts.
- (MODIFY) `docs/specs/reversi-ai.md` -- state the reinforcement run's visible
  progress contract before code changes.
- (MODIFY) `tools/reversi-ai-training/reinforcement.py` -- emit and flush
  completed-game progress to stderr at the ten count-based checkpoints.
- (MODIFY) `tools/reversi-ai-training/tests/test_reinforcement.py` -- assert
  checkpoint counts, final line, and unchanged canonical outputs.
- (MODIFY) `tools/reversi-ai-training/README.md` -- explain what the human sees
  and how progress relates to final verification.

## Black-box contract and work

1. For a long-running repository command with a known finite total, show
   progress from completed units, not started units. Emit no more than ten
   count-based milestones for totals of at least ten: threshold `ceil(k *
   total / 10)` for `k = 1..10`, de-duplicated for smaller totals. Each line
   identifies the phase and shows `N/total`; the final successful unit prints
   `total/total`. Flush each line so a terminal or redirected stderr receives
   it promptly. When a total is unknown, future jobs should state their phase
   and a bounded elapsed-time heartbeat rather than invent a percentage.
2. The reinforcement runner counts a game only after its terminal record and
   digest exist. Print to stderr after a completed game, including at pair
   boundaries. Progress lines are diagnostic and are absent from canonical
   artifacts, reports, digests, and the candidate CLI protocol. Failure remains
   a failure even if earlier progress lines were printed; no progress line
   represents validated candidate evidence.
3. Document the repo-only policy in `AGENTS.md` and the concrete runner output
   in the AI spec and operator README. Future long jobs use the same policy
   when their own execution plans are implemented; this plan changes only the
   reinforcement producer.
4. Preserve the frozen 0019 source worktree, manifest, CLI, and output path.
   Any later production run with new logging needs a newly frozen manifest and
   its own human-operated command. No AI-started or AI-monitored production run
   is introduced.

## Dependencies and sequencing

- Implement after this plan PR merges, on a fresh `feat/long-run-progress-logging`
  worktree. Update the black-box spec before the runner.
- The 0019 run and its independent output verification do not depend on this
  logging change. Do not rebase or modify its frozen source checkout.

## Verification

- Test checkpoint math for totals below ten, 64, and 2,500; require increasing
  counts, at most ten lines, and a final `total/total` line.
- With the tiny fixture, capture stderr and assert that progress follows
  completed games, remains outside stdout/protocol and canonical files, and
  output artifacts/reports remain byte-identical across two runs.
- Assert an interrupted or failed cycle cannot publish `report.json` merely
  because it emitted progress.
- Run `make pattern-training-test`, workflow lint, and `git diff --check`; run
  other applicable non-AI gates if implementation scope expands.

## Addresses

- N/A
