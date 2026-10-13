# 新契約入力の生成経路を再検証しpilotへ接続する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了境界

0037の実pilotに必要なwinner-empty入力を、既存のランダム対局生成・trainerと
保存Oracle出力まで遡って検証できるようにする。生成用の上限付き人間操作コマンドを
用意し、labelを`production`に変えただけのfixtureを改善証拠として受理しない。
実装・fixture検証・PR handoffを本計画の完了とする。実データ生成は0051、
実pilotと改善/不成立判定は0037、本番cycleは0019、強さの受け入れは0018に残す。

2026-10-14に確認したPR #266のheadは
`b4fcbb80f4bf848b9f39456bcee932880295b80b`。PRはOPEN、4 checksはSUCCESS。
Copilotの旧headの指摘に対して、現在のpilotは全入力の改善認定を無効にしている。
この計画はPR #266がマージされた後に、最新mainから実装する。
計画PRの作成自体は先行できる。

ユーザーは署名や別の承認ファイルを不要と指定した。信頼するローカル人間操作と
レビュー済みproducerの再現検証を採用する。SHAは同じbytesを照合するために使い、
悪意ある生成者の自己申告を認証したとは主張しない。外部allowlist、鍵管理、
承認サービスは追加しない。

## 新契約入力と工程の区別

| 必要物 | 生成工程・値の意味 |
| --- | --- |
| train / validation / held_out JSONL、全対局ログ、generator manifest/report | `random_inputs` v2。黒先手の合法random完成局のwinner-empty終局値。schema2 |
| baseline artifact、trainer manifest/report | 上記trainだけから`training` v2で再学習。format2。validationとheld_outは更新に使わない |
| Oracle corpus / schema2 golden / 実行原本 | 学習と独立した合法局面の全合法手childをstrong-engine-hcap-v1で解析。random終局教師や局面exact値とは別の比較基準 |
| reserved opening keys | 0018の既定開局から得るcanonical D4 board/side keys。suiteの対局・解析はしない |
| project CLI | マージ済みsource・Cargo.lock・build recipeから生成したbinary identity |
| pilot教師・candidate・比較結果 | 上記入力が揃った後の0037。baseline AI継続局の終局値。6局/768採用行/20比較局 |

`winner-empty-v1`の終局scoreは手番側の石差を`d`、空きを`e`として
`d + sign(d) * e`、引き分けは0。石そのものの枚数は変更しない。
旧raw差入力のschema/labelを変えて再利用しない。既存schema1の合法局面定義と
新契約scoreのgoldenは区別する。tiny winner-empty fixtureの存在は本番入力の存在を示さない。

## 参照

- `docs/specs/reversi-ai.md:175-245` — trainer、winner-empty random入力、2048/256/256局。
- PR #266 headの`docs/specs/reversi-ai.md:1297-1366`、`pilot.py:174-248,406-444,524-540`
  — 入力pin、baseline再現、現在の固定false gate、offline出力再構成。mainへマージ後に参照を更新する。
- `tools/reversi-ai-training/random_inputs.py:113-190,193-310,314-380`
  (`prepare`, `check_manifest`, `play`, `build`, `generate`, `verify`) — clean producer、
  全splitのD4排除、完全対局再生・決定的再生成。現在は全量RAM、終了時保存、resumeなし。
- `tools/reversi-ai-training/training.py:199-269,272-322,400-460`
  (`validate_manifest`, `validate_records`, `artifact_from`, `run`) — baseline/reportの再構成。
- `tools/reversi-ai-oracle/oracle.py:165-177,1180-1228,1443-1525,1586-1645,2113-2149`
  — strong profile、`run_solve`、全合法手child解析、`verify_saved_golden`。
  既存`verify`コマンドはlive再solveするので本計画のoffline入口から呼ばない。
- `tools/reversi-ai-benchmark/whole_game.py:63-85` (`oracle_runtime_identity`)、
  `exact_cache_verification_oracle.py:180-215` — binary/resources、保存stdout再解析の既存方式。
- `tools/reversi-ai-training/README.md:24-85`、`docs/references/reversi-ai-random-inputs-0032.md`
  — 旧runの時間/RSSは履歴。新契約の完成や今回の上限内終了の証拠にはしない。
