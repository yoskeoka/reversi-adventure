# Reversi AI unsafe cost experiment (0032)

## 固定した入力と候補

- 採用済み `main`: `fc51e144e4c500783913b47f103c02c0a1a344c5`。
- safe 対応版: `5fc7473ce89fd237bec247694b80b093af6d1a33`。公開
  `TranspositionTable::new(0)` は構築可能とし、probe は miss、store は無効とした。
- unsafe 実験版: `bbb425ef259e6c62e93f5294ed8d4f357a496c27`。safe 版から
  TT の probe/store の索引方法だけを `get_unchecked` / `get_unchecked_mut`
  に変更した。容量、置換規則、探索処理、割当、分岐は同じ。
- corpus: `tools/reversi-ai-benchmark/positions-v1.jsonl`、SHA-256
  `5831839527b433b4b92c314331b9f0e613d98e0f82b9b6edb725f8bd6cb97ff8`。
  `make benchmark-corpus-verify` で既存の16局面を検証し、再生成していない。
- Rust 1.98.1、release profile、x86_64、空の `RUSTFLAGS` でビルドした。
  release profiler binary の SHA-256 は順に `3f40c8941f9f419a24ae18137d3bafdb65957457ca910abff51e9f29c3cb416c`、
  `be8dc69c41c16359db952822053179ff5868f863b64bf2d025343fe2c80fa986`、
  `1d2aa2a8ea2388456443187949e281918bbe1b6a549fb88e7e6bb65f11bbb4f5`。

## 診断と安全性

同じ release 設定で生成した assembly では、safe 版の
`TranspositionTable::probe` に `entries.len()` に対する比較と
`panic_bounds_check` が残り、unsafe 版の同関数から両方が消えた。容量0の
分岐と剰余演算は両方に残る。元の `main` ではこれらに加えて容量0の剰余
panic 経路がある。TT の `entries` と `capacity` は private で、`new` が
ちょうど `capacity` 個の初期化済み要素を作り、`clear` は長さを変えない。
容量0を先に処理した後の `index = hash % capacity` は必ず配列内にある。
store の共有参照は置換判断の後に終了し、可変参照と重ならない。

診断の固定 node 上限は100,000/局面。main、safe、unsafe の16局面すべてで
outcome、score、PV、completed depth、exact、node 数、実行順 trace digest
が一致した。診断 report は
[reversi-ai-unsafe-cost-0032-diagnostics.json](reversi-ai-unsafe-cost-0032-diagnostics.json)
（SHA-256 `eb9fa9db3d41926de71f3ca416ecad0660f8269435c02c1d413bb8d4bd34524d`）。
main の診断では heuristic TT probe が452,581回、store が420,573回、
exact region update が372,377回であった。診断の inclusive 時間は
instrumentation の費用を含むため、採否用 timing に使っていない。

`EmptyRegions::assign` の添字は非ゼロ `u64` の `trailing_zeros` から
0..63 と導ける。一方 `after_placement` / `is_odd` の添字は公開フィールドを
持つ `Position` 由来であり、型そのものは行・列の範囲を保証しない。
この候補の安全性を局所的に証明できないため、`EmptyRegions` に unsafe を
導入しなかった。trained 特徴抽出も本計画の採否対象外である。

容量0と TT collision の focused tests に加え、既存の pass、期限切れ、
cancel、exact PV の tests を通した。固定 node 診断は release timing と
別 binary で行った。診断 binary SHA-256、trace JSONL SHA-256、各局面の
trace は機械可読 report に保存した。

## 同一 host の release 測定

host `xps`、Intel Core i7-1065G7、Linux
`6.18.33.2-microsoft-standard-WSL2-x86_64`。比較は直列で実行し、
各 binary/局面で1回 warm-up、交互順に5回測定した。各比較で160 raw
samples / 80 baseline-candidate pairs がすべて成功し、全公開結果と node
数が一致した。CPU と peak RSS は各 child の Linux `wait4` で測定し、
欠測はない。`elapsed_ns` は evaluator 構築後の探索区間、CPU/RSS は
process 起動から終了までの区間である。

