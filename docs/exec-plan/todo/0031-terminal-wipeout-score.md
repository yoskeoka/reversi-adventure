# Verify and correct search scores for early wipeout

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

盤面が埋まる前に片方の石が全滅し、白黒とも合法手がない局面で、
heuristic search と exact search が終局を検知し、評価器の推定値ではなく
確定した終局スコアを root 側の値として返すことを検証・修正する。
片方の石が 0 個でもう片方が 1 個以上ある終局は、石数・空きマス数に
関係なく勝者 `+64`、敗者 `-64` とする。例えば黒 63・白 0・空き 1 も、
黒 3・白 0・空き 61 も `+64` / `-64` になる。それ以外の終局は
従来どおり盤上の実石数差とし、両色 0 個は `0` とする。
`Game::score()` は引き続き盤上の実石数を返す。

## 既存の根拠

- `rust/reversi-engine/src/board.rs:72-76` の `Board::count` は盤上の石だけを数える。
  `rust/reversi-engine/src/game.rs:53-58` の `Game::score` も同じ値を返す。
  全滅スコアは search 固有の終局評価であり、この石数表示を変えない。
- `rust/reversi-ai/src/search/mod.rs:138-169` の `SearchEngine` は
  空きマス閾値で exact と heuristic の経路を選ぶ。
- `rust/reversi-ai/src/search/negascout.rs:57-72` は heuristic の
  root `GameOver` を `score: None` として返す。同ファイル `:134-142`
  は終局判定より先に深さ 0 で評価器を呼び、`:189-200` も途中終局で
  評価器を呼ぶ。
- `rust/reversi-ai/src/search/endgame.rs:253-265` と `:640-643` は
  exact 終局時に盤上の石数差を返す。同ファイル `:902-919` に
  1 マス空きの全滅盤面があるが、同じ計算を使う参照探索との比較のみ。
- `docs/specs/reversi-ai.md:490-525` は heuristic 無着手の無得点と
  exact 最終石差を規定している。全滅の ±64 はこの既存契約からの
  明示的な変更である。

## 変更対象

- (MODIFY) `docs/specs/reversi-ai.md` -- 全滅なら石数と空きマスに
  関係なく ±64、その他の終局なら実石数差という規則、root と探索内の
  終局、深さ 0 の優先順、`leaf_eval` の扱いを明記する。
- (MODIFY) `rust/reversi-ai/src/search/negascout.rs` -- 終局で評価器を
  呼ばずに実石数差を返す。深さ 0 の終局判定を評価より前に行う。
- (MODIFY) `rust/reversi-ai/src/search/mod.rs` -- 公開経路から heuristic と
  exact の途中全滅を検証する単体テストを追加し、既存の無着手テストを
  新しい終局スコア契約に合わせる。
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs` -- 終局スコアを
  全滅時だけ ±64 にし、1 マス空きの途中全滅について両色からの
  期待値を独立に固定するテストを追加する。
- (MODIFY) `rust/reversi-engine/src/game.rs` -- 最終手で全滅し空きマスを
  残したときの `GameOver` と表示用の実石数を検証する単体テストを追加する。
- (DELETE) この plan。検証と実装 PR 準備後に削除し、履歴から参照する。

## 実施順序

1. 全滅の ±64 とそれ以外の実石数差を spec に追加する。
2. 盤面に空きが残る全滅 fixture を `Game` と search のテストへ追加し、
   黒白双方の合法手が 0 であること、実石数、期待 ±64 を直接検証する。
   heuristic 経路は exact 閾値より空きが多い盤面とし、深さ 0 の
   終局を通る着手も含める。評価器に終局盤面を渡さないことを確認する。
3. `Negascout` の root と再帰の終局処理を修正する。パスは終局と
   区別し、予算中断時の既存 fallback と exact フラグを維持する。
4. exact の途中全滅に固定期待値を追加し、通常終局の実石数差と
   空盤面の `0` も検証する。関連する既存テストを更新する。

## 検証

- `cargo +1.98.1 test -p reversi-engine`
- `cargo +1.98.1 test -p reversi-ai`
- `cargo +1.98.1 clippy --workspace -- -D warnings`
- 適用される workflow lint と `git diff --check`。
- heuristic の GameOver に `score` と空の `leaf_eval`、exact の
  GameOver に `exact = true` と同じ ±64 が出ることを確認する。

## 依存・並行性

- `Game::score()` は表示用の石数として維持する単独修正。
  進行中の 0029、0030 の探索性能実験を取り込まない。

## Addresses

- N/A。
