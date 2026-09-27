# 探索 TT の手番側表現と盤面対称性を個別に評価する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

探索 TT の同値な局面を手番側/相手側の石配置で共有したときの効果を測り、さらに回転・反転 D4 正規化を加えた場合の効果を別に測る。どちらも着手、点数、完全読み、探索の中断条件を変えず、CPU 時間と peak RSS を含む同一ホスト比較で採否を判断できる証拠を残す。実験結果は、変更を採用しない場合も保存する。最終的な採用判断は人間に渡す。

Edax と Egaroucid の現行公開 source は手番側/相手側の bitboard を TT の局面 ID とし、幾何 D4 を TT の lookup に適用していない。参考実装の形を事実として記録し、D4 も有効だと仮定しない。

## 参照

- `docs/specs/reversi-ai.md:57-92,105-145` — 色相対評価、D4 特徴と探索の契約。
- `rust/reversi-ai/src/search/tt.rs:18-105` — 現行の黒/白/手番 Zobrist key と table。
- `rust/reversi-ai/src/search/negascout.rs:175-233` — 深さ/bound 判定と TT move ordering。
- `rust/reversi-ai/src/search/mod.rs:106-169` — evaluator/config fingerprint と探索。
- `rust/reversi-ai/src/eval/pattern.rs:190-207,240-298` — 特徴量用 D4 と色相対符号化。TT と同じ正規化ではない。
- `tools/reversi-ai-benchmark/positions-v1.jsonl` と `docs/references/reversi-ai-search-performance-0020-closeout.md` — 意味と時間の比較入力。
- Edax `src/board.c`, `src/hash.c`: https://github.com/abulmo/edax-reversi/tree/14f048c05ddfa385b6bf954a9c2905bbe677e9d3/src
- Egaroucid `src/engine/board.hpp`, `transposition_table.hpp`: https://github.com/Nyanyan/Egaroucid/tree/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/engine

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 先に TT identity、score 視点、対称手の逆変換、採否条件を規定する。
- (MODIFY) `rust/reversi-ai/src/search/tt.rs`, `search/negascout.rs` と関連テスト — 手番側表現 variant、D4 variant を互いに独立に切り替え可能な実験とする。
- (MODIFY/NEW) `tools/reversi-ai-benchmark/` と `docs/references/` — 同一ホスト raw samples、意味照合、各 variant の原因分析と結論。
- (MODIFY) `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md` — 採用が決まるまで実験 variant で新たな本番 manifest を凍結しない。

## ブラックボックス契約と作業

1. 現行 raw key を対照とし、(A) 手番側/相手側のみ、(B) A に D4 を追加、を独立に比較する。黒白を同時に交換した同値局面は A/B で同じ key とし、異なる手番の同一絶対盤面は混同しない。D4 の候補は常に合法座標へ逆変換し、pass、PV、bound、score 符号と exact/heuristic の区別を保つ。hash 衝突時は完全な局面 identity を照合し、誤 hit を許さない。
2. 各 variant は evaluator、探索設定、search semantics version、保持 table の失効条件を同じ方式で扱う。盤面正規化の計算費用、TT hit と有効 cutoff、node 数、time、CPU、RSS を分けて記録する。すでに採用した探索順や exact cache の状態を対照間で揃え、変更効果を混同しない。
3. 黒/白交換、D4 の8変換、pass、終局、同じ盤面で異なる手番、異なる evaluator、意図的な hash 衝突の局面で着手/点数/PV/完了深さ/完全読みが対照と一致する。独立 oracle の exact score も照合する。
4. 16 局 corpus の heuristic/exact と固定した全局自己対局で serial 比較する。採用候補には少なくとも一方の workload で 5% 以上の速度改善、他方の重大な後退がないこと、CPU/RSS の欠落がないことを求める。性能が基準を満たさなければ実験と結果を残し、採用コードにしない。基準を満たした場合も採用と PR の扱いは人間が決める。

## 依存関係と順序

- 0035 の全局計測と完全読み再利用後の固定実装を比較基点にする。0035 の長時間計測は人間が開始し、agent は監視しない。
- 手番側表現を先に測り、D4 の追加分はその差分として測る。個別の時間と RSS を同じ host/条件で記録する。
- 0037 の学習 pilot は選ばれた安定版のみを用い、実験 branch を入力にしない。

## 検証

- 同値変換の score/move/PV と衝突安全性、深さ/bound の既存契約を確認する。
- raw sample から集計を独立に再計算し、同一 host の serial 測定と差分の原因を report に記録する。
- 該当 Rust テスト、Clippy、GDExtension build、workflow lint、`git diff --check`。

## Addresses

- N/A
