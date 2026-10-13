# 自己対局の全局計測と完全読み再利用

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 2026-10-14: efficiency8 closeoutと残作業

2026-10-13の[0040 closeout](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md)
で8/8/8・exact16・`turn`・StrategicEvaluatorの固定サンプルが完了した。
平均は3.7699秒、nearest-rank P95は8.0750秒。132個のexact局面を252回のOracle queryで照合し、
すべてexactで、保存reportも検証済み。このprofileではTrainedEvaluator学習前に探索器や
対局ハーネスを広く高速化する必要はない。TrainedEvaluator自体の評価コストと学習batch総時間は測っていない。

0035で残る論点は、学習方法が選ぶ閾値でのexact tableのgame-scope再利用の効果である。
`turn`はexact tableの範囲であり、通常探索のTTはすでに同一対局内の手番間で再利用される。
game-scopeの診断機能は残し、本番のexact16/`turn`は維持する。既存のexact20比較から、
exact開始をさらに早めた閾値、たとえば空き30での効果は判断できない。0037または該当する学習計画で
閾値が決まった後、同一局面のturn/game比較を行う価値を判断し、行う場合はrootと選択childを
独立Oracleで検証する。それまでは広い速度改善を始めず、game-scope再利用の有効・無効も断定しない。
0035はその閾値が決まるまで待機する親計画であり、現時点で追加計測を実行しない。
比較が必要になった場合は、対象局面・件数・資源上限を定めた子計画を先に作る。

## 2026-10-06 の正確性修正と計測縮小

