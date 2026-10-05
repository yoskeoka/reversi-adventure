# 空き16/20/24・局内完全読み再利用の評価記録

2026-10-05、人間がnode制限ありのpilot/Oracleを完走した。Oracleの終了時RSS観測に不具合があり、
fullへ進めた閾値はなかった。人間指示でnode制限を撤廃し、新条件を別directoryで測定する。
速度改善や採用候補を示す証拠はまだない。0041はactiveのまま残し、
production exact=16と0018の候補対戦設定は維持する。

## 入力監査と承認された補完

既存game-8から空き24のlegal decision rootをopening/assignment/turn順で走査した。
重複排除キーはboard+side。黒は3種類、白は1種類だった。
opening-4のassignment 0/1が白を担当するが、両方の盤面は同一である。
0039の新binaryのgame-8も黒3・白1で、現契約の黒2・白2を用意できない。

| 入力監査 | 値 |
| --- | --- |
| source | workspace `.local/reversi-ai-whole-game-0035/results/game-8.json` |
| source report digest | `dff1f4fd55847674da1e482581f37f5062b1db0566da13d79eb17044c81f4e56` |
| raw監査 | workspace `.local/reversi-ai-whole-game-0035/exact-threshold-0041-input-audit.json` |
| 監査report digest | `0eefe1f4d8c100b0f7829ff08f80ff28e81df3338beca3cbf30b019e4b3d450d` |

2026-10-04、人間が白の対称変換追加と変換履歴の保存を承認した。
opening-4-seat0-turn31の白rootを180度回転し、4番目のwindowへ追加する。
標準初期盤面と色を保持し、開局と全prefixのboard/moveも同じ変換で固定して合法replayする。
fallback順序はrotate-180→main-diagonal→anti-diagonalで、最初の異なる盤面を選ぶ。
白の2windowは対称variantで相関があり、独立棋譜が2種類になったとは主張しない。
上の入力不足監査は補完前の事実として保存する。

| window | 色 | 元decision | 変換 |
| --- | --- | --- | --- |
| 1 | 黒 | opening-1-seat0-turn30 | identity |
| 2 | 黒 | opening-2-seat0-turn30 | identity |
| 3 | 白 | opening-4-seat0-turn31 | identity |
| 4 | 白 | opening-4-seat0-turn31 | rotate-180 |

## 測定の構成

- pilot: 16/20/24 × turn/game × 4window = 24。depth12/8/12、node capなし、310秒/decision、1,572,864 KiB/seat。
- pilot独立Oracle: 保存済み完成windowの各exact rootと選択継続を完全solve。位置totalを別manifestで固定し、1位置ごとにraw Console output・wait4 CPU/RSS・profileを保存する。
- gate: 同じ閾値のturn/gameで全4windowが完成し、履歴・着手・score/depth/exactness/outcomeが一致し、全Oracle位置が完成した閾値のみ通過する。
- full: gate通過閾値 × depth12/8 × turn/game × 8局、最大96局。node capなし、同じtimeout/RSS cap。閾値16も同じbinaryを使って測定する。
- full独立Oracle: 新しい完全読み領域を含む全exact rootと選択継続を照合する。

CLIとOracleはいずれも探索中にRSSを監視する。各seatの初期cacheはwindow/局ごとにresetする。
raw decisionは合法手数、phase、score/depth/exactness/outcome、node/cache、CPU counter差分、process累積RSSを保持する。
全局wallにはseat起動/reset/終了を含み、decision wallは別に残す。
phase CPUはLinux clock tickの精度であり、wait4の局CPUと同じ精度とは主張しない。
first exact rootとその後のrootはseat別に区別する。

完成unitと失敗unitをatomic保存し、再起動時に独立検証してskipする。未完成unitは再実行する。
失敗したunitを自動再試行しない。既存証拠が不正なら新しいprocessを起動せず拒否する。
同じ閾値・深度の全8局が両scopeで完成して照合も通るまで、平均や改善率を生成しない。
反復なしの小さな改善に有意性を主張しない。

## prepare/run/verify

prepareは `rtk make benchmark-exact-threshold-prepare EXACT_THRESHOLD_PREPARE_ARGS='...'` または
`rtk python3 tools/reversi-ai-benchmark/prepare-whole-game-measurement.py exact-threshold prepare ...` を使う。
入力は `--cli-binary`、`--oracle-binary`、`--artifact`、`--source-report`、新しい絶対pathの
`--output-dir`、binaryの `--source-revision`、実行checkoutの `--harness-revision`。
revisionは40桁のcommit SHAで固定する。prepareはreset protocolの短いprobeだけを行い、探索を開始しない。

harnessの修正後に保存済みpilotを引き継ぐ場合は、prepareへ `--resume-manifest <元manifest>` を渡す。
元manifestと保存済みunitをdigestで固定し、binary/source/artifact/host/roots/caps/search条件の一致と
元harnessのcommitを検証する。新しいdirectoryに出所付きreceiptを生成し、元ファイルは変更しない。
未保存のwindowは再実行する。

prepare完了後、人間が表示された `rtk bash /absolute/path/run-exact-threshold.sh` を別terminalで1回実行する。
scriptはpilot→独立Oracle→gate→full→独立Oracle→assessmentを同一hostで逐次実行する。
再開も同じ1行。`--progress-every N` をscriptへ追加できる。
pilotとgateだけなら `exact_threshold.py pilot --manifest <path>`、入力だけの再検証は
`exact_threshold.py verify-inputs --manifest <path>`、完成/失敗全証拠のoffline再検証は
`rtk make benchmark-exact-threshold-verify EXACT_THRESHOLD_MANIFEST=<path>` を使う。

