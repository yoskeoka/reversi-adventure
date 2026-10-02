# Playgroundの探索上限拡張と黒白の総思考時間表示

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

Playgroundの序盤探索深さ（1〜20手）は1〜12を維持し、中盤探索深さ
（21〜60手）は1〜16、完全読み開始空き数は0〜30を選べるようにする。
黒・白それぞれのAI着手要求に費やした総時間を仲介サーバーで測り、対局画面に表示する。
時間は概算の経過時間でよく、エンジン内部のCPU時間や厳密な探索時間を要求しない。

対局者とHuman Advisorの同名設定で範囲が一致し、最大値がサーバー・Rust CLI・
Oracle adapterを通って実際の設定に反映されることを完了条件とする。
深さ16や空き30での探索完了・速度・棋力は保証しない。既存の探索budgetと
プロセスtimeoutを維持し、未完了を完全読み済みとは扱わない。

## 参照

- `docs/specs/reversi-ai-local-playground.md:25-43,80-97` — 設定、snapshot、Oracle解析範囲、プロセス境界。
- `docs/specs/reversi-ai.md` — 共通DecisionMoveConfigと解析契約。通常AiConfigと固定profileの設定とは区別する。
- `docs/design-decisions/2026-03-02-reversi-ai-design.md`、`core-beliefs.md` — 共通Rust探索とspec-first。
- `tools/reversi-ai-playground/server/session.mjs:9,54-86` — `LIMITS`、`validatedSearch`、`oracleDepthArgs`。
- 同ファイル `Session.snapshot`、`Session.query`、`Session.drive:280-302` — snapshot、着手要求と状態更新。
- `tools/reversi-ai-playground/web/src/main.ts:5-28,39-46,132-159,198` — 型、入力、catalog範囲適用、対局表示。
- `rust/reversi-ai/src/config.rs:24-27,69-111,118-144` — 閾値の直接設定、`DecisionMoveConfig::new`、位相・identity・境界tests。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:133-160,382-393` — match/Advisorの共通設定検証とCLI tests。
- `rust/reversi-ai/src/search/mod.rs:196-204,267` — 閾値による完全読み選択。設定値の16へのclampはない。
- `tools/reversi-ai-oracle/oracle.py:102-138` — `analysis_config`、範囲生成とfingerprint。
- `tools/reversi-ai-playground/server/session.test.mjs:70-78`、`tools/reversi-ai-oracle/tests/` — Oracle範囲と解析の既存tests。
- `tools/reversi-ai-playground/package.json` — package所有のtest/lint/build。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai-local-playground.md` — 各入力範囲、catalog、総時間snapshotと表示、計測・reset・再接続契約。
- (MODIFY) `docs/specs/reversi-ai.md` — 共通decision-move設定とAdvisorの受理範囲、探索完了を保証しないこと。
- (MODIFY) `tools/reversi-ai-playground/server/session.mjs` — 序盤/中盤別の範囲、共通検証、黒白の時間累積とsnapshot。
- (MODIFY) `tools/reversi-ai-playground/web/src/main.ts` — catalog/snapshot型、対局者/Advisor入力、黒白の総時間表示。
- (MODIFY, 必要時) `tools/reversi-ai-playground/web/src/style.css` — 狭い画面でも読める時間表示。
- (MODIFY) `rust/reversi-ai/src/config.rs`、`rust/reversi-ai/src/bin/reversi-ai-cli.rs` — 共通受理範囲と境界tests。
- (MODIFY) `tools/reversi-ai-oracle/oracle.py` と解析tests — 可変解析設定の受理範囲。named profileはそのまま。
- (MODIFY) `tools/reversi-ai-playground/server/session.test.mjs` と必要な関連tests — 上限伝搬、時間累積、失敗・再接続・reset。
- (DELETE, 実装検証後) 本計画。

## ブラックボックス契約

