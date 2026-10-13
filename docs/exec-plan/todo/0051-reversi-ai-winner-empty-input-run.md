# 人間操作でwinner-empty baseline入力とOracle基準値を生成する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と外部完了境界

0037実pilotへ渡す新契約入力packageを生成する。PR #266と0050実装のマージ後に開始する。
人間が起動する生成・学習・Oracle解析、完成原本のoffline再検証、入力identityと
観測結果の記録が揃って本計画を完了する。コマンド準備だけでは完了しない。
実pilotや強さの改善は0037で別に確認する。本計画から0019をfreezeしない。

ユーザーの2026-10-14の質問に対する順序は、ツールのPRを先にマージし、
次に入力生成とbaseline再学習を行い、入力検証後に0037を実行する。
既存StrategicEvaluatorの8局計測を再実行する工程は含めない。

## 参照

- `0050-reversi-ai-training-input-provenance.md` — bundle、Oracle raw保存、資源runnerの実装契約。
- `tools/reversi-ai-training/random_inputs.py:113-190,193-310,314-380`
  — winner-empty v2のsplit規則、全2560局上限、生成とoffline再生成。
- `training.py:272-322,400-460` — deterministic baselineとreport。
- `docs/specs/reversi-ai.md:210-245`、0050実装後のinput-bundle契約。
- `docs/references/reversi-ai-random-inputs-0032.md` — 旧raw差runの履歴。新入力とは別物。
- PR #266の`tools/reversi-ai-training/README.md`、0037、0019、0018 — 残る実pilot/受け入れ。

## 変更マップ

- (NEW) `docs/references/reversi-ai-winner-empty-input-run.md` — producer/source/CLI、manifestと
  全出力digest、実数、時間/CPU/RSS、teacher意味、baseline診断、停止/失敗結果。
- (MODIFY) `docs/exec-plan/todo/0037-reversi-ai-training-method-pilot.md` — 入力完成証拠へのリンクと
  実pilotをprepareできる状態を記載。toolingの完成とpilot成功を混同しない。
- (DELETE) 本計画 — 実package完成とoffline再検証、記録、PR準備後のみ。
- (NEW, checkout外) immutable generator/baseline/Oracle/build bundleと原本logs。
  大量JSONL、binary、Oracle resourcesをGitへ入れない。

## 固定する実行単位と上限

| stage | 完成単位・既知total | wall上限 | 観測RSS上限 |
| --- | --- | ---: | ---: |
| calibration generate | random完成8局（4 train/2 validation/2 held_out） | 120秒 | 256MiB |
| calibration verify | 同8局と全出力rebuild | 120秒 | 512MiB |
| calibration train | 1 baselineとtrainer report（record totalは検証後pin） | 300秒 | 1GiB |
| full generate | random完成2560局（2048/256/256） | 600秒 | 1GiB |
| full verify | 全2560局と全出力rebuild | 1200秒 | 2GiB |
| full train | 1 baselineとtrainer report（record totalは検証後pin） | 1800秒 | 3GiB |
| corpus selection | 最大256 random候補ゲームから12 root（20/40/48石を各4） | 120秒 | 256MiB |
| Oracle golden | 全12 root、最大192非終局child query | 4200秒、各root300秒 | 3GiB |
| final bundle verify | 1完成bundle（stage検証結果を再構成） | 2400秒 | 3GiB |
| CLI artifact probe | 固定した1 opening局面のresetと合法手応答 | 10秒 | 3GiB |

上限は今回の初期予算であり、終了時間の予測・実行可能性の保証ではない。
calibrationの実測を保存し、上限超過・phase不足・失敗ならそこで停止する。
全量工程の資源見積りを記録し、上限を超える見込みなら新しい計画/manifestへ変更する。
古い0032の時間/RSS、StrategicEvaluatorの対局速度、8局の線形外挿だけで全量の完了を断定しない。
stage別wall上限の合計10870秒（181分10秒）をmanifestへ記録する。これはbuild/準備を除く
実処理予算であり、予想所要時間ではない。再試行は別runで、繰り返しを一runの上限内と数えない。

## 実行と検証の順序