- `0051-reversi-ai-winner-empty-input-run.md`、0037、0019、0018 — 工程の所有と依存。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 先に閉じた入力package、生成経路検証、資源上限、
  進捗、停止/再実行、pilotの認定条件を定義する。
- (NEW) `tools/reversi-ai-training/input_bundle.py`とtests — prepare、人間実行用stage runner、
  保存bundleのoffline検証。既存generator/trainerを再利用し別の学習器は作らない。
- (MODIFY) `tools/reversi-ai-oracle/oracle.py`とtests — 既存解析にproblem/argv/raw応答の
  保存入口を追加。通常golden出力・score/profileの意味は維持する。
- (MODIFY) PR #266で追加される`pilot.py`と`tests/test_pilot.py` — bundle入力と検証結果を
  manifest/reportへpinし、検証を通した実入力だけでstrength gateを有効にする。
- (MODIFY) Makefile、`tools/reversi-ai-training/README.md`、Oracle README — stage別コマンド、
  正確な上限・進捗・人間起動・offline入口を記載する。
- (MODIFY) 0037、0019の依存段落 — 0051の入力完成後にpilotをprepareする順序を記載する。
- (NEW) `docs/references/reversi-ai-training-input-bundle.md` — tooling検証、生成経路の信頼範囲、
  実run前の手順。0051の結果を捏造・先取りしない。

## ブラックボックス契約

### 1. 既存producerの完全な入力package

generator manifest、games、三split JSONL、generator report、trainer manifest、baseline
artifact/reportを一つのbundle manifestで列挙する。schema/contract、件数、seed、split規則、
source commit、merged-main base、producerファイルSHA、license、各出力SHAを固定する。
実行前manifestは既知のcounts/seed/上限/sourceだけを固定する。生成完了後に別のtrainer
stage manifestへ実record数と生成出力SHAを固定し、完成bundleは全stageの出力identityを
最後に列挙する。既存の凍結manifestを後から追記・書き換えない。
cleanなmerged-main producerをcheckoutして実行する。任意のsource名だけでは受理しない。
凍結したGit revisionのproducer bytes・ancestryを照合し、原本の`random_inputs.verify`で
manifestが宣言した全局と全splitを再生・再生成する（calibrationは8局、本番は2560局）。
本番gateは2048/256/256局を要求し、縮小入力はtooling専用にする。
baselineとtrainer reportも決定的に再構成し、
pilotのvalidation/held_outがbundle内の該当splitとbyte単位で一致することを確認する。
baseline更新にvalidation/held_outを混ぜない。source変更は新しいbundleを必要とする。
generator出力先は既存verifierが要求する6ファイルだけにする。bundle manifest、
stage原本logs、baseline artifact/report、Oracle出力はそれぞれ兄弟directoryに保存する。

bootstrapの教師はrandom終局値のまま維持する。強いAIで既存2560局をすべて再生成する
変更は加えない。0037のAI継続教師と混同しない。pilotの768行上限はpilotの更新行に適用し、
bootstrapの全train行数を768へ切り詰めるものではない。

### 2. Oracle保存値の生成経路

独立seed/domainの黒先手random完全対局から石数20/40/48の局面を各4個、計12 root採る。
各rootは合法手2..16、非終局childが1個以上。D4重複、三split、0018予約keysを除外する。
最大256候補ゲームをgame ID/turn順に調べ、12個を得られなければ失敗にする。
採用はscoreを観測する前に行う。全候補game logと選定/除外ID、seed、条件を保存する。
0037比較openingは後からこのcorpusを除外して生成する。

strong-engine-hcap-v1の全合法手childを解析し、最大192非終局child query、
rootごと300秒、stage全体4200秒/3GiBを上限にする。terminal childは盤面から計算する。
既存solveのtimeoutはbatch全体に適用されるため、12 rootをまとめずroot単位で解析する。
Oracle profileは既存8/12深度の契約を維持し、project側12/12/12・exact16と同一と呼ばない。
query対応problem、root/child/side符号mapping、argv、cwd、stdout/stderr、終了状態、
実行前後のOracle binaryとresources全体SHAを保存する。既存parserを使うoffline verifierが
raw応答から同じschema2 goldenを再構成する。解析未完了・不正出力・上限超過・runtime変化は
完成goldenとして扱わず、失敗原本を保存する。都合の良いrootへの差し替えや上限拡大はしない。
既存smoke/legacy goldenのprofile名・schemaだけを変えることは拒否する。
この記録は信頼したローカル実行の再現検査であり、外部生成者への暗号学的保証ではない。

