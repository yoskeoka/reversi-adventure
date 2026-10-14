# 0037 pilotツールの検証と実runの境界

2026-10-14、merged main `b7efbff10e96aa8aed641418f8e5bb9ed9d72cf5`から
`feat/reversi-ai-training-method-pilot`で実装した。
新契約の本番入力はまだないとユーザーが確認したため、この記録はツール検証を扱う。
実pilotの改善結果ではない。

## 実装した契約

- `pilot.py`の独立prepare/run/verifyとMake targets。
- 黒先手の合法6自己対局、重複排除後768教師行以下、座席交換10完全ペア20比較局。
- winner-empty-v1終局教師値、一回の既存bounded update、独立validation/held-out誤差。
- saved Oracle goldenの値からcorpus regretを再計算し、Oracleの追加solveを起動しない。
- frozen input/CLI/source identity、合法opening/全局replay、全指標とoutputのoffline再構成。
- timeout/未完了/改変/空の独立指標を拒否し、失敗時の完成済みゲームとartifactを保存。
- 全入力で`tooling_only=true`、`strength_inputs=false`、`improvement_observed=false`、
  `production_authorized=false`。callerのproductionラベルは改善認定に使わない。

一次資料の確認内容と採用理由は[学習方法調査](reversi-ai-training-method-review.md)、
起動・停止・再検証の手順は[README](../../tools/reversi-ai-training/README.md)を参照する。

## 検証

Rustはtask専用`CARGO_TARGET_DIR=/tmp/reversi-ai-0037-target`を使用した。

| gate | 結果 |
| --- | --- |
| `cargo test -p reversi-engine -p reversi-ai` | 151件成功 |
| `cargo fmt --all -- --check` | 成功 |
| `cargo clippy --workspace -- -D warnings` | 成功 |
| `cargo build -p reversi-godot` | 成功 |
| Oracle Python unit tests | 46件成功、live Oracle solveなし |
| `make pattern-training-test` | 認定無効化後に全63件成功（222.351秒）。修正前62件のlogは `/tmp/reversi-ai-0037-training-tests.log` |
| Pilot Python unit tests | 19件成功、fake CLIのみ、production改名でも認定不可 |
| 既存reinforcement / score移行の再検証 | 23件 / 10件成功 |
| Rust CLI artifact probe | reset ackと合法手d3を確認 |
| `tools/workflow-lint.sh --mode=pre-push`（PR title/body指定） | 全checks成功、fixable/advisory warningなし |
| `git diff origin/main --check` | 成功 |

Python trainingの初回検証はGodotの初回コンパイルと同時で、既存fixture CLIの
短いprotocol watchdogにtimeoutが発生した。入力やproductionの上限を緩めず、
コンパイル後の個別再検証と全62件の再検証は成功した。pilot fixtureのwatchdogは30秒とし、
timeout fail-closedそのものは故障注入で検証する。

## 完成fixtureの不変出力

`/tmp/reversi-ai-0037-fixture-reviewed/`にmanifest・全入力・summary、`output/`に全5出力を保存した。
認定無効化後に新しい保存先で再生成した。修正前のfixtureは元の保存先に残した。
これはfake CLIと小さいlicensed fixtureであり、実project-AI対局を示さない。
同じmanifestの2回実行がbyte単位で一致することはunit testで確認した。
offline verifierはCLI/Oracle起動を禁止するmockの下でも全出力を再構成した。

| identity | 値 |
| --- | --- |
| manifest digest（内部canonical identity） | `c5f71816a13f75ae685ce3794f03c693baf6db603c125f245ce10db9c2067c04` |
| manifest file SHA-256 | `96a697a5663d362b4329afbefa299dc50b2790a84d1bcc3de4ae3988340f77f8` |
| baseline artifact digest | `0bdbe54c3260f5d61ddcacdcba9132c9b5739c17bbeb81b25c3a032b01ad79b7` |
| candidate artifact digest | `d66cb04414b52cc695cfb4036d65397abeb5400fc8dfffd0ad7f9ce066e86c42` |
| candidate file SHA-256 | `7627abb140889714307e322e6f075e150ab4b7eebfd957e57b5af832a626aa6e` |
| report digest | `1b72311d0379a9ec6e380d020cd0c80ea29585a030f20ce7f26c9f0f68bec1cb` |
| report file SHA-256 | `fd0cf78cf57e7417d7a635d2529ddaff886cb39b1b14f597e37ec610c16903bc` |
| games file SHA-256 | `009090f0e7c9c31f1ec6258af9ef88c49105eef7449ddca67a9e369df2d80ee3` |
| teachers file SHA-256 | `d49dc7f49ba5f510a2e33329d4e5fe54fae6148ab43f83951a7f20f0eaa9961f` |
| corpus decisions file SHA-256 | `ab105cda416daa075101778a8fbede2e7d3b2ff8207bccba73ceead424105bfa` |

実数は6自己対局・318重複排除済み教師行・10完全ペア20比較局・7 corpus局面・1390 decisions。
全教師は合法replay後のterminal値で再計算した。

| fixture指標 | baseline | candidate | サンプル |
| --- | ---: | ---: | ---: |
| validation SSE / MSE | 5200 / 100 | 5222 / 100.4230769 | 52 |
| held-out SSE / MSE | 16848 / 324 | 13382 / 257.3461538 | 52 |
| corpus regret sum / mean | 0 / 0 | 0 / 0 | 7 |
| candidate比較 | — | 10勝10敗0分、10 match points | 20局 |

数値上の改善/悪化上限checksは満たすが、fixtureで`strength_inputs=false`のため
`tooling_only=true`、`improvement_observed=false`、`production_authorized=false`。
この結果を実pilot成功として0019へ渡さない。

実Rust CLI SHA-256は`86ed05425eda0bd1d3ff0a501725ddc04c541bc99b02989f1bc796b23314d416`。
fixture candidateを読み込み、`new_game`のready ackと標準盤面の合法手`d3`を確認した。
probeは1/1/1・exact16・turn・1000ms/1000nodesの一局面だけであり、対局性能や強さを示さない。
raw probeは`/tmp/reversi-ai-0037-fixture-reviewed/runtime-probe.json`に保存した。

## 未完了工程

Copilotの指摘により、自己申告のsource/profileと一致hashでは独立producerを認証できないと確認した。
改善認定はこのreleaseでは無効にした。実pilotの成功認定を有効にする前に、独立承認した入力identityと
producer manifest・CLI・saved Oracle outputの対応を認証する仕組みを別のreview済み計画で実装する。

実pilot用のwinner-empty train/validation/held-out、baseline artifact、対応trainer manifest、
新契約strong-engine Oracle corpus/golden、独立0018予約position keysが必要である。
本番入力生成・baseline学習は件数/上限/進捗/再開を固定する別の人間操作計画で行う。
その後、immutable pilot manifestをprepareし、人間がrunを起動する。
完成した不変出力だけを後からoffline検証し、改善または不成立を記録する。

0037計画は残す。成功した独立実pilotの検証前に0019の本番manifestを凍結しない。
0018の50%勝率や一般化の証拠は別のheld-out受け入れである。
