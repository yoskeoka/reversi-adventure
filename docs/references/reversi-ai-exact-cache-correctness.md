# 完全読みの手番間cache再利用停止（0043）

2026-10-06。基点は `21517911e69653fb3b71a8f37cdfa776c33c1e12`。
[0041の固定証拠](reversi-ai-exact-threshold-reuse-assessment.md) の
空き7・白手番で、gameはa7/+4を返したが選択childの独立値は+2だった。
この記録と過去のproducer/manifest/receiptは変更していない。

## 停止範囲

共有 `SearchEngine::search_with_budget` / `analyze_with_budget` は各呼び出しの
開始時にexact tableだけを一度消去する。通常TTの同一context内再利用、
再帰solveと一回のAdvisor候補比較内のexact再利用は維持する。
AiPlayer、Godot、Playground、自己対局も共有境界を通る。
`new_game` の通常TT/exact/context消去とflush済みackは維持する。

CLI既定はturn。明示gameは探索前に
`--exact-cache-scope game is suspended for exact-cache correctness; use turn`
で拒否する。新規reinforcement manifestはschema v4で実効turn、
`exact-cache-cross-decision-suspended-v1`、CLI SHA-256を固定する。
report/artifactの既存v3 encodingは維持し、reportのmanifest digestがv4 policyを含む。
旧v3 manifestはrunとregret採用経路で拒否し、完成reportのoffline verifyは維持する。

新規whole-game CLI計測はturnのみ。gameはprocess/lock/output作成前に拒否する。
既存6条件のprepare producerはgame条件を含むため新規prepare/runを拒否する。
過去のmanifest入力検証・完成report/comparison検証は元の契約を維持する。

## 短い確認

- `cargo test -p reversi-ai`: 108 tests、7 suites成功。
- 空き7の固定局面の連続CLI呼び出しは既定/明示turnともa4を返し、
  elapsedを除くdiagnosticsが一致する。
- 共有engineの連続child decisionとAiPlayerの繰り返しthinkはfresh tableの
  outcome/score/PV/nodes/cache countersと一致する。
- Advisorの繰り返し候補値はfreshと一致し、未完了/forced-pass呼び出しも
  前decisionの表を消去する。通常TTのhitと一回のsolve内のexact hitは残る。
- 新旧manifest、改変policy、game条件の事前拒否はRust/Pythonの小さいfixtureで確認する。

## Source SHA-256

| Path | SHA-256 |
| --- | --- |
| `rust/reversi-ai/src/search/mod.rs` | `5430b9156fce950f67f233a039ce6dc5fa18fa7c726f8604fa0a09bdd4b796c4` |
| `rust/reversi-ai/src/bin/reversi-ai-cli.rs` | `a952ca17b8dc0f548a389e1952b83cb9497794afe47a770ab99020535989bd3d` |
| `tools/reversi-ai-training/reinforcement.py` | `eca5244038b16d7936e9d65a7297eceb81e09bf5688b1349789b7470f4321952` |
| `tools/reversi-ai-benchmark/whole_game.py` | `e2bb8044f5e2d1e24d1e5ac2d84f88c8a319bfa984bc2d3c29928b15f7ff3444` |
| `tools/reversi-ai-benchmark/prepare-whole-game-measurement.py` | `92769cb56b4237eedc106ec9ff78a91726f8ca1dd49c441419d1e18dcda7b4d5` |

確認したdebug CLIのSHA-256は
`0a606618d67142fa469a0b99dee35520efa7ab689a7eb5d449f782283d41dad2`。
ローカルbinaryの識別であり本番freezeではない。新しいbinaryは毎回manifestに固定する。
`cargo test -p reversi-engine`（28 tests）、Clippy、fmt checkも成功した。
reinforcementの20 tests、whole-game/prepareの40 testsが成功した。
全体Python gateで停止policyにより旧gameのsignal fixtureが拒否されたため、
その合成fixtureだけをturnに直しSIGTERM/SIGKILLの両ケースも成功した。
最終gateは `make oracle-test`（Oracle harness 40、benchmark 95 tests）、
`make pattern-training-test`（31 tests）、`cargo build -p reversi-godot` が成功した。
原因修正は0044、縮小検証は0045、採用/設定/時間予算は0040の責任である。
この停止措置をroot/PV修正、全設定の正確性、性能改善や本番採用の完了と扱わない。
全局対局、Oracle同士対局、性能再測定は起動していない。

Copilotの指摘に従いCLI helpも既定turnとgame停止の案内へ更新した。
CLI integration 10 testsと実際の `--help` 出力を再確認した。
