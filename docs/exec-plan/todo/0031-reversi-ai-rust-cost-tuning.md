# Execution plan: measure and tune Reversi AI Rust implementation cost

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

PR #212 で閉じた 0020 の採用済み `main` を出発点として、Reversi AI の
Rust 実装コストを序中盤の通常探索と終盤の完全読みに分けて測る。測定前に
最適化手法を決めない。現行コードの診断結果から、実装上の余分な仕事を
特定でき、探索意味論を固定できる範囲だけを小さく調整する。

成果物は、再実行可能な診断手順、同一ホストでの elapsed/CPU time/peak RSS
比較器、根拠付きの選択または変更を見送る判断、二つの workload の report
である。実装候補を採用する条件は、現行 `main` に対する
`heuristic-depth-12` または `exact-16` のどちらかの局面別 median 比の
幾何平均が `<= 0.95`、全 sample の公開結果一致、実装コスト比較における
探索順・node accounting・決定的 trace の一致、CPU/RSS の実測が揃うこと。
両 workload と資源増減を必ず報告し、数値と原因を示して採否を人間に委ねる。
改善箇所が特定できない、または同一探索を証明できない場合は、計測基盤と
診断 report のみを完成させ、未採用候補の code/commit/report を消さない。

## 現状の根拠と測定上の欠落

