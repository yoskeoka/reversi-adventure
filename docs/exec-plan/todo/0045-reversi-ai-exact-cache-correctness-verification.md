# 修正後の再利用を短い照合と各3局で検証する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 実装・測定の境界（2026-10-07）

専用prepare/run/verify、固定sample、短い回帰とoffline証拠検証を実装した。
保存済み752 receiptを元の42f6d57 producer契約で検証し、既知root/a4/a7値を確認した。
各3局×2条件と抽出Oracleのhuman-runは未実施であり、計画の測定完了条件は残る。
この計画は測定結果の受領とoffline verify後に削除する。
入力済みscript、固定digest、未達と採否条件は
[検証記録](../../references/reversi-ai-exact-cache-correctness.md) に記録する。

## 目的と完了条件

0044の修正を既知反例と少数の独立Oracle局面で確認し、実際の自己対局用設定だけを各3局で比較する。
既存Oracle/CLIの全局時間は参考基準として使い、同じ基準値を得るための再測定をしない。
既定の安全措置は0043のturnのまま。結果と失敗理由を0040へ渡し、人間が採否を判断する。
不一致が一つでもあれば再利用は採用しない。3局成功を一般的な正確性や有意な高速化の保証にしない。

## 参照

- `0044-reversi-ai-exact-cache-correctness-repair.md` — 短い修正前/後回帰と棋譜。
- [PR #251](https://github.com/yoskeoka/reversi-adventure/pull/251) — frozen producer `42f6d57`、全752 receipt、既存時間/Oracle証拠。
- `tools/reversi-ai-benchmark/whole_game.py` — `verify_game`, `measurement_identity`, `measure_resumable`。
- `tools/reversi-ai-benchmark/prepare-whole-game-measurement.py:169-179` — 現在の深度×scope×常駐matrix。
- PR #251の `tools/reversi-ai-benchmark/exact_threshold.py` — `measure_unit`, `verify_unit`, `verify_position`。
- `tools/reversi-ai-benchmark/whole-game-openings-v1.json` — 開局/assignmentの既存identity。
- `docs/specs/reversi-ai.md:651-775` — 不変8局report、資源観測、reset/再開の契約。

## 固定する最小matrix

| 段階 | 条件/対象 | 完成単位と上限 |
| --- | --- | --- |
| 既知反例 | 0044の短いwarm-bound/suffix fixtureとroot/a4/a7の保存Oracle query | 1反例、既存3局面のoffline検証。新しいOracle solveは0 |
| 全局比較 | 修正済み同一CLI、12/8/12・exact20、turnと明示game、1局1seat1process | scopeごと3局、合計6局、反復1回 |
| 独立Oracle | game側3局から各3個以下の終盤rootと選択child | 最大9root、最大18query位置。既存一致queryは再利用 |

3局は `opening-1/assignment-0`, `opening-2/assignment-0`, `opening-4/assignment-0` の順に固定する。
通常の開局、既知反例の開局、旧測定でpassを含んだ開局を残す。assignmentの鏡像対局を追加しない。
sample偏りと反復なしを明記する。修正後の同じ開局にpassが現れる保証はないため、passは短い回帰でも確認する。

Oracle同士の全局、旧CLIの全局、深度12の全局、閾値16/20/24の総当たり、
常駐/非常駐の全局比較、序盤8rootのコスト計測はこのmatrixに追加しない。
約8分/局を使う単純な事前見積りでは全局探索は計約48分だが、修正後の実測や上限とは区別する。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 専用3局subset、条件数/単位/Oracle上限、証拠再利用を先に定義。
- (NEW) `tools/reversi-ai-benchmark/exact_cache_verification.py` とtests — 固定matrixのprepare/run/verify、短いOracle照合。
- (NEW) `tools/reversi-ai-benchmark/exact-cache-verification-sample-v1.json` — 3局identityと固定抽出規則。
- (MODIFY) `Makefile` — 小規模検証のprepare/run/verify入口。
- (MODIFY) `tools/reversi-ai-benchmark/whole_game.py` — 必要な下位game/resource検証の再利用。既存8局形式は維持。
- (MODIFY) `docs/references/reversi-ai-exact-cache-correctness.md` — source/input/report digest、局別・exact部分の結果と失敗。
- (MODIFY) `docs/exec-plan/todo/0040-reversi-ai-self-play-performance-closeout.md` — 検証結果・未達・採用条件を接続。
- (DELETE, 完了時) 本計画。

## ブラックボックス契約と作業

1. PR #251の固定manifest/receiptを元のproducer契約で検証し、0044の反例回帰を確認する。
   root +4と選択childの白視点+4を要求する。既存failed receipt内の完全なqueryを使う場合も
   query/process/失敗理由を検証し、failed receipt自体を成功に書き換えない。
2. 専用形式 `exact-cache-verification-v1` のmanifest/reportを新設し、`games_total=3`、
   ordered sample identity、2条件、修正source/CLI/artifact/harness digest、host、実効scope、
   cache lifetime/reset、depth/exact、timeout/RSS、全output identityを固定する。
   v1/v2の8局reportを3局と読み替えたり、過去の集計に追加して8局の完成を装ったりしない。
3. 両条件の3局は同じbinary/artifact/設定/hostでserialに測る。node上限は設けない。
   CLI decision timeout310秒、seat peak RSS1,572,864KiBを継承する。
   全3局の完成後だけ条件平均を生成する。失敗/未完了は保存してその条件を不採用にし、
   件数や条件を増やした自動retryをしない。同一条件の棋譜・盤面・score・depth・exactness・outcomeを照合する。
4. 全局Oracle照合の代わりに、game側の各完成局から、最初の空き12以下のexact root、
   最初の空き8以下のexact root、空き12以下の最後の非終局exact rootをこの順で抽出する。
   該当位置がなければ省略し、高い空き数のrootへ代替しない。早い終局で抽出位置が0の局も追加対局しない。
   重複rootを除き各局最大3、計最大9。非終局の選択childも完全読みし、rootと選択手の値を照合する。
   `(board, effective_side, oracle_binary_digest, profile_digest, score_contract)` が一致する完成queryを
   先に再利用する。抽出・重複排除後の実位置を順序付きで記録し、未照合位置だけの最大18queryの
   manifestと実query数（0も可）をstage前に固定する。終局childは規定の終局値で照合しqueryを増やさない。
   新規Oracle queryは1位置30秒・peak RSS1,572,864KiBを上限とし、node上限は設けない。
   timeoutは失敗として残し、上限を自動で延ばさない。最大18queryの探索待ち時間は計9分までとする。
   抽出外のexact rootは独立Oracleで確認したと主張せず、turn/game意味一致とRust回帰を別の証拠として示す。
5. Oracle score契約の±39/±40不一致を値の一律加減算で隠さない。
   未解決のscore意味差、選択手不一致、不完全query、timeout/RSS超過は失敗証拠として保存し採用を止める。
   高い閾値のtimeoutを再現するための24-empty試験は追加しない。
6. 人間が入力済みscriptを一行で実行する。agentは長い対局やOracle計測を起動・待機・監視しない。
   1局/1queryをatomic checkpointとして保存し、検証済み成功/失敗はskip、中断単位だけ再開する。
   旧8局reportや0041 directoryは不変とし、新しい `.local/reversi-ai-exact-cache-correctness/` を使う。
7. stderrは `progress exact-cache-verification stage=<inputs|regression|games|oracle|verify> condition=<turn|game|none> unit=<fixture|game|position> done=<n> total=<n> status=<running|saved|skipped|interrupted|verified|failed> elapsed_s=<value>`。
   gamesは各条件total3、oracleはmanifestの残りquery総数、regressionは固定fixture数。
   `--progress-every N` は既定1、通常進捗だけ間引き、失敗/中断/最終を必ずflushする。
8. 局別wall/user/system CPU/RSS、legal-count/phase、raw資源観測、exact nodes/cache/timeを保持する。
   exact部分と全局の差を分け、nodesが同じheuristic時間差をcache効果としない。
   既存約8分/局やOracleの既知時間は元digest・条件付きで引用し、新binaryの比較対照として代用しない。

## 依存関係と順序

- PR #251→0043→0044→本計画→0040の判断。prepare/fixture検証とhuman-run結果受領を区別する。
- 閾値20は比較用実験設定であり、本番の16を変更する承認ではない。
   本番20を選ぶ場合のproduction spec/manifest互換更新は採用判断後の別計画。
- 0037の学習pilot、0019の本番freeze、0018の強さ受け入れはこの6局と混同しない。

## 検証

- 正確に3局/2条件、入力順序/重複/余分/欠落を拒否。8局v1/v2との形式分離。
- 短いfixtureでreset、保存後中断、resume/skip、失敗再利用、raw資源不足、digest/host/settings変更を拒否。
- Oracle位置抽出の最大9root/18query、dedup、既存queryの再利用、root/child値と失敗理由の照合。
- 完成3局と抽出位置の証拠をoffline再計算し、不一致や不完全結果から平均/採用を作らない。
- 該当Rust/Python tests、workflow lint、diff check。長時間計測をCI/test前提にしない。

## Addresses

- N/A
