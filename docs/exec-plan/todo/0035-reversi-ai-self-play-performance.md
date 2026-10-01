# 自己対局の全局計測と完全読み再利用

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 2026-10-02 の到達点と再計画

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
2. [0040: 証拠の補完と設定選択](0040-reversi-ai-self-play-performance-closeout.md)
   — 変更前後の意味一致、局reset常駐条件の測定、序盤コスト分析、目標と採用判断を記録。
3. [0041: 空き20/24の完全読み再利用実験](0041-reversi-ai-exact-threshold-reuse-assessment.md)
   — 閾値16/20/24で局内turn/gameを比較し、上限付きpilot後に全局時間への効果を測る。
   0039の後に実行し、結果を0040の設定選択へ渡す。

プロセスが常駐しても、前の局の探索結果は利用しない。同じ局内の数手前の読みだけを
再利用する。旧persistent値は本来の性能採用証拠から外し、0039/0040で局reset条件を測る。

0040の証拠と人間の設定/時間予算判断がそろった時点で0035を削除する。
目安未達を合格と記録しない。追加最適化が必要なら観測した原因から別計画を作る。
新manifestの凍結と本番学習は0019/0037の責務とし、0035の完了と混同しない。

## 目的と完了条件

0019 の学習用自己対局を反復できる時間に短縮する。まず同一ホスト・同じ開局で Egaroucid 同士と project-owned CLI 同士の全局時間を独立に計測し、oracle の実測を基準に目標を固定する。目安は project-owned CLI 同士の 1 局 2–3 分だが、oracle の全局実測前に合否値として確定しない。深さ 12/12/12・残り 16 空き完全読みと、自己対局の中盤深さ 8・残り 16 空き完全読みを別条件として記録する。

完全読みの結果を次の手番でも有界に再利用し、選択手・点数・完全読み結果を独立 oracle と照合する。局あたり時間、CPU 時間、peak RSS、探索回数、完全読みキャッシュの利用状況を残す。停止済みの version-2 run の部分出力は候補証拠にせず、次の生産 run は新しい manifest で凍結する。

## 参照

- `docs/specs/reversi-ai.md:105-145,190-235` — 探索時間、学習用入力、0019 の自己対局と証拠。
- `tools/reversi-ai-training/reinforcement.py:204-252,430-524` — 常駐 CLI、自己対局、候補対戦、公開。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:151-224` — 1 プロセス・1 `SearchEngine` の対局プロトコル。
- `rust/reversi-ai/src/search/mod.rs:106-169` — 通常探索 TT の保持と完全読み solver の毎回生成。
- `rust/reversi-ai/src/search/endgame.rs:219-243,568-586` — 完全読み表の生成と hash 参照。
- `tools/reversi-ai-oracle/oracle.py:1443-1460,1469-1545` — 既存 oracle 自己対局と GTP session。
- `docs/references/reversi-ai-search-performance-0020-closeout.md:1-58` — 単独局面の計測。全局時間の基準ではない。
- Edax と Egaroucid は開発用外部 oracle とし、Rust/GDExtension/配布物には組み込まない。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 先に全局速度・正確性・資源上限・自己対局設定の black-box 契約を定める。
- (MODIFY) `rust/reversi-ai/src/search/mod.rs`, `search/endgame.rs` と関連テスト — コンテキスト分離、衝突確認、容量制限付きの完全読み再利用。
- (MODIFY) `rust/reversi-ai/src/bin/reversi-ai-cli.rs` と `tools/reversi-ai-training/reinforcement.py` — 既存 protocol と canonical artifact を保ったまま、全局の診断と自己対局専用の探索設定を固定可能にする。
- (NEW/MODIFY) `tools/reversi-ai-benchmark/`、Make target、`docs/references/` — oracle と CLI の全局比較手順、凍結入力、後から独立検証できる計測結果。
- (MODIFY) `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md` — 新しい生産 manifest は本計測と選択した自己対局設定の後に凍結する。

## ブラックボックス契約と作業

全局比較 corpus は標準の黒先手から到達できる固定 4 開局を両色の seat 割当で指す 8 局とする。

1. 同一ホストの固定された合法開局、色割当、バイナリ digest、評価 artifact、各探索条件と資源上限を凍結する。Egaroucid 同士、現行 CLI 同士、改善 CLI 同士の全局対戦を計測する。oracle 比較では全条件を同じ「1 seat につき 1 プロセスを 1 局だけ保持」の寿命にそろえ、起動/終了時間を別計測して探索中の時間と混同しない。加えて本番 runner と同じ CLI の全局間常駐を別の workload として測る。両色・pass・完全読みを含む位置を用意し、wall time、user/system CPU、peak RSS、各手時間と完了状態を記録する。並行ベンチマークの干渉を避け、結果が疑わしければ静かなホストで直列再計測する。長時間の本計測は人間が別 terminal で開始し、agent は起動・待機・監視しない。
2. 既存の完全読みは手番ごとに solver/table を再生成している。次の root でも再利用できる表を設計し、盤面と手番の完全な識別、同値な root 視点の点数、bound、最善手/PV、pass、異なる探索コンテキスト、hash 衝突、容量上限と置換を明示する。前回の未完了探索や不足した証明から完全読み結果を捏造しない。通常探索 TT の深さ判定は維持する。
3. 自己対局の手ごとの探索を、深さ 12 と中盤 8 の両条件で同じ入力から評価する。中盤 8 は学習用自己対局だけに指定でき、候補選択・0018 受け入れの探索設定と混同しない。選んだ条件・完全読み閾値・CLI digest は manifest/report に固定する。`prepare/run/verify` は不一致と旧 manifest の誤用を拒否する。
4. 同一探索設定の改善前後で着手・点数・完全読み結果を同じ盤面で照合し、完全読みは project-owned solver と独立 oracle の点数で一致を確認する。深さ 12 と中盤 8 の heuristic 着手は相互一致を要求せず、別 report にする。診断は flushed stderr または独立計測 report に出し、候補 protocol、棋譜、学習 artifact、既存 report digest には混ぜない。性能の採用理由として改善量と、何が時間を減らしたかを記録する。2–3 分目安と oracle 実測に届かない場合は、その理由と選べる設定を report に残し、時間だけを理由に探索の意味を変えない。

## 依存関係と順序

- 先に全局 oracle/CLI 基準と意味検証を作り、次に完全読み表を変更し、最後に同一ホストで比較する。
- TT の色・幾何正規化は 0036 の独立した実験で判断する。学習方法の pilot は 0037 で扱う。
- 停止済み version-2 run の部分出力をこの新しい性能測定の代わりにしない。

## 検証

- bounded table の容量、hash 衝突、同一/別 evaluator、pass、色、root 変更、timeout/interruption と置換の意味を確認する。
- 同一設定の同じ局面で最善手・点数・完全読み結果が改善前後で一致し、完全読み点数が独立 oracle と一致する。中盤 8 と 12 は別条件として記録する。
- 全局の raw timing と集計を再計算でき、wall/CPU/RSS 欠落は性能採用判定に使わない。
- 該当 Rust/Python テスト、Clippy、GDExtension build、workflow lint、`git diff --check`。

## Addresses

- N/A