1. **準備（agent可）**: PR #266と0050実装のmerged commitを確認する。最新mainから新しい
   `ww` worktreeを作り、clean producer commit/source SHAをpinする。release CLIの
   source/Cargo.lock/build command/binary SHAを保存する。Oracle v7.8.1のbinary、resources、
   cwd、source identityを確認する。0018の開局keysだけを保存し、suiteをプレイ・解析しない。
   checkout外の新しいrun rootへ実パス・seed・上限入りmanifestと各stageコマンドを用意する。
   generatorの出力directoryには既存6ファイルのみ置き、manifest/logs、baseline、Oracleは
   兄弟directoryへ分離する。追加ファイルで既存verifierを失敗させない。
   実行前manifestはcounts/seed/上限/sourceを固定する。生成後のrecord totalと出力SHAは
   新しいtrainer stage manifestへ固定し、全完成出力を別のcompletion bundleへ記録する。
   凍結済みmanifestは後から変更しない。
   署名や別承認ファイルは作らない。ここでagentのturnをhandoffする。
2. **calibration（人間起動）**: 独立seedで4/2/2 random局を生成し、offline検証・baseline学習。
   wall/CPU/RSS、全split phase coverageと出力digestを保存する。8局でも三phase要件を満たさない
   ときは失敗を保存し、勝手にseedを探し直さない。seed/count変更は新manifestにする。
3. **全量入力（人間起動）**: 別seedと新しいmanifestで2048/256/256局を生成。
   実行前にsplit game ID、CC0-1.0、8 placements開始、128 turn上限、producerをfreezeする。
   生成→verify→trainを別コマンドで行う。次stageは直前の完成・検証後にだけ開始する。
   random完成局のwinner-empty値をbootstrap教師とし、AI/exact教師だとは記載しない。
4. **Oracle（人間起動）**: 三splitと0018予約keysを除外した独立corpusを、値を観測する前に
   12 rootへ固定する。全合法手のchildをstrong profileで解析し、0050の原本を保存する。
   missing/timeout/root失敗の結果を完成goldenへ混ぜず、rootを都合よく差し替えない。
5. **完成原本のoffline検証（後続agent可）**: 人間からimmutable paths/digestsを受け取り、
   凍結producerのgenerator replay/rebuild、baselineとtrainer report再現、Oracle raw→golden
   再構成、CLIとsource identity、D4分離を検証する。live再solveを呼ばない。
6. **記録/PR（agent）**: 新契約bundleの全identity、件数・三phase・target範囲・失敗、
   時間/CPU/RSS、baseline held-out/zero-weight診断と非zero重み数を記録する。
   診断MSEを強さ改善と呼ばない。0037へ渡す具体的path/sha一覧とprepareコマンドを記載する。
   本計画を削除し、review-taskでPR handoffする。0037は実pilot終了まで残す。

## 停止・再実行・進捗

agentは実生成・学習・Oracle batchを起動、待機、poll、監視しない。
人間はstageプロセスを終了させて停止できる。資源runnerはprocess groupを停止し、
raw出力と失敗/中断記録を保存する。未完成stageを再開せず、新しい出力先で最初から実行する。
検証済みの前stageはidentityを再確認した上で次stageへ渡せる。途中trainerや途中goldenを
完成入力として使わない。bundle完成reportは最後に保存する。

0050で規定したstage開始/完了と5秒heartbeat、既定毎単位のprogressを使用する。
`--progress-every`は正数、最終単位は表示。ゲームtotalは8/2560、Oracleは12 root、
trainerのrecordsは生成後manifestにpinする。時間/RSSの診断はcanonical artifactを変えない。

## 依存と並列性

PR #266マージ → 0050実装マージ → 8局calibration → 全量入力/再学習 → Oracle生成 →
bundle offline検証 → 0037実pilot → 成功時のみ0019 → 0018。
corpusのsplit除外は完成三splitに依存するため全量生成前にOracleを実行しない。
freeze済みproducerからCLIをbuildする準備とfixture検証は並行できる。

## 検証と失敗時の完了扱い

- 全stageの完成・合法終局、source/score identity、三split独立、全出力digest一致。
- Oracle全childとraw応答、profile/resources、offline再構成、独立legal rootの存在。
- 実baselineをCLIが受理する。validationの元の行順で最初の、石数20以下・合法手あり・
  0018予約keys外の局面を事前pinして一度だけprobeする。1/1/1・exact16・turn、
  100ms/1000nodes、応答watchdog2秒、stage wall10秒でreset ackと合法手を確認する。
  board/side、argv、raw応答とbinary/artifact SHAを兄弟directoryの`cli-probe.json`へ保存する。
- 数値reportの記録とdoc links、workflow lint、diff check。
- 失敗原本の検証/記録だけでは入力完成としない。必要な再計画を記して本計画を残す。
  勝率、統計的一般化、0037改善、0019freeze、0018達成は未認定のままとする。

## Addresses

- N/A。
