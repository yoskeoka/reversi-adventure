# table32 が Oracle の検証済みソース identity を使う

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了境界

0054 の table32 cycle が、0019 の historical manifest に記録された Oracle 実行バイナリ digest の差だけで停止しないようにする。Oracle は Egaroucid 7.8.1、pinned source archive SHA-256 `173af642276216a284498f8d7e32de23dbb9dc6611686c370b0de3eddbc1238b`、runtime setup receipt で識別する。0019 の manifest・artifact・run 出力は変更しない。

緩和は 0054 の入力検証だけに適用し、source version、archive SHA、profile、runtime receipt、実際に使う binary/resource の identity は新しい run root に保存して再開・offline verify で再検証する。candidate CLI、0019 採用 artifact、0051/0052/0053 の全入力、他の production workflow の digest 検証は維持する。

実際の 0054 prepare、教師生成、学習、対局、Oracle query は人間が別途開始する。本計画の完了は tooling/spec/fixture のみであり、0054 の実行や候補採用を意味しない。

Addresses: N/A — 0054 tooling の historical Oracle runtime identity 境界を明確化する。

## 根拠と契約

- `tools/reversi-ai-training/production_cycle.py:checked_manifest` は 0019 の全 frozen file digest を照合し、`oracle_binary` の digest 差で停止する。
- `tools/reversi-ai-training/table32.py:prepare` は runtime receipt を検証して runtime identity を run manifest に保存する。
- `tools/reversi-ai-oracle/oracle.py:verify_runtime_receipt` は保存済み source archive、version、build recipe、runtime identity を検証する。
- `docs/specs/reversi-ai.md#Project-owned-table32-pilot-0054` は原本の read-only 境界、Oracle profile/source/binary pin、prepare/resume/offline verify 契約を定義している。
- `tools/reversi-ai-training/README.md#0054` は人間向け setup と操作コマンドを定義している。

新しい black-box 契約では、0054 が指定する Oracle version と source archive SHA が receipt と 0019 manifest の両方で一致し、runtime receipt が保存済み archive/build/runtime を検証し、実行時 binary/resource identity が receipt に一致する場合に限り、0019 の historical `oracle_binary.sha256` mismatch を許可する。runtime binary path は historical manifest の path と一致させ、入力検証と prepare receipt はこの例外の適用を明示的に記録する。source checksum/version/profile/path/receipt のどれかが違えば停止する。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 0054 の Oracle identity、historical binary digest mismatch の限定例外、runtime receipt の保存・再検証条件を定義する。
- (MODIFY) `tools/reversi-ai-training/production_cycle.py` と `table32.py` — 厳格な既定検証を保ち、0054 専用の明示的な source-verified Oracle validation path を追加する。
- (MODIFY) `tools/reversi-ai-training/table32.py` / table32 tests — version、archive SHA、profile、path、runtime digest の一致・不一致 fixture を追加し、prepare/resume/offline verify を検証する。
- (MODIFY) `tools/reversi-ai-training/README.md` — Oracle runtime の用意方法、receipt path と操作手順を契約に合わせる。
- (MODIFY) `docs/references/reversi-ai-learning-method-reproduction.md` — 実施済み tooling の根拠と、historical Oracle binary digest を要求しない理由を記録する。

## サブタスク・依存・並列性

1. 0054 の black-box spec を更新し、例外条件と保存する identity を固定する。
2. strict default を維持したまま table32 専用 validator を実装する。
3. receipt/source/path mismatch と historical binary digest mismatch の fixtures を追加する。
4. README と調査記録を更新し、PR を準備する。

1→2→3→4。Git 書き込みは直列。fixture は Oracle build、Oracle query、training、対局を起動しない。

## 検証

- table32 用 Python unit tests: source/version/profile/path mismatch の reject、検証済み receipt 下で historical binary digest mismatch を許可、receipt と現在 runtime の改変を reject。
- `python3 -m unittest discover -s tools/reversi-ai-training/tests`。
- workflow lint と diff check。
- 実 run root の prepare/run/verify、学習・対局・Oracle query は本計画の品質 gate に含めない。
