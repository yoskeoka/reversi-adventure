# 0035 whole-game measurement handoff

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
a report on illegal moves, timeout, incomplete search depth, missing CPU/RSS,
or a failed game.

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
