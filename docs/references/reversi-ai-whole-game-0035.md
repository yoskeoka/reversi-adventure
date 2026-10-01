# 0035 whole-game measurement handoff

## Resumable reset measurement

Prepare a new output directory with the merged reset-capable release CLI.
Preparation verifies a bounded `new_game` acknowledgement without playing a
game. It freezes source and harness commit IDs, SHA-256 and absolute paths of
the CLI, external Oracle, artifact, openings and Python harness, host identity,
depths, ordered assignments, resource limits and process lifetimes. Preparation
never starts a measurement. Keep the checkout at the pinned harness commit;
changes to either the checkout revision or harness files fail input verification.

```sh
rtk python3 tools/reversi-ai-benchmark/prepare-whole-game-measurement.py prepare \
  --source-revision FULL_CLI_SOURCE_COMMIT --harness-revision FULL_HARNESS_COMMIT \
  --cli-binary /absolute/path/reset-capable/reversi-ai-cli \
  --oracle-binary /absolute/path/Egaroucid_for_Console.out \
  --artifact /absolute/path/baseline.json \
  --legacy-dir /absolute/path/existing/results \
  --legacy-binary /absolute/path/pre-236/reversi-ai-cli \
  --legacy-candidate-binary /absolute/path/pr236/reversi-ai-cli \
  --timeout-seconds 310 --max-rss-kib 1572864 \
  --output-dir /absolute/path/new-reset-measurement
```

`--legacy-dir` explicitly registers all 14 immutable v1 reports, comparisons
and Oracle checks at depths 12 and 8. Each is independently verified and
hashed during preparation and every launch. Legacy persistent results retained
caches between games; they remain reference evidence and cannot fill the new
reset conditions. Omit all three legacy options for a separate measurement
without this registry. The new run measures six conditions: turn, game and
persistent at depth 12, followed by the same three at depth 8. Its progress
`conditions` total is six; registered legacy artifacts do not increase this
measurement total.

Preparation prints the single launch command. The human operator runs it
serially on the same quiet Linux host in another terminal:

```sh
rtk bash /absolute/path/new-reset-measurement/run-whole-game.sh
```

Restart that same script after interruption. Every completed game is validated,
flushed and atomically saved; incomplete temporary files do not count as games.
An interrupted game starts again from its opening with empty caches. Both seat
processes acknowledge `new_game` before the first decision, clearing ordinary
and exact search tables; cache reuse occurs only within a game. Eight verified
games produce an atomic complete report. Existing completed reports and
comparison/Oracle evidence are independently verified and skipped. Changed
inputs, malformed records and identity mismatches stop the run without replacing
existing evidence. A driver lock rejects a concurrent launch.

One-game-per-seat conditions have per-game wait4 CPU and peak RSS. Persistent
conditions save diagnostics and CPU differences immediately after each game;
their RSS values are cumulative segment peaks, not independent per-game peaks.
Each new segment starts with empty game caches and never warms up by replaying
completed games. Session/segment and startup/shutdown evidence distinguishes
resumed segments from eight games in a single uninterrupted process. Final
wait4 segment peaks also obey the RSS cap. Completed-game checkpoint aggregates
and full segment aggregates are labelled separately; the latter include process
overhead and measured work from an interrupted game.

```sh
rtk make benchmark-whole-game-inputs-verify WHOLE_GAME_MANIFEST=/absolute/path/new-reset-measurement/manifest.json
rtk make benchmark-whole-game-manifest-verify WHOLE_GAME_MANIFEST=/absolute/path/new-reset-measurement/manifest.json
```

The first command verifies inputs and the legacy registry without starting
measurement. The second requires and verifies all six completed reports, both
comparisons and both Oracle checks offline. `benchmark-whole-game-prepare`
accepts the preparation arguments in `WHOLE_GAME_PREPARE_ARGS`;
`benchmark-whole-game-run` accepts `WHOLE_GAME_MANIFEST` and optional
`WHOLE_GAME_PROGRESS_EVERY`. Failures and completion progress always flush.

## Original v1 procedure and evidence

The checked-in `whole-game-openings-v1.json` fixes four legal six-placement
openings. The runner plays each opening twice with reversed seat assignments,
giving eight complete games per condition. Each seat is one process for one
game; `cli-persistent` keeps two CLI processes for all eight games as a
separate runner workload.

The GTP oracle uses pinned, bookless, one-thread
Console profiles `whole-game-depth-12-exact-16` and
`whole-game-depth-8-exact-16`. The former uses depth 12 until 48 occupied
discs and depth 16 thereafter; the latter uses depth 8 only at 21–44
occupied discs. Both are separate from candidate acceptance settings.

The human operator runs each command below **serially on the same quiet host**
with explicit release binaries and the same trained artifact for both CLI
conditions. `make benchmark-oracle-setup` provisions the pinned external
Console binary; the runner never embeds it in Rust or a release artifact.
Freeze and record the SHA-256 of that binary, the accepted pre-0035 CLI, the
0035 CLI, the trained artifact, and the opening file. Keep output paths
immutable.

The diagnostic comparison uses the 0035 CLI with
`WHOLE_GAME_CACHE_SCOPE=turn` for a per-turn table and `game` for retained
exact proofs. Both use identical search code and diagnostic fields. The old
CLI lacks this diagnostic contract; its raw timing can be measured separately,
but that report alone cannot support an adoption claim.

