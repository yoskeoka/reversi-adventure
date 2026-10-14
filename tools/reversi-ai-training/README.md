# Reversi AI pattern training

This tool uses the Python standard library to build repeatable sparse weights
for the pattern evaluator. The tiny fixture uses `CC0-1.0` and supports tests
only. Use labelled final scores for training; the oracle corpus supplies move
sets for checks.

Run the bounded fixture twice and compare its declared output:

```sh
python3 tools/reversi-ai-training/training.py train \
  --manifest tools/reversi-ai-training/fixtures/tiny-winner-empty-manifest.json \
  --artifact /tmp/pattern-artifact.json --report /tmp/pattern-report.json
python3 tools/reversi-ai-training/training.py validate --artifact /tmp/pattern-artifact.json
```

Large datasets and mutable optimizer caches belong outside the checkout. A real
manifest must pin each data file digest and each record's source, license, and
source digest.

The emitted artifact has only sparse integer tables, a fixed
60-phase/64-feature contract, per-feature bounds no greater than one, and
canonical SHA-256 identity fields.

## Project-owned random-game baseline inputs

新規production入力は下記のinput-bundle経路と0051の固定予算を使う。
この節の直接起動例と旧0032の実測だけでは新bundleの生成経路・資源gateを満たさない。

`random_inputs.py` draws complete legal games from the canonical initial board.
Its frozen manifest pins the exact clean producer checkout, merged-main base,
and digests of the generator and imported game/trainer modules, plus seed,
split game ids, random and split rules, `CC0-1.0` provenance, record start and
turn cap.

Defaults are 2,048 train, 256 validation, and 256 held-out games;
every split must cover opening, midgame, and endgame. The validation file is
separate from training and held-out inputs, with all production files stored
outside the checkout.

First run a small pilot with the same generator and use `/usr/bin/time -v` to
record elapsed time and peak memory use.

Set a production wall-clock and peak-memory cap from that measurement before freezing the production
manifest. If the estimated production run exceeds either cap, choose new
counts and freeze a new manifest before generation.

```sh
make pattern-random-prepare RANDOM_INPUT_MANIFEST=/tmp/random-pilot/manifest.json \
  RANDOM_INPUT_TRAIN_GAMES=4 RANDOM_INPUT_VALIDATION_GAMES=2 RANDOM_INPUT_HELD_OUT_GAMES=2
/usr/bin/time -v make pattern-random-generate \
  RANDOM_INPUT_MANIFEST=/tmp/random-pilot/manifest.json RANDOM_INPUT_OUTPUT_DIR=/tmp/random-pilot/output
make pattern-random-verify \
  RANDOM_INPUT_MANIFEST=/tmp/random-pilot/manifest.json RANDOM_INPUT_OUTPUT_DIR=/tmp/random-pilot/output
```

Use fresh paths for production. `prepare` refuses to overwrite a manifest;
`generate` refuses a nonempty output directory and writes `report.json` last.
Only a successful `verify` establishes complete input evidence.

```sh
make pattern-random-prepare RANDOM_INPUT_MANIFEST=/absolute/path/input-manifest.json
make pattern-random-generate RANDOM_INPUT_MANIFEST=/absolute/path/input-manifest.json \
  RANDOM_INPUT_OUTPUT_DIR=/absolute/path/inputs \
  RANDOM_INPUT_PROGRESS_EVERY=1
make pattern-random-verify RANDOM_INPUT_MANIFEST=/absolute/path/input-manifest.json \
  RANDOM_INPUT_OUTPUT_DIR=/absolute/path/inputs
make pattern-random-train RANDOM_INPUT_MANIFEST=/absolute/path/input-manifest.json \
  RANDOM_INPUT_OUTPUT_DIR=/absolute/path/inputs \
  RANDOM_INPUT_ARTIFACT=/absolute/path/baseline.json \
  RANDOM_INPUT_TRAIN_REPORT=/absolute/path/baseline-report.json \
  PATTERN_PROGRESS_EVERY=1
```

Record the SHA-256 of the generator manifest, all output files, trained
artifact and trainer report. The trainer report measures held-out error only;
compare that error against zero-weight predictions on the same held-out rows.
Playing strength needs separate match evidence.

For 0019, record the exact baseline artifact and validation input
(`inputs/validation.jsonl`) paths and digests, while reserving the 0018 openings
for its acceptance run.

