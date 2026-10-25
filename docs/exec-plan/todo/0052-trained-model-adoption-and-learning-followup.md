# 採用済み0019モデルを基準に自前教師データで更新方式を比較する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了境界

0019のselected candidateを現在のTrainedEvaluatorモデルとして採用した
[記録](../../references/reversi-ai-0019-adopted-model.md)から、学習更新方式の比較へ進む。
0019は一回のcycleを完了済みであり、勝率目標未達を理由に再開しない。
ユーザーはまず同じ教師データによる更新方式比較を選択した。
教師は自前で生成する。Egaroucid/Edaxの対局・公開棋譜・評価値・重みを教師に使わない。
外部Oracleは独立した診断・検証だけに利用する。

同じ0019初期baseline・自前教師3,364行から、現行の整数一回更新と浮動小数点Adamの
反復更新を比較できるtoolingを実装する。その後、人間が上限内の実比較を開始し、
完成出力を別途offline検証して更新方式の改善・不成立を記録した時点を完了とする。
toolingのマージだけでは本計画を削除しない。比較が不成立でも完了できる。
本計画の結果で現行採用モデルを自動的に置換せず、0018の50%目標達成も主張しない。

## 参照

- `docs/references/reversi-ai-0019-adopted-model.md` — run-root・report/選択artifactのidentity、実成績、採用判断。
- `tools/reversi-ai-training/production_cycle.py::load_context, tuning_rows, semantic_phase_check, build_final_report` — 入力・原本・完了phaseの再構成。
- `tools/reversi-ai-training/reinforcement.py:452-487` — `updated_artifact`の一回残差更新と`mse`。
- `tools/reversi-ai-training/training.py:194-204,299-305,337-377` — 64特徴/60phase、整数予測、artifactの重み/optimizer検証。
- `rust/reversi-ai/src/eval/trained.rs::TrainedEvaluator::from_path` — runtime loaderとformat2の制約。
- `docs/specs/reversi-ai.md`のTrained evaluator runtime / Pattern-evaluator training contract / 0019 production cycle。
- `docs/references/reversi-ai-training-method-review.md:14-33,48-62` — Egaroucid一次資料と現方式の違い。
- `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md:93-115` — 次候補に新計画が必要な境界。

## 比較する方式と固定条件

既存方式はbaselineの予測から残差を一度計算し、bucketの平均残差を64で割って丸め、
各重みを`[-1,1]`へ制限する。名称は`bounded_td_v1`だが、このrunの教師は
自前継続対局の終局winner-empty値であり、隣接局面のbootstrapped TD値ではない。
弱さの原因をこの更新則と断定せず、対照実験で確かめる。

| 条件 | 固定値・比較 |
| --- | --- |
| 共通初期値 | 0019 manifestのbaseline artifact（SHA-256 `23ed5f73d939300cd04b0842ce24e840f8c829e3ee942244a7de56a293dc6875`） |
| 共通教師 | 0019の完了自己対戦64局から再構成した3,364行。新しい教師生成0局 |
| 対照A | `bounded_td_v1`を一度再生し、採用済みcandidateのweights/weight digestと一致させる |
| 比較B | 同じ初期値と教師で`project_adam_v1`。f64で学習、各step後`[-1,1]`へprojection |
| 特徴・評価器 | 同じ64特徴/60phase、同じpattern catalog、同じformat2の整数表引き |
| Adam既定値 | learning rate 0.01、beta1=0.9、beta2=0.999、epsilon=1e-8、L2=0 |
| 損失・勾配 | batch平均の二乗誤差。予測は該当64重みの和、active parameterの勾配は`2*(prediction-target)/batch_rows`の和 |
| batch/epoch | batch256、最大20 epochs、seed20261025、epochごとの決定的shuffle。教師を一周した単位をepochとする |
| 初期状態 | m/v/stepは0。教師にない重みは初期値を保持し、zero entryはexportから除く |
| export | 各epochで既存`round_division`と同じhalf-away-from-zeroで整数化。feature bound各1・総和64以内 |
| checkpoint選択 | 整数export後のvalidation MSEが最小のepoch。同点は早いepoch。5 epochs改善なしで停止 |
| 比較相手 | 現在採用済み0019 candidate。Bをそのcandidateからさらに学習させず、初期値を揃える |

