# 空き16/20/24・局内完全読み再利用の評価記録

2026-10-04時点では測定基盤を実装し、入力を監査・補完した。pilot/full/独立Oracleの長時間測定は
起動していない。速度改善や採用候補を示す実測証拠はまだない。0041はactiveのまま残し、
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

- pilot: 16/20/24 × turn/game × 4window = 24。depth12/8/12、10,000,000 nodes、310秒/decision、1,572,864 KiB/seat。
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
