# ローカル対局 Playground の探索設定、Advisor、起動導線を整える

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

`tools/reversi-ai-playground` で各 AI 対局者の序盤 1〜20 手と中盤 21〜60 手の探索深さ、および完全読み開始空き数を設定できる。Human に AI Advisor を選ぶと、その手番で自動的に全合法手を評価し、計算完了後に盤面の候補手の●を `+1`、`-4`、`+0` のような値に置き換える。ルートの `make playground-install` は pnpm 依存、外部 Oracle、デモ用 TrainedEvaluator artifact を準備し、`make start-playground` は追加の手動設定なしで全対局者が選べる UI を起動する。実際に学習した重みの強さは完了条件に含めない。

全合法手の評価値を揃えて返すには探索 API と CLI、および Oracle adapter の拡張が必要なため、これを `0040-reversi-ai-advisor-analysis` の第1段階に分ける。この計画は、その成果を使う UI、session、install/start を第2段階として実装する。同時に、第1段階で追加した Playground 固有名の分析設定を共有 AI API として整理し、同じ探索設定と全合法手分析を Godot からも呼べるようにする。既存の AI、benchmark、Godot 側の既定フェーズ境界や強さ評価は変更しない。

## 現状の参照

- `docs/specs/reversi-ai-local-playground.md:1-29` — 起動、対局者、設定、wire、process の現行ブラックボックス契約。
- `docs/specs/reversi-ai.md:320-336`, `rust/reversi-ai/src/config.rs:1-59`, `rust/reversi-ai/src/search/mod.rs:142-178` — 通常探索は石数で既定フェーズを選び、完全読みは空き数閾値で先に選ぶ。現行の序盤境界 20 石は「第 20 手の前に 23 石」と一致しない。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:13-17,52-133,170-257`, `rust/reversi-ai/src/search/mod.rs:19-32,126-194` — 現行 CLI/探索は最善手とその score だけを返す。全合法手の分析は 0040 で追加する。
- `tools/reversi-ai-playground/server/session.mjs:7-45,48-91,112-185` — 対局者検証、同一深さの CLI 引数、固定 Oracle level、盤面更新、AI 応答照合と Human 着手。
- `tools/reversi-ai-playground/server/index.mjs:9-42,49-91`, `server/config.mjs:1-13`, `web/src/main.ts:1-67,95-242` — 外部 path の検証、任意ローカル設定、WebSocket 操作、設定 UI と盤面表示。
- `tools/reversi-ai-oracle/oracle.py:80-159,213-245,698-705,850-945,1774-1780` — Oracle の着手番号別 `-depthprobrange`、pin 済み source/cache/setup。
- `rust/reversi-ai/src/eval/trained.rs:42-143`, `tools/reversi-ai-training/training.py:282-343`, `tools/reversi-ai-training/fixtures/tiny-manifest.json`, `tools/reversi-ai-training/README.md:1-15` — TrainedEvaluator の artifact 契約と強さを主張しない小さな fixture。
- `Makefile:1-9,155-158`, `tools/reversi-ai-playground/README.md:1-49` — 現行の install/start と既存 Oracle setup target。
- `docs/exec-plan/todo/0040-reversi-ai-advisor-analysis.md`（PR #240） — 第1段階の全合法手分析プロトコルと専用フェーズ境界。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai-local-playground.md` — 着手番号、探索・完全読み設定、Advisor、設定凍結と再接続、install/start の可観測契約を先に更新する。
- (MODIFY) `docs/specs/reversi-ai.md`, `rust/reversi-ai/src/config.rs`, `rust/reversi-ai/src/search/` と関連テスト — 第1段階の Playground 固有名の設定を共有 AI 設定として整理し、同じ意味の探索・全合法手分析を両 UI に提供する。通常の `AiConfig` の既定動作は維持する。
- (MODIFY) `rust/reversi-godot/src/bridge.rs` と関連テスト — 共有設定と全合法手分析を Godot から呼べる入口を設ける。Playground と異なるフェーズ判定や score を再実装しない。
- (MODIFY) `tools/reversi-ai-playground/server/session.mjs`, `server/index.mjs`, `server/config.mjs`, `web/src/main.ts`, `web/src/style.css` と関連テスト — seat/Advisor 設定、Human 手番での自動分析、全候補 score の表示、状態同期を実装する。
- (NEW) `tools/reversi-ai-playground/scripts/` の setup 補助 — 既存 Oracle setup の検証済み出力を機械可読に受け取り、fixture 由来のデモ artifact と checkout 外のローカル設定を再現可能に準備する。既存の source pin、cache 検証、artifact 検証を再利用する。
- (MODIFY) `tools/reversi-ai-oracle/oracle.py` — 必要なら setup 結果の binary/data path を機械可読に返す追加出力だけを設ける。全候補分析は 0040 が担当する。
- (MODIFY) `Makefile`, `tools/reversi-ai-playground/README.md` — `playground-install` と `start-playground` の利用方法、前提、デモ artifact の明示、任意の実学習 artifact 指定を記す。

## ブラックボックス契約と作業

