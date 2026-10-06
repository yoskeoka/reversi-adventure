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

## 選択手の証明修正（0044）

2026-10-07。0043がマージ済みの `0015b09` を基点とする。
保存済み0041の8 receipt（turn/game × assignment 0/1のCLIとOracle）を
offlineで照合し、canonical report digest、実ファイルSHA-256、manifest/source
identityを固定した。全53着手を合法に再生し、passなしで白手番・空き7の反例へ
到達した。入力とdigestは
`tools/reversi-ai-benchmark/fixtures/exact-cache-counterexample-v1.json` に保存した。
元gameのa7/+4、選択childの白視点+2という失敗証拠は変更していない。
保存Oracleはroot +4（Oracleの選択はa5）、a4 childの黒視点-4、a7 childの
黒視点-2であり、a4だけを唯一の最善手とは扱わない。

### 短い再現と原因

空き7のcold tableへnull-window [3,4]を入れる2呼び出しでは再現しなかった。
同じ盤面の整数null-window全域を試しても選択childの不一致はなく、窓[3,4]を
原因と断定しなかった。保存棋譜の白側suffixを試し、空き9→7、11→9→7では
通過し、13→11→9→7で元のa7/+4/child +2を再現した。
先行3rootだけをfull-windowで解き、同じtableで空き7を解く。
通常testへ序中盤の深度12探索や全局対局は持ち込んでいない。

原因は、scalar/general両経路でcached LOWERのscoreをalphaへ代入し、
その更新後の窓で最善手/PVを作っていたことにある。最善値の下限+4があっても、
あるchildが+4以下というfail-low結果だけでは、その手が+4を達成する証明には
ならない。最初のその手をbestへ置き、後続の真の最善手もalphaと同値に抑えられると、
strict greater-than更新が働かず、値+4と値+2の選択手が結び付いていた。
`original_alpha` の保存位置だけを変えてEXACTへ昇格させても選択手の証明にはならない。

修正は両経路の非cutoff LOWERによるalpha引き上げを除去するだけである。
EXACT hit、LOWER/UPPERによる証明済みcutoff、表容量、衝突identity、置換方針、
探索順と同値時の選択規則は維持する。最善手を証明する探索は呼出元の窓を保持し、
EXACTのPVに採用する手には、その値を達成する継続の証明が必要となる。

### 同一fixtureの旧/新結果

`retained_lower_bound_proves_selected_counterexample_child` を現行testsと
基点mainのproduction `endgame.rs` の組合せで実行し、独立child値のassertionが
`left: 2 / right: 4` で失敗することを確認した。同じfixtureとtestsで修正後は
a4/+4/child +4、全4solve合計46,017 nodes、cache hits 4,207で成功した。
修正前のsuffix合計は45,978 nodesだった。nodesはこの小さい再現の診断値であり、
速度改善や全設定の性能・正確性の証拠ではない。

rootとa4/a7 childはproduction PVSとは別の既存 `full_window_reference` で解く。
選択child値の一致に加え、PVの各着手を独立完全読みで確認し、合法着手、暗黙passの
符号、終局とterminal scoreを検査する。空き1〜4の到達局面ではLOWER/UPPERを
実探索で生成してからfull-windowへ戻し、forced-passと終局も照合する。
空き7でも両bound、capacity=1の衝突/置換、bound保持中の中断と再開を確認する。
中断rootはscore/PVを出さず、`exact=false`、`completed_depth=0`となる。

### 診断用gameの境界と残る制約

CLIの既定/明示turnと共有AI/学習の既定は0043の停止policyを保持する。
明示 `--exact-cache-scope game` だけが診断用engineを作り、decision間でexact
tableを保持する。Advisorはgameを拒否し、共有Advisor境界も毎回消去する。
`new_game` とsearch context変更は両scopeのtableを消去する。
探索のstderr診断に加えて `exact_cache_policy_v1` の別行へposition id、実効scope、
turnの `exact-cache-cross-decision-suspended-v1` またはgameの `diagnostic-game-v1`
を記録する。既存 `search_diagnostic_v1` はcurrent parser互換のため変更しない。
whole-game/prepareとreinforcement manifestのproduction停止措置は維持する。

0045の縮小診断と0040の採用判断は未完了であり、この修正で再有効化しない。
空き16の±39/±40のscore差も別の未解決の採用阻害条件として残す。
長い計測・Oracle同士対局・閾値総当たりは起動していない。

### 最終quality gates

- `cargo test -p reversi-ai`: 114 tests、7 suites成功。
- `cargo test -p reversi-engine`: 28 tests成功。
- `make oracle-test`: Oracle harness 40、benchmark 95 tests成功。
- `make pattern-training-test`: 31 tests成功。
- Clippy（workspace、warnings拒否）、GDExtension build、fmt check、diff check成功。
- 新CLIの実際のturn出力を既存whole-gameのfull-match parserで受理できた。
  既定/明示turn、診断gameのpolicy別行、再利用とresetはCLI integrationでも検査した。

単独回帰の再実行は
`rtk cargo test -p reversi-ai retained_lower_bound_proves_selected_counterexample_child -- --nocapture`。
fixtureのbudgetはsuffix全体で100,000 nodes、表容量は262,144 entriesである。