PR [#251](https://github.com/yoskeoka/reversi-adventure/pull/251) の0041結果には、
同じ棋譜の終盤空き7で、再利用ありだけが最善値+4を報告しながら値+2の手を返す反例がある。
閾値16を含む再利用全般の採用を保留し、深度8の固定棋譜の成功でこの反例を打ち消さない。

後続は [0043: 手番間再利用停止](0043-reversi-ai-exact-cache-correctness.md) →
[0044: 小さい正確性修正](0044-reversi-ai-exact-cache-correctness-repair.md) →
[0045: 縮小検証](0045-reversi-ai-exact-cache-correctness-verification.md) →
[0040の完了記録](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md) と進んだ。
新しい全局比較は12/8/12・exact20のturn/game各3局、計6局・反復1回に限る。
Oracle同士と現行CLIの既知時間を取り直さず、独立Oracleは既存queryを優先し少数終盤位置だけを照合する。
元の8局/v1/v2契約と14reportは不変証拠として残す。

以下の到達点と元の手順は歴史的契約。0043/0044/0045/0040の実施内容は各PRと
[0040の完了記録](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md)を参照する。
現在の残りの範囲は冒頭の閾値別game-scope評価だけとし、全深度や常駐方式の総当たり、
序盤8rootの追加計測は行わない。

## 2026-10-02 の到達点と再計画

以下は2026-10-02時点の状態を残す履歴であり、現在の状態は冒頭の更新に従う。

本計画は未完了。PR [#236](https://github.com/yoskeoka/reversi-adventure/pull/236) と
[#246](https://github.com/yoskeoka/reversi-adventure/pull/246) はマージ済みで、
深度12/8それぞれの全局5条件、turn/game比較、独立完全読み照合の計14レポートを
現行mainの検証器で再検証した。測定準備や失敗したturn-8の再測定は完了済み。
詳細・入力/report digest・残る証拠の限界は
[結果レビュー](../../references/reversi-ai-whole-game-0035-results.md) に記録する。

| 区分 | 状態 |
| --- | --- |
| 有界な完全読み表、衝突/コンテキスト分離、CLI診断、自己対局専用設定 | #236で実装済み |
| 合法forced passの計測/検証 | #246で修正済み |
| 同一ホストの深度12/8全局wall/CPU/RSS | 各条件8局、10レポート検証済み。旧常駐は局間cacheありの参考値 |
| turn/gameの同一盤面・着手・点数・深度・exactness | 442/408 decisionが一致、比較2レポート検証済み |
| gameの完全読みと独立Oracle | 138/98位置が一致、照合2レポート検証済み |
| 変更前CLIとの点数・exactness一致 | legacyは診断なし。着手列一致だけ確認済み、残作業 |
| 局間cacheを消去する常駐条件 | 未測定。旧常駐は深度8の2/8局で着手列が変化 |
| 性能目標、採用理由、自己対局設定の選択 | 未確定。game平均1017.8/415.7秒、2–3分目安未達 |
| 1局保存・中断再開・固定入力script | 現scriptは8局単位で保存。新要件として残作業 |
| 次の本番manifest | 未凍結。0037 pilotと0032入力検証も必要 |

深度8条件のdecision時間の約95.4%は序盤深度12に費やされ、完全読みは8局で
約5.1秒。turn/gameのwall短縮0.37/0.61%だけを大幅高速化や採用確定の理由にしない。
中盤深度を下げても序盤コストが残るため、次は序盤の評価/探索コストを調べる。

以下の子計画へ残作業を移す。この親にある元の変更マップと手順は当初の契約を
残したもので、実装済み範囲を再実装しない。実行は子計画の変更マップに従う。

1. [0039: 計測の1局保存と再開](0039-reversi-ai-whole-game-resumable-measurement.md)
   — 固定パラメータscript、局単位checkpoint、検証済み条件skip、局開始時の通常TT/完全読み表reset。
2. [0040: 証拠の補完と設定選択](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md)
   — 固定8局と全exact局面のOracle照合、性能判断を記録。完了済み。
3. [0041の評価結果](../../references/reversi-ai-exact-threshold-reuse-assessment.md)
   — 閾値16/20/24の実験は完了。空き20・中盤深度8の固定8局は照合成功したが、
   深度12設定の終盤完全読みに再利用ありだけの選択手不一致がある。
   結果と採用前の正確性修正を0040へ渡す。計画は[実装PR #251](https://github.com/yoskeoka/reversi-adventure/pull/251)で取得する。

プロセスが常駐しても、前の局の探索結果は利用しない。同じ局内の数手前の読みだけを
再利用する。旧persistent値は本来の性能採用証拠から外し、0039/0040で局reset条件を測る。

0040の証拠と人間の設定/時間予算判断は完了した。0035は閾値別game-scope評価の要否を
学習方法の選択後に決めるまで残す。追加最適化が必要なら観測した原因から別計画を作る。
新manifestの凍結と本番学習は0019/0037の責務とし、0035の完了と混同しない。

## 目的と完了条件

元の全般的な学習前高速化目標は、8/8/8・exact16・`turn` の固定profileで
0040のcloseoutにより判断済みである。3.77秒の平均と8.08秒の観測P95から、
このprofileに対する中盤探索最適化は現時点で必要としない。

現在の残りの目的は、学習方法がexact閾値を決めた後に、その閾値でexact-tableの
game-scope再利用が性能上有効かつ正確かを判断することである。候補閾値が30空きなら
その条件を対象にし、同じ局面・探索条件でturn/gameを比較し、時間と資源を記録する。
root・選択childを独立Oracleで検証する。採用を決めるまでproductionはexact16/`turn`を維持し、
診断機能は残す。単局面のTrainedEvaluator評価時間や学習batch総時間は別途測定する。

## 参照

- `docs/specs/reversi-ai.md:105-145,190-235` — 探索時間、学習用入力、0019 の自己対局と証拠。
- `tools/reversi-ai-training/reinforcement.py:204-252,430-524` — 常駐 CLI、自己対局、候補対戦、公開。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:151-224` — 1 プロセス・1 `SearchEngine` の対局プロトコル。
- `rust/reversi-ai/src/search/mod.rs:106-169` — 通常探索 TT の保持と完全読み solver の毎回生成。
- `rust/reversi-ai/src/search/endgame.rs:219-243,568-586` — 完全読み表の生成と hash 参照。
- `tools/reversi-ai-oracle/oracle.py:1443-1460,1469-1545` — 既存 oracle 自己対局と GTP session。
- `docs/references/reversi-ai-search-performance-0020-closeout.md:1-58` — 単独局面の計測。全局時間の基準ではない。
- Edax と Egaroucid は開発用外部 oracle とし、Rust/GDExtension/配布物には組み込まない。

## 旧変更マップ（現行scopeではない）

- (MODIFY) `docs/specs/reversi-ai.md` — 先に全局速度・正確性・資源上限・自己対局設定の black-box 契約を定める。
- (MODIFY) `rust/reversi-ai/src/search/mod.rs`, `search/endgame.rs` と関連テスト — コンテキスト分離、衝突確認、容量制限付きの完全読み再利用。
- (MODIFY) `rust/reversi-ai/src/bin/reversi-ai-cli.rs` と `tools/reversi-ai-training/reinforcement.py` — 既存 protocol と canonical artifact を保ったまま、全局の診断と自己対局専用の探索設定を固定可能にする。
- (NEW/MODIFY) `tools/reversi-ai-benchmark/`、Make target、`docs/references/` — oracle と CLI の全局比較手順、凍結入力、後から独立検証できる計測結果。
- (MODIFY) `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md` — 新しい生産 manifest は本計測と選択した自己対局設定の後に凍結する。

## 旧契約と作業（歴史的・現在の範囲は冒頭を参照）

全局比較 corpus は標準の黒先手から到達できる固定 4 開局を両色の seat 割当で指す 8 局とする。

1. 同一ホストの固定された合法開局、色割当、バイナリ digest、評価 artifact、各探索条件と資源上限を凍結する。Egaroucid 同士、現行 CLI 同士、改善 CLI 同士の全局対戦を計測する。oracle 比較では全条件を同じ「1 seat につき 1 プロセスを 1 局だけ保持」の寿命にそろえ、起動/終了時間を別計測して探索中の時間と混同しない。加えて本番 runner と同じ CLI の全局間常駐を別の workload として測る。両色・pass・完全読みを含む位置を用意し、wall time、user/system CPU、peak RSS、各手時間と完了状態を記録する。並行ベンチマークの干渉を避け、結果が疑わしければ静かなホストで直列再計測する。長時間の本計測は人間が別 terminal で開始し、agent は起動・待機・監視しない。
2. 既存の完全読みは手番ごとに solver/table を再生成している。次の root でも再利用できる表を設計し、盤面と手番の完全な識別、同値な root 視点の点数、bound、最善手/PV、pass、異なる探索コンテキスト、hash 衝突、容量上限と置換を明示する。前回の未完了探索や不足した証明から完全読み結果を捏造しない。通常探索 TT の深さ判定は維持する。
3. 自己対局の手ごとの探索を、深さ 12 と中盤 8 の両条件で同じ入力から評価する。中盤 8 は学習用自己対局だけに指定でき、候補選択・0018 受け入れの探索設定と混同しない。選んだ条件・完全読み閾値・CLI digest は manifest/report に固定する。`prepare/run/verify` は不一致と旧 manifest の誤用を拒否する。
4. 同一探索設定の改善前後で着手・点数・完全読み結果を同じ盤面で照合し、完全読みは project-owned solver と独立 oracle の点数で一致を確認する。深さ 12 と中盤 8 の heuristic 着手は相互一致を要求せず、別 report にする。診断は flushed stderr または独立計測 report に出し、候補 protocol、棋譜、学習 artifact、既存 report digest には混ぜない。性能の採用理由として改善量と、何が時間を減らしたかを記録する。2–3 分目安と oracle 実測に届かない場合は、その理由と選べる設定を report に残し、時間だけを理由に探索の意味を変えない。

## 依存関係と順序（旧作業履歴）

- 先に全局 oracle/CLI 基準と意味検証を作り、次に完全読み表を変更し、最後に同一ホストで比較する。
- TT の色・幾何正規化は 0036 の独立した実験で判断する。学習方法の pilot は 0037 で扱う。
- 停止済み version-2 run の部分出力をこの新しい性能測定の代わりにしない。

## 検証（旧作業履歴）

- bounded table の容量、hash 衝突、同一/別 evaluator、pass、色、root 変更、timeout/interruption と置換の意味を確認する。
- 同一設定の同じ局面で最善手・点数・完全読み結果が改善前後で一致し、完全読み点数が独立 oracle と一致する。中盤 8 と 12 は別条件として記録する。
- 全局の raw timing と集計を再計算でき、wall/CPU/RSS 欠落は性能採用判定に使わない。
- 該当 Rust/Python テスト、Clippy、GDExtension build、workflow lint、`git diff --check`。

## Addresses

- N/A
