# Egaroucidの公開パターン表学習を自前データで縮小再現する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了境界

成功例の学習工程を先に再現し、既存方式の局所改善だけを次候補にしない。
Egaroucidの固定revisionのパターン表・共有・数値精度・full-batch Adam・整数exportを
一式の方法として自前実装し、自前生成128局＋序盤最大256局面で
生成→学習→export→独立対戦→offline検証の1学習サイクルを回せるか確認する。
これは上流の学習済みモデルや強さの完全再現ではなく、規模を縮小した工程の再現である。

2026-11-01、人間は旧6案を見直し、この方式1本と128局＋序盤256局面の規模を選択した。
旧6案の丸め・初期値・phase等は再現条件と後日の原因分析へ移し、独立計画として提出しない。
本計画PRは計画と調査記録のみ。学習・対局・Oracle診断は開始しない。
merge後の実装は `feat/reversi-ai-next-method-experiments` でspecを先に更新する。

tooling実装PRは仕様・fixture検証・有界な操作手順・未実行の明示までとする。
実比較は人間が後日開始し、完成原本を別タスクで独立検証する。
未完なら残作業を本計画へ明記して保持し、工程の成功または有効な停止結果の独立検証・
結論記録後に本計画を削除する。fixture成功を実学習・実強度の証拠としない。
現在の0019採用モデルは維持し、0018受け入れは開始しない。

Addresses: N/A — 0018の次候補検討であり、strong-engine親issueを本試験では閉じない。

## 根拠・仮説と代替案

0053は7.0/20点で停止し、200局・Oracle対戦へ進まなかった。Adamのepoch13は
float/integer validationを改善せず、corpus regretは悪化、既存held-out MSEは微改善した。
原因は単独確定できない。0052は同じ3,364教師と既存の[-1,1]重み制約で
Adamだけを比較しており、公開方式の工程全体を実施したことにはならない。

仮説は「共有pattern table、raw32精度、出現回数に応じたfull-batch学習、
損失を見た整数化、複数prefix長と序盤の別教師生成を一組で実装すると、
現在と異なる学習サイクルが成立し、独立対戦で検討可能な候補を作れる」である。
複数要素が変わる方式全体の比較であり、効果を丸めやデータ量の一要因へ帰属しない。

代替案は旧6案の局所比較、少量データ向けpattern networkによる表展開、
Edax/Logistello等の別方式調査。人間は今回は表＋Adam方式1本を選択した。
公開wrapperの外部棋譜/教師や配布weightを使う案は採らず、教師生成をproject-ownedへ置換する。

## 正確な既存参照

- `docs/project-plan.md:23-27` — 名人程度・高速省メモリの目標。
- `docs/design-decisions/core-beliefs.md:1-6`、`docs/design-decisions/adr.md`
  （Tech Stack Selection）、`docs/design-decisions/2026-03-02-reversi-ai-design.md`
  （Adopted pattern-evaluator representation）。子repoにREADMEは存在しないため、
  workspace側の `docs/design-decisions/README.md` も確認した。
- `docs/references/reversi-ai-learning-method-reproduction.md` — 一次資料・工程比較・意図した差分。
- `docs/references/reversi-ai-optimizer-comparison.md:9-42` — 0052/0053の実結果・identity。
- `docs/references/reversi-ai-0019-adopted-model.md:13-41` — 現行artifactと原本identity。
- `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md`
  の `If the acceptance gate misses` — held-outと次候補の境界。
- `docs/exec-plan/todo/0037-reversi-ai-training-method-pilot.md`
  の `実pilotの完了結果` — 完了済みpipelineで、新手法の比較ではない。
- `docs/specs/reversi-ai.md:112-218,294-338` — 現行feature/artifact/runtimeと0053評価gate。
- `tools/reversi-ai-training/optimizer_compare_inputs.py:83-110` — `load_source`。
- `tools/reversi-ai-training/optimizer_adam.py:17-34,56-84` — 既存設定と単純整数export。新方式と混同しない。
- `tools/reversi-ai-training/reinforcement.py:452-482` — 現行整数一回更新。
- 上流revision `67aa89f18bfd22fa35730cdc0a9f4e7501c2239a`：
  `src/tools/evaluation/evaluation_definition_20241125_1_7_5.hpp:34-70,198-242`
  （model/scale/共有）、`eval_optimizer_cuda.cu:387-414,498-552,594-745`
  （Adam/split/count/停止/export）、
  `src/engine/evaluate_generic.hpp:515-525` （raw32総和のruntime変換）。
  URLは調査記録に固定する。説明中の7.7モデルや7.8.1配布weightと同じ学習runだったとは主張しない。

