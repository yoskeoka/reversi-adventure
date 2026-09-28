# ローカル対局 Playground の探索設定、Advisor、起動導線を整える

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

`tools/reversi-ai-playground` で各 AI 対局者の序盤 1〜20 手と中盤 21〜60 手の探索深さ、および完全読み開始空き数を設定できる。Human には AI Advisor を選べ、助言を見てから自分で着手できる。ルートの `make playground-install` は pnpm 依存、外部 Oracle、デモ用 TrainedEvaluator artifact を準備し、`make start-playground` は追加の手動設定なしで全対局者が選べる UI を起動する。実際に学習した重みの強さは完了条件に含めない。

探索エンジン側は Playground 専用のフェーズ境界指定と既存の完全読み閾値の利用で足りるため、単一の実行 plan とする。既存の AI、benchmark、Godot 側の既定フェーズ境界や強さ評価は変更しない。

## 現状の参照

- `docs/specs/reversi-ai-local-playground.md:1-29` — 起動、対局者、設定、wire、process の現行ブラックボックス契約。
- `docs/specs/reversi-ai.md:320-336`, `rust/reversi-ai/src/config.rs:1-59`, `rust/reversi-ai/src/search/mod.rs:142-178` — 通常探索は石数で既定フェーズを選び、完全読みは空き数閾値で先に選ぶ。現行の序盤境界 20 石は「第 20 手の前に 23 石」と一致しない。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:13-17,52-133,170-235` — CLI 引数、探索設定、盤面ごとの応答。CLI は各フェーズ深さを受けるが境界指定はない。
- `tools/reversi-ai-playground/server/session.mjs:7-45,48-91,112-185` — 対局者検証、同一深さの CLI 引数、固定 Oracle level、盤面更新、AI 応答照合と Human 着手。
- `tools/reversi-ai-playground/server/index.mjs:9-42,49-91`, `server/config.mjs:1-13`, `web/src/main.ts:1-67,95-242` — 外部 path の検証、任意ローカル設定、WebSocket 操作、設定 UI と盤面表示。
- `tools/reversi-ai-oracle/oracle.py:80-159,213-245,698-705,850-945,1774-1780` — Oracle の着手番号別 `-depthprobrange`、pin 済み source/cache/setup。
- `rust/reversi-ai/src/eval/trained.rs:42-143`, `tools/reversi-ai-training/training.py:282-343`, `tools/reversi-ai-training/fixtures/tiny-manifest.json`, `tools/reversi-ai-training/README.md:1-15` — TrainedEvaluator の artifact 契約と強さを主張しない小さな fixture。
- `Makefile:1-9,155-158`, `tools/reversi-ai-playground/README.md:1-49` — 現行の install/start と既存 Oracle setup target。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai-local-playground.md` — 着手番号、探索・完全読み設定、Advisor、設定凍結と再接続、install/start の可観測契約を先に更新する。
- (MODIFY) `docs/specs/reversi-ai.md` — CLI から選べる Playground 専用のフェーズ境界と既定境界の維持を定義する。
- (MODIFY) `rust/reversi-ai/src/config.rs`, `rust/reversi-ai/src/bin/reversi-ai-cli.rs` と関連テスト — Playground 用の明示的な第 20 手境界を追加し、設定 fingerprint と CLI 検証に反映する。
- (MODIFY) `tools/reversi-ai-playground/server/session.mjs`, `server/index.mjs`, `server/config.mjs`, `web/src/main.ts`, `web/src/style.css` と関連テスト — seat/Advisor 設定、Oracle 深さ、助言要求と表示、状態同期を実装する。
- (NEW) `tools/reversi-ai-playground/scripts/` の setup 補助 — 既存 Oracle setup の検証済み出力を機械可読に受け取り、fixture 由来のデモ artifact と checkout 外のローカル設定を再現可能に準備する。既存の source pin、cache 検証、artifact 検証を再利用する。
- (MODIFY) `tools/reversi-ai-oracle/oracle.py` — 必要なら setup 結果の binary/data path を機械可読に返す追加出力だけを設ける。既存 corpus/profile の意味は維持する。
- (MODIFY) `Makefile`, `tools/reversi-ai-playground/README.md` — `playground-install` と `start-playground` の利用方法、前提、デモ artifact の明示、任意の実学習 artifact 指定を記す。

## ブラックボックス契約と作業