### 3. 資源上限と保存

0051のstage別wall/RSS上限をmanifestに記録し、人間が個別コマンドを起動する。
runnerはLinuxのprocess group全体を対象に上限を監督し、wall超過/観測RSS超過で停止する。
RSS観測は1秒間隔、samplingの限界を記録し、厳密な瞬間最大値を保証したと呼ばない。
監督中にmetric取得不能ならfail-closed。CPU、wall、peak observed RSS、exit/timeout、
raw stdout/stderrとstage manifestを保存する。stageの完成reportは検証後に最後に公開する。

既存生成・trainerは途中再開しない。中断したstageは原本を残して新しい出力先で最初から
やり直す。完成・検証済みの前stageを次stageから再利用できるが、未完成局や途中trainerを
resume入力にしない。stageが失敗したら後続stageを自動起動しない。
root単位の完了記録を保存するが、今回Oracle stage内のresumeも実装しない。

既存のper-game/per-record診断は維持する。runnerのstderr形式は
`progress input-bundle stage=<stage> done=<n> total=<n> status=<running|saved|verified|failed> elapsed_s=<value> rss_bytes=<value>`。
stageは`calibration-generate/verify/train`、`generate/verify/train`、`corpus`、`oracle`、`bundle-verify`、`cli-probe`。
wrapperのdone/totalは各stageの完成0/1、内部generatorは既知の8/2560局、Oracleは12 root、
trainerは入力検証済みrecord数をtotalにする。stage開始/完了と5秒ごとのresource heartbeat、
`--progress-every N`で内部単位の頻度を制御（既定1、正数のみ、最終単位を必ず表示）。
診断はcanonical output/identityに入れない。resource heartbeatは`--heartbeat-seconds`既定5。

### 4. pilotへの接続

新しいpilot producer/schemaでbundle manifestと全出力のidentityをpinする。
旧PR #266 manifest/reportは凍結producerで従来どおりtoolingとして検証できるように残す。
新schemaはproduction bundleの完全再検証とCLI build identityを通した場合だけ
`strength_inputs=true`にできる。CLIはsource commit、Cargo.lock、build recipe、binary SHAを
bundleに保存し、実際に使用するbinaryと照合する。fixture mode/縮小入力は常にtooling。
boolを呼び出し元contextへ書き込んだだけでは認定されない設計にする。
goldenのshapeチェックだけ、文字列labelだけ、bundle内の自己申告のverified flagだけでは通さない。

認定可能な実入力であっても、0037の全6局/768行以下/10完全ペア20局、独立指標、
保存出力再構成をすべて満たして初めて改善/不成立を記録する。検証済み入力の存在だけでは
0019 freezeを許可しない。`production_authorized=false`を維持する。

## 作業順序・並列性

1. PR #266マージを確認し、source/schema差分を確認してspecを更新する。
2. random packageの再検証・baseline/report再現と資源runnerを実装する。
3. Oracle raw保存・独立corpus選定・offline再構成を実装する。2と3の調査は並列可。
4. 2/3の完成後、pilotの新schemaとgateへ接続する。Git書込みは一人で直列化する。
5. bounded fake fixtures、異常系、旧manifest互換、品質gateを検証し、0051用commandをhandoffする。
6. 本計画だけを完了削除する。0051と0037は実runの完成まで残す。

## 検証

- fixtureのproduction改名、source/profile改名、resealされた不正game/row/golden、
  一致しないgenerator/trainer report、旧契約、任意verified boolを拒否する。
- 正しい小fixtureはrepeatで同じbytes、offline検証でCLI/Oracleを一切起動しない。
- 全child mapping、pass/terminal、空き加点、raw parser、missing query、binary/resource変更を検査する。
- process group停止、wall/RSS/metrics取得失敗、未完成出力拒否、新stage再実行、診断頻度をfakeで検証する。
- 0018予約keysの除外と三split/Oracle/pilotのD4独立性を確認する。
- 該当Python tests、Rust engine/AI tests、fmt/Clippy、GDExtension build、workflow lint、diff check。
  実2560局・実Oracle・実pilotはtests/CI/agent作業から起動しない。

## Addresses

- N/A。PR #266の生成経路不足を後続実装として扱う。新規の外部issueはない。