## 変更マップ（実装時）

- (MODIFY) `docs/specs/reversi-ai.md` — 新table32契約、生成・学習・評価・gate・資源・進捗・再開をコードより先に追加する。
- (MODIFY) `docs/design-decisions/adr.md` — 既存表現を置換せず新候補を隔離する設計判断を記録する。
- (NEW) `tools/reversi-ai-training/table32.py`、
  `table32_inputs.py`、`table32_optimizer.py`、`table32_verify.py` と対応tests。
  原本検証、prepare/run/verify、決定的CPU実装、整数化、独立再構成を担当する。
- (NEW) `rust/reversi-ai/src/eval/table32.rs` とtests。
- (MODIFY) `rust/reversi-ai/src/eval/mod.rs`、
  `rust/reversi-ai/src/bin/reversi-ai-cli.rs` — 明示的な別evaluator/loaderを追加。
  既存 `trained` artifactの契約、Godot/Playgroundの既定モデルは変えない。
- (MODIFY) `tools/reversi-ai-training/pilot.py`、`Makefile`、
  `tools/reversi-ai-training/README.md` — `table32 prepare|run|verify` と人間向け操作手順。
- (NEW) checkout外 `.local/reversi-ai-runs/0054-<run-id>/` — manifest/snapshot/receipt/checkpoint/report。
- (MODIFY) `docs/references/reversi-ai-learning-method-reproduction.md` — fixtureと後日の実比較を分けて追記。
- (DELETE) 本計画のみ、実出力の独立検証・結論記録後。他のtodo/issueや原本は削除しない。

## 再現仕様と意図した差分

### 1. モデル・数値表現・runtime

16種類のpattern tableを64対称配置で共有し、手番側石数featureを加えた65feature、
60phase、色相対三進code、反転indexの共有を固定revisionの定義に合わせる。
公開された配置と対応を仕様のcatalogへ列挙し、geometry/feature順・phase/反転mapのdigestをpinする。
コード・配布asset・weightをruntime依存として取り込まず、抽出/共有を自前実装する。
現行の8base×8変換＋盤面canonical化をそのまま同じモデルと呼ばない。

新identity `reversi-ai-pattern-table32-v1` はraw32のint16重み、
parameter範囲[-4091,4091]とint32以上の安全な総和を持つ。
raw値の特徴総和に正負付き16を足して32で0方向除算し、石差[-64,64]へclipする。
各tableを個別に石差へ丸めない。terminal/exact/search/protocolは既存winner-empty石差単位を維持する。
raw ±15→0、±16→±1、集計前後丸めの差、overflowとpassのphase不変を試験する。

CLIは明示的 `--evaluator trained-table32 --trained-artifact PATH` とし、
feature/scale/phase/score/provenance/digestを検証して失敗時fallbackしない。
artifact identityをTT contextに含め、旧trainedとcacheを共有しない。
既存format2を新形式として読み替えたり、既存artifactを上書きしない。

### 2. 凍結入力とteacher policyの実行可能性

原本0051/0019/0052/0053はread-only。原本manifest/report/receiptsと採用artifactをoffline照合し、
採用S0を `models/trained/0019-20261020-02.json`、
SHA-256 `13e8bdf59553746ba32ce47b53a09c011eb79223cabf4ddefb224b2640d283de` に固定する。
producerのclean commit、候補CLI、generator、学習実装、入力・設定を新manifestへpinする。

teacher policyは学習中Bではなく凍結S0、自前探索11/11/11・exact25・turn・book off。
序盤labelは同じS0の17/17/17・exact25による探索値を使う。
探索限界は300000ms/10000000 nodes、protocol timeout310秒。
これは上流と同じ強さを保証せず、自前teacherの質という明示的差分である。

