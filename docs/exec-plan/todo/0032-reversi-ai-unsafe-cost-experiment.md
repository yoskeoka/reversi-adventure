# Execution plan: measure whether unsafe improves Reversi AI implementation cost

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

PR #216 の Rust 実装コスト改善とは独立して、探索の意味論を変えない小さな
`unsafe` 候補を次のセッションで検証する。候補ごとに境界検査が release
最適化後も残ること、前提条件を局所的に証明できること、安全な同等実装に対して
実測で大きな追加利益があることを確認する。現時点で採用する `unsafe` は決めない。

完了条件は候補ごとの codegen・安全性・結果一致・elapsed/CPU/peak RSS の
再実行可能な report と、採用または見送りの根拠を PR に残すこと。
`unsafe` 固有の利益は同一アルゴリズムの safe 版に対して、
`heuristic-depth-12` または `exact-16` の局面別 median 比の幾何平均で
`<= 0.95` を目安とする。最新採用済み `main` に対する最終候補も同じ 5% gate
を満たし、両 workload の結果、CPU、RSS と悪化を全て報告する。閾値を
満たしても自動採用せず、変更の危険と利益を人間が判断する。
見送る場合も実験 commit と report は残し、勝手に破棄・PR close しない。

## 現状と候補

- PR #216 の 0031 は安全な ordering 改善と CPU/RSS 付き比較器を用意した。
  固定 16 局面・5 反復の候補/基準 elapsed 比は通常探索
  `0.9406831253153776`、完全読み `0.9918580986140435`。
  [比較 report](https://github.com/yoskeoka/reversi-adventure/pull/216) は
  `docs/references/reversi-ai-rust-cost-0031-comparison.json` にあり、
  `unsafe` の効果は測っていない。PR #216 は本 plan 作成時点で未 merge。
- `rust/reversi-ai/src/search/tt.rs:73-112` の `TranspositionTable::new`、
  `probe`、`store` は `capacity` で割った添字から `entries` を参照する。
  公開 `new(0)` は現在構築できるため、`entries.len() == capacity > 0`
  は現状の不変条件ではない。最初に容量 0 を入口で拒否するか、
  `probe` / `store` が安全に処理するかを仕様化し、容量 0 の回帰テストを
  加える。その上で最適化後に bounds check が残るか、TT コストに
  寄与するかを調べる候補である。
- `rust/reversi-ai/src/search/endgame.rs:35-78` の
  `EmptyRegions::assign`、`after_placement`、`is_odd` は 64 要素配列を
  bit index で参照する。`trailing_zeros` は非ゼロ mask から 0..63 と
  導けるが、`Position::bit_index` 側の有効範囲は公開型の構築経路を含めて
  別途証明する必要がある。証明できなければこの候補を使わない。
- `rust/reversi-ai/src/eval/pattern.rs:240-256` と
  `rust/reversi-ai/src/eval/trained.rs:156-171` の特徴抽出は診断上重いが、
  現行の tiny artifact は代表的な本番 workload ではない。trained 側の
  `unsafe` は本 plan の採否対象から外し、代表 artifact が揃った後の
  別評価に委ねる。
- `docs/specs/reversi-ai.md:331-419` は profiler の結果投影と
  `heuristic-depth-12` / `exact-16` の比較契約を定める。PR #216 merge 後は
  elapsed に加え子プロセス単位の CPU と peak RSS、および保存 report の
  検証が利用可能になる。

## 変更対象と契約

- (MODIFY) `docs/specs/reversi-ai.md` -- コードより先に、`unsafe` の有無で
  公開結果、評価値、探索順、node accounting、TT 容量・置換、exact score、
  PV、期限切れ時の結果が変わらないことを黒箱契約に明記する。性能の採否は
  固定 corpus と測定値で判断し、CI に速度閾値を置かない。
- (MODIFY, 診断で選ばれた場合のみ) `rust/reversi-ai/src/search/tt.rs` または
  `rust/reversi-ai/src/search/endgame.rs` -- 前提を証明できる最小の hot path
  一箇所だけに限定する。各 `unsafe` block に英語の `// SAFETY:` で
  配列長、添字範囲、初期化、aliasing/lifetime の根拠を記す。公開入力や
  将来の容量変更で破れる不変条件に依存させない。
- (MODIFY, 必要な場合のみ) 対象 crate の focused tests と
  `tools/reversi-ai-benchmark/` -- 境界、pass、TT collision、期限切れ、
  cancel、report の一致と失敗条件を補強する。測定器自体の変更は
  `unsafe` 実装と別 commit にする。
- (NEW) `docs/references/reversi-ai-unsafe-cost-0032.md` と必要な
  機械可読 report -- baseline / safe 対応版 / unsafe 版の source・binary
  digest、codegen、計測環境、両 workload、CPU/RSS、採否根拠を残す。
- (DELETE) この plan -- 実装・検証・PR 準備後に削除し、PR/Git history
  から追跡する。

## 実行順序

1. PR #216 の計測器が merge された最新 `main` から、新しい
   `feat/reversi-ai-unsafe-cost-experiment` worktree を作る。PR #216 の
   候補採否や、0029/0030 の変更が先に進んだ場合は、最新採用済み `main`
   の SHA を baseline として固定し直す。0032 は 0031・0020 の完了条件に
   追加しない。corpus を再生成せず、`positions-v1.jsonl` の SHA-256
   `5831839527b433b4b92c314331b9f0e613d98e0f82b9b6edb725f8bd6cb97ff8`
   と `make benchmark-corpus-verify` を確認する。
2. Rust 1.98.1 の同じ release profile / target / flags で TT と
   EmptyRegions の最適化後コードを調べ、残存 bounds check、呼出頻度、
   現行診断での費用を記録する。診断 instrumentation と microbenchmark は
   候補選択に限り、採否用 timing には使わない。check が消えている、
   hot path ではない、または安全性の不変条件を証明できない候補は見送る。
3. 残った一箇所について safe 対応版と `unsafe` 版を別 commit/binary で
   作る。両者の探索処理、データ構造、割当、分岐、結果は揃え、`unsafe`
   以外の改善を利益に混ぜない。`get_unchecked` 等の前提を境界値と型の
   全生成経路から検証し、release codegen の差分を記録する。TT を選ぶ
   場合は公開 `new(0)` の扱いと回帰テストを safe / unsafe の両版へ同じく
   適用し、その API 変更の費用を `unsafe` 固有の利益に混ぜない。
4. fixed-node の baseline / safe / unsafe で通常探索と exact の
   outcome、score、PV、completed depth、exact、node 数、実行順 trace
   digest を照合する。pass、TT collision、期限切れ、cancel も対象。
   一つでも異なれば cost-only 候補としての採否を止める。
5. instrumentation 無しの release binary を同一 Linux host、同じ
   power policy、低い背景負荷で直列比較する。16 局面それぞれ fresh
   engine、binary ごとに warm-up 1 回、交互順に 5 measured 反復以上。
   safe vs unsafe と最新 `main` vs 最終候補を分けて報告する。
   各比較は 160 sample / 80 pair の全件成功、time-only の要求 depth
   完了、全公開結果・node 数一致を要する。
6. 局面別 elapsed と CPU median 比の workload 別幾何平均、peak RSS の
   binary/workload 別最大、悪化、測定区間、host/toolchain/flags/digest を
   残す。CPU または RSS 欠測、timing 失敗、結果不一致なら fail closed。
   `unsafe` の追加利益が `<= 0.95` に届かない場合は採用しない。
   候補を提示できる場合も、安全性の証明と全資源値を添えて人間の判断へ
   渡す。

## 依存と検証

- 実装開始の依存は PR #216 の計測器の merge。0029/0030 とは並行して
  診断できるが、同じ host の timing は直列で行い、採用済み変更を含む
  baseline に更新する。
- `cargo +1.98.1 test -p reversi-ai`、workspace Clippy、GDExtension
  build、`make benchmark-corpus-verify`、workflow lint、
  `git diff --check`。必要なら Miri 等の動的検査を補助に使うが、
  不変条件の証明や独立の結果照合の代わりにしない。
- 保存 report の schema/digest 検証を行う。計測不能時に CPU/RSS を
  推測で埋めない。候補なしなら診断と見送り理由のみを成果物にする。

## Addresses

- N/A。新しい追跡 issue はない。
