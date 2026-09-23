# Child plan: refine search-owned PV storage after 0023

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

親計画 0020 の二つの workload で、探索中に必要な PV を保持する方法と、
compact な exact table から不足した経路だけを補う方法を分離して評価する。
棄却した 0023 の結果は、固定容量表と後段の PV 再探索を組み合わせた
PR #200 の実装結果であり、探索所有の storage 全般の否定とは扱わない。
開始点は採用済み変更のみを含む最新 `main` とし、PR #200 を丸ごと
取り込まない。PR #200 のコード・状態の変更はこの計画に含めない。

公開結果の条件は「exact スコア、合法な着手だけからなる終局までの PV、
パス、最終石差、同点時の決定性が整合すること」である。スコア確定後の
二回目の探索は条件ではなく、経路を失った場合の実装選択肢の一つとする。
時間切れ・キャンセル時は従来の合法 fallback または完了済み結果だけを
返し、未完成の exact スコアや PV を出さない。

候補ごとに完全な意味論検証を行い、最終候補だけを同一ホストの release
wall-clock 比較で判定する。各 workload は独立に報告し、親計画の
「どちらかで geometric mean 5% 以上改善」を採用の性能条件とする。
CPU time と peak RSS も実測・報告し、増加する場合は採用前にその
トレードオフを明示する。node 総数は診断値のみで、資源上限や採用条件に
しない。所定の条件を満たさない結果も不変の report として残す。

## 既存の根拠