大量生成前に、保存されたproject-owned合法棋譜から空き20/22/24/25を各3、
計12rootを結果を見ず決定的に選び、実際の両手番数を保存する。
合法な進行でその空き数に到達した手番を保ち、手番配分を揃えるための人工的色反転はしない。
不足なら生成に進まず停止する。自前exact25 decision12回が全て完全読み・合法・資源内であること、
各rootとselected childを独立Oracleで最大24query照合することを要求する。
OracleはEgaroucid7.8.1の専用full-solve profileでsource/binary/resources/argvをpinし、
book off・1thread・hash25・確率的枝刈りoff、root/childの残り空き数を完全に読む。
0018対戦profile exact12を流用しない。既存queryの再利用は同一設定・score契約のexact証拠に限る。
Oracleの値は診断だけで教師へ戻さない。
序盤label poolの先頭2rootも指定depth17の完了を確認し、完成labelは同じIDとして後で再利用する。
どちらも未完了なら `teacher-policy-infeasible` で停止し、depth/thresholdを黙って下げない。

### 3. 自前生成：128局＋序盤最大256局面

- master seed `2026110101`、用途/length/split/gameからSHA-256でstreamを分離する。
  prefix長はplacementsで12/18/21/24/30/40/50/58の8層。
  各層train12・validation2・test2局、合計96/16/16=128局。
  1prefixから1継続対局とし、標準黒先手からsorted合法手を一様抽出する。D4変換を別の独立局数に数えない。
- prefix後は凍結teacher policyで終局まで継続し、ランダム区間は教師から除外する。
  全対局logは保存し、教師はprefix終了後にpolicyが着手判断する非終端局面からのみ取る。
  全行へterminal winner-empty値を手番側視点で付ける。個々の局面のminimax正解値とは呼ばない。
  generation上限128 terminal games、1局120decision、採用教師全split合計15,360行。
- splitはgame生成前に固定し、canonical D4 board-and-sideの交差重複を全splitから除外する。
  除外ID・原本/採用keys・game・side・prefix長・phase別の数を保存する。
  空split・欠けたprefix層・非終局・不正手・資源超過で停止。失敗局を別の都合のよい開局へ交換しない。
- 序盤は標準初期盤面から0–11 placementsのunique到達局面を別poolとして収集する。
  決定的なseed付き合法prefix列を最大10,000本走査し、各occupied phaseの候補上限32、
  全体上限256root。各lengthの先頭1rootを先に確保し、残りはcanonical keyのseed付きhash順位で採用する。
  12個のlength全てが非空でなければ停止。pool原本・prefixと採用/除外根拠を保存する。
  depth17の完成探索値のみをそのrootの教師とし、timeout/浅いfallbackは採用しない。
- 序盤256は全列挙約束ではない。上流の11手全列挙からの明示的縮小である。
  序盤labelはtrain専用にし、train/validation共用を行わない。
  希少phaseで独立validationが作れない場合は `validation-unavailable` と明記し、
  train lossを独立評価と呼ばず、下記step上限だけで止める。
- 外部の棋譜・評価値・重み・公開学習データを教師に使わない。自前探索の序盤値とterminal教師は別source-kindで保存する。
  0051のrandom終局教師を新方式の教師へ混ぜてデータ量を補わない。

### 4. CPU full-batch Adamと整数export

各phaseを独立に学習し、全parameterをゼロ開始、f64のweights/m/v・stepを保存する。
抽出後の60phase全てにtrain行が必要で、欠ければ `training-phase-unavailable` で停止する。
未学習のゼロ表を黙って完成候補へ含めない。validationだけがないphaseとは区別する。
phase全trainを安定したrow順で走査し、scale32のtargetとclipしたpredictionの残差を
feature indexと反転indexへ集約する。同じindexに重なる場合も固定sourceの加算回数を再現する。
出現0は更新せず、出現数は元数とmin(50,count)の両方を保存する。
LR=`alpha/min(50,count)`、beta=.9/.999、epsilon=1e-7、
sourceどおりのbias correction位置・parameter limit・residual clippingを再現する。
mini-batch256、[-1,1] projection、gradientのbatch平均を混ぜない。
固定式は自前の小さい手計算fixtureと照合し、上流CUDAは実行・依存しない。

