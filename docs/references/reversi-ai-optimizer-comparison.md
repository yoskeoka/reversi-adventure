# 0052 更新方式比較の実装・実行記録

## 現在の状態

比較toolingと人間操作の実比較が完了した。2026-10-26の結果は`not-improved`で、
offline verifierも完了reportを再構成して検証した。結果を本記録に固定し、0052計画を
closeoutする。採用済み0019 artifactは変更せず、0018受け入れも実施していない。

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

## 2026-10-26 人間操作の比較結果

人間がrunを完了し、`optimizer-compare verify`が成功した。A/Bは同じ0019初期baselineと
3,364行の自前教師で比較した。新しい教師対局は生成していない。

| identity | 値 |
| --- | --- |
| run root | `/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.local/reversi-ai-runs/0052-20261026-01` |
| execution commit | `725bf637402c3ba6c037f20dc93ca8fd97453215` |
| manifest digest | `9df3d46b2c9ec9d3cf44c051f57238d1ac336c0d29876eb139529ab7fc59c224` |
| manifest file SHA-256 | `f75e0d34af7a96d507fbf381318f7804d2ec5642c6f5bcc015fe5d7db7aab334` |
| report canonical digest | `6a96a4e115603cb49884f4a8b9007c95be8c1b0bcdbf740422ac9db4101687c0` |
| report file SHA-256 | `3cd323ef29649d8c59a62267cb933a3d73db0ce56c9e00b1ac9a2e1e6a970d43` |
| candidate artifact file SHA-256 | `e77d333d8c3f5591dfa8161e1f2f8acbf393b76ad1172bab670705f2596a56d8` |
| candidate artifact digest / weight digest | `1bfe822be189a117c6a1bdc5886812c24ba3eddc7f7ef2bf74fc69a7a04ddfed` / `04acdcba8b2c8240d2802f5780bf40612440a279e807483e4586a922e6d183d9` |
| offline verification | `optimizer-compare offline verified digest=6a96a4e115603cb49884f4a8b9007c95be8c1b0bcdbf740422ac9db4101687c0` |

The manifest fixes learning rate `0.01`, beta1 `0.9`, beta2 `0.999`, epsilon `1e-8`, L2 `0`,
batch `256`, maximum `20` epochs, seed `20261025`, patience `5`, and decision timeout `1800` seconds.
The selected integer export was epoch 13 of 18; Adam training took `729.3688` seconds.

| metric | A: one integer update | B: projected Adam, selected integer export |
| --- | ---: | ---: |
| train MSE | `220.75862068965517` | `715.7951843043995` |
| validation MSE | `321.5026490560406` | `321.8856055518245` |
| held-out MSE | `268.0373419142408` | `266.51118760757316` |

Held-out contained 13,363 records and its gate passed. The validation gate did not pass because
B's integer validation MSE was higher than A's. At epoch 13, float validation MSE was
`323.55768953600483`, also higher than A; this result does not show a float improvement erased
only by integer export.

The report outcome is `not-improved`, a complete valid comparison result. The comparison match,
corpus diagnostic, and Oracle match all have status `not-run` with reason
`integer validation MSE did not strictly improve`; zero games or positions were counted as
completed. The adopted model was not replaced, and this run is not 0018 strength-acceptance
evidence. Any further optimizer settings or update method require a separate plan and manifest.