1. 序盤1〜12、中盤1〜16、完全読み0〜30を整数で受理する。範囲外は拒否する。
   catalogは`openingDepth: [1,12]`、`midgameDepth: [1,16]`、`exact: [0,30]`を返し、
   UIの通常入力とAdvisor入力が同じ範囲を使う。既定値と位相境界は維持する。
   legacy単一`depth`は序盤/中盤に同値を渡すため、共通に合法な1〜12までを受理する。
2. 設定値を黙って丸めない。Rust共通設定とOracle解析も同じ範囲で検証する。
   Oracleの完全読み開始は`61-E`手目で、E=30なら31手目、E=0なら切替なし。
   固定strength/training/benchmark profileやGodot既定値の更新は含めない。
3. snapshotに`thinkingTimeMs: { B: number, W: number }`を追加する。
   単位はミリ秒、有限の非負値で、対局作成時は両方0。
   仲介サーバーの単調時計で各`Session.query`の直前から完了までを測り、要求した色へ一度だけ加算する。
   query内の通信・応答待ちを含む。プロセス起動、相手着手のOracle同期、Humanの待ち時間、
   Advisor解析、UI描画は含めない。Randomは同じquery境界で測る。
4. 着手応答や失敗/timeout後に終了したqueryの時間を累積し、次のsnapshotで公開する。
   失敗したqueryもその色へ一度だけ加算する。強制passでqueryを出さない場合は加算しない。
   終了・エラー・再接続で累積を保持し、新規対局で0へresetする。
   閉じた旧sessionの遅延応答が新sessionの値を変更しない。
5. 黒・白に「総思考時間」を表示し、ミリ秒から秒へ変換して小数1桁（例: `12.3 秒`）で示す。
   Humanは0を表示する。対局終了後も両方を残す。
   初版は完了したqueryの累積を表示し、思考中の連続更新は必須としない。

## 作業順序と依存

1. 二つのspecを先に更新する。
2. RustとOracleの可変設定の検証・境界testsを更新する。
3. server catalogと検証を分け、UI入力と接続する。最大値がCLI引数・Oracle rangeに到達することを確認する。
4. server queryの経過時間累積、snapshot、UI表示を実装する。
5. 下記検証を行い、計画を削除し、`review-task`で実装PRを作成・最新headを確認する。

設定範囲と時間表示の調査・独立レビューは並列化できる。spec更新とGit書き込みは直列に行う。
実装は本計画PRのレビュー・マージ後、`feat/playground-search-limits-thinking-time`の新規worktreeで行う。

## 検証

- Rust/CLI・server・Oracleで序盤12受理/13拒否、中盤16受理/17拒否、完全読み30受理/31拒否、
  下限、legacy depth、位相20/21手を確認する。閾値30と31空きの切替は設定伝搬または
  小さいnode budgetで検証し、30空きの全探索をテスト条件にしない。
- 対局者/Advisorで同じ最大値が渡ることと、Oracle E=30のrange/fingerprintを確認する。
  固定profileと既存identityの互換性も確認する。
- 制御可能な時計とquery doubleで黒白の別累積、複数着手、失敗/timeout、強制pass、
  Human/Advisor除外、終局・再接続保持、新規reset、旧session完了の隔離を検証する。
  実時間sleepの精密な一致をテスト条件にしない。
- `rtk cargo test -p reversi-ai`、`rtk cargo test -p reversi-engine`、
  `rtk cargo clippy --workspace -- -D warnings`、`rtk cargo fmt --all -- --check`。
- `rtk pnpm --dir tools/reversi-ai-playground test`、同`lint`、同`build`、`rtk make oracle-test`。
- ブラウザーで通常/Advisor入力上限と黒白時間表示を確認し、浅いAI対局で累積と終局保持、
  Human対局の0、新規対局reset、狭い画面で盤面の寸法が変わらないことを確認する。
- `rtk git diff --check`、`rtk ./tools/workflow-lint.sh --mode=pre-push`。
  計画PRはMarkdown構造・参照確認とdiff/workflow lintを行う。

## Addresses

- N/A