| 比較 | workload | elapsed 比 | CPU 比 | process elapsed 比 | peak RSS baseline → candidate |
| --- | --- | ---: | ---: | ---: | ---: |
| safe → unsafe | `heuristic-depth-12` | `1.0128852932407244` | `1.0130588366999507` | `1.0130233475593613` | 27,052 → 27,052 KiB |
| safe → unsafe | `exact-16` | `0.995774361767293` | `0.9976111594348657` | `0.9965398070250964` | 34,892 → 34,936 KiB |
| main → unsafe | `heuristic-depth-12` | `0.9958115536113767` | `0.9951891975197575` | `0.9951750274244308` | 27,052 → 27,052 KiB |
| main → unsafe | `exact-16` | `1.0099516922361556` | `0.9924922433644976` | `0.9934312979350198` | 35,016 → 34,924 KiB |

各局面の中央値を比較すると、safe → unsafe で最大の悪化は
`self-play-4-44` の `1.1308`、main → unsafe では `self-play-3-48` の
`1.0620`。両 workload の全局面別比と raw samples は
[safe 対 unsafe report](reversi-ai-unsafe-cost-0032-safe-vs-unsafe.json)
（SHA-256 `581eb0d8fc764f76015e8f9952809c01d0a05a830f1d5d9995f942f95ea90df7`）と
[main 対 unsafe report](reversi-ai-unsafe-cost-0032-main-vs-unsafe.json)
（SHA-256 `3c9670e5f412c55d91e29db0433a9b567173a2c957d2071578846d507f800775`）にある。
局面別 elapsed median 比から独立に幾何平均を再計算し、report と一致した。

## 採否と再実行

unsafe 固有の追加利益は heuristic で約1.29%悪化、exact で約0.42%改善に
とどまり、いずれも `<= 0.95` gate を満たさない。最新 `main` 対候補でも
heuristic は約0.42%改善、exact は約1.00%悪化で gate を満たさない。
境界チェックの削除は assembly で確認できたが、同一 host の実測では
危険を伴う実装を採用する利益が確認できない。**unsafe 候補は採用見送りを
提案する。** 実験 commit、binary digest、report、PR は追跡のため残す。
この PR の merge/close と最終採否は人間が判断する。

再実行には上記 source commit ごとに次を実行し、profiler binary を別名で
保存する。診断版は同じコマンドに `--features cost-diagnostics` を加える。

```sh
rtk cargo +1.98.1 build --release -p reversi-ai --bin reversi-ai-search-profile
rtk make benchmark-corpus-verify
```

固定 node 診断は各診断 binary に対して次を実行し、出力を別々の JSONL に
保存する。

```sh
rtk /tmp/reversi-ai-0032-unsafe-diag --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --node-limit 100000 --opening-depth 12 --midgame-depth 12 --endgame-depth 12 --exact-solver-empty-squares 16 > /tmp/reversi-ai-0032-unsafe-diag.jsonl
rtk python3 tools/reversi-ai-benchmark/verify_unsafe_cost.py --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --main-binary /tmp/reversi-ai-0032-main-diag --main-trace /tmp/reversi-ai-0032-main-diag.jsonl --safe-binary /tmp/reversi-ai-0032-safe-diag --safe-trace /tmp/reversi-ai-0032-safe-diag.jsonl --unsafe-binary /tmp/reversi-ai-0032-unsafe-diag --unsafe-trace /tmp/reversi-ai-0032-unsafe-diag.jsonl --verify-report docs/references/reversi-ai-unsafe-cost-0032-diagnostics.json
```

release 比較と保存 report 検証は次の通り。`--verify-report` は渡した
binary の内容を再ハッシュし、全 schema、順序、計算、結果、資源値を確認する。

```sh
rtk python3 tools/reversi-ai-benchmark/compare.py --baseline /tmp/reversi-ai-0032-safe --candidate /tmp/reversi-ai-0032-unsafe --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --output /tmp/reversi-ai-0032-safe-vs-unsafe.json --repetitions 5 --time-limit-ms 300000
rtk python3 tools/reversi-ai-benchmark/compare.py --baseline /tmp/reversi-ai-0032-main --candidate /tmp/reversi-ai-0032-unsafe --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --output /tmp/reversi-ai-0032-main-vs-unsafe.json --repetitions 5 --time-limit-ms 300000
rtk python3 tools/reversi-ai-benchmark/compare.py --verify-report docs/references/reversi-ai-unsafe-cost-0032-safe-vs-unsafe.json --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --baseline /tmp/reversi-ai-0032-safe --candidate /tmp/reversi-ai-0032-unsafe
rtk python3 tools/reversi-ai-benchmark/compare.py --verify-report docs/references/reversi-ai-unsafe-cost-0032-main-vs-unsafe.json --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --baseline /tmp/reversi-ai-0032-main --candidate /tmp/reversi-ai-0032-unsafe
```