```sh
rtk make benchmark-whole-game WHOLE_GAME_KIND=oracle WHOLE_GAME_BINARY=/absolute/path/Egaroucid-for-Console WHOLE_GAME_DEPTH=12 WHOLE_GAME_REPORT=/absolute/path/oracle-12.json
rtk make benchmark-whole-game-verify WHOLE_GAME_REPORT=/absolute/path/oracle-12.json WHOLE_GAME_BINARY=/absolute/path/Egaroucid-for-Console
rtk make benchmark-whole-game WHOLE_GAME_KIND=cli-legacy WHOLE_GAME_BINARY=/absolute/path/pre-0035/reversi-ai-cli WHOLE_GAME_ARTIFACT=/absolute/path/baseline-artifact.json WHOLE_GAME_DEPTH=12 WHOLE_GAME_REPORT=/absolute/path/legacy-12.json
rtk make benchmark-whole-game WHOLE_GAME_KIND=cli WHOLE_GAME_BINARY=/absolute/path/candidate/reversi-ai-cli WHOLE_GAME_ARTIFACT=/absolute/path/baseline-artifact.json WHOLE_GAME_DEPTH=12 WHOLE_GAME_CACHE_SCOPE=turn WHOLE_GAME_REPORT=/absolute/path/turn-12.json
rtk make benchmark-whole-game WHOLE_GAME_KIND=cli WHOLE_GAME_BINARY=/absolute/path/candidate/reversi-ai-cli WHOLE_GAME_ARTIFACT=/absolute/path/baseline-artifact.json WHOLE_GAME_DEPTH=12 WHOLE_GAME_CACHE_SCOPE=game WHOLE_GAME_REPORT=/absolute/path/game-12.json
rtk make benchmark-whole-game WHOLE_GAME_KIND=cli-persistent WHOLE_GAME_BINARY=/absolute/path/candidate/reversi-ai-cli WHOLE_GAME_ARTIFACT=/absolute/path/baseline-artifact.json WHOLE_GAME_DEPTH=12 WHOLE_GAME_REPORT=/absolute/path/candidate-persistent-12.json
rtk make benchmark-whole-game-verify WHOLE_GAME_REPORT=/absolute/path/game-12.json WHOLE_GAME_BINARY=/absolute/path/candidate/reversi-ai-cli WHOLE_GAME_ARTIFACT=/absolute/path/baseline-artifact.json
```

Repeat oracle and CLI runs at self-play midgame depth 8, changing only
`WHOLE_GAME_DEPTH=8` and output names. `WHOLE_GAME_MAX_RSS_KIB` defaults to
1,048,576 KiB and `WHOLE_GAME_TIMEOUT_SECONDS` to 310 seconds per decision;
set both explicitly if the host requires other caps. The runner stops without
a report on illegal moves, timeout, an incomplete legal-move search, missing
CPU/RSS, or a failed game. A nonterminal forced pass below the exact threshold
is valid with `outcome=pass`, `score=null`, `completed_depth=0`, and
`exact=false`; it remains a decision in the game record. An exact-region pass
requires an integer score, `exact=true`, and completed depth equal to the
remaining empty squares. Measurement attachment and offline verification reject
malformed pass diagnostics and require configured depth and an integer score
for every legal-move search.

The depth-8 `turn` measurement previously stopped at
`opening-4-seat0-turn27`, a legal forced pass after 27 placements, before
writing its report. After this fix merges, rerun that eight-game condition in
the existing output directory. Independently verify the completed reports
already there and reuse them; the failed `turn-8` sample must be measured anew.

`benchmark-whole-game-verify` independently replays the
games and recomputes resource totals and report digest. Report
`seat_processes` separates startup and shutdown from game wall time.

After the `turn` and `game` reports have both verified, run the comparison.
It fails if any same-game position, move, score, depth, or exactness differs.
The report gives wall and CPU ratios, peak RSS, nodes, and cache activity.

```sh
rtk make benchmark-whole-game-compare WHOLE_GAME_TURN_REPORT=/absolute/path/turn-12.json WHOLE_GAME_GAME_REPORT=/absolute/path/game-12.json WHOLE_GAME_COMPARISON=/absolute/path/comparison-12.json
rtk make benchmark-whole-game-compare-verify WHOLE_GAME_TURN_REPORT=/absolute/path/turn-12.json WHOLE_GAME_GAME_REPORT=/absolute/path/game-12.json WHOLE_GAME_COMPARISON=/absolute/path/comparison-12.json
```

The independent exact check is another human-operated command. It runs the
pinned oracle's complete solve for each exact CLI decision and its selected
continuation, and requires the root-side scores to agree.

It writes an
immutable evidence report only after all checks complete; the verifier checks
its positions, source report, oracle profile, binary identity, and digest.

```sh
rtk make benchmark-whole-game-oracle-check WHOLE_GAME_GAME_REPORT=/absolute/path/game-12.json WHOLE_GAME_BINARY=/absolute/path/Egaroucid-for-Console WHOLE_GAME_ORACLE_EVIDENCE=/absolute/path/exact-check-12.json
rtk make benchmark-whole-game-oracle-check-verify WHOLE_GAME_GAME_REPORT=/absolute/path/game-12.json WHOLE_GAME_BINARY=/absolute/path/Egaroucid-for-Console WHOLE_GAME_ORACLE_EVIDENCE=/absolute/path/exact-check-12.json
```

After all reports exist, compare the same workload and host, including raw
per-game wall time, user/system CPU, peak RSS, search count, and cache
probes/hits/stores. Compare shared board-and-side decisions for equal move,
score, and exactness at the **same** depth; depth 8 and 12 are separate
conditions. Check exact scores against independent Console solves. Record the
ratios and the cache-hit/node change that explains any time difference.

The 2–3 minute guide is not an acceptance threshold until the oracle's
eight-game result is known. A stopped version-2 reinforcement run is not
benchmark input or candidate evidence. Freeze a fresh production manifest
only after choosing the self-play setting from these reports.
