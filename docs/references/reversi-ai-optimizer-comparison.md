# 0052 更新方式比較の実装・実行記録

## 現在の状態

0052の比較toolingを実装した。fixtureによる検証と人間操作の実比較を区別する。
実比較は未実行で、改善・不成立の実結果はまだない。0052計画を残し、採用済み0019
artifactと0018受け入れ候補は変更しない。

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

人間の完成出力が提供されたら、固定manifestと全receipt/checkpoint/ゲーム/指標をoffline
検証して、この文書へrun-root・report SHA-256・best epoch・A/B指標・各gate・実対戦数・
改善/不成立と次の判断を追記する。その後に0052を削除する。
float改善が整数化で失われた場合は、固定小数点/量子化を次の独立計画の候補とする。
自前複数cycle・opening多様化・phase偏り補正・探索強度の検討も実結果を受けた別計画とする。
