# Verify and correct search scores for early wipeout

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

盤面が埋まる前に片方の石が全滅し、白黒とも合法手がない局面で、
heuristic search と exact search が終局を検知し、評価器の推定値ではなく
実際の石数差を root 側のスコアとして返すことを検証・修正する。
空きマスは石として数えない。例えば黒 63・白 0・空き 1 の終局は
黒から `+63`、白から `-63` になる。ゲームの `Game::score()` と
既存の exact score 契約に合わせる。

## 既存の根拠

- `rust/reversi-engine/src/board.rs:72-76` の `Board::count` は盤上の石だけを数える。
  `rust/reversi-engine/src/game.rs:53-58` の `Game::score` も同じ値を返す。
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
  exact 最終石差を規定している。前者を終局に限り改める。

## 変更対象

- (MODIFY) `docs/specs/reversi-ai.md` -- 終局時の実石数差、空きマスの扱い、
  root と探索内の終局、深さ 0 の優先順、`leaf_eval` の扱いを明記する。
- (MODIFY) `rust/reversi-ai/src/search/negascout.rs` -- 終局で評価器を
  呼ばずに実石数差を返す。深さ 0 の終局判定を評価より前に行う。
- (MODIFY) `rust/reversi-ai/src/search/mod.rs` -- 公開経路から heuristic と
  exact の途中全滅を検証する単体テストを追加し、既存の無着手テストを
  新しい終局スコア契約に合わせる。
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs` -- 1 マス空きの
  途中全滅について両色からの期待値を独立に固定するテストを追加する。
- (MODIFY) `rust/reversi-engine/src/game.rs` -- 最終手で全滅し空きマスを
  残したときの `GameOver` と実石数を検証する単体テストを追加する。
- (DELETE) この plan。検証と実装 PR 準備後に削除し、履歴から参照する。

## 実施順序

1. 実石数差と早期終局の観測可能な契約を spec に追加する。
2. 盤面に空きが残る全滅 fixture を `Game` と search のテストへ追加し、
   黒白双方の合法手が 0 であること、実石数、期待スコアを直接検証する。
   heuristic 経路は exact 閾値より空きが多い盤面とし、深さ 0 の
   終局を通る着手も含める。評価器に終局盤面を渡さないことを確認する。
3. `Negascout` の root と再帰の終局処理を修正する。パスは終局と
   区別し、予算中断時の既存 fallback と exact フラグを維持する。
4. exact の途中全滅に固定期待値を追加し、関連する既存テストを更新する。

## 検証

- `cargo +1.98.1 test -p reversi-engine`
- `cargo +1.98.1 test -p reversi-ai`
- `cargo +1.98.1 clippy --workspace -- -D warnings`
- 適用される workflow lint と `git diff --check`。
- heuristic の GameOver に `score` と空の `leaf_eval`、exact の
  GameOver に `exact = true` と同じ実石数差が出ることを確認する。

## 依存・並行性

- 既存の exact solver と `Game::score()` 契約を基準とする単独修正。
  進行中の 0029、0030 の探索性能実験を取り込まない。

## Addresses

- N/A。
