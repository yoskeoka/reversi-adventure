# Reversi AI efficiency8 closeout（2026-10-13）

TrainedEvaluatorの学習前に行う、探索器と全局ハーネスの効率計測を記録する。
探索に必要な方向性と単局面あたりの評価コストの代理として`StrategicEvaluator`を使った。
trained artifactの読み込み・評価や学習batchは測っていない。

## 固定profileと結果

- runがpinしたsource revision: `b82b04d691bffd1866cc02e28416eaebaf2b4680`
- release CLI SHA-256: `5663fa9c876d66ed5f7692371a52a20bb7202ed236a4efc1a6265a908d5b0dec`
- score contract: `winner-empty-v1`
- 設定: StrategicEvaluator、8/8/8、exact閾値16、exact cache scope `turn`、
  search time/node limitなし、1手のhang検知watchdog 600秒、1 processあたりRSS上限1,572,864 KiB
- 8局すべて完了。wall timeは2.4699、2.4461、4.2581、4.3553、8.0750、3.9973、2.3353、2.2223秒。
- 平均3.7699秒（目標180秒）。
- nearest-rank P95は8.0750秒（改善検討点300秒）。8局では最遅観測値であり、
  安定した裾の推定ではない。
- 時間値は打ち切り条件ではない。遅いことを理由に終了した局はない。
  600秒は1手のprotocol応答が止まった場合のwatchdog。

両方の効率目安を大きく下回り、このprofileについて学習前に探索器や対局ハーネスを
広く高速化する根拠はない。TrainedEvaluator自体の評価コストと学習batch総時間は別に測る。

## Oracleと資源の証拠

132個のexact局面を252回のOracle queryで照合し、全queryがexactだった。
rootと選択childのOracle evidenceおよび全局reportはoffline検証を通過した。
Oracle processのpeak RSSは1,394,576 KiBで、processあたりの上限1,572,864 KiB以内。

ここでのOracle計測はプロジェクト側のexact判断に対する正確性・資源確認であり、
Egaroucid同士の全局self-play速度計測ではない。Oracle query processのwall time合計
1,740.169秒はquery subprocess間の合計であり、1局の所要時間として解釈しない。

最初の実行はnode `xps`、machine `x86_64`、WSL2 Linux kernel `6.18.40.1`。
検証済みresumeは同じnode・machine・platformのkernel `6.18.54.1`で行われた。
reportには両方のinvocation記録があり、元のrun identityを維持している。

## 保存した証拠

検証済みartifactは`/home/yoske/reversi-ai-efficiency8-run-2026-10-13/`に保存されている。

| artifact | file SHA-256 | 内部report digest |
| --- | --- | --- |
| `summary.json` | `d5cacc4bd2759976b5ddf62f1c21d9941177c9406dc78ad5685149fdc3450a5f` | `6e8679ba1aadfcc68ad8cc97b9191920e997c816e06e69a746f9f155fe242832` |
| `whole-game-report.json` | `9c2cf8fe38ca23ce244b0d674ea9118b4755f5ca64e82dd3f66a6901cbedfbf` | `2eea3c6e00536a41d3c00e98d3bd346d58c990077add5807ffae081fe33ae677` |
| `oracle-evidence.json` | `70f814a45b56cabe376b5acfc820ff7c07ced3a18ef0f6c3fb5522251e8ddeb8` | `ed111a1f6090cd3fd98b9e021bbdf2f51f524453b721b6334f0a0f0fff685e9e` |

run identity digest: `246ff77b8be1260f8c7744727e5fa37025769cb380e092ce844923e8a1b586e1`。
Oracle binary SHA-256: `0381e279206317c6d678d066c505afdb9b7d20eda7db62eef6f420c1bf009312`。

## 判断と残作業

0040の固定profile計測、全exact局面のOracle照合、資源観測、性能判断は完了した。
ただし、exact開始を16空きより早めたときにexact tableの`game` scopeが有効かは分からない。
診断機能は保持し、本番のexact16/`turn`は変更しない。0035は、学習方法が選んだ閾値
（例: 30空き）での範囲限定評価が必要か判断するために残す。通常探索のTTはexact tableの
`turn`とは独立して、すでに同一対局内で手番をまたいで保持される。

0037の学習方法pilot、0019の本番入力・候補cycle、0018のheld-out Oracle受け入れは別作業として残る。