測定後は `assessment.json`、stage manifest、unit/位置reportのdigestと各条件の失敗・node/CPU/wall/RSSを
この文書へ転記し、0040へ選べる条件を渡す。高い閾値のproduction採用には別のspec/manifest互換更新計画が必要。

## このworkspaceの起動先

固定入力の準備先はworkspace `.local/reversi-ai-whole-game-0035/exact-threshold-0041-<harness HEAD>/`。
CLIは `.local/reversi-ai-whole-game-0035/target/exact-0041/release/reversi-ai-cli`、
source revisionは `fc1c841d4b6e7136dd74f8825d642a671bd96001` のRust sourcesからrelease buildしたもの。
Oracle/artifact/元game-8は既存0035証拠と同じ実ファイルをpinする。
manifestはprepare時のharness commitと全依存Pythonのdigestを記録する。

workspace rootで人間が実行する1行:

```bash
rtk bash .local/reversi-ai-whole-game-0035/run-exact-threshold-0041.sh
```

script生成と入力のoffline検証だけをagentが行う。測定開始・待機・監視は行わない。
このlauncherは最後に準備したHEADのscriptを呼ぶ。以前のmanifest/scriptは元のdirectoryへ保存し、上書きしない。
人間の測定後、同じworktreeで `rtk python3 tools/reversi-ai-benchmark/exact_threshold.py verify --manifest <launcherが使うdirectory>/manifest.json` を使って再検証する。

## RSS検証停止の修正

最初の実行はharness `c3fdcfaeae4d2869f0c56c3dcf5e76f24d22d206` で、
`pilot-16-8-turn-window-1-seat0` を保存した。2window目は
`decision resource totals mismatch` で停止し、unitは未保存だった。

原因は実行中の `/proc` VmHWMが終了時のwait4 RSS以下になるという検証条件だった。
短い8 MiB child probeでもVmHWM 16,524 KiB、wait4 16,440 KiBとなり再現した。
生値はworkspace `.local/reversi-ai-whole-game-0035/rss-accounting-probe.json` に保存した。
Linuxの[proc_pid_status(5)](https://man7.org/linux/man-pages/man5/proc_pid_status.5.html)は
VmHWMの値をinaccurateと記載している。

修正後は両方の生値を保持して最大値をunit RSSに使い、各値の上限を検証する。
CPU差分とwait4合計の照合は維持する。保存済み1windowは上の引継ぎ手順で再利用する。

## node制限ありの初回結果と再測定

人間がharness `8e69c1949e7b2cf239202f5f7ed47c8e7838449e` のrunを完了した。
元directoryはworkspace `.local/reversi-ai-whole-game-0035/exact-threshold-0041-8e69c19/`。
manifest digestは `d033f428cddd197d7540755dce39be551ddfd0a312f5f57ffb2bd15f80b2f6e1`、
gate digestは `804e51f354b11123e5857d8f72e063b978883447edf44a46ce7b346abdb0862e`、
assessment digestは `8ce914b3aa4cebb39ac682726791b2e7c660b9c60ebd137b9a6cc3b5f8d58f21`。

| 閾値 | 完成 / 失敗window | 観測nodes合計 | window wall / CPU合計（秒） | 最大RSS（KiB） |
| --- | --- | --- | --- | --- |
| 16 | 8 / 0 | 13,024,262 | 78.899 / 78.603 | 71,568 |
| 20 | 4 / 4 | 47,005,260 | 59.131 / 58.962 | 69,724 |
| 24 | 0 / 8 | 80,000,000 | 76.042 / 75.982 | 69,728 |

合計には失敗attemptを含み、全局の平均や改善率ではない。失敗12windowは全て
最初のexact rootで10,000,000 nodesに達し、`exact=false`、`score=null`、`completed_depth=0` だった。
20は黒window1/2、24は全windowで失敗した。後続exact rootへ到達しておらず、再利用の効力や
310秒以内の実行可否はこのrunから判断できない。

Oracleは全32位置が `process peak RSS is unavailable` で失敗し、queriesは空だった。
非blocking waitと `/proc` 観測の間にprocessが終了すると、終了直後のRSS欄がなくなる。
修正後はwait4を再確認し、正常終了と最終RSS上限を確認できた場合だけ完成へ進む。
まだ実行中なら観測失敗を維持する。終了statusも新しいraw receiptへ保存する。
旧receiptのstdout/資源だけでは正常終了を証明できず、成功へ書き換えない。

2026-10-05、人間がnode上限を不要と指示した。新pilot/fullはnode上限なし、
310秒/decisionと1,572,864 KiBのRSS上限を使う。探索条件が違うため旧24windowをskipせず、
新しいmanifest/directoryで再測定する。元runの全unit・失敗・gateはそのまま保存する。

保存済みのwindow2・空き16/15/14/13のroot Console出力は、両scopeでOracleが
`-40/+40/-40/+40`、CLIが `-39/+39/-39/+39` だった。これは成功証拠として回収しない。
projectのterminal scoreはwipeout以外で石数差を使う一方、固定Egaroucidは残り空きマスを
勝者へ加算する。終局評価の違いが1点差を説明する可能性があるが、該当するterminal leafは
保存されておらず、原因の確証やroot点数の機械的な変換は行わない。
新測定も点数不一致を失敗として保存し、full/adoptionのgateを通さない。
