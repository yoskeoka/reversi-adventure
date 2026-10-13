# 0035 全局計測の結果レビュー（2026-10-02）

PR [#236](https://github.com/yoskeoka/reversi-adventure/pull/236) と [#246](https://github.com/yoskeoka/reversi-adventure/pull/246) はマージ済み。現行main `bbd4000` の `whole_game.py` で完成済み全14レポートを再検証した。バイナリ/artifactを再hashし、canonical JSON、棋譜、資源、比較、独立Oracle証拠の検証が成功した。長時間の測定やOracle再solveは起動していない。

元結果はworkspace `.local/reversi-ai-whole-game-0035/results/`、人間の実行手順は同じ親directoryの `run-reversi-ai-whole-game-0035.sh` にある。raw JSONはignored local evidenceで、この文書だけからraw棋譜を復元することはできない。元結果を保持し、以下のdigestで識別する。

## 条件と解釈

- 固定4合法開局×両seat、各条件8局。同一ホスト `xps` のLinux/WSL2で逐次測定。反復測定や信頼区間はない。
- opening/endgame depth=12、midgame=12または8、exact_empty=16。timeout=310秒/decision、peak RSS cap=1,572,864 KiB。
- Oracle/legacy/turn/gameはone-game-per-seat、persistentはall-games-per-seat。起動/終了は別のseat_processes。局wallはdecision区間を含む対局時間。
- 旧persistentは局間で通常TT/完全読み表も保持するため、局内だけ再利用する本来の自己対局性能の採用証拠から外す。数値は既存計測の参考値として残す。新条件は常駐しても各局の開始時に両cacheを消去する。
- Oracleは外部Egaroucid v7.8.1、bookless/one-thread。異なる探索/評価器なので、Oracleとの比率は同一アルゴリズムの改善率を示さない。
- Oracle12の8局wall合計702.164秒と人間ログの全体elapsed815.8秒は計時範囲が異なる。

## 全局時間・CPU・RSS

時間/CPUは8局合計（秒）、平均wallは8で割った値。RSSはKiB。

| 中盤深度 | 条件 | wall合計 | 平均wall/局 | user CPU | system CPU | peak RSS | decision / search |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | oracle | 702.164 | 87.771 | 831.300 | 92.351 | 1,394,572 | 440 / 432 |
| 12 | legacy | 8868.299 | 1108.537 | 8861.466 | 4.793 | 69,632 | 442 / 432 |
| 12 | turn | 8172.657 | 1021.582 | 8171.640 | 2.080 | 71,404 | 442 / 442 |
| 12 | game | 8142.245 | 1017.781 | 8141.671 | 1.658 | 71,232 | 442 / 442 |
| 12 | persistent | 8281.906 | 1035.238 | 8279.620 | 0.730 | 69,636 | 442 / 442 |
| 8 | oracle | 139.301 | 17.413 | 228.887 | 40.446 | 1,394,516 | 436 / 432 |
| 8 | legacy | 3470.021 | 433.753 | 3470.474 | 1.382 | 69,632 | 408 / 400 |
| 8 | turn | 3346.142 | 418.268 | 3346.695 | 1.302 | 71,332 | 408 / 408 |
| 8 | game | 3325.783 | 415.723 | 3326.469 | 1.257 | 71,360 | 408 / 408 |
| 8 | persistent | 3155.605 | 394.451 | 3154.780 | 0.360 | 69,636 | 411 / 411 |

diagnostic条件のsearch数にはforced passも含む。legacy/Oracleでは合法着手の数であり、単純な探索回数の比較には使わない。

## 同一局内の完全読み表保持

同じPR #236 binary、artifact、条件、棋譜でturn→gameを比較し、442/408 decisionのmove/score/completed_depth/exactness/outcomeが一致した。

| 深度 | wall短縮 | CPU短縮 | 全node turn→game | exact node turn→game | exact decision時間 turn→game |
| ---: | ---: | ---: | --- | --- | --- |
| 12 | 0.372% | 0.372% | 944,666,624 → 943,359,452 | 9,193,836 → 7,886,664 | 9.835 → 8.334秒 |
| 8 | 0.608% | 0.605% | 394,375,506 → 392,971,174 | 6,782,818 → 5,378,486 | 6.800 → 5.121秒 |

完全読みnodeは14.2%/20.7%減り、heuristic nodeは双方で同数（935,472,788 / 387,592,688）。完全読みdecision時間の短縮は約1.50/1.68秒で、全局wall短縮30.41/20.36秒全体を説明しない。残りの差の原因はこの一回の計測から確定できず、全差をcacheの効果と主張しない。cache hit総数も665,572→558,706 / 583,722→449,594に減った。8局中6局が短縮し2局が増加。

## 時間を使っているphase

exact=trueを先に分類し、それ以外をdecision盤面のoccupied<=20がopening、<=44がmidgame、残りがendgameとする。decision_elapsed_nsの和であり、CPUをphase別に直接計測した値ではない。

| 条件 | opening | midgame | endgame heuristic | exact | openingの比率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| game-12 | 3306.388 | 4787.617 | 39.806 | 8.334 | 40.61% |
| game-8 | 3171.912 | 104.205 | 44.451 | 5.121 | 95.38% |
| persistent-8 | 3017.089 | 89.266 | 45.172 | 3.982 | 95.61% |

中盤8でも序盤12が約95.4%を占め、完全読みは8局で約5秒。次の調査対象は序盤の評価/探索コスト。sparse lookupやfeature抽出が主因かは未測定なので断定しない。序盤深度を下げる案は探索条件を変える別workloadとして扱う。

## 意味一致の到達点と限界

- 独立Oracle完全solveのroot/選択継続照合は深度12が138/138、深度8が98/98位置で一致。保存済み照合証拠を再検証した。
- legacy/gameのboard/side/move列は深度12の442、深度8の408 decisionすべて一致。ただしlegacyにはscore/depth/exactness診断がなく、変更前後の全意味一致は未証明。
- persistent/gameの深度12は8局442 decisionの着手列と診断が一致。深度8は2/8局が分岐する。最初の分岐は下表。最初の分岐までの共通rootでscore/depth/exactness/outcomeの差はなかった。

| 最初の分岐ID | occupied / side | game / persistent着手 | 両者score / depth / exact | 終局黒点数 game / persistent |
| --- | --- | --- | --- | --- |
| opening-1-seat1-turn9 | 19 / W | c2 / f2 | -1 / 12 / false | 16 / -6 |
| opening-2-seat1-turn3 | 13 / W | f5 / f2 | 0 / 12 / false | -32 / 22 |

常駐深度8は411 decisionでgameの408と異なる。同点手/TT履歴が原因の可能性はあるが未確認。異なる棋譜の5.1%程度の時間差を、process保持だけによる改善と解釈しない。局間cacheを使った旧条件の原因調査によって採用可能にするのではなく、局開始resetの新条件で再測定する。

## 完了済みと残作業

0035の実装/既存条件の全局測定/turn-game比較/独立Oracle照合は完了。速度目安は未達で、Oracle測定後の正式閾値、cacheの採用理由、自己対局の設定選択が残る。変更前CLIのscore/exactnessと、通常TT/完全読み表を局開始時にresetする常駐条件を補完する。

局単位保存/再開/scriptの[0039計画](https://github.com/yoskeoka/reversi-adventure/blob/8bc7f009f645da0b5277cb83794c17b3e56afe1d/docs/exec-plan/todo/0039-reversi-ai-whole-game-resumable-measurement.md)は実装し、起動手順は[計測handoff](reversi-ai-whole-game-0035.md)へ記録した。残る[0040](../exec-plan/todo/0040-reversi-ai-self-play-performance-closeout.md)は意味証拠/序盤コスト/設定判断を扱う。0035はその判断までactive。新本番manifestは0037 pilot成功と0032の完全game/provenance検証後に0019で凍結する。

試遊で中盤深度8/12が遅く空き16の完全読みは速かったという人間の観察に基づき、
[0041の評価記録](reversi-ai-exact-threshold-reuse-assessment.md)で空き20/24も測定した。
空き20・中盤深度8は固定8局の意味/Oracle照合が通った。後続exact rootのnodesは7.22%減ったが、
全局時間差は反復なしの参考値であり、全てをcache効果とは解釈しない。
深度12設定の終盤完全読みには再利用ありで選択手の値が最善値に届かない反例がある。
0040の本番選択には正確性の修正・再検証も必要であり、今回の実験だけで高い閾値を採用しない。

benchmark artifactのdigest検証と学習元データ全体のprovenance検証は別。
0032はPR #223で全量検証を完了し計画を削除済み。2026-10-08に保存source digestを
凍結producer 790209d9のGit blobと照合し、3 sourceとも一致した。
現行sourceによるgenerator source digest mismatchを入力破損とは扱わない。
0019の新freeze前に元producer/契約で再検証し、その条件での失敗だけを別途解決する。
現在の速度・強さ・計画の境界は[判断材料](reversi-ai-current-status.md)を参照する。

## 固定入力digest

| 入力 | SHA-256 |
| --- | --- |
| legacy CLI | `7934e682513c3363d68ecd2affab6623396dc5a0c28c58bf9183050c5d94b5b6` |
| PR236 CLI | `8898cc1caafe50ba8836f09b185823b6a6af4c0c82e3dd8a13a20ebe3fcb246d` |
| Egaroucid | `b97a36a29eb4dad32a18b9edafb9eb6776cef3a96b9c198c01102c22c7c0a148` |
| baseline artifact | `d206b9bf5a86c7670c1e7c9e2cdbbeb442a94d18ba3d8efeb3423b11cbb3eb8f` |
| openings | `6147a633b6ba5bab7514b5f452b8512381cb9cda6eeae91a22e1b62d926bae83` |

## 完成レポートdigest

report_digestはそのフィールドを除くcanonical reportから計算した値で、ファイル全体のSHA-256とは異なる。

| ファイル | report_digest |
| --- | --- |
| comparison-12.json | `d38102ee9edb6af747f3a2b2f1d8505613c08f64b5cd50a59f425489f109e536` |
| comparison-8.json | `1c7fee5663766b220e4347b449dfa412fd75ac751a8f107b2b6867d5f4c8165b` |
| exact-check-12.json | `fb708ef5aabb99e3d5e4bc72e706b08390b2f160bc81b1062da7528475bcd906` |
| exact-check-8.json | `6d8372523841efc235d70e18acec0b6f8f931423c8762d643225d29d40945db5` |
| game-12.json | `66748f0dd44eee7e9944b9c6523bf2d661ff9a8af75908c11b987d50a22ab17c` |
| game-8.json | `dff1f4fd55847674da1e482581f37f5062b1db0566da13d79eb17044c81f4e56` |
| legacy-12.json | `6c51988e35d43664254973f40ac5182c1ec6ee415e623891e1be094f1b4f83f4` |
| legacy-8.json | `3bdcea328071d88a5508bf9914720aa598cfbaa7cf823f5e71932216e56279ed` |
| oracle-12.json | `a4b615fdd0116fcb628885fe644f54103f47d9f9acd0b732af035fca16b7ba5e` |
| oracle-8.json | `18334af636f0b685b044e28d878a7430dd21e53ea67df3bb9e96f7c5ab1b6d0e` |
| persistent-12.json | `82159f903abb3b98a4dff690a6bce08b9426b38b7cf3a9ec65e7b46863e6387f` |
| persistent-8.json | `f412e23b84b699c91f3b7cfbc4e45ab96c3bb6274327a6d2813d6a34aaabc340` |
| turn-12.json | `fb5a087fed96da1f5172763fbcc8d02b20a1d8b369d883a3d95ea1039c53d662` |
| turn-8.json | `501e490ffd348d1298d98664d94ee6b9b4a6a2d577f999ea2eae55d4aa0aff64` |

## 再検証と再集計

`whole_game.py verify --report <path> --binary <path> [--artifact <path>]` を10全局reportに実行する。比較2件は `verify-comparison --baseline-report <turn> --candidate-report <game> --output <comparison>`、照合2件は `verify-oracle-check --report <game> --oracle-binary <oracle> --output <exact-check>`。すべて `rtk python3 tools/reversi-ai-benchmark/whole_game.py` 経由で、verify系は測定プロセスを起動しない。

以下をworkspace rootで実行すればphase集計を再計算できる。完了reportのaggregateから上の時間表を再計算し、comparison reportのratiosとexact=trueのstepsからnode/時間を集計する。

```bash
rtk python3 - <<'PY'
import collections, json, pathlib
root = pathlib.Path(".local/reversi-ai-whole-game-0035/results")
for name in ("game-12", "game-8", "persistent-8"):
    report = json.loads((root / (name + ".json")).read_text())
    times = collections.defaultdict(int)
    for game in report["games"]:
        for step in game["steps"]:
            occupied = 64 - step["board"].count(".")
            phase = "exact" if step["search"]["exact"] else (
                "opening" if occupied <= 20 else
                "midgame" if occupied <= 44 else "endgame")
            times[phase] += step["decision_elapsed_ns"]
    print(name, {key: value / 1e9 for key, value in times.items()})
PY
```

## 0040のoffline再検証（2026-10-10）

保存済み0035入力は、登録済みlegacy manifestを使った
`prepare-whole-game-measurement.py verify-inputs --legacy-offline` で再検証した。
14件（whole-game report 10件、comparison 2件、独立Oracle照合2件）が終了code 0で通った。
これは元のscore契約とidentityに固定された既存証拠の検証であり、新しい対局や探索は実行していない。
0035/0041/0045の時間・Oracle receiptはwinner-empty-v1の性能やOracle一致を示さない。
その境界と人間判断の残件は[0040](../exec-plan/todo/0040-reversi-ai-self-play-performance-closeout.md)に記録する。
