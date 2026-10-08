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

## 縮小検証の実装とhuman-run準備（0045）

2026-10-07。修正済みmain 1f2eb5aから専用
exact-cache-verification-v1 prepare/run/verifyを実装した。
ordered sampleはopening-1/2/4、assignment 0のみ。turn/game各3局、
12/8/12・exact20・seatごと1game/1processでserialに測る。
CLI decision上限310秒、Oracle新規query上限30秒、RSS上限1,572,864 KiB。
新規Oracle queryは最大18、抽出は最初の<=12、最初の<=8、最後の<=12
という最大9rootであり、存在しないselectorを追加局面で置換しない。

独立Oracle完全読みprofileは旧保存queryと同じdepth12/exact20を使用する。
測定CLIのmidgame depth8とは別のidentityであり、board/effective side、
binary/profile digest、score契約の完全一致時だけ旧queryを再利用する。
旧producer 42f6d575b7115b4ccd6aa2ab6d9d805adadc1b89のコードをGitから
読み出し、manifest、24 pilot/32 full/112 pilot-Oracle/584 full-Oracle、
計752 receiptと派生stage/assessmentをoffline再計算した。
元manifest digestは
7d3104d720fdbe605839af893a0ff4c47207e423d9b3eec633a6add1728de960。
8件の保存counterexample receiptはfixtureの実ファイルSHA-256とsealに一致し、
root +4、a4 +4、a7 +2を確認した。元failed receiptは失敗のまま保存する。

clean checkoutのlocked release buildと入力CLI SHA-256を照合し、
source/harnessファイル、artifact、Oracle評価資源、sample、host、outputを固定する。
保存game/queryの成功と失敗は再開時に検証してskipし、中断単位だけ再実行する。
未知/破損outputや変更identityは探索前に拒否する。
完成3局だけ条件平均を生成し、意味不一致やOracle不成立の場合は平均を採用証拠にしない。

準備時点では6局のhuman-runと抽出Oracleの結果は未受領だった。
2026-10-08に人間の実行結果を受領し、下記のoffline verifyで確認した。
エージェントは長い対局や新規Oracle solveを起動・待機・監視していない。
反復なし・assignment0の選択sampleであり、3局成功も一般的な
正確性や有意な速度差を保証しない。抽出外rootを独立照合済みとは扱わない。
本番turn/exact16、空き16の±39/±40未解決score契約、0040の人間判断を残す。
0045計画は準備時に測定受領/検証待ちとして残し、下記の検証後に削除した。

### 固定済み入力と実行

source/harness revisionは `2516a63db511d8cada44624bbd97dec910768f22`。
出力はworkspaceの
`.local/reversi-ai-exact-cache-correctness/run-0045-2516a63/`。
manifestは全input/source/harness/Oracle評価資源/hostとoutput registryを保持する。
ファイル一覧を持つmanifestを受領時の正本とし、個別receiptと派生reportを再計算する。

| Evidence | SHA-256 / canonical seal |
| --- | --- |
| Manifest seal | `44d8a52750e4c4606b5d9ede2ff9b4bc031e4f5670cbf5637f9a8792afcbd75d` |
| Manifest file | `3c7ccaf8e6c2dbbbb28b0088d464360c8e16fc99a83f94cf41d52f656f7e0614` |
| Regression seal | `50daaa40d1f0fb134ca3581e2b1d93b5c940cab244b1d7cd384db60376d216f1` |
| Launch script | `09c2758f7cffd72966952e44a5ba2adfd68f81535fe2307f1230bb2a8b0b9352` |
| Repaired release CLI | `323cb7460bcf3f621221c65b506d748402cc05594f4d2f8589682b404c5b5dc7` |
| Evaluator artifact | `d206b9bf5a86c7670c1e7c9e2cdbbeb442a94d18ba3d8efeb3423b11cbb3eb8f` |
| Three-game sample | `4fadb5144ad54e74320bd4cecf574136d0c6e969f9aab2dfbf58f37e404516d0` |

prepareが実行した短いfixtureは、warm suffixの選択child/PV証明、
bound/collision/中断再開、空き4以下の全到達局面・pass/終局の3件。
全件成功。新しいOracle solveは0、全局測定は0。
入力済みscriptは人間がworkspaceから一行で実行する。

```bash
rtk bash .local/reversi-ai-exact-cache-correctness/run-0045-2516a63/run-exact-cache-verification.sh
```

同じscriptを再実行すると検証済み成功/失敗単位をskipする。
結果を受領したら、このworktree内で
`rtk make benchmark-exact-cache-verification-verify EXACT_CACHE_VERIFICATION_MANIFEST=<絶対manifest.jsonパス>`
を実行する。ソースを変更した場合は旧freezeを更新せず、再prepareで新directoryを作る。
source/harnessファイルを変えない後続docs commitはfreezeを無効化しない。

quality gates: engine 28、AI 114、Oracle harness 40、pattern training 31、
新しい専用offline tests 38、Clippy、Godot build、fmt、diff/workflow lint成功。
benchmark全体の最終件数はPR Verificationへ記録する。
準備時点では実測結果は未受領だった。以下に測定とoffline検証を記録する。

## 人間の6局測定とoffline検証（0045完了）

2026-10-08。人間が固定scriptを実行した結果を受領し、上記manifestを指定して
`rtk python3 tools/reversi-ai-benchmark/exact_cache_verification.py verify --manifest <絶対manifest.jsonパス>`
を実行した。終了code 0、最終進捗6/6 verified（6.394秒）。
752件の旧receipt、固定input/source/harness、短い回帰3件、保存6局、Oracle stageと
10 query、派生reportをoffline再計算した。全game/queryはskipされ、新規探索は0。
turn/game各3局はcompleted、全3組の棋譜・盤面・score・depth・exactness・outcomeが一致した。
timeout/RSS超過、policy不一致、Oracle不成立は0件。旧failed receiptは変更していない。