The trainer writes flushed stderr progress for validated and prediction-checked
records, with start and done boundaries for loading, aggregation, metrics, and
publication. `PATTERN_PROGRESS_EVERY=N` is a positive interval override;
diagnostics never change the artifact or report bytes.

## Winner-empty input bundle（0050/0051）

`input_bundle.py`は既存random generator/trainerを再利用し、生成経路と原本をoffline再構成する。
署名や承認ファイルは不要。merged-mainのclean producer、全出力SHA、CLIのsource/Cargo.lock/
release build recipe/binary SHAをpinする。縮小入力は常にtoolingである。
[保存方式と信頼範囲](../../docs/references/reversi-ai-training-input-bundle.md)も参照する。

実処理は0051で人間がstageごとに起動する。agent/CIは実2560局・実Oracle・実pilotを
起動・監視しない。生成出力6ファイルは`generated/`だけへ置き、manifest、logs、baseline、
corpus、Oracle原本、probeは兄弟directoryへ保存する。Linuxのprocess groupを1秒ごとに
観測し、wall/RSS超過・metric取得不能で停止する。観測RSSは瞬間最大値ではない。
`--heartbeat-seconds`既定5、内部`--progress-every`既定1・正数のみ、最終単位を必ず表示する。

| stage | wall秒 | 観測RSS |
| --- | ---: | ---: |
| calibration-generate / calibration-verify / calibration-train | 120 / 120 / 300 | 256MiB / 512MiB / 1GiB |
| generate / verify / train | 600 / 1200 / 1800 | 1GiB / 2GiB / 3GiB |
| corpus / oracle | 120 / 4200（rootごと300） | 256MiB / 3GiB |
| bundle-verify / cli-probe | 2400 / 10 | 3GiB / 3GiB |

合計10870秒は予算であり予測時間ではない。8局calibrationは4/2/2、productionは
2048/256/256局で固定する。失敗時は原本を残し、新directoryでstageを最初から再実行する。
途中game/trainer/Oracleのresumeと後続stage自動起動はない。

以下はmerged clean checkoutで準備するstage入口の例。実path/seedは0051でfreezeする。
CLI buildは準備工程として次の固定recipe入口で原本とreceiptを保存する。

```sh
rtk python3 tools/reversi-ai-training/input_bundle.py build-cli \
  --output-dir /absolute/run/cli-build
rtk python3 tools/reversi-ai-oracle/oracle.py prepare-runtime \
  --output-dir /absolute/run/oracle-runtime
```

stageは構造化requestの入力を自動pinし、producer workerを固定する。
追加の前stage reportを`--input`でpinする。任意argvをstageとして実行しない。
以下のrequestを`/absolute/run/requests/generate.json`に保存する。

```json
{"generator_manifest":"/absolute/run/generator-manifest.json","output_dir":"/absolute/run/generated","progress_every":1}
```

```sh
rtk python3 tools/reversi-ai-training/input_bundle.py prepare-stage \
  --manifest /absolute/run/manifests/generate.json --stage generate \
  --request /absolute/run/requests/generate.json \
  --input /absolute/run/stages/calibration-train/report.json
# 人間が単独で起動する
rtk make pattern-input-bundle-run-stage \
  INPUT_BUNDLE_MANIFEST=/absolute/run/manifests/generate.json \
  INPUT_BUNDLE_STAGE_OUTPUT=/absolute/run/stages/generate
```

generator manifestは実行前にpinする。全量generate→verify→trainは別stageとし、
生成後のrecord数とsplit SHAをtrainer-stage manifestへpinする。calibrationも別seedと出力先で行う。
`--input`には直前の必要stageの`report.json`を渡す（calibration-generateのみ前stage不要）。
cli-probeはtrain、bundle-verifyはoracleとcli-probeの両reportを要求する。
requestのfieldは次のとおり。全pathは絶対path、reservationは下記のJSON object。

| stage（calibration prefixも同じfields） | request fields |
| --- | --- |
| generate | generator_manifest, output_dir, progress_every |
| verify | generator_manifest, generator_dir, progress_every |
| train | generator_manifest, generator_dir, artifact, report, record_total, progress_every |
| corpus | generator_manifest, generator_dir, seed, output_dir, reservation, progress_every |
| oracle | corpus_dir, binary, oracle_cwd, output_dir, progress_every（productionはruntime_receiptも必要） |
| cli-probe | validation, artifact, cli, output_dir, reservation |
| bundle-verify | bundle_manifest, cli, report |