1. **手数と探索設定**: 手数は初期盤面から打たれた石の数で、次の意思決定の番号を「盤上石数 − 3」とする。パスでは進まない。第 1〜20 手の判断は序盤深さ、第 21〜60 手は中盤深さを使用する。完全読み開始空き数 0〜16 は独立設定とし、閾値以下では通常探索深さより完全読みを優先する。終盤深さ入力は置かない。Strategic、Novice、Trained、Oracle の各 seat と Advisor に独立設定を持ち、対局開始時に凍結する。Random は探索しないため深さ・完全読み入力を持たない。既定 CLI 利用者の 20/44 石境界は変えず、Playground が明示指定した場合だけ第 20 手境界と中盤深さの終局までの適用を行う。
2. **Oracle**: 検証済み Egaroucid の `-depthprobrange` で 1〜20 手、21〜60 手を指定し、完全読み閾値以降は残り空き数を解く深さへ切り替える。閾値 0 は明示的な完全読み移行なしとする。起動引数と実際の境界局面で、指定深さと完全読みへの移行を確認する。Oracle の option が同等の動作を示せない場合に限り、序盤・中盤を同一深さとして UI と snapshot にその制約を表示する。Oracle の解を project AI の品質保証とみなさない。
3. **Advisor**: Human の黒・白それぞれに `none` または利用可能な非 Human 対局者を選ぶ。探索する Advisor は seat と独立した序盤/中盤深さ・完全読み閾値を持つ。人間の手番で明示的な「助言を求める」操作を受けると、サーバーが現在局面を問い合わせ、推奨合法手と担当 AI を snapshot に表示する。助言は自動着手せず、人間は別の合法手も選べる。推奨は session/revision/盤面に紐づけ、着手、パス、再開始、失効時に消し、遅延応答は表示しない。Human 着手は助言待ちを妨げない。助言失敗は Advisor のエラーとして表示し、対局可能なままにする。Random Advisor は合法手の一様な参考提案のみを返す。
4. **Advisor のプロセス境界**: 対局 AI と Advisor は別の子プロセス/状態を持ち、同一 session の終了・期限切れで閉じる。CLI 応答は既存の position ID・合法性検証を使う。Oracle Advisor の `genmove` は内部盤面を進めるため、助言要求ごとに専用の Oracle process を起こしてその時点までの合法着手とパスを再生し、応答後に閉じる。人間の実着手が提案と異なっても次回は実際の履歴を再生する。助言は本対局の Oracle 対局者の GTP 状態に触れない。再接続では凍結設定と有効な助言だけを復元する。
5. **install/start**: `make playground-install` は pnpm install と既存の pin 済み Oracle setup を実行し、成功時に checkout 外の設定ファイルへ検証済み binary/data の絶対 path を保存する。Oracle download/build/検証に失敗した場合は target 自体を失敗させる。学習済み重みがまだない環境でも、既存 tiny fixture から生成した強さ未確認のデモ artifact を checkout 外に置いて TrainedEvaluator を選択可能にし、UI でデモ用と明示する。`PLAYGROUND_CONFIG` で実学習 artifact や Oracle path を指定した場合は項目単位で準備済み設定より優先し、無効な任意設定は該当対局者だけを利用不可にする。`make start-playground` は準備済み設定を渡して既存のローカル dev server を起動し、未 install なら前提不足を明示する。既存の `make playground` は互換 alias として扱う。Oracle、artifact は Rust/GDExtension/配布依存に入れない。

## 作業順序と依存

1. 上記 2 つの spec を先に更新する。第 20/21 手、パス、完全読み境界、Oracle 設定の意味を固定する。
2. CLI に Playground 専用境界を追加して CLI 単体で検証する。既定設定、探索順、他のプロファイルの挙動に波及させない。
3. setup 導線と Oracle/デモ artifact の起動前検証を実装する。
4. seat 設定、Advisor query/state、UI を実装する。Oracle 対局者と Oracle Advisor の GTP 状態は独立に扱う。
5. README を更新し、実際の install/start とブラウザー操作を確認する。

## 検証

- 第 1/20/21/60 手、パスを含む盤面、完全読み閾値の前後で CLI と Oracle に渡る深さを確認する。既定 CLI のフェーズ境界と config fingerprint/キャッシュ隔離も確認する。
- Human 対局者の Advisor 選択、助言の表示、助言と異なる合法着手、連続助言、Human 両席、Oracle 対局者との同時利用、古い助言の破棄、再接続、期限切れ、失敗後の対局継続を確認する。
- `make playground-install` で pnpm、pin 済み Oracle の再利用/検証、デモ artifact/設定生成を確認し、`make start-playground` で全対局者が選べること、`PLAYGROUND_CONFIG` で実 artifact を優先できることを確認する。Oracle の長い download/build は既存 cache を使い、生成物は checkout 外とする。
- Playground の `pnpm test`, `pnpm lint`, `pnpm build`、関連 Rust テストと Clippy、該当 Python テスト、workflow lint、`git diff --check`。

## Addresses

- N/A