alpha初期値300、warmup off、validation悪化連続>100で停止、連続悪化10でalpha×0.7、
同値改善はcounter reset、各phase最大1,000 Adam stepとする。
alpha300は本縮小実験の固定選択であり、上流の実学習run値が確認済みとは主張しない。
float validationがないphaseは固定1,000stepで止める。step未完を成功checkpointとしない。
停止時weightsをexportし、best epochを選び直さない（上流loopにはbest復元がない）。

各phaseのexportはceil/floor候補を用意し、初期nearestからseed固定のparameter/反転index対を
切替え、clip込みの全train損失が非悪化なら採用する。
上流のwall60秒方式との差として、最大1,000提案（整数値しかないparameterへの空振りも数える）、
改善率停止は少なくとも100提案後に `improvements*100/tries <= 0.01` とする。
wall上限60秒へ先に達したら中断stateを保存して再開し、未完のartifactを採用しない。
上流のceilf/floorfによるf32変換を含む境界と反転pairの扱いをfixtureで固定する。
浮動小数点state、export表、runtime predictionは別digestを持つ。
CPU固定順・seed固定・step/提案上限は再現性とbounded実行のための意図した差分である。

### 5. 独立評価と完了・停止・続行

新test splitは学習・停止・exportに使わず、候補固定後に1回だけ測る。
既存validation/held-out/corpusは露出済みの参考診断で、重み・方式・seed・規模の再選択に使わない。
新testの小標本誤差やcoverageの欠落を必ず記録する。
0018 suiteは `not-yet-selected` を維持し、その局面・結果を一切使わない。
全opening/decision/terminal/教師/validation/test/corpus露出keysを後段0018へ渡す。

候補B対採用S0の100pair/200局計画を対戦開始前に固定する。
開局は合法で、学習・validation・test・corpus・既存比較/Oracle開局と
canonical D4 board-and-side rootが独立なものをseed別streamで生成する（pool試行10,000上限）。
各pairは同じ盤面・手番からseatだけを交換する。対戦中の偶然の中間局面一致は記録し、完成局を除外しない。
両者12/12/12・exact16・turn・book off、同じtime/node/資源上限にする。

初回20局で10点未満なら `not-improved-at-pilot-scale` で停止。
10点以上のときだけ人間の明示continueで同じ計画の残り180局を追加できる。
200局で>100点を `promising-at-pilot-scale`、100点以下を改善未確認とする。
MSEは対戦省略gateにしない。対戦のOracle診断は本計画では0局。
fixture、工程の完走、20局screening、200局の候補成績を別の状態としてreportに保存する。

12root preflight、128局、序盤label、全学習phase、export、許可された対戦段階、
offline再構成が上限内で完了すれば学習サイクルの成立を確認できる。
有効な資源停止・負の対戦結果も保存・検証して結論を記録する。
新artifactの自動採用や0018合格は行わず、完了済み0019 cycle/0037を再開しない。

## 資源・進捗・保存・再開

- 生成128局、序盤label最大256root（preflightの先頭2は内数）、preflight自前exact12decision、
  Oracle最大24query、各phase1,000step、export各phase1,000提案、比較最大200局。
  新しい学習cycleは1回だけとし、無制限反復や自動データ拡大はしない。
- child timeout310秒、RSS≤1,572,864KiB、producer RSS≤262,144KiB。
  学習はphase単位にstream/loadして上限を守る。run累積実行wallは72時間まで、
  同一root全attemptの累積を永続保存し、resumeでリセットしない。人間待ち時間は除く。
- prepareに実行commit・source/input/CLI/Oracle identity・seed・全設定・上限を保存する。
  人間がtimeout/phase再開点等を指定できる明示CLIを用意し、本計画の上限より大きい値は拒否する。
  input/source/binary/seed/学習・探索設定変更は新root。引き継げる完成単位だけを同一設定照合して参照する。
- phaseはinput-verification→teacher-preflight→generation→early-labels→extraction→
  phase-training→export→diagnostics→match20→explicit-match200→offline-verification。
  各phaseと完成game/label/Adam step/export提案をatomic receipt/checkpointで保存する。
  step checkpointはweights/m/v/count/alpha/counters/次cursor/RNGと前decessor digestを含む。