```json
{"state":"not-yet-selected","artifact":null,"keys":[]}
```

独立corpusは三splitと実予約suiteがある場合だけそのkeysを除外してscore観測前に固定する。
Oracleは12 rootを個別解析しraw problem/mapping/argv/cwd/stdout/stderr/exit/runtimeを保存する。
`prepare-runtime`は固定archiveを照合してbuild/version確認し、archive原本とruntime receiptを保存する。
receiptのbinary/cwdをoracle requestへ設定し、`runtime_receipt`にはそのreceiptの絶対pathを指定する。
receiptなしのfake runtimeは件数やprofile名にかかわらずtoolingに限る。
CLIは最初の適格validation openingを事前選択し、固定の小予算でresetと合法手をprobeする。

完了したstage原本を用いて`finalize --help`の全path引数を設定し、completion bundleと
検証reportを最後に保存する。`verify`はCLI/Oracleを起動せず全producer出力を再構成する。

```sh
rtk python3 tools/reversi-ai-training/input_bundle.py finalize \
  --manifest /absolute/run/bundle.json --report /absolute/run/bundle-report.json \
  --generator-manifest /absolute/run/generator-manifest.json \
  --generator-dir /absolute/run/generated \
  --baseline-artifact /absolute/run/baseline/artifact.json \
  --baseline-report /absolute/run/baseline/report.json \
  --corpus-dir /absolute/run/corpus --oracle-dir /absolute/run/oracle \
  --cli /absolute/checkout/target/release/reversi-ai-cli \
  --build-receipt /absolute/run/cli-build/build.json \
  --cli-probe /absolute/run/probe/cli-probe.json --stage-reports /absolute/run/stages
rtk make pattern-input-bundle-verify \
  INPUT_BUNDLE_MANIFEST=/absolute/run/bundle.json \
  INPUT_BUNDLE_CLI=/absolute/path/reversi-ai-cli
rtk make pattern-pilot-prepare \
  PILOT_INPUT_BUNDLE=/absolute/run/bundle.json \
  PILOT_CANDIDATE_EXECUTABLE=/absolute/path/reversi-ai-cli \
  PILOT_MANIFEST=/absolute/pilot/manifest.json
```

0018 suiteは候補選定後に作るため、それまでは`not-yet-selected`と空予約keysを保存する。
実`reserved`状態はversioned artifact/path/digestとnonempty keysが必要。
bundle/pilot/0019の露出keysは後段0018の開局root衝突検査に渡す。
旧pilot schemaは凍結producerでtoolingとして検証し、新schemaのproduction bundleだけが
改善判定の入力gateを通せる。入力完成だけでは0037成功や0019 freezeを認めない。
完成bundleの最終資源gateは`bundle-verify` requestをprepareし、そのstageを人間が起動する。
上の直接`verify`は既に完成した不変出力を受け取った後のoffline検証にも利用できる。

## One bounded reinforcement cycle

Build a project-owned `reversi-ai-cli` from the accepted, merged source commit.
Keep the baseline artifact, a separate licensed validation JSONL, and all
outputs outside the checkout. Validation rows use the training record schema,
`split: "validation"`, and a `source` distinct from the later 0018 opening
suite.

A versioned tiny validation input and fake CLI under `fixtures/` exercise the
protocol in unit tests. They are too small for strength evidence.

Freeze a manifest. The Make defaults record 64 self-play games in 32
color-swapped D4 pairs and a separately generated 50-game candidate match;
only a result above 25 match points continues to 200 games.

The production seed is newly generated and recorded in the manifest. It also
records six opening plies, the
accepted 12/12/12 match depth and 16-empty exact threshold, disabled book, a
five-minute per-move search limit, ten-million-node cap, 310-second protocol
timeout, and 7,680 total decisions.

Schema 6 gives each search setting its own prepare argument and Make variable.

| Setting | Make variable | Prepare argument | Range | Default |
| --- | --- | --- | --- | --- |
| Opening depth | `REINFORCEMENT_SELF_PLAY_OPENING_DEPTH` | `--self-play-opening-depth` | 1–64 | 12 |
| Midgame depth | `REINFORCEMENT_SELF_PLAY_MIDGAME_DEPTH` | `--self-play-midgame-depth` | 1–64 | 12 |
| Endgame depth | `REINFORCEMENT_SELF_PLAY_ENDGAME_DEPTH` | `--self-play-endgame-depth` | 1–64 | 12 |
| Exact threshold | `REINFORCEMENT_SELF_PLAY_EXACT_EMPTY` | `--self-play-exact-solver-empty-squares` | 0–30 | 16 |