実行前にlearning rate/batch/epoch/seed/patienceとtimeoutを引数で指定できるようにし、
上限は20 epochs・teacher3,364行・各種対戦20局を超えない。実行後の探索的な再試行は
本比較に混ぜず、別manifestとして残す。倍精度checkpoint、optimizer stateと整数artifactの
identityを分け、非有限値やruntimeのscore/bounds違反は失敗にする。

## ブラックボックス契約と作業

1. **spec先行**: 新しいoptimizer identity、入力・split・進捗・checkpoint・export・再開と
   失敗時の保存を`docs/specs/reversi-ai.md`に定義する。既存optimizerの意味・legacy検証は保持する。
   新しいtrainer/provenanceをPythonとRustが検証できるようにするが、旧optimizerを偽装しない。
   推論形式・探索・score契約は変更しない。小数重みをruntimeへ渡すための形式変更は別計画。
2. **入力固定**: 0019 manifest、report、全phase receipts、teacher rowsと初期/採用artifact、
   0051 bundle/receiptをpinする。Aの重み再現を実験の前提にし、元のrun-rootは変更しない。
   teacher sourceはproject-owned self-playのみとする。外部Oracle corpus/goldenや公開棋譜を
   train行へ変換する入力を用意しない。各行の出典・game ID・score視点を保持する。
3. **独立split**: 0019の13,401 validation局面を同じ原本・除外規則で再構成し、checkpoint選択だけに使う。
   validationおよび0051 held-outと教師のD4同値board-and-side衝突を再検査し、原本・採用行・除外keysを保存する。
   held-outは事前に固定して最後に一度だけ指標を計算し、空splitを拒否する。
   0051 held-outは方法比較用であり、未選定の0018 held-out suiteではない。
   0018の開局・局面・結果は学習、epoch選択、再試行の調整に使用しない。
4. **更新実装と診断**: 特徴を一度抽出して安定順に処理する。AとBの学習時間、phase別件数、
   changed/nonzero/saturated weights、float/整数exportそれぞれのtrain/validation MSE、
   丸めにより変化が消えたparameter数を保存する。Bのcheckpointを整数export後の指標で選ぶ。
   validationがAより厳密に改善しない場合も全epochと不成立理由を残し、対戦へ進まない。
5. **bounded対戦**: validation改善時だけ、人間がB vs 採用済みAを未使用opening10個の
   座席交換20局で実行する。0019既存対戦を新方式の比較に流用しない。両者とも
   12/12/12・exact16・turn、bookなし、300000ms / 10000000 nodesとする。
   timeoutは実行時に選びattemptへ記録する。B vs Oracle診断は20局を上限とし、
   B vs Aを過半数で勝ち抜いたときだけ実行する。Oracle診断開局も新規・disjointとする。
   Oracleは0019 manifestと同じEgaroucid 7.8.1のbinary/source identityをpinし、
   `oracle-0018-acceptance-v1`（6/6/6・exact12・bookなし・1 thread・hash25）とする。
   Bは上記12/12/12・exact16。両側の設定と実行binary SHA-256を実行前manifestに固定する。
   Corpusは既存の12局面で保存goldenを診断に使い、教師に混ぜない。
6. **判定**: 方法比較の改善は、整数export後validation MSEがAより低下、最後のheld-out MSEと
   corpus平均regretの悪化10%以内（基準0なら0を維持）、B vs Aで`match_points > 10/20`を
   全て満たす場合に限る。小標本の方法比較で一般化や0018達成を主張しない。
   対戦がgateで省略された場合、`not-run`と理由を記録し、予定20局を完了数に数えない。
   float改善がexportで消えた場合は、次の固定小数点/量子化方式の検討材料として保存する。
