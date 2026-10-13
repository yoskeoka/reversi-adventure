# 0048 One-command Reversi AI self-play measurement closeout

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Give a human one command that runs the active 0040 measurement through verified
results. The command builds the release project CLI, runs all eight
`StrategicEvaluator` games at 8/8/8, exact16, `turn`, verifies the whole-game
report, independently checks every exact root and selected child with the
external Oracle, verifies that evidence, then writes one completion summary.
The human starts the process in a terminal and can wait while it reports
progress. It does not launch in CI or as a background task.

Search has no per-decision time or node budget. The 600-second CLI response
watchdog detects a stalled move; it does not impose a game or batch wall limit.
The mean 180-second goal and nearest-rank P95 300-second review point remain
diagnostic only. The runner does not train a `TrainedEvaluator`, tune a profile,
or decide whether the result is acceptable. 0040 remains open until the saved
results and human performance judgment close its gates.

The external Oracle stage means the independent exact root and selected-child
solve for each exact CLI decision, under the current `winner-empty-v1` contract.
Record both score agreement and each Oracle solve's elapsed time, nodes, process
wall time, CPU, and RSS. These are per-query diagnostics, not an Oracle-vs-
Oracle match or a claim about Oracle throughput. Keep source, CLI, Oracle,
settings, and report identities attached to the combined result.

## References

- `docs/exec-plan/todo/0040-reversi-ai-self-play-performance-closeout.md` — active profile, completion gates, human measurement boundary.
- `docs/specs/reversi-ai.md`, “Whole-game self-play performance”, “Durable whole-game measurement and game boundaries”, and “0040 one-command efficiency closeout” — report, timeout, checkpoint, and progress contracts.
- `tools/reversi-ai-benchmark/whole_game.py:1300-1430` — `measure_resumable`, per-game checkpoints, report verification, and summary generation.
- `tools/reversi-ai-benchmark/whole_game.py:885-956` — `oracle_evidence` and `verify_oracle_evidence` exact root/selected-child checks.
- `tools/reversi-ai-benchmark/exact_threshold.py:460-515` — existing wait4 Oracle query runner, per-query timeout, and RSS observation/enforcement.
- `tools/reversi-ai-benchmark/whole_game.py:1430-1515` — `main` measurement, verification, and Oracle-check CLI dispatch.
- `tools/reversi-ai-benchmark/prepare-whole-game-measurement.py:230-305` — existing pinned-input and resumable-run conventions.
- `tools/reversi-ai-benchmark/test_whole_game.py` — existing report and Oracle-evidence fixtures.
- `docs/design-decisions/adr.md` and `docs/design-decisions/2026-03-02-reversi-ai-design.md` — existing technology and architecture decisions. `docs/design-decisions/README.md` is absent in this repository; the available decision records were reviewed instead.

## Black-box contract

Add `docs/specs/reversi-ai.md` before implementation with a single-entrypoint
contract and these requirements:

1. On a clean Linux checkout, pin the full source SHA and build
   `reversi-ai-cli` in release mode. Preflight the required Oracle binary and
   working directory, output directory, RSS cap, and progress interval before
   any long search starts.
2. Run the fixed eight-game efficiency sample with no trained artifact, no
   search-time limit, no node limit, and a 600-second per-decision response
   watchdog. Retain the current required host RSS safety cap as an explicit
   input. Keep all eight games even when the 180/300-second references are
   exceeded.
3. Verify the canonical whole-game report offline against the built CLI and
   pinned identity before using it for Oracle queries.
4. Run the external Oracle root and selected-child solve for every exact search
   decision in the report. Each individual Oracle solve has a fixed 600-second
   watchdog; the same explicit `--max-rss-kib` cap applies per CLI seat process
   and per Oracle solve process. Advance Oracle evidence to schema 3. Record
   the Oracle search elapsed time/nodes and
   process wall time/user CPU/system CPU/peak RSS for every query. Version the
   evidence schema and verify its settings, resource observations, limits,
   report digest, and Oracle binary digest offline.
5. Atomically publish a final summary only after all prior stages pass. Include
   all eight wall times, mean, nearest-rank P95, Oracle exact-position and query
   counts, per-query Oracle data and aggregates, full source/CLI/Oracle
   identities, report and evidence digests, and stage/total elapsed times. A
   failed or partial run has no success summary.