Use midgame depth 8 when needed, or exact threshold 0 to disable solving.
Thresholds such as 18, 20, 22, and 24 set the number of empty squares at which
exact search starts.

The defaults are `12/12/12` with exact16. Before the larger TrainedEvaluator
learning batch, measure search-engine and game-harness throughput with
`StrategicEvaluator`: set all three phase depths to `8`, keep exact16 and cache
scope `turn`. This is a directional heuristic with comparable per-position
evaluation cost. The efficiency sample therefore needs no TrainedEvaluator
artifact and does not claim trained-model strength or evaluator cost.

Run all eight fixed games to completion. Record the mean goal of 180 seconds
and the nearest-rank P95 review point of 300 seconds. These times guide engine
tuning before a large learning batch. They do not stop a game.

The per-decision CLI response timeout is separate. It can detect a search that
stops responding. The 180/300-second whole-game references never stop a game
or limit the full training batch.

The measurement manifest freezes the per-decision search limit, node cap, and
protocol watchdog. A failed or interrupted game is not a completed timing
sample. These settings do not impose a whole-game time cap.

Candidate matches, corpus regret, and later 0018 acceptance retain 12/12/12
and exact threshold 16. The manifest/report freeze all self-play settings, CLI SHA-256,
resource limits, and the turn cache policy. Flexible settings do not clear the
production freeze or its independent correctness gates.

New prepare/run and regret adoption require schema 6. Completed schema 3/4/5 reports require `verify --legacy-offline`; their frozen
producer replays the original raw disc-difference teachers. Schemas 3/4 retain
12/(8|12)/12 and exact 16; schema 5 retains its flexible settings.

Keep failed evidence from an interrupted schema 3/4 run.

Start a new schema 6 run with a separate manifest and output directory. Changing a manifest
after completion fails the report identity checks. Versions 1/2 are unsupported.

All accepted manifests pin `new_game-v1` and the binary digest. Prepare checks
the reset acknowledgement. Each player resets before every game, and the
verifier checks those reset events.

Set time and node caps explicitly if the host needs different limits. The
match profile still requires depths 12/12/12 and the 16-empty threshold. The
protocol timeout must exceed the search time limit, and the resulting manifest
is immutable.

```sh
make pattern-reinforcement-prepare \
  REINFORCEMENT_BASELINE_ARTIFACT=/absolute/path/baseline.json \
  REINFORCEMENT_VALIDATION_INPUT=/absolute/path/validation.jsonl \
  REINFORCEMENT_CANDIDATE_EXECUTABLE=/absolute/path/reversi-ai-cli \
  REINFORCEMENT_VALIDATION_SOURCE=project-owned-validation-v1 \
  REINFORCEMENT_MANIFEST=/absolute/path/cycle-manifest.json
```

A human starts the following long-running command in another terminal and
stops it by terminating that process.

A failed or interrupted cycle has no valid `report.json`; its 50-game checkpoint is diagnostic only, never resume input.
Start over from self-play in a fresh output directory. `run` rejects a
nonempty directory, including one containing a checkpoint.

An agent and the test targets leave this run to the human operator.

```sh
make pattern-reinforcement-run \
  REINFORCEMENT_MANIFEST=/absolute/path/cycle-manifest.json \
  REINFORCEMENT_OUTPUT_DIR=/absolute/path/cycle-output \
  REINFORCEMENT_PROGRESS_EVERY=1
```

The runner writes flushed stderr diagnostics: one completed-game line by
default, plus start and done lines for each later stage. `N/total` counts
individual games.

Use a positive `REINFORCEMENT_PROGRESS_EVERY=N` to log every Nth game and the
final game. Progress stays on stderr, separate from the candidate protocol and
output files; final verification is still required.

After the human run finishes, a later task validates the immutable outputs and
records the SHA-256 of the manifest, five output files, and regret report.

The verifier replays every legal move, recomputes each game digest and the bounded
update, checks validation exclusions, the checkpoint, match points, and selection.
The report includes validation position keys for 0018 to compare with its
acceptance suite and the replayed self-play positions.

Validation MSE is diagnostic only. The candidate is selected only after more
than 25 match points at 50 games and more than 100 at 200 games; otherwise the
baseline wins.