1. **手数と探索設定**: 第1段階が定義する「次の意思決定番号 = 盤上石数 − 3」を UI と seat 設定に使う。第 1〜20 手の序盤深さ、第 21〜60 手の中盤深さ、完全読み開始空き数 0〜16 を Strategic、Novice、Trained、Oracle の各 seat と Advisor に独立設定として持ち、対局開始時に凍結する。終盤深さ入力は置かない。Random は探索しないため深さ・完全読み入力を持たない。project AI の設定値とフェーズ判定は共有 Rust API で定義し、Godot でも同じ設定を選択できるようにする。
2. **Oracle**: 第1段階が提供する全合法手 score adapter と着手番号別 `-depthprobrange` を使う。完全読み閾値 `E` の開始手 `61 − E`（`E = 0` は移行なし）を seat/Advisor 設定と一致させる。同等の序盤/中盤設定が Oracle で成立しないと検証された場合に限り、両方を同一深さとして UI と snapshot にその制約を表示する。
3. **Advisor の選択と開始**: Human の黒・白それぞれに `none` または利用可能な Strategic、Novice、Trained、Oracle を選ぶ。Random は数値評価を返さないため Advisor から除く。project AI の Advisor は対局者と同様に session 中は専用の永続 CLI child を持ち、独立した evaluator/探索設定で第1段階の分析モードへ問い合わせる。Oracle Advisor は対局者の GTP child と独立した外部分析 adapter を使う。Human の手番開始時にサーバーが現在局面の**全合法手評価**を自動開始する。ボタン操作は不要で、助言は自動着手しない。計算中も Human は着手できる。着手、パス、再開始、失効で pending/結果を消し、次の Human 手番では新局面を自動評価する。
4. **Advisor の表示と受信境界**: 分析の全候補が揃うまでは従来の候補手●を維持し、盤面横の該当 Human 対局者名のそばに「Advisor 思考中…」を表示する。候補を1つずつ途中表示しない。完了した同一 session/revision/盤面の結果だけを受理し、合法手集合が完全一致した場合に全ての●を同時に符号付き値へ置き換え、思考中表示を消す。値は選択した Advisor 自身の評価値で、有限数を表示時に整数へ四捨五入し、正数は `+N`、負数は `-N`、丸め後の正負ゼロは常に `+0` とする。負値の中間値を含め .5 は絶対値を切り上げる。異なる AI 間や heuristic/exact の値を同一尺度とは扱わない。着手や session 終了時は未完了分析を中断して子プロセスを必要に応じて再生成し、次の局面に古い応答を持ち越さない。分析失敗は思考中表示を消して●を残し、Advisor のエラーを表示して対局を続けられるようにする。再接続では同一 Session の pending または有効な結果を復元する。遅延応答は破棄し、本対局の Oracle GTP process には触れない。
5. **install/start**: `make playground-install` は pnpm install と既存の pin 済み Oracle setup を実行し、成功時に checkout 外の設定ファイルへ検証済み binary/data の絶対 path を保存する。Oracle download/build/検証に失敗した場合は target 自体を失敗させる。学習済み重みがまだない環境でも、既存 tiny fixture から生成した強さ未確認のデモ artifact を checkout 外に置いて TrainedEvaluator を選択可能にし、UI でデモ用と明示する。`PLAYGROUND_CONFIG` で実学習 artifact や Oracle path を指定した場合は項目単位で準備済み設定より優先し、無効な任意設定は該当対局者だけを利用不可にする。`make start-playground` は準備済み設定を渡して既存のローカル dev server を起動し、未 install なら前提不足を明示する。既存の `make playground` は互換 alias として扱う。Oracle、artifact は Rust/GDExtension/配布依存に入れない。

## 作業順序と依存

1. 0040 の plan と実装 PR を先に merge し、全候補の評価プロトコルを確定する。この計画は UI と session の可観測動作を `docs/specs/reversi-ai-local-playground.md` に追記してからコードを変更する。
2. 第1段階の設定と分析を共有 Rust API に整理し、同じ設定・結果を Godot bridge に公開する。通常の AI 設定は変更しない。
3. setup 導線と Oracle/デモ artifact の起動前検証を実装する。
4. seat/Advisor 設定、自動分析、snapshot の pending/結果、候補手 UI を実装する。対局中の Oracle GTP 状態と分析 adapter を独立に扱う。
5. README を更新し、実際の install/start とブラウザー操作を確認する。

## 検証

- 第 1/20/21/60 手、パス、完全読み閾値 0/16 の前後で seat と Advisor の設定が第1段階の分析プロトコルへ正しく渡ることを確認する。
- 同じ project AI の設定と局面を Playground と Godot bridge に渡したとき、フェーズ判定・合法手集合・各 score の意味が一致することを確認する。
- Human 手番開始で分析が自動開始すること、完了までは全候補が●のままで Human 表示の横に「Advisor 思考中…」が出ること、完了時に全合法手へ一斉に符号付き整数が出て思考中表示が消えることを確認する。小数の四捨五入、負の .5、負のゼロと `+0`、不正値、候補集合の不足/過剰も確認する。
- Human が分析中に着手する場合、連続する Human 手番、Human 両席、Oracle 対局者との同時利用、古い結果の破棄、再接続、期限切れ、分析失敗後の対局継続を確認する。
- `make playground-install` で pnpm、pin 済み Oracle の再利用/検証、デモ artifact/設定生成を確認し、`make start-playground` で全対局者が選べること、`PLAYGROUND_CONFIG` で実 artifact を優先できることを確認する。Oracle の長い download/build は既存 cache を使い、生成物は checkout 外とする。
- Playground の `pnpm test`, `pnpm lint`, `pnpm build`、関連 Rust テストと Clippy、該当 Python テスト、workflow lint、`git diff --check`。

## Addresses

- N/A