- [PR #212](https://github.com/yoskeoka/reversi-adventure/pull/212) は
  `6a437d9912fabd32b2807a526622a142bc472ea7` として merge 済み。
  `docs/references/reversi-ai-search-performance-0020-closeout.md:8-51` の
  16 局面・5 反復は通常探索 `0.4079137674489783`、完全読み
  `0.2092294536017321` の wall 比を示すが、CPU/RSS は未測定で、
  個々の Rust コストを帰属できない。
- `rust/reversi-ai/src/eval/trained.rs:40-42,145-165` は 60 phase の
  sparse table と評価時の特徴抽出・lookup、
  `rust/reversi-ai/src/eval/pattern.rs:240-256` は対称変換と特徴構築を担う。
  artifact 読み込み・検証の初期費用は探索中の評価費用と分ける。
- `rust/reversi-ai/src/search/negascout.rs:126-295` は budget check、node
  計上、leaf 評価、TT、通常/PVS 再探索、PV 構築を行う。
  `rust/reversi-ai/src/search/ordering.rs:51-112` は move ordering の
  scored vector、mobility 計算、安定した順序を持つ。
  `rust/reversi-engine/src/moves.rs:68-83` の `generated_moves` は合法手を
  再計算するため、既存 `moves_mask` と重複する可能性がある。これらは
  **計測候補**であって、変更対象の事前決定ではない。
- `rust/reversi-ai/src/search/tt.rs:38-113` は Zobrist 計算と direct-mapped
  TT、`rust/reversi-ai/src/search/mod.rs:41-183` は node-only budget、
  evaluator context、通常探索と exact の切替を持つ。TT の容量・置換、
  ordering の優先度、評価値は探索順を変え得るため、この plan の
  実装コスト比較に混ぜない。
- `rust/reversi-ai/src/search/endgame.rs:35-167,216-618` は評価器を呼ばず、
  空き領域、着手順、exact cache、PV、PVS を処理する。通常探索とは
  別の経路として診断する。
- `rust/reversi-ai/src/bin/reversi-ai-search-profile.rs:16-211` は fresh
  `SearchEngine` と node-only/time-only の結果を出すが、現在は
  `StrategicEvaluator` 固定。`tools/reversi-ai-benchmark/compare.py:83-197`
  は elapsed の比較のみで、子プロセスごとの CPU/RSS を保持しない。
  `docs/specs/reversi-ai.md:331-419` は corpus、完了 depth、交互 5 反復、
  成功 sample と結果投影の現行契約である。
- `tools/reversi-ai-training/fixtures/tiny-manifest.json` と
  `tools/reversi-ai-training/training.py` は再現可能な artifact 入力と
  生成器である。小規模 fixture の sparse table は本番モデルの性能を
  代表しないため、trained 側の数値を 0020 系の採否 gate に使わない。

## 変更対象と仕様

- (MODIFY) `docs/specs/reversi-ai.md` -- 測定の観測可能な契約として、
  二つの workload、trained 診断の区別、各 sample の elapsed/CPU/peak RSS、
  同一探索の検証、欠測時の失敗を明記する。AI の公開結果・評価値・探索規則は
  変更しない。
- (MODIFY) `rust/reversi-ai/src/bin/reversi-ai-search-profile.rs` と
  `tools/reversi-ai-benchmark/compare.py` -- 再現可能な trained 診断経路、
  決定的 trace 診断、子プロセス単位の資源計測と report 検証を加える。
  trace/instrumentation は release timing では無効にする。
- (MODIFY, 診断後に確定) `rust/reversi-ai/src/eval/trained.rs`、
  `rust/reversi-ai/src/eval/pattern.rs`、`rust/reversi-ai/src/search/negascout.rs`、
  `ordering.rs`、`tt.rs`、`mod.rs`、`endgame.rs`、必要なら
  `rust/reversi-engine/src/moves.rs` のうち、測定で特定した最小範囲。
  実際の変更ファイルと選択理由を report に確定する。
- (MODIFY) `tools/reversi-ai-benchmark/tests/` と対象 crate の focused
  tests -- schema 算術、欠測失敗、決定的 trace・結果の一致を検証する。
- (NEW) `docs/references/reversi-ai-rust-cost-0031.md` と機械可読 report --
  baseline、診断、候補、計測環境、両 workload、資源値、採否の根拠を保存。
- (DELETE) この plan -- 実装、検証、PR 準備後に削除し PR/Git history から
  参照する。

## 実行順序と選択規則

1. 最新採用済み `main` の commit、Rust 1.98.1/toolchain flags、corpus
   `tools/reversi-ai-benchmark/positions-v1.jsonl` の SHA-256
   `5831839527b433b4b92c314331b9f0e613d98e0f82b9b6edb725f8bd6cb97ff8`
   を固定し、`make benchmark-corpus-verify` を実行する。局面は再生成しない。
   20/40/44 occupied の 12 局面を通常深さ 12、48 occupied の 4 局面を
   exact-16 とする。各局面は fresh engine。time-only では要求 depth の
   完了を必須とし、node-only は再現性診断に使う。
2. 診断 build で、通常探索の leaf 評価、特徴抽出/lookup、ordering、
   合法手生成、TT hash/probe/store、PV・一時確保を、完全読みの ordering、
   region 更新、exact table、PV、探索本体と分けて計数・時間観察する。
   追加計測自体の overhead を記録し、重複区間を足し合わせない。
   trained evaluator は `tools/reversi-ai-training/fixtures/tiny-manifest.json`
   から既存 trainer で生成・検証した artifact を診断入力とし、manifest、
   artifact、trainer commit の digest、生成コマンド、evaluator context を
   report に固定する。artifact load/validation と search 中の評価を
   別々に計数・観察する。exact では evaluator 呼出数が 0 と確認する。
   profiler は `--evaluator strategic|trained`（既定 strategic）と
   trained 専用の必須 `--trained-artifact PATH` を受け、他の組合せを
   拒否する。採否用 release 比較は従来の strategic、深さ 12/exact-16
   のみ。trained は固定 artifact を使う通常探索の補助診断とし、
   その比率を 5% gate や 0029/0030 の結果へ混ぜない。fixture は
   `python3 tools/reversi-ai-training/training.py train --manifest
   tools/reversi-ai-training/fixtures/tiny-manifest.json --artifact
   /tmp/pattern-artifact.json --report /tmp/pattern-report.json` で生成し、
   同 tool の `validate --artifact /tmp/pattern-artifact.json` で検証する。
   strategic 採否 report と trained 診断 report は profile 名と digest を
   持つ別成果物とする。
3. 診断値と呼出回数・allocation 等の帰属から、一つの支配的コストを
   選ぶ。同程度なら通常/exact の両方に効く箇所、または変更範囲の狭い
   箇所を優先する。改善余地が測れなければ tuning を実施しない。
   評価値、phase/table 内容、探索窓、ordering 順序と tie、TT の
   identity/容量/置換、枝刈り条件、node accounting は固定する。
4. original と tuned の診断 binary を同じ局面・node-only budget で走らせ、
   局面/side/depth/window、順序付き着手、TT 判定、再探索/cutoff の
   trace digest と node 数、結果・score・PV・depth・exact を照合する。
   trace は実行順を保持して hash し、単なる集合比較にしない。
   相違があれば実装コストとしての比較は中止し、意味論/探索手法の変更として
   別途扱う。通常/exact と pass・TT collision・期限切れ・cancel を含む。
5. 検証済み候補と現行 `main` の instrumentation 無し release binary を
   固定する。同一 Linux host、同じ power policy、低い背景負荷で直列実行。
   各局面/binary の warm-up 1 回後、順序を交互にして 5 反復以上測る。
   全 time-only sample の完了と outcome/score/PV/depth/exact 一致を要求する。
   診断 trace の一致とは別に、全 sample の node 数も照合する。
6. 局面別 elapsed と user+system CPU の各 binary median、その
   candidate/baseline 比の workload 別幾何平均、peak RSS の binary・
   workload 別最大を報告する。両 workload の改善・悪化を隠さず、
   診断値から説明できる原因、binary/commit/report digest、実行環境、
   0029/0030 の baseline への影響を記す。資源増加は採用前の判断材料とし、
   node 数だけで速度やメモリを代用しない。採用判断はユーザーに渡す。

## 資源計測と失敗条件

比較器は Linux 上で各 profiler 子プロセスを個別に `wait4` で回収し、
stdout/stderr を欠落・deadlock なく取得する。各 measured sample に
非負の `user_cpu_ns`、`system_cpu_ns`、正の `peak_rss_kib` を記録する。
`ru_maxrss` は Linux の KiB として保存し、
`measurement_method: linux-wait4`、host/OS/CPU、binary digest、
Rust flags を environment に記録する。同じ起動から終了までの区間で
`process_elapsed_ns`、CPU、peak RSS を測り、baseline/candidate の
process 指標を対で集計する。従来の 5% gate に用いる
`search_elapsed_ns`（現行 profiler の `elapsed_ns`）は evaluator 構築後に
profiler が測る別区間として
保持する。load 込み process 値と search-only 値の比を直接比較せず、
report で区間を明示する。trained の初期 load が process 指標に含まれる
ことを明記し、診断計数で search 中の費用を別に示す。warm-up は集計から
除外する。累積 `RUSAGE_CHILDREN` を sample 値に使わない。

異常終了、rusage 欠落/不正、RSS 0、局面や反復の不足、host/計測方式の
不一致、未完了 depth、結果または node/trace の不一致は fail closed。
成功 report と採用判断を作らず、欠測は推測しない。synthetic fixture で
schema、中央値・幾何平均、peak 集計、欠測・不一致の拒否を検証し、
CI に経過時間や資源量の速度しきい値を置かない。

## 0029・0030 との関係

- 本 plan は採用済み `main` の共通実装コストと測定基盤を先に扱う。
  0029 の 0023 storage 分解、0020 と同じ 5% gate、PV の完全性条件、
  20-empty 条件を代行・変更しない。0029 は本 plan の資源計測器を再利用し、
  storage 固有の診断から着手する。
- 0030 は 0024/0025/0028 の棄却手法に固有の余分な実装コストを、
  0029 の結果を含む最新採用済み `main` 上で追試する。本 plan の
  baseline 調整をそれらの手法の利益に算入しない。0030 の
  original-vs-tuned 同一探索条件と独立の 5% gate を維持する。
- 実施順は本 plan、0029、0030。0020 と PR #212 は完了済みで、
  本 plan を過去の完了条件へ追加しない。両既存 plan の変更は依存と
  共通計測器の所有範囲だけに限定する。

## 検証

- Rust 1.98.1 の対象 crate tests、workspace Clippy、GDExtension build、
  benchmark corpus verify、workflow lint、`git diff --check`。
- fixed-node の再実行と original/tuned trace・node・結果の完全一致。
  trained artifact の同一性と invalid artifact の拒否、exact が評価器を
  呼ばないことを確認する。
- tuning 候補がある場合、独立した release 比較で全 160 measured sample
  （16 局面 × 2 binary × 5 反復）が成功し、80 baseline/candidate pair が
  一致することを確認。CPU/RSS が全 sample に存在すること。候補を
  見送る場合は、両 workload の baseline 資源測定と診断値で理由を示す。
  必要な場合だけ、採用 exact 側の 20-empty fixture を単調 5 分 deadline
  と独立 oracle score で再確認。

## Addresses

- N/A。0020 の local issue は PR #212 以前に解決済み。