```sh
make pattern-reinforcement-verify \
  REINFORCEMENT_MANIFEST=/absolute/path/cycle-manifest.json \
  REINFORCEMENT_OUTPUT_DIR=/absolute/path/cycle-output
make pattern-reinforcement-regret \
  REINFORCEMENT_MANIFEST=/absolute/path/cycle-manifest.json \
  REINFORCEMENT_OUTPUT_DIR=/absolute/path/cycle-output \
  REINFORCEMENT_REGRET_REPORT=/absolute/path/corpus-regret.jsonl
```

The regret command uses the frozen CLI and selected artifact with the frozen
search controls and protocol timeout under oracle profile
`strong-engine-hcap-v1`. It reads the
existing oracle corpus only; the 0018 held-out openings stay unopened until
their separate acceptance run.

## Training method pilot (0037)

The pilot tool fixes the full-size counts at 64 games, 7,680 teacher rows and
200 match games, then divides by ten and rounds down to caps of 6/768/20.
Only unique rows passed to the one bounded weight update count as teachers.

Six legal Black-start games produce terminal winner-empty teachers.
Ten other legal openings are each played twice, with the players swapping seats.

The frozen search settings are 8/8/8 for self-play and 12/12/12 for match and
corpus choices, all with exact16 and turn cache scope.
The teacher is the completed project-AI game's final value.

Random rollout labels and per-position exact scores are separate label types.
Read the [method review](../../docs/references/reversi-ai-training-method-review.md)
for pinned sources and the reason for this choice.

Prepare needs a format2 baseline and its original trainer manifest, separate
schema2 validation and held-out rows, plus the Oracle corpus and saved golden values.
Pin these inputs and the accepted CLI before running.

Also supply a reserved-opening file with
`{"schema_version":1,"position_keys":["<canonical-board>:B", ...]}`.
The key helper is `training.canonical_position_key`.

Use the reserved 0018 keys without playing its suite.
Keep real inputs outside the checkout and generate new winner-empty data under
a separate plan that a human runs.

Prepare rejects old format1 baselines and raw-disc labels.

```sh
make pattern-pilot-prepare \
  PILOT_MANIFEST=/absolute/path/pilot/manifest.json \
  PILOT_BASELINE_ARTIFACT=/absolute/path/baseline.json \
  PILOT_BASELINE_MANIFEST=/absolute/path/inputs/trainer-manifest.json \
  PILOT_CANDIDATE_EXECUTABLE=/absolute/path/reversi-ai-cli \
  PILOT_VALIDATION_INPUT=/absolute/path/inputs/validation.jsonl \
  PILOT_HELD_OUT_INPUT=/absolute/path/inputs/held_out.jsonl \
  PILOT_RESERVED_OPENINGS=/absolute/path/reserved-0018-keys.json \
  PILOT_CORPUS=/absolute/path/winner-empty-corpus.jsonl \
  PILOT_GOLDEN=/absolute/path/strong-profile-golden.jsonl
```

Defaults are seed 20261014, six opening plies, 300000 ms and 10000000 nodes
per decision, with a 310-second reply timeout.
The time and node caps limit each search; they do not bound the whole batch.

To change them, set `PILOT_SEED`, `PILOT_OPENING_PLIES`, `PILOT_TIME_LIMIT_MS`,
`PILOT_NODE_LIMIT` and `PILOT_DECISION_TIMEOUT_SECONDS` before prepare.
Each new setup needs a fresh manifest and output folder.

Prepare checks the reset reply to confirm that the CLI accepts the baseline.

A human starts the real run in another terminal:

```sh
make pattern-pilot-run PILOT_MANIFEST=/absolute/path/pilot/manifest.json \
  PILOT_OUTPUT_DIR=/absolute/path/pilot/output PILOT_PROGRESS_EVERY=1
```

Stop by ending that process and keep failed output for diagnosis.
Restart in a fresh folder, since the tool cannot resume partial runs.

The final report is saved last, after all six self-play and twenty match games
and all metrics finish.
Agents leave startup, waiting and monitoring of the real batch to the human.

After the human supplies completed immutable output:

```sh
make pattern-pilot-verify PILOT_MANIFEST=/absolute/path/pilot/manifest.json \
  PILOT_OUTPUT_DIR=/absolute/path/pilot/output
```

The offline check replays every opening and move, checks all ten seat-swap pairs,
then rebuilds the unique teachers, weights, errors, regret and match points.
It also checks each input and output digest.

