# 長時間バッチの経過時間を読みやすくする

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

Addresses: N/A

## 目的と完了条件

運用者が長時間バッチの進捗行から経過時間を読み取れるようにする。table32 の開始、通常進捗、待機中の通知、完了・失敗と、同じ `elapsed_seconds` を出す optimizer 比較の進捗に、人間向け表示を追加する。次に作る長時間バッチでも適用されるよう、リポジトリ全体の規約と、開発待ちの table32 規模拡大計画に反映する。

## 現行の契約と実装箇所

- `AGENTS.md:36` の **Long-running batches** は出力項目と頻度を計画・仕様で定める規約。`docs/specs/reversi-ai.md:262–266,2334–2338` と `tools/reversi-ai-training/README.md:694,873` に現行の数値秒の診断形式がある。
- `tools/reversi-ai-training/table32_store.py:140–146` の `Journal.progress` は通常進捗、`table32.py:881` は入力検証の予定行、`table32_process.py:205–210,245–248` の `supervise` は待機中の通知と完了・失敗を出す。`table32_combine.py:335–339` も `supervise` を使う。
- `tools/reversi-ai-training/optimizer_compare.py:52–73` の `Progress` と `source_hashes` が比較用進捗と実行ソースの固定を担当する。
- `table32.py:23–29,245–247` と `table32_combine.py:144–162` は保存済み manifest が固定したソースと実行時ソースを照合する。`table32_process.py:203–204,234–242` は測定結果を数値として保存する。
- `docs/exec-plan/todo/0054-reversi-ai-next-method-experiments.md:232–235` と `0060-table32-training-scale.md:67–71` は現行または今後の進捗行に `elapsed_seconds` を指定している。

## 黒箱仕様に追加する契約

- 上記の進捗行は既存のフィールドと順序を維持し、末尾に `elapsed=<duration>` を出す。`elapsed_seconds` と `elapsed` は同じ経過時間の測定値を使う。例は `table32 phase=06 unit=000000 completed=401 total=12823 elapsed_seconds=962.222 status=running elapsed=16m02s`。
- 秒未満を切り捨て、最大の単位から秒までを一つのトークンで出す。形式は `0s`、`59s`、`1m00s`、`1h00m00s`、`1d00h00m00s`。先頭の単位はゼロ埋めせず、途中の単位と秒は二桁に揃える。
- stderr への出力・flush・表示頻度と、時間の測定起点を維持する。予算判定、構造化された成果物や resource log の数値、protocol stdout の契約を維持する。新規の長時間バッチは人間向け進捗の経過時間にこの形式を使い、仕様に例を記載する。変更する既存バッチは従来の数値診断フィールドも維持する。
- 固定済み run は記録された producer checkout で続行・検証し、新しい表示を使う run は新しい実装で準備する。ソース同一性と過去の証跡の取扱いは現行の契約に従う。

## 変更と実装順

1. (MODIFY) `docs/specs/reversi-ai.md` の進捗契約を先に更新する。`AGENTS.md` から新規・更新バッチの計画と仕様に規約を適用する。(MODIFY) 有効な 0054・0060 の計画に新しい形式を反映する。0060 が先に実装された場合は `table32-scale` の仕様・実装・fixture を同じ契約に揃える。
2. (NEW) `tools/reversi-ai-training/progress_time.py` に経過時間の共通フォーマッタを置く。(MODIFY) table32 の上記の出力箇所と `optimizer_compare.py` を共通化し、新しいモジュールを比較のソース固定に含める。共通書式の確定後、table32 と optimizer の改修・検証は独立して進められる。現在の table32 固定対象は training 直下の Python ファイルを含む。
3. (MODIFY) `tools/reversi-ai-training/README.md` に出力例と producer checkout の扱いを書く。(MODIFY) `tests/test_table32_cli.py`、`tests/test_table32_process.py`、`tests/test_optimizer_compare.py` などの既存 fixture で、表示と数値記録を確認する。
4. (DELETE) 検証と実装 PR の準備後に本計画を削除する。

## 検証

- 小数秒、分・時間・日をまたぐ境界、複数日の表示を検証する。`962.222` が `16m02s` と表示されることを確認する。
- table32 の予定行、通常進捗、ハートビート、終了行と optimizer 比較の進捗を fixture で検証する。数値秒と人間向け表示が同じ測定値を使い、従来の項目とステータスが維持され、`--progress-every` と resource log・receipt の形式に影響がないことを確認する。
- `make pattern-training-test`、workflow lint、`git diff --check` を実行する。動作確認は fixture で行う。