### 保存された証拠

出力directory、source/harness revision、CLI/artifact/sampleは上記freezeと同じ。
manifestとregressionのsealも変わらない。次のsealと実ファイルSHA-256を固定する。

| Evidence | Canonical seal | File SHA-256 |
| --- | --- | --- |
| `oracle-manifest.json` | `01d2749ed113ac84373d25814e065b4e4dc6d59680863bc039592e28bab066c3` | `246ea9b76575e57c546e2b6181e97ec55f77b88e3427ca65c5913fbb4d797458` |
| `report.json` | `c2d3714b4e99610009ca9abb9234aa17128688347f3f2e16e76454e1bc55ff6b` | `e9a5d899fb5555c908ae058f21a1da23205bd249b06262cd89cafe2e4c263192` |

6 game receiptのsealはreportのordered `game_digests` と対応する。

| Scope | Opening | Game receipt seal |
| --- | --- | --- |
| turn | 1 | `a3d9629aee5ccd13f88090d5fbcb8e897c39538028befa935c82ee818ad18bc2` |
| turn | 2 | `688e8b11eb8741e1f26b1e79f3f407ca2b9c8b0803cb4c15938f8316b3f8a088` |
| turn | 4 | `7c7ca911e9f3c78c6212d8b19b459a0edc3ef60580d17769aa547d63423db5c2` |
| game | 1 | `6d7da26f357a0a352eac3306936d3850570b4beacd851b6df7613aec4aef118f` |
| game | 2 | `b3f77ee83c0d9811083ab9c37e840ff88510f849aa3341f398075d2ef0713da8` |
| game | 4 | `0527174e91d96af850a8bca32521b4c378ed94e991574505e449bab8fa038ae0` |

### 局別資源とexact部分

wallはprocess起動/resetを含む全局、exact秒はexact decisionのelapsed合計。
user/system CPUはseat process合計、RSSはseat最大値（全局72,276 KiB）。
raw資源観測、legal-count/phase、policy/reset ackは各receiptに残る。

| Scope | Opening | Wall s | User CPU s | System CPU s | Exact s | Exact CPU s | Exact nodes | Exact hits |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| turn | 1 | 387.587 | 387.101 | 0.281 | 70.616 | 70.590 | 72,501,028 | 7,158,273 |
| turn | 2 | 484.634 | 484.153 | 0.257 | 83.756 | 83.730 | 90,140,571 | 7,257,930 |
| turn | 4 | 685.541 | 685.061 | 0.244 | 1.351 | 1.340 | 1,543,770 | 269,426 |
| game | 1 | 382.962 | 382.582 | 0.196 | 71.864 | 71.830 | 71,415,159 | 7,056,626 |
| game | 2 | 468.950 | 468.572 | 0.184 | 79.477 | 79.450 | 89,738,268 | 7,224,594 |
| game | 4 | 654.749 | 654.381 | 0.200 | 1.163 | 1.160 | 1,396,032 | 227,422 |

| Scope | Mean wall s | Mean exact s | Exact / wall | Mean heuristic s | Mean exact nodes | Mean heuristic nodes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| turn | 519.254 | 51.907 | 10.00% | 466.518 | 54,728,456.333 | 51,729,310.667 |
| game | 502.221 | 50.835 | 10.12% | 450.678 | 54,183,153.000 | 51,729,310.667 |

gameの平均wallはturnより17.033秒（3.28%）短いが、exact部分の差は
1.073秒（2.07%）、exact nodesの差は約1.00%に留まる。
heuristic nodesは同じで、heuristic時間差15.840秒がwall差の大半を占める。
この時間差をcache効果とせず、3開局・assignment0のみ・反復1回の観測値とする。
opening-1のexact時間はgame側が長く、有意な高速化や一般的な正確性は主張しない。

### 独立Oracleの抽出範囲

stageの順序はopening-1、opening-2のそれぞれ最初の<=12、最初の<=8、最後の<=12。
6 rootと非終局child4位置、計10新規queryが全件completedし、旧queryの再利用は0件。
最後の2 rootのchildは終局値で照合し、追加queryを作らなかった。

| Opening | Step suffix | Empty | Move | Root score | Selected child (root view) |
| --- | --- | ---: | --- | ---: | ---: |
| 1 | 42 | 12 | d1 | +22 | +22 |
| 1 | 46 | 8 | a5 | +22 | +22 |
| 1 | 53 | 1 | b1 | -22 | -22 |
| 2 | 42 | 12 | d7 | -36 | -36 |
| 2 | 46 | 8 | b3 | -36 | -36 |
| 2 | 53 | 1 | a1 | +36 | +36 |

opening-4は41 decisionで黒48/白0、空き16で終局した。最後の探索rootも空き17で、
<=12/<=8 selectorは全て存在しないため抽出0件。高い空き数のrootへの代替や追加対局は行っていない。
抽出外root（opening-4を含む）を独立Oracle確認済みとは扱わない。
新規Oracle queryの最大wallは22.160秒、最大RSSは1,394,512 KiBで固定上限内だった。

### 0040へ渡す境界

人間の固定6局測定とoffline検証を完了したため0045を削除する。
本番設定はturn/exact16を維持し、診断game/exact20の本番採用は承認しない。
未解決の空き16 ±39/±40 score契約、設定/時間予算/採否の人間判断、必要なproduction
spec/policy/manifest互換更新は0040に残る。0035や学習freezeの完了とは扱わない。
保存reportの `remaining_blockers` にあるhuman-run acceptanceは生成時の固定文言であり、
受領後の検証完了はこの記録とPRで示す。reportを変更して後付けの採用証拠は作らない。