Corpus values come from the saved Oracle golden file, while the runner records
project CLI choices without new Oracle solves.
The offline check starts no process.

Corpus rows that overlap training, reserved roots or played boards are excluded
with IDs; at least one separate legal root must remain.
Validation and held-out exclusions also cover the random opening moves.

Use the manifest's pinned source checkout for the offline check.
Source changes fail the digest check, so preserve the original hashes.

Progress goes to stderr and shows each completed game by default.
Set a positive `PILOT_PROGRESS_EVERY=N` to print less often; the final unit always prints.

The main success rule is lower held-out MSE, with validation MSE and mean regret
no more than 10% worse than baseline and at least 10/20 match points.
A zero baseline must stay zero.

Both success and failure retain the candidate and raw output.
Fixtures use `PILOT_INPUT_KIND=fixture` to mark their results as tool checks.

旧schema1は`PILOT_INPUT_KIND=production`でも`tooling_only=true`、
`strength_inputs=false`、`improvement_observed=false`を維持する。
新schema2は`PILOT_INPUT_BUNDLE`を指定し、merged producerの全対局/学習再現と
Oracle原本再解析・CLI build identityを通したproduction入力だけで入力gateを有効にする。
ハッシュはbytesの照合であり生成者の暗号学的認証ではない。
検証済み入力に加えて実pilotの全対局・独立指標・保存出力再構成が成功したときだけ
次の0019 manifestを準備できる。`production_authorized=false`は維持する。

The [tooling verification record](../../docs/references/reversi-ai-training-pilot-tooling.md)
tracks implementation evidence. With no new-contract production inputs as of
2026-10-14, plan0037 stays active until the human run and independent result
verification are complete.

## Winner-empty migration and preserved evidence

New trainer manifests and records use schema 2, training-v2, explicit
`score_contract="winner-empty-v1"`, and `target.semantics="winner_empty_v1_for_side"`.

Artifact/feature format 2 uses `score_scale="winner_empty_v1"`; only training-v2
(sparse_mean_v1) or reinforcement-v4 (bounded_td_v1) may produce it.

Random-inputs-v2 emits schema 2 manifests, records, games and reports under
project-owned-random-games-v2. Reinforcement-v4 uses manifest 6 and game/report/
checkpoint 4.

Teachers use the legally replayed terminal board:
`own - opponent + sign(own - opponent) * empty`. Random `black`/`white` and
reinforcement `disc_counts` still count physical discs, with draws scoring zero.

Old source bytes are preserved in `legacy_offline/`, with pinned source digests.
The explicit offline adapter loads these isolated producers for verification:

```sh
python3 tools/reversi-ai-training/training.py validate --legacy-offline --artifact OLD_ARTIFACT
python3 tools/reversi-ai-training/training.py validate --legacy-offline --manifest OLD_TRAINER_MANIFEST
python3 tools/reversi-ai-training/random_inputs.py verify --legacy-offline --manifest OLD_MANIFEST --output-dir OLD_OUTPUT
python3 tools/reversi-ai-training/reinforcement.py verify --legacy-offline --manifest OLD_MANIFEST --output-dir OLD_OUTPUT
```

These entry points verify saved data offline, without CLI calls or data
conversion. Runtime, prepare, train, generate, run, regret-command and
regret-timeout reject old inputs.

Keep old digests and root/minimax scores intact. The source snapshot preserves
the producer bytes, random seeds, source digest, raw labels, policy presence
and report shapes.

Original fixtures stay unchanged. A separate tiny winner-empty fixture stores
four legal random-game replays and their labels for regression checks.
Production data generation, training and 0037/0019/0018 human gates remain frozen.

The bundled random snapshot reproduces the pre-0047 producer. Older production
manifests (including 0032) may pin an earlier producer commit. Check out the
manifest's exact `source_commit` in a separate checkout and point the adapter
to that checkout's original source directory:

```sh
python3 tools/reversi-ai-training/random_inputs.py verify --legacy-offline \
  --legacy-source-dir /original-checkout/tools/reversi-ai-training \
  --manifest OLD_MANIFEST --output-dir OLD_OUTPUT
```

Before import, all three original producer files must match the manifest's
`generator_sha256` and `producer_sources`, after which the original verifier
checks its checkout ancestry and complete output bytes.

Keep the original manifest and digests intact. A source directory with different
producer bytes is rejected; `--legacy-source-dir` requires `--legacy-offline`.