7. **実行・再開**: `pilot.py`の既存entrypointにoptimizer比較のsubcommandを追加し、
   既存`execute`での0019再開と区別する。Makeからも同じentrypointを呼ぶ。
   prepare→入力再検証→対照再現→最適化→整数選択→対戦→offline検証のphaseごとにreceiptを保存する。
   開始前に実行epoch数/既知の最大batch数・対戦数を表示し、進捗は
   `optimizer-compare phase=... epoch=E/Emax batch=B/Btotal games=G/Gtotal elapsed_seconds=S`。
   `--progress-every`でbatch出力間隔を選べるようにし、既定10・phase境界/完成局は必ず出す。
   `--resume-from PHASE`とcheckpoint再開で完了phaseを検証して引き継ぎ、不完全batch/局だけやり直す。
   各完了batchを原子的なcheckpointとして保存する。weights・m/v・global step・epoch・
   shuffle順/RNG・次batch cursor・best epoch・patienceを含め、最後の完成batchから再開する。
   epoch境界のstateも保存し、変更した学習設定では同じattemptを再開しない。
   人間が長時間runを開始する。agentは起動・監視せず、完成した不変出力だけ後から検証する。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 上記の比較・optimizer provenance・出力契約を先に定義。
- (NEW) `tools/reversi-ai-training/optimizer_compare.py` とtests — 固定入力のA/B、Adam、checkpoint/export、offline再構成。
- (MODIFY) `tools/reversi-ai-training/pilot.py`, `training.py`, `reinforcement.py`とtests — entrypoint・共通helper・新optimizerを明示検証。
- (MODIFY) `rust/reversi-ai/src/eval/trained.rs` とtests — 正式な新trainer/provenanceだけを許可し、重み表現とscore boundsは維持。
- (MODIFY) Makefile / `tools/reversi-ai-training/README.md` — prepare/run/verifyと人間操作のコマンド、上限・再開。
- (NEW) `docs/references/reversi-ai-optimizer-comparison.md` — fixture/toolingと人間の完成結果を区別して記録。
- (MODIFY) 本計画・0018 — tooling完了と実比較完了を区別し、最終結果から次の手法へ接続。
- (DELETE) 本計画 — 人間の完成出力を独立検証し、改善/不成立の実結果と次の判断を残した後。

## 依存・後続

採用記録と本計画のPRをreview/mergeしてから、新しい`feat/trained-model-adoption-and-learning-followup`で実装する。
0019原本・0051 bundleは読み取り専用。教師再生成・新しい強い教師の導入・自動multi-cycleは本比較に含めない。
Egaroucidから参考にするのは[Adam等の方法](https://github.com/Nyanyan/Egaroucid/blob/v7.8.1/src/tools/evaluation/eval_optimizer_cuda.cu)であり、
教師データや重みの取り込みではない。
更新方式の実結果を受けて、採用済みproject AIによる複数cycle・多様な合法opening・phase別件数の
偏り補正・自前探索の強度を次の別計画で比較する。NNUEや特徴変更はその後の独立候補とする。
0018の開局freeze・受け入れは後続候補選定後まで行わない。

## 検証

- 手計算できる小表でAdamの勾配・bias correction・projection・丸めとbest checkpointを照合する。
- 現行Aのweight digest再現、同一入力/seedの再現とbatch途中/epoch境界の再開一致、変更設定/欠損state/NaN/境界違反の拒否。
- 全epochでfloat改善しても整数exportは改善しないfixtureが、改善認定/対戦を許可しないこと。
- disjoint split・D4/color・forced-pass/終局教師値と新規座席交換開局を検証する。
- mocked CLI/Oracleで対戦gate、省略件数、timeout fail-closed、phase/epoch/game receiptsの改変拒否を検証する。
- verifierはCLI/Oracle/新規学習を起動せず、保存入力とstate/出力からartifact・指標・判定を再構成する。
- 該当Python tests、Rust evaluator tests、`cargo fmt --all -- --check`、Clippy、GDExtension build、workflow lint、diff check。
- 人間操作結果は上限・全記録・profile・artifact identityを再検証する。未実行なら本計画を残す。

## Addresses

- N/A