- 起動時に既知の各総数と上限を表示し、stderrへ
  `table32 phase=PHASE unit=UNIT completed=N total=T elapsed_seconds=S status=STATUS`
  をflushする。step/game/query/labelが完成単位で、通常出力は `--progress-every`
  正整数（既定1）、phase境界・停止・完了は常時表示する。protocol stdoutやdigestへ混ぜない。
- timeout、不正手、未完局、未完探索、非有限値、改変、split漏洩、資源超過は失敗として保存する。
  失敗を教師・負け・引分に読み替えない。failure.jsonにphase/unit/実効設定/理由/commit/ログdigestを残す。
- 再開はreceiptと意味を検証した連続完成prefixだけを再利用する。
  unfinished gameは同じopeningの初めから、unfinished step/export提案は直前atomic stateからやり直す。
  completed label/queryは完全な設定identityを再確認してskipする。過去attemptは削除・上書きしない。
- offline verifyは算術遷移、特徴、教師値、game合法replay、全出力/gate/reportを保存原本から再構成する。
  trainer/candidate CLI/Oracleをspawnせず、不足unitと再開phaseを提示する。
  人間用のprepare/run/resume/verifyコマンドは実装後の実CLIで確認しREADMEへ記載する。
  agentは本番runを起動・待機・監視しない。

## 大規模化は別計画

128局は工程成立を見る規模であり、十分な学習データ量を決める実験ではない。
4,000局や2,560局を強度の十分条件・最終上限にしない。
必要量はゲームの全局面数だけでは決められず、phaseごとの教師数・unique pattern coverage、
teacherの質、誤差・対戦成績の学習曲線と生成/学習コストを観測して判断する。

次の拡大判断用に、prefix/phase別のraw・dedup・採用数、非ゼロ/未観測/出現回数分布、
clip率、float/export/runtime誤差、全phase coverage、生成局/教師行あたりのwall/CPU/RSSを保存する。
今回の小標本から必要な最終局数を外挿しない。工程停止時は原因を直して同一方式を再検討し、
工程成立後は、独立評価を使い回さない学習曲線のためのデータ段階・予算・次のseedを
人間と相談して別のbounded計画にする。Bの勝敗だけで規模拡大を自動許可しない。

## サブタスク・依存・並列性

1. specとADRへ再現対象・意図した差分・新artifact/CLI・上限を定義する。
2. catalog/共有/数値変換とPython/Rust loaderを実装し、共通fixtureを照合する。
3. generator/split/label/preflightと、Adam/export/checkpointを実装する。
4. orchestrator/receipt/独立対戦gate/資源監視/offline verifierを接続する。
5. boundedな人間操作手順とfixture結果・本番未実施を記録して実装PRを準備する。
6. 後日、人間が開始したrunの完成原本を独立検証し、限界と次の判断を記録する。

1→2→3→4→5→6。2の契約確定後はgenerationとoptimizerのfixture整備を並行可能だが、
Git書込は直列。旧6案、pattern network、game-scope cache、大規模化の実行に依存しない。

## 検証

- 公開式に対する手計算Adam・count cap・clip・反転自己一致・patience/LR・整数化の境界fixture。
- Rust/Python共通のfeature/共有/scale/digest/prediction照合、旧artifact拒否とTT context分離。
- 全split/prefix層/上限、前半2label再利用、fallback拒否、root/child/passのwinner-empty、
  学習行0のphase拒否とvalidationのみ欠落の区別、
  seed固定、累積資源、改変/非有限値・未完了・設定変更・再開の試験。
- 9.5/20、10/20、100/200、100.5/200のgate、Oracle教師混入拒否、
  subprocessを禁止したoffline verify、連続/中断再開の同じartifact/report digest。
- 該当Python suite、engine/AI tests、workspace Clippy、fmt、GDExtension build、
  workflow lint、diff check。外部学習や実対戦は品質gateの前提にしない。
- 実run後は全棋譜・教師・算術・出力digestをoffline再構成し、工程の成立/停止と強度を区別して記録する。
