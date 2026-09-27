# AI・oracle・人間を選べるローカル対局 Web UI

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

`pnpm` で起動できるローカル開発用 Web 対局ツールを `reversi-adventure` に追加する。黒・白それぞれに人間、`TrainedEvaluator`、`StrategicEvaluator`、`NoviceEvaluator`、合法手を一様に選ぶ random、外部 oracle を指定できる。AI は browser 内で動かさず、backend が project-owned CLI または外部 oracle を起動して対局を管理する。人間の着手と AI の返答を WebSocket で即時に反映する。

`reversi-ai-arena/visualizer` の盤面描画と replay model を参考にする。局面の正当性と手番は backend が権威を持ち、visualizer の再生検証を server のルール代わりにしない。このツールは開発時専用で、ゲーム配布物や Rust/GDExtension には外部 oracle を含めない。

## 参照

- `docs/specs/reversi-ai.md:105-145,774-788` — CLI 探索と外部 oracle 境界。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:14-18,151-224` — evaluator 設定と常駐 stdin/stdout protocol。
- `rust/reversi-ai/src/eval/novice.rs:7-53` — novice は random 専用 player ではない。
- `tools/reversi-ai-oracle/oracle.py:1161-1223,1469-1545` — 候補 CLI と外部 oracle GTP session。
- `rust/reversi-engine/src/game.rs:1-105` — 着手、pass、終局の project-owned ルール。
- `../reversi-ai-arena/visualizer/src/renderer/board.ts:4-120` と `src/replay/model.ts:1-105` — 盤面描画、色、着手、再生状態の参考。
- `../reversi-ai-arena/visualizer/src/main.ts:53-100` — score/turn 表示の参考。既存 visualizer は browser-only の再生 UI であり、backend/WebSocket は今回追加する。

## 変更マップ

- (NEW) `docs/specs/reversi-ai-local-playground.md` — 先に player 選択、手番、合法手、pass、終局、WebSocket の black-box 契約を定義する。
- (NEW) `tools/reversi-ai-playground/` — pnpm package/lock、backend、Web UI、開発起動 command、README。
- (MODIFY) Makefile または root README — 開発用起動入口と前提条件を示す。
- (NEW) backend と UI の対象を絞った検証 — protocol、状態遷移、着手反映、プロセス終了。

## ブラックボックス契約と作業

1. backend が標準の初期盤面から board、黒白、合法手、pass、石数、終局を管理する。黒・白の各 seat は、人間/strategic/novice/trained/random/oracle から独立に選択できる。project-owned AI の各 seat は中盤探索深さと完全読みを始める残り空き数を UI で個別に調整できる。完全読み自体は終局までなので、後者を「完全読み開始空き数」と明示する。許可範囲はその engine の受け入れ済み設定に制限し、着手中の変更は次局から適用する。trained は読み込み済み artifact の digest、探索設定と実体 CLI を画面と session 記録に示す。random は合法手から選び、seed を固定できる。oracle が未設定・起動不可ならその選択だけを利用不可として明示する。UI は `trained-baseline` などの安定した player ID だけを送信し、server のローカル設定が ID を CLI 実体・artifact、oracle 実体・data に対応させ、開始前に存在と digest を検証する。
2. project-owned AI には固定の許可済み実行ファイルと引数を backend が渡す。1 seat につき常駐 CLI を使い、複数手を protocol でやり取りする。oracle は既存の外部 GTP adapter の timeout、pass 同期、終了処理を参考に、checkout 外の binary/data を起動する。WebSocket の入力を shell command、任意実行パス、任意 artifact path に直結しない。新しい対局、timeout、AI 異常応答で子プロセスと session を有界に終了する。WebSocket 切断時は 30 秒の再接続猶予を設け、その間は session とプロセスを保持し、猶予切れで終了する。
3. WebSocket は接続直後に完全な局面 snapshot を送り、以後も revision を付けて手番/着手/思考中/pass/終局/error を配信する。人間の着手要求には session/revision と座標を含め、server が手番・合法性・鮮度を検証する。AI/oracle への問い合わせにも session/revision/position ID を付け、返答がその局面と一致する場合だけ状態を更新する。遅延・古い・違法・不正形式・不正 pass の返答は盤面/revision を変えずに拒否し、対象プロセスを停止して error を配信する。相手側の着手は人間の追加操作なしに配信する。30 秒以内の再接続時は token で同じ session に復帰し最新 snapshot を表示する。期限後は新規 session が必要で、古い着手要求を拒否する。
4. UI は現在手番、黒白の player 名と各 seat の中盤探索深さ・完全読み開始空き数、合法着手候補、最後の着手、石数、AI 思考中、pass、勝敗と原因が分かる error を表示する。人間が担当する色だけを操作できる。双方 AI の場合も最後まで自動で進み、双方人間でも一つの画面から交互に指せる。ローカルホストだけで待ち受け、起動停止手順と必要な CLI/oracle 設定を README に記す。
5. 作業ディレクトリを `tools/reversi-ai-playground/` とし、そこから `pnpm install` と `pnpm dev` で起動する。`pnpm dev` は repo 内の `cargo build --release -p reversi-ai --bin reversi-ai-cli` で project-owned CLI を用意し、その digest を server で固定する。trained artifact と oracle binary/data は checkout 外の任意実行入力として WebSocket へ渡さず、server 側のローカル設定に置く。未設定時は対応 seat を利用不可と表示し、他の player で起動できる。既存 visualizer から再利用する部分のライセンスと依存関係を確認し、UI と backend の protocol をこの repo 内で管理する。production release/Steam/Godot の依存にしない。

## 依存関係と順序

- この UI は 0035–0037 の探索・学習改善と独立に作れる。モデルと artifact は実行時に選んだ安定版を使用し、実験 branch をデフォルトにしない。
- 先に server の対局/プロセス契約と WebSocket schema を固定し、その後に UI を接続する。
- 外部 oracle は開発/CI のみで使い、Rust・GDExtension・release artifact に入れない。

## 検証

- 人間対人間、各 project-owned AI、random、oracle を黒白の両側で選べることを局所的に確認する。AI ごとの中盤探索深さと完全読み開始空き数を選び、server が凍結した値で CLI を起動し、許可範囲外の入力を拒否する。oracle 不在時も他の player が動く。
- pass、終局、違法/古い着手、AI/oracle の不正形式・違法着手・不正 pass・遅延返答・timeout/異常終了、session の入替と 30 秒以内/以後の WebSocket 再接続で server と UI の状態が一致し、失敗時には盤面/revision を変えず error を通知する。
- 手動の browser 確認で着手の即時反映と選択 UI を確かめる。`pnpm` build/lint、該当 backend/Rust gates、workflow lint、`git diff --check` を実施する。

## Addresses

- N/A