6. Reuse only canonical, digest-valid, identity-matching outputs. Resume the
   existing per-game checkpoints; add identity-pinned per-exact-decision Oracle
   checkpoints, including timeout/RSS settings and resource observations, so a
   restart does not repeat completed Oracle work. Reject corrupt or mismatched
   saved data without overwriting it. A run lock prevents concurrent writers
   to one output directory.
7. Emit flushed stderr progress with stable `progress efficiency8` records for
   stage boundaries, completed games, completed Oracle positions, and final
   completion. Include completed/known-total counts and elapsed seconds; include
   game or exact-position identity on unit records. `--progress-every` is a
   positive interval defaulting to 1, with stage boundaries and final output
   always emitted.

The existing README instruction to pin search/node limits for `efficiency8`
must be corrected; the current runner requires those limits to be absent.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` — define one-command run, stage order,
  output identity, progress format, resume, and failure behavior.
- (NEW) `tools/reversi-ai-benchmark/run-efficiency8-closeout.py` — preflight,
  release build, ordered subprocess stages, progress forwarding, resume and
  final summary.
- (MODIFY) `tools/reversi-ai-benchmark/whole_game.py` — add resumable,
  identity-pinned Oracle exact-position checkpoints; record and verify each
  root/child solve's score, elapsed time, nodes, process CPU/RSS and pinned
  limits; add rate-controlled `oracle-check` progress while preserving existing
  CLI contracts and canonical verifier behavior.
- (MODIFY) `tools/reversi-ai-benchmark/exact_threshold.py` — make its existing
  wait4-measured Oracle subprocess helper accept explicit timeout/RSS limits so
  whole-game Oracle checks can reuse the same enforcement and resource format.
- (MODIFY) `tools/reversi-ai-benchmark/test_whole_game.py` — test Oracle
  checkpoint validation, resume, progress interval, and mismatch rejection.
- (MODIFY) `tools/reversi-ai-benchmark/test_exact_threshold.py` — cover explicit
  Oracle timeout/RSS arguments while preserving current threshold-run defaults.
- (NEW) `tools/reversi-ai-benchmark/test_efficiency8_closeout.py` — exercise
  stage ordering, required preflight, reuse of verified stages, failure
  propagation, and completion-summary publication with stub commands only.
- (MODIFY) `tools/reversi-ai-benchmark/README.md` — document the one-command
  human-run entrypoint and correct stale search/node-budget guidance.
- (MODIFY) `docs/exec-plan/todo/0040-reversi-ai-self-play-performance-closeout.md`
  — point the active measurement gate to the new runner while keeping the
  human measurement and acceptance gate open.
- (DELETE, after implementation verification and PR preparation)
  `docs/exec-plan/todo/0048-reversi-ai-self-play-measurement-runner.md`.

## Work and dependencies

1. Merge this plan/spec PR before implementation, following the repository
   plan-first workflow.
2. On a fresh `feat/reversi-ai-self-play-measurement-runner` branch from current
   main, implement Oracle checkpoint/resume and rate-controlled unit progress.
   Validate checkpoint identity and canonical digest before any query is
   skipped.
3. Implement the one-command Python driver. It must call the existing
   measurement, verification, Oracle-check, and Oracle-evidence verification
   entrypoints rather than duplicate their scoring or report logic.
4. Add stub-based unit tests for orchestration. Tests must not launch the
   eight-game measurement or real external Oracle.
5. Update operator documentation, run applicable unit tests, format/compile,
   workflow lint, and diff checks. Create the implementation PR through
   `review-task`, then remove this execution plan after verification and PR
   preparation. Do not remove or mark 0040 complete.

No independent parallel implementation is planned because checkpoints,
identity validation, and orchestration share the same report contract.

## Verification

- `rtk python3 tools/reversi-ai-benchmark/test_whole_game.py` passes, including
  interrupted/restarted Oracle evidence and corrupt/mismatched checkpoint cases.
- `rtk python3 tools/reversi-ai-benchmark/test_efficiency8_closeout.py` passes
  with all subprocess calls stubbed.
- `rtk make oracle-test` passes.
- `rtk cargo fmt --all -- --check`, Python compile checks, workflow lint, and
  `rtk git diff --check` pass.
- A bounded local smoke test uses stub CLI/Oracle programs and a synthetic
  report; the real eight-game and external Oracle runs remain human-started.
- Final output is independently re-verified and records all eight games plus
  every exact root/selected-child match before the completion summary appears.

## Addresses

N/A — no linked issue.
