# 0052 更新方式比較の実装・実行記録

## 現在の状態

0052の比較toolingと人間操作の実比較を完了した。fixtureによる検証と実比較は区別して記録する。
比較結果は不成立で、採用済み0019 artifactを維持する。0018の受け入れ試験は未実施である。

## 2026-10-31 Adam候補の実比較

人間操作の評価run `0053-20261026-01` をoffline verifierで検証した。

| 項目 | 結果 |
| --- | --- |
| source training root | `.local/reversi-ai-runs/0052-20261026-01` |
| source report SHA-256 | `3cd323ef29649d8c59a62267cb933a3d73db0ce56c9e00b1ac9a2e1e6a970d43` |
| evaluation root | `.local/reversi-ai-runs/0053-20261026-01` |
| report file SHA-256 | `ae00bd4957fe5e4f0ffeda824e523b177aea1f8999dac3d28468d9dca4c1f641` |
| verifier canonical digest | `8054e350e1b9faf65ed467c1fc68b8b97e7f31bbcbb4ff29e4a3d3702ff56838` |
| outcome | `not-improved` |
| baseline artifact SHA-256 | `13e8bdf59553746ba32ce47b53a09c011eb79223cabf4ddefb224b2640d283de` |
| candidate artifact SHA-256 | `e77d333d8c3f5591dfa8161e1f2f8acbf393b76ad1172bab670705f2596a56d8` |

Adamはepoch 13を整数export後のvalidation MSEで選択した。baselineのinteger train/validation MSEは
`220.75862068965517` / `321.5026490560406`。candidateのfloat train/validation MSEは
`212.06570613501674` / `323.55768953600483`、integer export後は
`715.7951843043995` / `321.8856055518245`で、validation MSEは改善しなかった。
held-out MSEはcontrol `268.0373419142408`からcandidate `266.51118760757316`へわずかに改善した一方、
corpus regretは12局面で合計14（平均`1.1666666666666667`）から合計32（平均`2.6666666666666665`）へ悪化した。
held-outとcorpusは診断値として残し、いずれも候補採用や0018受け入れの証拠にしない。

baselineとの最初の20局はcandidate 7勝・0分・13敗、7.0/20 pointsだった。
10/20 pointsの続行基準を下回ったため200局へ進まず、Oracle診断も
`20-game baseline match scored below the 10/20 continuation threshold`を理由に未実施とした。
この結果からprojected Adam方式を採用せず、0019 artifactを現在の採用モデルとして維持する。
この比較は0018のheld-out受け入れ試験を実施したことを意味しない。

次の学習方法を選ぶ専用の実行計画はまだない。0018には、丸めと開始artifact、複数cycle・opening多様化・
phase偏り補正、自前探索強度の候補方向があるが、次候補の実行前に診断結果を踏まえた別計画を作る。
todoに残る0037は同じ更新方式のpipeline pilotであり、新しい学習方法を比較する計画ではない。

2026-11-01、次候補は局所変更6案から見直し、Egaroucidの公開パターン表学習を
自前データで縮小再現する[0054](../exec-plan/todo/0054-reversi-ai-next-method-experiments.md)として計画化した。
[方式の差と選択](reversi-ai-learning-method-reproduction.md)を参照する。
128局＋序盤最大256局面で工程の成立を確認する計画で、実行は未着手。
0052/0053をEgaroucidの学習工程全体の再現と扱わず、0019採用モデルと0018の境界を維持する。

## 入力と方法

[採用記録](reversi-ai-0019-adopted-model.md)のmanifest/report/artifact identityに
一致する原本だけを許可する。全phaseと0051をoffline再構成し、自前教師3,364行と
validation13,401行を再現する。教師のsource/game_id/side視点、splitの原本keys・
採用keys・除外keysを新run-rootへ保存する。held-outは教師とvalidation・過去の露出から
独立に固定する。0018入力や外部教師を取り込む入口は設けない。

Aは0019初期baselineから現行一回更新を再生し、採用済みweight digestを再現する。
Bは同じ初期baselineからf64のprojected Adamで学習し、epochごとに整数artifactを保存する。
整数validation MSEで最も早い最良epochを選ぶ。浮動小数点だけの改善では対戦へ進まない。
既定20epochs・batch256・patience5、教師追加0局、比較20局・Oracle最大20局である。
対戦・held-out・corpusのgateと実行profileは[仕様](../specs/reversi-ai.md#frozen-optimizer-comparison-0052)を参照。

## 実行と再開

手順は[training README](../../tools/reversi-ai-training/README.md#0052-optimizer-comparison)に記載する。
人間が新しいcheckout外のrootを指定してprepare/runを開始する。agentは実比較を起動・監視しない。
prepare時のclean commitと全学習・対戦設定をmanifestへ固定する。
設定や実行sourceを変える場合は別root/manifestにする。同じrootでは保存済みcheckpoint・
完成局を検証して引き継ぎ、不完全batch/局のみをやり直す。

prepareと各phaseのreceipt、各完成batchおよびepoch境界のcheckpoint、各epochの整数artifact、
失敗記録を保持する。checkpointはweights/m/v/step/epoch/shuffle seedと順序/cursor/
best epoch/patienceを含む。整数artifactと浮動小数点stateのSHA-256は別々に保存する。
offline verifierは保存state間の算術遷移・出力・gateを再構成する。trainerコマンドや
candidate CLI/Oracleを起動せず、完成出力を書き換えない。

## tooling検証と実比較の完了境界

自動fixtureは手計算Adam・bias correction・zero-gradient momentum・projection・丸め、
同一seedとbatch/epoch境界の再開、整数化で消える改善、設定変更/非有限値/改変拒否、
split独立性・対戦gate・timeout時の完成prefix保持・offline replayを検証する。
これらは実モデル改善やplaying strengthの証拠ではない。

2026-10-25のtooling検証では、Python training suite130件（新規比較fixture26件を含む）、
engine28件・AI124件のRustテスト、workspace Clippy、GDExtension build、
`cargo fmt --all -- --check`、workflow lint、diff checkが通過した。
最終orchestrator修正後にも該当fixtureを再実行して通過した。

保存原本のread-only再構成では、0019全phase/reportの検証、Aの重み再現、
採用identity、64自己対戦局・教師3,364行・validation13,401行・corpus12局面の
一致、held-outのnonempty/disjoint検査まで通過した。
この検証processは修正前のpin収集関数をimport済みだったため、最後のOracle resourceの
論理path解決で停止した。修正済みcollectorは`resolved_path`を使い、別途163ファイルの
identity照合と対応regression testを通過している。新しい学習・対戦・Oracle solveは実行していない。

次の比較を実施する場合は、固定小数点/量子化、自前複数cycle、opening多様化、phase偏り補正、
探索強度のうち、今回の実結果で説明できる課題に対応する候補を別の実行計画で選ぶ。