- [PR #200](https://github.com/yoskeoka/reversi-adventure/pull/200)
  (`f1c87a2b99988e493c4755d619c771c1956f3e80`) は 0023 の候補実装。
  `rust/reversi-ai/src/search/negascout.rs:18-57` の PV scratch は pass で
  ply が増える境界を未検証。`rust/reversi-ai/src/search/endgame.rs:8-50`
  は毎回 `2^21` table slots を初期化し、同ファイル `:253-304` は
  root score の確定後に exact PV を再探索する。
- `docs/references/reversi-ai-search-performance-0023.json` は PR #200 の
  5 反復 report (SHA-256
  `434df787dab03b52a0755f84aa5071041d0a4a972d87223ecf518bfb1da1b791`)。
  heuristic-depth-12 は `0.967535169107137`、exact-16 は
  `1.0492089294729376`。全 160 timing sample は成功し、80 組の
  outcome/score/PV/depth/exact が一致した。RSS 実測値はない。
- `rust/reversi-ai/src/search/endgame.rs:8-205` の現行実装は再帰結果と
  exact cache entry に PV を保持し、exact hit 時に複製する。
  `rust/reversi-ai/src/search/negascout.rs:18-291` は heuristic PV の現行経路。
- `docs/specs/reversi-ai.md:379-401` は comparator の warm-up、5 回以上、
  順序交互、raw sample、意味論フィールドを定める。同文書 `:461-489` は
  exact 結果と中断時の公開契約を定める。
- `tools/reversi-ai-benchmark/compare.py:83-172` は現行比較器。
  `docs/issues/0011-exact-solver-20-performance.md:1-37` は 20-empty の
  oracle score `+26` と 5 分で未完了の状態を記録する。
- Edax の [search-owned state](https://github.com/abulmo/edax-reversi/blob/master/src/search.h)
  と [compact hash entry](https://github.com/abulmo/edax-reversi/blob/master/src/hash.h)、
  Egaroucid の [table](https://github.com/Nyanyan/Egaroucid/blob/main/src/engine/transposition_table.hpp)
  と [PV 出力経路](https://github.com/Nyanyan/Egaroucid/blob/main/src/engine/principal_variation.hpp)
  は設計上の参照のみ。GPL コード・重み・バイナリを製品へ取り込まない。

## 変更対象

- (MODIFY) `docs/specs/reversi-ai.md` -- exact PV の観測可能な条件を
  終局までの合法 replay と最終石差で明確化し、後段の再探索を必須としない。
- (MODIFY) `rust/reversi-ai/src/search/negascout.rs` -- 採用候補となる
  heuristic scratch の pass-aware 境界と中断時の最終完了結果。
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs` -- compact cache と
  完全な exact PV を両立する二つの限定候補を試す。
- (MODIFY) 必要な `rust/reversi-ai/src/search/` の focused tests と
  `tools/reversi-ai-benchmark/` -- 意味論検証と process-specific な
  CPU time / peak RSS 計測、report schema と synthetic validation。
  比較器の wall-clock 算術は維持する。
- (MODIFY) `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md`
  と `0019-reversi-ai-pattern-reinforcement-cycle.md` -- 0029 の結果を
  候補 freeze と long-run manifest の前提に加える。
- (NEW) `docs/references/` の候補別診断記録と最終 5 反復 report。
- (MODIFY) `docs/exec-plan/todo/0020-reversi-ai-search-performance.md`
  -- 両 workload の比率、実測資源、原因の切り分け、report digest と
  採用／不採用を記録する。
- (DELETE) この child plan。検証と PR 準備が終わった時点で削除し、
  内容は PR/Git history から取得する。

## 作業と比較順序

1. `main` と PR #200 report の commit・binary・corpus digest を固定する。
   0023 の 16 局面 report を再生成して byte 一致を要求しない。
2. まず診断用に PR #200 型の table 初期化、cache hit/衝突、PV 構築に
   要する時間を別々に測る。これらは原因推定用であり、採用判定は
   instrumentation を外した release binary の full-depth wall-clock
   のみで行う。proof/reconstruction の node 内訳は新設しない。
3. 候補 A は heuristic PV の search-owned scratch だけを現行 `main`
   から独立に適用する。pass を含む最大 ply に対して境界を証明するか、
   安全な fallback を設ける。各完了 depth の結果は即時に返せるよう
   保持し、exact solver と cache は変更しない。
4. 候補 B は exact search で compact score/bound/move cache を使う。
   初回 budget check 前の巨大な初期化を避け、容量・置換方針は bounded
   かつ deterministic とする。完全な PV は、探索中の経路保持を第一案、
   選択経路の exact 証拠が欠ける箇所だけを同じ budget 内で補う方法を
   第二案として比較する。TT の hash 一致だけで局面同一とみなさず、
   bound や best-move chain だけから完全な PV を捏造しない。
5. A と B を別々の binary/commit で意味論検証し、診断計測で無益な案を
   落とす。両方を残す場合だけ統合候補を作る。各 binary の SHA-256 と
   commit を記録し、最終候補は必ず最新の採用済み `main` と比較する。
   0024--0028 が先に merge した場合は baseline と意味論を再確認する。
6. 5 反復 report と process ごとの CPU time / peak RSS の実測を保存し、
   0020 の性能条件で判定する。局面・反復ごとの意味論が異なる、測定が
   失敗する、または CPU/RSS が未測定なら成功 report としない。

## 資源計測と report schema

- Linux の同一ホストで比較器が起動した各 profiler 子プロセスを個別に
  `wait4` で回収し、その子の `rusage` を採取する。`RUSAGE_CHILDREN` の
  累積値や複数の子の最大値を個別 sample に割り当てない。比較器は
  `subprocess` の stdout/stderr を欠落・deadlock なく回収する。
- report schema/runner version を更新し、各 measured
  `raw_samples[]` に `resource_usage` を置く。値は非負の
  `user_cpu_ns` と `system_cpu_ns`、正の `peak_rss_kib` とし、
  `measurement_method: linux-wait4` を environment に記録する。
  Linux `ru_maxrss` の KiB をそのまま記録し、曖昧な byte 換算をしない。
  warm-up の値は report と集計から除く。
- 局面ごとに baseline/candidate の 5 件の
  `(user_cpu_ns + system_cpu_ns)` の median を算出する。workload ごとの
  candidate/baseline CPU 比は局面比の幾何平均とする。peak RSS は
  workload・binary ごとに全 measured sample の最大 KiB を報告する。
  wall-clock の既存 median と幾何平均を変更せず、CPU/RSS を代替 gate
  にしない。増加は数値とともに明示し、採用前の判断材料にする。
- 子プロセスの異常終了、rusage 欠落、非整数・負値、RSS が 0、sample
  数不足、baseline/candidate で計測方式・ホストが異なる場合は fail
  closed とし、成功 report を書かない。Linux 以外で同じ方式が使えない
  場合も欠測を推測せず、測定環境を整えてから実行する。
- synthetic fixture で resource schema、CPU median/ratio、peak RSS の
  算術、欠測・不一致による失敗を検証する。CI は wall-clock または
  CPU/RSS の速度・使用量しきい値を assert しない。

## 検証と採用判断

- Rust 1.98.1 の focused tests、workspace Clippy、GDExtension build、
  workflow lint、`git diff --check`。
- exact PV を root から終局まで replay し、各手の合法性、pass の処理、
  最終石差と `score` の一致、同点時の決定性を確認する。独立 oracle で
  同じ盤面を解き、cache hit、衝突、置換、強制 pass、即時 deadline、
  cancellation、深い heuristic pass を含む focused cases を検証する。
- release comparator は一局面・binary ごとに warm-up 1 回と交互の
  5 timed repetitions。全 raw sample の `timing_success` と outcome、
  score、PV、completed_depth、exact の一致を要求する。採用判断は
  `heuristic-depth-12` と `exact-16` の幾何平均比を個別に行う。
- CPU time、peak RSS、wall-clock の測定方法、全 binary/report digest、
  実行ホストを公開する。RSS の推測や node 数による代替判定はしない。
  5% に達しない場合も報告し、PR #200 の扱いは変更しない。
- exact 側を採用する場合に限り、20-empty fixture を 5 分の単調 deadline
  で再確認する。閾値 16 を引き上げる判断はこの計画に含めない。

## 依存・並行性

- 親 0020 と PR #201 の結果を前提とし、PR #200 は未採用の設計資料。
- exact 変更は 0026--0028 より先に評価するか、各 child の最新採用
  `main` に合わせて baseline と candidate を作り直す。heuristic 側の
  0024--0025 とは独立に進められる。

## Addresses

- N/A。`docs/issues/0011-exact-solver-20-performance.md` は親 0020 が所有し、
  この child の結果だけでは閉じない。
