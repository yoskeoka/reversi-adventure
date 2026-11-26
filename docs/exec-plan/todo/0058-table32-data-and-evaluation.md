# table32の損失評価と序盤全局面・教師データ

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了境界

0056結合候補の全60 phaseについて実際の整数評価器のtrain/validation/test損失と
データ量・feature被覆を確認し、今後はvalidation/testの不足を検知して余裕を持って用意する。
人間がPlaygroundで試したところランダム打ちに近くStrategicEvaluatorより弱く感じた、
という観察は調査動機であり、厳密な対戦結果や原因確定ではない。

自前で到達可能な0–9手の全局面を決定的に列挙し、固定局面データを通常Gitに保存する。
スコア付けは別処理であり、当面0–9に限ってEgaroucidの版と設定を明記した探索値を教師に
使う。10–59の教師は自前生成を維持する。ラベルは別成果物として保存し、後から検証・交換できる。
現在の候補と0019採用モデルを変更せず、0018 acceptanceや採用判断と区別する。

本計画は仕様、可視化、列挙・ラベル付け・入力準備のtoolingと運用手順を対象とする。
実装時は小規模fixtureと既存保存結果のoffline分析、全局面の列挙・検証・Git保存まで行う。
大量ラベル生成、追加自己対局、実学習、独立対局は人間が別途開始する。小規模な実測も
人間が開始する。label実行の準備と復旧手順を提示し、処理済み局面を勝手に再生成しない。
実行後の改善の有無は別途記録する。0054の完了・採用・0018受け入れはこの実装完了から推論しない。

Addresses: N/A — 既存0018親課題の完了ではない。

## 方針変更と根拠

- 人間の2026-11指示は、0054のproject-owned teacher限定を **0–9のEgaroucidラベルのみ**
  更新する。既存0054 runとそのmanifest、receipt、結論は変更しない。既存の「外部評価値を
  教師にしない」specおよび0054計画との矛盾を、新規experimentの適用範囲と優先関係を明記し
  spec-firstで解消する。external engineを他phaseの教師や採用・0018 gateへ暗黙に広げない。
