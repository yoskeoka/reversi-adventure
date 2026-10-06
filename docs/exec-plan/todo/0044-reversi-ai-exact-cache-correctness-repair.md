# 完全読み再利用の評価値と選択手を一致させる

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

0041の空き7・白手番の反例を短い回帰テストへ落とし、再利用時の値と選択手の不整合を修正する。
修正前で失敗し修正後で成功する再現、原因の説明、最善値と選択childの独立した値の一致までを
小さなPRで完了する。全局速度の改善、閾値の選択、本番再利用の再有効化は含めない。
0043の既定turnは保持する。修正後の明示game指定だけを0045の診断用に許可する。

## 参照と再現入力

- [0043の停止措置と短い検証](../../references/reversi-ai-exact-cache-correctness.md) —
  共有decision境界のturn固定、CLI game拒否、manifest v4と旧reportの検証境界。

- [PR #251の評価記録](../../references/reversi-ai-exact-threshold-reuse-assessment.md) — 完全な棋譜と4記録の照合。
- `rust/reversi-ai/src/search/endgame.rs:361-405` — `EndgameSolver::solve` のroot結果/PV。
- 同 `:567-580,789-830` — cached LowerBoundによる窓更新と`original_alpha`。
- 同 `:1336-1390,1587-1640` — null-window bound再利用とrepeated-rootの既存tests。
- 同 `:1134` — testsの `full_window_reference`。production PVSとは別のchild値検証。
- `rust/reversi-ai/src/search/mod.rs:167-240,312-320` — 共有decision/Advisor境界と消去。
- `docs/specs/reversi-ai.md:634-648,690-725` — proof/bound、手番視点、exact/PVの契約。
- `0043-reversi-ai-exact-cache-correctness.md`, `0045-reversi-ai-exact-cache-correctness-verification.md`。

標準初期盤面・黒先手から選択直前までの全53着手、passなし。

```text
c4e3f3g3f6c5g2f4e2f5h3h1f2g4h4h2g5h5g6e6f7d7d6c7c8h7h6g7h8d8e8c6g1e7d3f1e1b3b8b7a8b5b6b4c3d1d2c1c2b2f8g8a6
```

```text
..WWWWWW.WWWWWWW.WWBWWBW.WBWBWBW.BBBWBWWBBBBWWWB.BBWBWWBBBBBBBWB
```

白手番、空き7。測定条件は12/12/12・exact20。turnはa4/+4/399nodes、
gameはa7/+4/30nodesだった。独立完全読みはroot +4、a4のchildは白視点+4、
a7のchildは白視点+2。assignment違いの2件は同じ棋譜なので1反例として扱う。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 再利用したboundとrootの最善手/PVの証明条件を先に明示。
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs` と関連tests — 原因を再現した部分だけを修正。
- (MODIFY) `rust/reversi-ai/src/search/mod.rs`, `rust/reversi-ai/src/bin/reversi-ai-cli.rs` と関連tests — 診断gameの明示opt-in。既定turnは保持。
- (NEW) `tools/reversi-ai-benchmark/fixtures/exact-cache-counterexample-v1.json` — 棋譜、局面、証拠digest、短い再利用入力。
- (MODIFY) `docs/references/reversi-ai-exact-cache-correctness.md` — 原因、修正、旧/新結果と残る制約。
- (DELETE, 完了時) 本計画。

## ブラックボックス契約と作業

1. 棋譜を合法に再生して反例盤面/手番を確認し、PR #251の固定receiptとOracle queryを照合する。
   盤面をcold solveするだけの成功を再利用の再現として扱わない。
2. まず同じtableのnull-window探索で有効なboundを生成し、その後full-windowでrootを解く
   2呼び出しのfixtureを作る。窓[3,4]は原因候補であり、再現前に原因と断定しない。
   窓更新後の`original_alpha`、EXACT/LOWER/UPPERとPVの証明範囲を調べる。
   必要なら保存棋譜のWhite側9→7、11→9→7、13→11→9→7空きのsuffixを順に試す。
   通常testsに47手の深度12探索や8局対局を持ち込まない。13空き以下の固定fixtureでも
   再現できなければ、その未達と必要な追加再現作業を記録し、勝手に長い計測へ拡大しない。
3. root scoreだけでなく、選択手を適用したchildを既存の独立test helper
   `full_window_reference` で解き、root視点へ戻した値がroot scoreと一致することを要求する。
   保存Oracleのroot/a4/a7値も照合する。fresh production PVSだけを独立した正解にしない。
   PV長だけの検査で済ませず、合法PV、passの符号、boundの種別、未完了の扱いを確認する。
   最善値の証明と選択手の証明が揃わなければ`exact=true`を返さない。
4. 必要なroot/表参照/保存の処理だけを修正する。評価器、heuristic深度、cache容量、
   置換方針や対称性最適化を同時に変更しない。通常の探索順/tie契約を維持する。
5. 小さい回帰fixtureは修正前sourceで失敗、修正後sourceで成功することを残す。
   root +4だけでなく選択手の白視点値+4を確認する。元のa7/+2証拠は上書きしない。
   修正後gameは実験用明示opt-inと実効policyを記録し、共有AI/学習の既定turnは変えない。
6. 空き16の±39/±40という別の点数差は、この選択手不具合と混同しない。
   score契約やOracleとの違いが未解決なら残る採用阻害条件として記録する。
   この小さい修正の完了を、全設定の正確性/本番採用の完了に読み替えない。

## 依存関係と順序

- PR #251と0043のマージ後、spec→短い失敗再現→原因限定修正→同じfixtureの成功→PR。
- 固定receipt検証はofflineで行い、既存のroot/a4/a7の完成Oracle証拠を再利用する。
- 0045の長い計測は別PR・人間実行。0044の完了にその待機を含めない。

## 検証

- 有効なlower/upper boundからのfull-window root、異なるroot、pass、衝突/置換、timeout中断。
- 新しい回帰fixtureでroot値と選択child値、合法PV、完全読み完了状態を別々に検査する。
- 明示game/既定turn、共有AI境界のテスト。既存exact/通常探索の回帰を通す。
- 該当Rust/Python tests、Clippy、GDExtension build、workflow lint、diff check。
- Oracle同士対局、深度12の全局、閾値総当たりを実行しない。

## Addresses

- N/A
