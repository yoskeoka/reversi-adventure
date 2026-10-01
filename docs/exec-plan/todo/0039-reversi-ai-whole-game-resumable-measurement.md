# 全局計測を1局単位で保存し再開する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

人間がパラメータ入力済みscriptを1回起動し、中断後も検証済みの完了局を利用して
測定を続けられるようにする。0035の既存14レポートを保持し、再測定を要求しない。
測定結果の存在確認と独立検証によるskip、1局完了ごとの永続保存、途中再開を
満たす。8局そろう前のcheckpointを全局比較の完成証拠として扱わない。
探索結果の再利用は同じ局内だけとする。プロセスを常駐させても局の開始前に通常TTと
完全読み表を必ず消去し、前の局の探索結果を利用しない。

## 参照

- `docs/specs/reversi-ai.md:633-695` — 全局測定、診断、資源、プロセス寿命、意味一致。
- `tools/reversi-ai-benchmark/whole_game.py:332-431` — `persistent_games`, `measured_game`, `run`。現在は局をメモリに保持する。
- `tools/reversi-ai-benchmark/whole_game.py:633-705` — `main`。現在は8局完成後にだけreportを書き出す。
- `tools/reversi-ai-benchmark/whole_game.py:442-554` — `verify`, `comparison`。
- `rust/reversi-ai/src/search/mod.rs:125-141,312-327` — `SearchEngine` の通常TT/完全読み表と現状のexact-only clear。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:260-345` — request loopとmove protocol。
- `tools/reversi-ai-training/reinforcement.py:212-264` — 常駐 `Candidate` protocol。
- `tools/reversi-ai-benchmark/test_whole_game.py` — offline verifier regression tests。
- `docs/references/reversi-ai-whole-game-0035.md` — 現行の測定/検証手順。
- workspace `.local/reversi-ai-whole-game-0035/run-reversi-ai-whole-game-0035.sh` — digest固定と完成条件skipの既存例。
- `docs/references/reversi-ai-whole-game-0035-results.md` — 既存証拠と常駐時の着手差。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 以下の保存/再開契約を先に定義する。
- (MODIFY) `tools/reversi-ai-benchmark/whole_game.py`, `test_whole_game.py` — checkpoint、identity検証、resume、atomic完成report。
- (MODIFY) `rust/reversi-ai/src/search/mod.rs`, `rust/reversi-ai/src/bin/reversi-ai-cli.rs` と関連tests — 局開始時の全探索cache resetとack。
- (MODIFY) `tools/reversi-ai-training/reinforcement.py` と関連tests — 自己対局/候補対戦の各局開始時にも同じresetを行う。
- (NEW) `tools/reversi-ai-benchmark/prepare-whole-game-measurement.py` — 固定入力から測定manifestと実行scriptを生成する。
- (MODIFY) `Makefile`, `docs/references/reversi-ai-whole-game-0035.md` — prepare/run/verify手順と寿命別の再開限界。
- (NEW, ignored runtime output) workspace `.local/reversi-ai-whole-game-0035/` 内の新manifest/script/checkpoint。既存JSONを上書きしない。

## ブラックボックス契約

1. prepareは明示したsource/harness revision、CLI/Oracle/artifact/openingsの絶対pathとSHA-256、
   深度、exact閾値/cache scope、seat割当順、寿命、timeout/RSS上限、output directoryを
   manifestへ固定する。script生成後の起動は `rtk bash /absolute/path/run-….sh` の1行。
   毎回多数のMake変数を渡さずに起動でき、起動時にファイルdigestとharness identityを
   再確認する。測定をprepareから起動しない。再開中も同一ホストで直列実行する。
2. 既存の完成reportがあれば、canonical JSON、digest、合法棋譜、全8局、資源、
   manifest identityをverifyして条件全体をskipする。既存v1レポートも明示的に
   manifestへ登録して検証/skipできる。存在するだけではskipしない。破損/入力不一致は
   fail closedし、再計測で黙って置き換えない。比較/Oracle照合も検証済み完成結果をskipする。
3. one-game-per-seat条件は1局完了時に局面/手番/着手、診断、終局、wall/CPU/peak RSS、
   起動終了時間、条件/manifest digest、開局/assignment identityを局reportへ含める。
   同じdirectoryの一時ファイルへwrite/flush/fsync後atomic renameし、directoryもfsyncする。
   局reportが耐久保存されてから完了数を進める。二重起動はlockで拒否する。
4. Ctrl-C/SIGTERMや強制終了後も保存済み局を利用する。未完成一時ファイルは完成局として
   数えず、再開時はその局からやり直す。各完了局を独立verifyし、重複/欠落/identity違いを
   拒否して残りだけ測る。8局がそろったときだけ既存相当のaggregate/report digestを計算し、
   atomicに完成reportを公開する。中断前後の測定session identityを残す。
5. 局開始の明示的control request `new_game\t<game-id>` をCLIへ追加し、通常TT/完全読み表と
   局の探索履歴を消去してから `new_game\t<game-id>\tready` をflushして返す契約を先にspecへ書く。
   move request/responseの形式は維持し、runnerは両seatのackを確認してから最初の着手を送る。
   自己対局/候補対戦runnerにも適用する。各局のreset event、処理時間、cache寿命 `one-game` を
   report/manifestへ固定する。未対応CLIやack欠落は新条件の計測に使わない。
   trainingのprepare/run/verifyもcache寿命とreset対応binary identityを固定/検証し、
   局間cacheを残す旧manifestを新条件として誤用できないようにする。
   同じ局の次の手番ではcacheを保持する（turn比較では完全読み表だけを手番ごとに消す）。
6. cli-persistentも可能な限り各局直後に診断と累積CPUの差分を保存する。RSSは差分にせず、
   checkpoint時のprocess/segment累積peakを絶対値で保存し、segment終了時のwait4 peakで
   検証する。局だけの独立peakとは呼ばない。ただしプロセスが
   失われた場合も、各局の初期cacheは空なので完了局の再生/warm-upをせず残りの局から再開する。
   中断された局は新プロセスの空cacheから局全体を再測定する。起動session/segmentと
   startup/shutdownを残し、単一プロセスで8局測った事実とは区別するが、局間cacheは両方式で
   必ず空にする。segment累積RSSを局単体のRSSへ読み替えない。
   既存v1 persistent reportは局間cacheを保持した参考値として保存/verify/skipする。
   新しい局reset条件の完成結果とは扱わず、新条件だけを測定する。
7. progressの作業単位は保存済み1局、totalは条件ごと8局と全条件数。stderrの既定書式を
   `progress whole-game condition=<id> games=<done>/8 status=<measuring|saved|skipped|interrupted|verified> elapsed_s=<value>`
   としてspecに固定する。prepare→入力検証→局測定/保存→完成report検証→比較/照合のstageを
   表示する。既定は1局ごと、`--progress-every N` は通常進捗だけを間引き、失敗/中断/完成は必ずflushする。

## 作業と依存関係

1. specでv1完成reportとの互換、局/条件identity、局間cache禁止、reset/ack、再開を定義する。
2. engine/CLI/runnerの局reset、局保存とoffline集約、lock、中断cleanupを実装する。
3. script生成とv1完成結果登録/skipを実装し、測定を起動せずworkspaceに起動可能なscriptを配置する。
4. 下記検証後に0039を削除しPRを作る。0040はmerged 0039を利用する。

## 検証

- tiny fake-seat fixtureで「2局保存後に中断→再開→未測定6局のみ実行」、保存直前/直後の
  crash、未完成temp、二重起動、破損局、異なるdigest、重複/欠落を確認する。
- 完成v1レポート存在時にseatプロセスを起動せずskipし、破損時は停止する。
- 分割して再開したone-game条件の棋譜/診断/集計と連続fixtureが一致する。
  wallのbyte一致は要求せず、raw値からCPU/RSS/wallが再集計できることを確認する。
- persistentのsegmentをall-games-per-seatと誤認できないこと、局reportに診断が即時保存されることを確認する。
- 同一局内の手番間再利用を確認し、次の局では通常TT/完全読み表が空であることを確認する。
  連続常駐と各局fresh engineでmove/score/depth/exactness/node数が一致するfixture、
  同じ開局を繰り返した場合の局間hit禁止、reset ack欠落拒否、自己対局runnerへの適用を確認する。
- Rust/Python tests、Clippy、GDExtension build、`rtk make oracle-test`、script構文/生成fixture、workflow lint、`rtk git diff --check`。
- 長時間の実測は人間が別terminalで起動する。agentは起動/待機/監視しない。

## Addresses

- N/A