- Egaroucidの[技術解説](https://www.egaroucid.nyanyan.dev/ja/technology/explanation/)
  は対称形同一視で0–9の到達局面を1, 1, 3, 14, 60, 322, 1773, 10649, 67245, 434029
  と報告し、同エンジンは7.4.0 level 17で序盤11手をラベル付けしたと説明する。
  我々の集合は0–9のみ、計514097を独立実装で照合する。盤面・手番、pass、終局の定義差を
  明示し、単に件数を合わせるために局面を捨てたり重複させない。
- 既存7.8.1の[level定義](https://github.com/Nyanyan/Egaroucid/blob/v7.8.1/src/engine/level.hpp)
  ではlevel 21が既定で、序盤は深さ21・選択的探索。level 17より深いが品質や時間比は未測定。
  当面の初期案を7.8.1 level 21とし、version/levelはoperatorが選択可能にする。探索値を
  理論最善・完全読みの確定スコアと呼ばない。代表局面で時間・RSSを測定後、全体を見積もる。
- 現在の結合結果は20局で6点、`not-improved-at-pilot-scale`。phase10ではtrain 12局面に対し
  validation/testは各2局面、重み約61万のうち観測621で、十分な汎化を確認できない。
  直近の分析でphase10 testを参照したため、このsplitを次の最終holdoutに再利用しない。

## 正確な既存参照

- `docs/exec-plan/todo/0054-reversi-ai-next-method-experiments.md` — 元の教師制約と独立評価。
- `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md` — 予約openingsとacceptance。
- `docs/specs/reversi-ai.md:2119` 以降 — table32 pilot、部分学習・coverage・結合契約。
- `docs/specs/reversi-ai-table32-catalog.md` — phase/feature・重みの意味。
- `docs/references/reversi-ai-learning-method-reproduction.md` — 0054の由来とデータ方針。
- `tools/reversi-ai-training/table32_optimizer.py:58-78,155-177` の `loss`、`train_step` — floatと整数評価、
  lossが更新前・保存重みが更新後というstepずれ。
- `tools/reversi-ai-training/table32.py:446-574`、`table32_extract.py:36-67,137`、`table32_inputs.py:81-101`、
  `table32_combine.py`、`table32_verify.py` — 生成・split・report・結合・検証。
- `tools/reversi-ai-training/legacy_offline/training.py` のcanonical position keyと
  `rust/reversi-engine` の合法手、pass、終局。表現と合法性を横断確認する。
- `tools/reversi-ai-oracle/oracle.py`、`tools/reversi-ai-oracle/` — runtime/protocolとidentity。
- 完了 root `.local/reversi-ai-runs/0056-20261119-early-01`、
  `0054-20261114-phase10-19`、`phase20-29`、`phase30-39`、
  `0054-20261111-partial-01`、`0054-20261114-phase50-59`、
  `0056-20261119-combined-01`。原本および [PR #307](https://github.com/yoskeoka/reversi-adventure/pull/307)
  の保存物は不変。各rootを列挙する際、短縮表記の `phaseNN-NN` は `0054-20261114-` を補う。

## 実装順序と変更マップ

1. (MODIFY) `docs/specs/reversi-ai.md` と必要なcatalog/operational spec：以下の黒箱契約、
   自前限定の例外、既存結果の不変性、split・acceptance予約と保存先をコードより先に定義。
   (MODIFY) 0054計画に本計画への限定的な優先関係を追記し、履歴を書き換えない。
2. (NEW/MODIFY) `tools/reversi-ai-training/` にoffline phase別損失・被覆report/plot生成とtests。
   (MODIFY) `tools/reversi-ai-training/README.md`：既存root指定・欠測・成果物の読み方。
   保存済み0056の分析結果、machine-readable data、MSE/MAEの図と限界を
   `docs/references/` または識別可能な候補分析場所に記録する。
3. (NEW) `tools/reversi-ai-training/` に固定序盤集合の決定的generator/verifierとtests。
   (NEW) repo内の固定コーパス：phase別かつサイズ制限内の決定的shard、manifest、README。
   各shardの全件・digestを検証し、コーパスにはスコアを混ぜない。
4. (NEW/MODIFY) 0–9限定のEgaroucid label producer・fixture protocol・validator・
   dataset importer と運用文書。事前小規模測定、manifest、shard、再開可能なhuman-operated
   commandを用意し、既存teacherの条件を暗黙に差し替えない。
5. (MODIFY) `table32_inputs.py`・extraction・training入口とtests：将来の実験で
   train/validation/test量を独立指定し、phase別不足をfail-closedまたは明示的unavailableにする。
   固定0–9とEgaroucid labelを明示的に組み合わせて学習する経路を実装する。新runではphase 0も
   指定されたlabelを学習し、旧runの暫定ゼロを引き継がない。学習局面数・step・phase範囲・
   再開点を操作可能とし、未露出testや0018 acceptanceを偽装しない。
6. (MODIFY) `docs/references/reversi-ai-learning-method-reproduction.md` とoperator README：
   データ/スコア/学習/採用を区別、結果の保存と復元・予算・次の人間操作を記録。
   (DELETE) 本計画はtooling・列挙の検証とPR準備が終わった後。実ラベル生成や学習の実施を
   計画削除の根拠としない。新たな実験の結果確認が未完ならその別作業を明記して保持する。

## 黒箱契約と検証項目

### 現在の全phase損失

- 入力は結合candidate artifactおよび検証済み元rootとする。保存されたextracted rowsを使い、
  外部engine・trainer・対局を起動しない。phase 0の固定ゼロを明示する。
- 横軸phase 0–59、縦軸MSE（石差²）とMAE（石差）の別図。主系列は実際の結合済み整数
  artifactについてruntimeと一致する丸め・clip・手番視点で再評価したtrain/validation/test。
  浮動重みを使う場合は参考別系列とし、clip・単位を区別する。出力は画像と機械可読表で、
  phase/splitの件数、teacher由来、root、候補digest、欠測理由を含む。
- 0件はnull/欠測であり0誤差ではない。少数sampleやphase間の分布差を示し、損失のみで
  強さや学習十分を断定しない。観測・未観測feature/parameter数と出現頻度、train–validation–test
  の差も示す。referenceのEgaroucidとlabel・データ分布を混同しない。
- 固定fixtureで浮動/整数の各誤差を手計算と比較、結合artifactをphaseごとに照合、
  欠測・phase0・不正input・原本不変・再実行同値をtest。中間stepの曲線を併記する場合は
  既存保存lossと重みの1 stepずれを回避する。

### 十分な検証データと独立性

- 10–59の今後の新規runは各prefix/splitの局数をoperatorが指定し、暫定の初期設定として
  validation 32局・test 32局以上を各対象prefixに用意する。trainも独立設定可能。これは
  統計的な十分性の保証ではない。phase別の実行数、到達・unique数と偏り、重複排除後数を
  示し、指定最低数未満は成功扱いしない。所要時間・RSSを事前見積もりし、12時間程度の
  人間運用単位で分割・途中再開できる。設定はattemptに記録する。
- game単位でtrain/validation/testを分離、D4正規化した重複および同一局の漏洩を拒否。
  validationは学習制御、testはそのrunの診断。testをモデル設計に使った場合は後続の最終
  holdoutに再使用しない。独立対局（現在採用S0・StrategicEvaluator・ランダム打ちを別々に
  比較する条件、深さ・seed・先後・opening・時間）を準備し、Playgroundの体感は別の観察として残す。
- 極序盤はunique不足を固定閾値で隠さず実測する。0–9全局面をtrainに使う場合、同じ盤面を
  独立testと呼ばず、欠測または同一集合への当てはまりを明示し、未露出の後続局面・独立対局を
  併用。全列挙と0018予約が衝突しうるため、phase・prefix・露出を実際に照合し、必要なら
  予約を除くか別の独立acceptanceを計画する。固定コーパスの全収録と、予約を除いた学習用
  subsetは別に扱う。0018 suiteを学習や調整に流用しない。

### 全局面とEgaroucidラベル

- 初期盤から合法手を展開、D4対称同値と盤面・手番で重複排除。passは着手数を増やさず、
  終局・最短終局・手番を明示。全手数0–9の盤面を決定的順序で保存し、列挙規則・数・
  全体/shard digest・generator versionをmanifest化。検証は独立した合法性・対称性・
  同一性・再生成・既知件数、pass/終局・小盤面fixtureを含む。
- ラベル生成は別の未作成rootとshard群へ、入力局面IDに1対1で対応。教師version、source、
  runtime identity、level、探索/book/thread/hash等、timeout、scoreの手番/黒視点、石差規約、
  seed、バッチ範囲、進捗・失敗を記録する。CLIのスコア符号・単位、winner-empty変換、
  pass/終局と合法性はfixtureおよび少数の手計算局面で確認する。不明な値は変換を推測せず停止。
- 初期盤面を含むphase 0–9のlabel済み入力を新しいtraining runが読み、実際の手番・phaseに
  対応する表へ学習しexportする。labelが欠落した局面・phaseは暗黙にゼロや旧自前教師で
  補完せず、欠測として停止または明示的に対象外とする。旧固定ゼロの成果物はそのまま保存し、
  fixtureでphase 0の非ゼロlabelがlossと出力に反映されることを検証する。
- まずphaseを層別した少数の代表局面で人間がlevel21の時間とRSSを計測し、未完了・timeoutも
  記録、全体時間と機械的な不確実性を見積もる。level17との比較は任意の独立測定であり
  勝手なlevel変更はしない。無期限の一括投入を行わず、完了shardをatomicに保持し、
  attempt秒数・対象範囲・並列度・resumeをoperatorが選択可能とする。
- 実行物の版/入力のidentityは新runに記録するが、過去runのcommitや旧binary digestへの一致を
  新run開始の条件にしない。開始・resume・verify・combineのいずれも、現在checkoutのHEADと
  過去のbuild/producer commitとの一致を要求しない。commitは来歴情報として記録する。
  同一runのresume時はそのrunに凍結された設定と入力を検証し、
  変化時は既存成果を保持して新rootまたは明示的な互換回復を使う。

### 保存・実行予算

- 完成した評価エンジン用modelと0–9の固定局面データは通常Gitに保存。採用とは区別する。
  ラベルはversion/level別に、まず通常Gitで扱えるbatch別圧縮に保存し、再生成した結果で
  旧出力を上書きしない。
- 途中の局面・棋譜などは、まずphase/batch別に圧縮・分割してpushし、manifestとdigestで復元可能に
  する。通常Gitのshardは50 MiB未満を目標とし、100 MiB超は分割する。サイズ限度や総容量等で
  無理ならGit LFS、なお無理ならlocalまたは別storageを検討し、選択と
  復元手順・未保存範囲を記録する。LFSへの自動移行や有料契約は行わない。既存PR #307は保持。
- batch生成やlabel付けは既知総数・完成単位・現在phase/件数・経過時間・statusを出し、
  出力頻度とattempt壁時計・RSSを選べる。固定入力・設定と完成済みunitを再開時に保持。
  中断・資源超過・不足・非互換・不正scoreのfixtureをtestし、実学習や大量ラベルは人間が開始。

## 検証とPR

- spec更新が実装より先、docsの整合・既存0054/0018境界・生成器とsplit/label/plotのfixture。
- 全局面の各phase件数、合計、hash、合法手・対称性、shard復元の独立検証を記録。
- 保存済み候補で全phase report/plotを作成し、代表phaseを別計算と照合し、元rootを変更しない。
- 関連 `test_table32*.py`・新規tests、適用するlint、`git diff --check`、workflow lint。
  PRには人間が実施する小規模level21測定とその後のbatch実行・resumeを記し、未実行を明示。
