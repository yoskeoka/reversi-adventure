# Playground で XOT 開始を選択する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

AI Playground の新規対局で通常開始または XOT を選ぶ。XOT は公式８手棋譜をランダムに選び、合法手として自動適用してから次の手番を開始する。large を既定とし、指定不要のオプションで small も選べる。人間・AI・Oracle・Advisor の組み合わせ、再接続、新規対局で一貫する。Godot 本編には適用しない。既定の通常対局は従来どおり。Addresses: なし。

## 根拠と変更箇所

- (MODIFY) `docs/specs/reversi-ai-local-playground.md` の Session and rules / Wire contract: 設定、選択と初期化、revision・last move、Oracle 同期、エラー、再接続を実装より先に定義する。
- (NEW) `docs/references/xot.md`: LLM 向けに公式の目的、８手、large 10,784 件（Edax/Ntest の各 level 16/20 で -2〜+2）、small 3,623 件（-1〜+1）、出典、取得日、データ形式、利用条件の確認結果、digest を記録し、参照一覧から辿れるようにする。
- (NEW) 両リストの固定データまたは確実に再現できる取得・検証手段。公式は使用のためのダウンロードを案内するが、明示的な再配布ライセンスは確認できていない。配布条件を確認して適切な取扱いを決め、未確認の権利を主張しない。配布データ URL は `https://berg.earthlingz.de/xot/downloads/openingslarge.txt` と `https://berg.earthlingz.de/xot/downloads/openingssmall.txt`、説明は `https://berg.earthlingz.de/xot/aboutxot.php?lang=en`。2026-11-24 取得の SHA-256 はそれぞれ `ccbeb0ed7b7ae23de20013a3992b9a6ede77610bbb5cacda82ccbaedaab72530`、`8a441b077b1093af7b0d1cb55fa5a0d3d1700ce200a1b2d5b6e28d7b17139580`。
- (MODIFY) `tools/reversi-ai-playground/server/session.mjs:96`（生成と snapshot）、`:124`（子プロセス）、`:245`（query）、`:259`（着手と Oracle 同期）、`:280`（進行）、`server/index.mjs:64`（start）、`server/rules.mjs:1`（初期盤・合法手・着手）。８手の有効性を検証し、初期化完了後に初回 snapshot と AI/Advisor を開始する。各 Oracle seat の GTP 棋譜を全８手同期し、思考時間に含めない。失敗は明示し半端な対局を開始しない。通常棋譜と混同しない情報を snapshot に含める。
- (MODIFY) `tools/reversi-ai-playground/web/src/main.ts` の開始設定・表示と `tools/reversi-ai-playground/README.md`。通常/XOT を選択可能にし、small は任意、large は省略時既定とする。選択した設定は対局開始時に固定する。
- (MODIFY) `tools/reversi-ai-playground/server/session.test.mjs` および関連 UI/接続テスト。

## 手順と検証

1. データの利用条件と取得方法を確認し、両リストの行数・形式・digest と配布方針を記録。全行を標準盤面から実際に合法再生し、重複や異常を報告する。選択はリスト行に対して均等、テストでは選択源を固定できるようにする。
2. black-box spec を先に更新。自動８手を revision にどう数え、last move と表示をどう扱うかを明記し、手番、開始失敗、リスト指定不正、既定値、Oracle 同期と reconnect の契約を固定する。
3. 開始設定、正確な再生、Oracle 全 seat 同期と UI を実装。`start` の非同期初期化中に古い対局の遅延結果が新対局を変更しないことも確認する。
4. 全リスト合法性、両リスト選択と既定、通常開始の互換性、human/AI/Oracle の初手、同期順、Advisor、思考時間、エラー、再接続・置換を自動検証。Playground の `pnpm test`, `pnpm lint`, `pnpm build` と適用される workflow lint を実行し、ブラウザで開始・表示を確認する。
5. 検証後この計画を削除し PR を作成する。Arena 側の計画とは独立して作業可能であり、共有ランタイムや同時マージは必要ない。
