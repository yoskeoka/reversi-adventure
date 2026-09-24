# Follow-up plan: recheck implementation cost in rejected search methods

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

0020 の探索手法実験がすべて終了した後、不採用だった手法について、探索規則の
効果が Rust 実装の余分な仕事で隠れた可能性を追試する。0024 の aspiration
windows は必須対象とし、0025--0028 のうち不採用になった手法も対象にする。
0023 の PV storage と exact table は 0029 が扱うため、この計画では重複して
再実装しない。0029 の結果は比較時の最新採用済み `main` に含める。

手法ごとに、元の候補を最新 `main` に移した基準版と、探索規則を変えずに
実装コストだけを減らした版を分けて測る。計測で余分な仕事を特定できない
場合は変更せず、その限界を記録する。各手法の結果は、原因、元候補と調整版
の差、最新 `main` に対する両 workload の時間比、全結果の一致、report digest、
採用／不採用を残す。改善版の採用には、0020 と同じ「少なくとも一方の
workload で幾何平均 5% 以上短縮」と完全な意味論一致を要求する。

この計画は 0020 の完了条件には含めない。0020 が完了し、その親計画と
issue の扱いが確定してから着手する。未完了の 0020 を本計画の結果で
先取りして閉じない。

## 既存の根拠

- [draft PR #203](https://github.com/yoskeoka/reversi-adventure/pull/203)
  (`feat/reversi-ai-aspiration-windows`) は 0024 の未採用コードを保持する。
  `rust/reversi-ai/src/search/negascout.rs` の root retry は失敗窓でも
  `NodeResult` の PV を組み立てる。最終候補の 160 sample report は
  `docs/references/reversi-ai-search-performance-0024.json`、SHA-256
  `04006088940dcbc4497a1b93d468a39a8f4858ff0ec6f33e457a9e8024415d0e`。
  heuristic depth-12 比 `0.985057117170627`、exact-16 比
  `1.0077264536193302` であり、全 80 組の結果投影は一致した。
- `docs/exec-plan/todo/0020-reversi-ai-search-performance.md` の shared
  acceptance rules は二つの workload と 5% gate を定める。0020 の完了時に
  不採用手法の一覧、最終 baseline、各 report digest を固定する。
- `docs/exec-plan/todo/0029-reversi-ai-search-storage-refinement.md` は
  0023 の storage 案、CPU time、peak RSS を扱う。この計画は探索手法を
  再評価する際の実装コストだけを扱い、0029 を代行しない。
- `rust/reversi-ai/src/search/negascout.rs:18-291` は heuristic の PV 構築、
  TT、PVS の現行経路。`rust/reversi-ai/src/search/endgame.rs:8-262` は
  exact 経路。対象手法の候補 commit と report は 0020 の記録から取得する。
- `tools/reversi-ai-benchmark/compare.py:83-172` と
  `docs/specs/reversi-ai.md:318-401` は full-depth の 16 局面比較、固定
  ノード診断、結果投影、release 計時の契約を定める。

## 変更対象

- (MODIFY) `docs/specs/reversi-ai.md` -- 採用する場合だけ、公開結果や
  探索意味論に影響する差を先に記す。診断だけなら製品契約は変えない。
- (MODIFY) 対象の `rust/reversi-ai/src/search/` 実装 -- 探索規則を固定した
  まま、計測で示した一時割当・コピー・初期化などの余分な仕事を減らす。
- (MODIFY) 対象の focused tests と必要な診断用 tooling -- 変更前後の
  探索結果、node 数、実装コストを独立に比較する。
- (NEW) `docs/references/` の手法別診断、候補 commit/binary digest、
  full-depth release report。
- (DELETE) この plan -- 検証と PR 準備後に削除する。

## 作業と比較順序

1. 0020 の全 child の採否と親計画の完了を確認する。対象は 0024 と、
   0025--0028 の不採用手法だけに固定する。0023/0029 は除外する。
   各元候補の commit、設定、report、基準 commit、Rust/toolchain を記録する。
2. 手法ごとに最新の採用済み `main` へ元候補を移し、探索規則と
   0021 corpus を固定する。手法の定数、窓幅、cutoff 条件、評価器、
   exact 閾値をこの追試の中で調整しない。
3. まず元候補の余分な仕事を診断する。0024 では失敗窓の回数、再探索
   node、PV 構築と一時割当の量を分けて記録する。ほかの手法ではその
   実装が追加したコピー、table 操作、初期化などを対象にする。
   instrumentation は採用判定用の release binary から外す。
4. 診断で根拠が得られた手法に限り、一手法につき一つの限定した実装
   改善版を作る。元候補と改善版の完全な結果投影を比較し、node 数や
   探索順が変わった場合は実装コストの効果と探索木の効果を混同しない。
   変化を分離できなければ採用判断を保留せず不採用として記録する。
5. 元候補、改善版、最新 `main` を別々の commit と binary として凍結し、
   同一ホスト、同じ power policy と低い背景負荷で release 比較する。
   各 binary/局面に warm-up 1 回、交互の計時を最低 5 回行う。16 局面
   すべての full-depth timing sample が成功し、outcome、score、PV、
   completed depth、exact が一致することを要求する。node-only 反復は
   再現性診断に使い、時間 gate の代わりにしない。
6. 各手法の両 workload 比、元候補からの差、CPU time と peak RSS
   （その時点の比較器で取得可能な場合）、原因の説明と digest を報告する。
   最新 `main` に対して gate を満たした改善版だけを別 PR で提案する。
   不採用版のコードは製品 `main` に入れず、検証可能な commit/report を
   残す。exact 側を採用する場合だけ 20-empty fixture を 5 分の単調
   deadline と独立 oracle score で再確認する。

## 依存・並行性

- 0020 の全 child と親計画の完了後に開始する。0029 の結果を取り込んだ
  最新採用済み `main` を基準とする。0020 の未完了条件を本計画の前提に
  繰り込まない。
- 0024 の結果を記録する [PR #204](https://github.com/yoskeoka/reversi-adventure/pull/204)
  が merge 済みであることも確認する。PR #203 は未採用コードの参照元であり、
  その merge を前提にしない。
- 各手法の診断は独立に行えるが、release timing は同一ホスト上で直列に
  実行する。後続の採用版が `main` に入ったら、次の手法の基準を更新する。

## 検証

- 元候補と改善版に対し、pass、game-over、TT bound、期限切れ、cancel、
  最終完了反復の focused tests と、決定的な到達可能局面での差分試験。
- 0021 corpus の全 16 局面で、全反復の意味論一致を独立に検証する。
  固定ノード試験は同じ binary の結果投影・node 数が繰り返し一致すること。
- Rust 1.98.1 の対象 crate tests、workspace Clippy、GDExtension build、
  corpus verify、workflow lint、`git diff --check`。CI の速度しきい値は
  設けず、同一ホストの release report のみで採否を判断する。

## Addresses

- N/A。0020 が所有する `docs/issues/0011-exact-solver-20-performance.md` は
  0020 の完了時に別途扱う。この追試はその issue の先行解決条件ではない。
