# 空き16/20/24・局内完全読み再利用の評価記録

2026-10-06、人間のnode上限なしの測定と全証拠のoffline verifyが完了した。
空き20・中盤深度8は両scope各8局と全256Oracle位置の照合を通った。
空き16は点数不一致、空き24はpilot時間切れ、空き20・中盤深度12は終盤の選択手不一致で除外する。
実験の成否を報告する0041は完了し、計画は[実装PR #251](https://github.com/yoskeoka/reversi-adventure/pull/251)から取得する。
production採用は0040で人間が判断する。exact=16と0018の候補対戦設定は維持する。

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

## node上限なしのpilotと終了待機の修正

人間がharness `32f62173e34e5ec6b1e4b7b8c6cc12d6fed77a09` のrunを完了した。
元directoryはworkspace `.local/reversi-ai-whole-game-0035/exact-threshold-0041-32f6217/`、
manifest digestは `f76e7e7d988ed5b7c1657584492ee464d9def48be8e180081521ecee4f80868a`。
全証拠のoffline verifyは通ったが、fullへ進めた閾値はまだない。

| 閾値 | 完成 / 失敗window | 失敗理由 |
| --- | --- | --- |
| 16 | 8 / 0 | — |
| 20 | 8 / 0 | — |
| 24 | 4 / 4 | 黒window1/2が両scopeで約309秒のCLI時間上限に到達 |

Oracleは全112位置がRSS取得エラーの失敗として保存された。全112processの最終wait4は
終了status/returncodeとも0、peak RSSは1,394,040–1,394,512 KiBで上限内だった。
即座のwait4再確認でも終了処理が済んでいない間は回収できず、前回修正はこの間を失敗にしていた。

修正後はRSSが消えた際にLinuxの終了flag/stateを観測する。
`PF_EXITING` はメモリ情報の解放より前に設定され、親への終了通知は後になる。
根拠はLinuxの[do_exit](https://github.com/torvalds/linux/blob/v6.18/kernel/exit.c#L862)と
[PF_EXITING定義](https://github.com/torvalds/linux/blob/v6.18/include/linux/sched.h#L1631)。
終了途中を示す生値があれば既存deadline内でwait4をpollし、正常終了と最終RSS上限を確認する。
終了を観測できない生存processのRSS欠落、deadline超過、異常終了、RSS超過は失敗のまま残す。

新しいmanifestは同じ探索条件の24pilotを出所付きで引き継ぎ、Oracleから再開する。
元112失敗は書き換えず保持する。点数不一致のgateも維持する。

## 最終結果（2026-10-06）

測定harnessは `42f6d575b7115b4ccd6aa2ab6d9d805adadc1b89`。
workspace `.local/reversi-ai-whole-game-0035/exact-threshold-0041-42f6d57/` の全証拠を
このharness checkoutで `exact_threshold.py verify --manifest <directory>/manifest.json` により再検証した。
新しい測定は起動していない。以下は反復なしの単一serial runであり、有意性や本番採用を主張しない。
本書のcloseout commitとは測定producer SHAを区別し、再検証は上の固定harnessで行う。

PRレビュー後、失敗Oracleの途中queryとprocess観測も検証し、v2報告のdecision資源情報を
必須化した。現行validatorで保存済み752 receipt（pilot 24、full 32、pilot Oracle 112、
full Oracle 584）の内容を追加照合し、元の成功・失敗結果を確認した。
これはreceipt内容のoffline照合であり、現行HEADと固定manifestのproducer同一性を
検証したものではない。固定manifest・測定ファイルは変更していない。

| 証拠 | report digest |
| --- | --- |
| manifest | `7d3104d720fdbe605839af893a0ff4c47207e423d9b3eec633a6add1728de960` |
| pilot Oracle manifest | `2e708d572dbb1256e33776bcfad756c699f247c80ad6fe155d3fe5fecc8fd5cc` |
| full gate | `4db4ae75d5fba34324ae35a498729d37a6be4e9662684251b92d7e198eec8b1b` |
| full Oracle manifest | `a07866790f5fe7d0c433804d752e3f6e8fa22f42250291a0324bb2e187c757df` |
| assessment | `8d7f01cd5b67c510c3377f5cc1b2700952c566d5c42707505639baa5d00455a8` |

| 閾値 | pilot完成 / 失敗 | pilot Oracle成功 / 不一致 | gate |
| --- | --- | --- | --- |
| 16 | 8 / 0 | 8 / 8 | 不一致で除外 |
| 20 | 8 / 0 | 48 / 0 | full 32局へ進む |
| 24 | 4 / 4 | 48 / 0（完成windowのみ） | 時間切れで除外 |

RSS取得エラーは0件。終了途中の観測を保持して待機したprocessはpilot Oracleで204件、
full Oracleで1,128件あり、実際の終了待機も検証した。fullは両深度・両scopeの全32局が完成した。
中盤深度8のOracleは256/256成功、中盤深度12は326成功・2不一致で、後者の平均/改善率は生成しない。

### 空き20・中盤深度8の有効な比較

| 8局の測定 | turn | game |
| --- | --- | --- |
| 平均全局wall（秒） | 495.633415 | 487.652113 |
| 平均全局CPU（秒） | 495.446297 | 487.480398 |
| 最大RSS（KiB） | 71,616 | 71,616 |
| exact nodes合計 | 646,005,240 | 640,356,092 |
| exact wall合計（秒） | 603.940128 | 592.095600 |
| exact CPU合計（秒） | 603.760 | 591.950 |

観測された全局wall差は1.6103%、CPU差は1.6078%。exact nodesは0.8745%減った。
各seatの最初のexact rootは16件で、nodesは両scopeとも567,713,578だった。
後続112rootのnodesは78,291,662→72,642,514（7.2155%減）、
wallは73.347847→66.968821秒、CPUは73.250→66.900秒だった。

| phase（8局合計） | decision数 / 合法手数合計 | nodes（両scope、exactはturn→game） | wall秒（turn→game） |
| --- | --- | --- | --- |
| opening（depth12） | 88 / 702 | 368,192,278 | 3251.141521→3200.477038 |
| midgame（depth8） | 190 / 1704 | 12,503,474 | 104.644804→103.313230 |
| exact（空き20以下） | 128 / 724 | 646,005,240→640,356,092 | 603.940128→592.095600 |

exact wallは全局wallの約15.2%で、序盤が支配的だった。全局時間差の大半はnodesが同じ
heuristic phaseの時間差であり、全局1.61%差の全てをcache再利用の効果とは解釈しない。
既存exact16は別workloadで、今回full gateを通っていないため、この測定から20が16より速いとは言わない。

### 中盤深度12設定での終盤完全読みの選択手不一致

中盤のheuristic評価に正解を要求したわけではない。対象は空き7マス・白手番のexact root。
opening-2のassignment 0/1で、それぞれturn47まで同じ盤面・同じ意味履歴の両scopeを比較した。

| scope | CLIの選択手 / 報告score / nodes | Oracle root | Oracle選択後（黒視点） | 選択手の白視点の値 |
| --- | --- | --- | --- | --- |
| turn | a4 / +4 / 399 | +4、depth7 complete | -4、depth6 complete | +4 |
| game | a7 / +4 / 30 | +4、depth7 complete | -2、depth6 complete | +2 |

gameは最善値+4を報告しながら値+2の手を選んでいる。両queryは非終局でcomplete solve済み。
同じprefixを持つturnでは照合が通り、保持したexact cache条件の選択手に問題がある証拠となる。
cache実装内の原因は未特定。これは空き16の±39/±40という点数差とは別に扱う。
失敗jobは `full-20-12-game-opening-2-seat0-position-47` と `seat1-position-47`。

0040へは「空き20・中盤深度8の固定8局では照合成功、深度12には完全読みの選択手不一致あり」と渡す。
高い閾値の本番採用にはcache正確性の修正・再検証とproduction spec/manifest互換更新の別計画が必要。
