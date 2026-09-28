# 全合法手の Advisor 評価値を CLI から取得する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

ローカル対局 Playground が、選択した Strategic、Novice、Trained、Oracle から現在の Human 手番にある**全合法手**の評価値を取得できる。全候補を同一の完了探索深さ・同一局面の結果として返し、途中結果や古い局面の値を盤面に出さないための有界な分析プロトコルを用意する。通常の AI 対局者が使う最善手プロトコル、既定探索フェーズ、既存 oracle corpus/profile は維持する。UI と Make の導線は 0039 の後続実行計画が担当する。

この計画は、0039 の Human Advisor を「明示的に推奨手を1つ得る」方式から、手番開始時に全合法手の値を自動表示する方式へ修正するための第1段階である。探索 API と Oracle adapter の変更が CLI 引数追加だけでは済まないため、ユーザー指定に従い2段階に分ける。

## 現状の参照

- `docs/specs/reversi-ai-local-playground.md:1-29` — 既存の対局者、設定、プロセスとスナップショット契約。
- `docs/specs/reversi-ai.md:320-336`, `rust/reversi-ai/src/config.rs:1-59`, `rust/reversi-ai/src/search/mod.rs:19-32,126-194` — 既定フェーズ、最善手だけの `SearchResult`、完全読みと予算。
- `rust/reversi-ai/src/search/negascout.rs:53-106` — 反復深化で単一の最善手/PV を完了結果として保持する通常探索。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:13-17,52-133,170-257` — 既存の設定引数と `position_id<TAB>move|pass` stdout プロトコル。
- `rust/reversi-ai/src/eval/strategic.rs:5-34`, `eval/novice.rs:31-55`, `rust/reversi-ai/src/explain.rs:58-79` — 通常評価は evaluator 固有の重み付き値、完全読みは最終石差。
- `tools/reversi-ai-oracle/oracle.py:80-159,213-245,1077-1115,1228-1315` — Oracle の着手番号別設定、子局面一括評価、root 側への符号変換とパス処理。
- `tools/reversi-ai-playground/server/session.mjs:73-91,112-122`, `server/processes.mjs:1-78` — 対局者の CLI/GTP 起動と1行応答の制限。
- `docs/exec-plan/todo/0039-reversi-ai-playground-controls.md`（PR #239） — 後続の UI/起動計画。両 PR の merge 順序はこの基盤を先とする。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — Playground 専用の 1〜20/21〜60 手境界と全合法手分析の意味、score 視点・深さ・予算・結果完全性を先に定義する。
- (MODIFY) `docs/specs/reversi-ai-local-playground.md` — Advisor 用の全候補評価プロトコルと利用可能な AI、Oracle 評価の制限を定義する。
- (MODIFY) `rust/reversi-ai/src/config.rs`, `rust/reversi-ai/src/search/mod.rs`, `rust/reversi-ai/src/search/negascout.rs`, `rust/reversi-ai/src/bin/reversi-ai-cli.rs` と関連テスト — 明示的な Playground 境界、全 root 合法手の分析 API、CLI の独立モードを追加する。実装で探索順の変更が必要ならその範囲を限定し、対局モードとの差分をテストする。
- (MODIFY) `tools/reversi-ai-oracle/oracle.py` と関連テスト — pin 済み Oracle に対する局面単位の全候補評価コマンドを追加し、既存 child solve と score 符号処理を再利用する。
- (MODIFY) `tools/reversi-ai-oracle/README.md` — 分析プロトコル、score の意味、限界と再実行手順を記す。

## ブラックボックス契約と作業

1. **位置と設定**: 次の着手番号は `盤上石数 − 3` とし、パスでは増やさない。明示的な Playground 設定だけが第 1〜20 手に序盤深さ、第 21〜60 手に中盤深さを使い、終盤深さ入力は持たない。完全読み開始空き数 0〜16 は別設定で、閾値以下では通常探索より優先する。既定 CLI/他の profile の 20/44 石境界を変えず、設定 fingerprint に新境界を含める。
2. **project AI の全候補分析**: 既存 CLI の既定 `position_id<TAB>move|pass` を維持し、明示した分析モードだけが `position_id` と、合法座標を漏れ・重複なく含む `{move, value}` の組を返す。値は現在の手番側から見た有限の評価値とする。通常探索では全 root 候補を**同じ完了深さ**で評価し、root 深さ D に対して各候補の子探索を整合する深さで行う。即終局の候補だけは探索を省き、確定した exact 値を返せる。全候補の探索を同一の単調 deadline/ノード上限で管理し、最後に全候補を完了できた反復の一組だけを返す。初回の完全な一組がない場合は明示的に失敗し、部分集合、別々の深さ、根局面からフェーズがずれた子局面の評価を成功扱いしない。完全読み領域は全候補の exact proof が完了した場合だけ数値を返す。Pass/GameOver は空集合と明示的な outcome を返す。既存の探索結果、対局応答、stderr 診断を壊さない。
3. **Oracle の全候補分析**: GTP `genmove` は最善手しか返さないため、pin 済み外部 Oracle の既存 `-solve` 子局面一括評価を基盤に、局面と全合法手から root 側の値を求める独立コマンドを用意する。第 1〜20/21〜60 手は `-depthprobrange` で指定する。意思決定番号 `m` の空き数は `61 − m` で、完全読み閾値 `E` が 1〜16 なら `m = 61 − E` から残り空き数以上の深さを使用し、`E = 0` ならその range は作らない。子局面に1手進めた分の深さ、手番反転、強制パス、即終局の値を検証する。全合法手が規定深さまで完了しない場合は失敗とし、無関係な corpus/profile や GTP 対局者の状態に触れない。
4. **共通出力**: 両 producer は `position_id`、局面、手番、全合法手の座標と有限 numeric score、完了深さ、exact/heuristic 区分を照合可能な形で返す。受け手は合法手集合との完全一致、局面 ID、重複、不正数値を検証できる。値は Advisor 固有の単位であり、異なる AI や通常探索と完全読みを同一尺度として比較しない。UI の整数化は後続 0039 で行う。

## 作業順序と依存

1. 2 つの spec を先に更新し、全候補の完了条件と失敗条件を固定する。
2. Rust の専用フェーズ設定、探索 API、CLI 分析モードを実装する。
3. Oracle の独立した全候補分析コマンドを既存アダプターに追加する。
4. この PR を merge してから、0039 の UI/Make 実装を開始する。0039 の plan PR はこの依存と新しい Advisor 表示契約を記録する。

## 検証

- 第 1/20/21/60 手とパス、完全読み閾値 0/16 の前後でフェーズ・Oracle depth range・root 側 score を確認する。
- 複数合法手の一つが制限に達する場合は部分結果を出さず、全件完了時だけ全合法手を一度に返す。初期盤面、強制パス、終局、即終局候補、同点候補、色反転、古い position ID、不正値を確認する。
- 対局 CLI の stdout プロトコルと既存既定フェーズ、TT/context 隔離、Oracle GTP/corpus/profile の既存動作を確認する。
- 関連 Rust/Python テスト、Clippy、workflow lint、`git diff --check`。外部 Oracle を使う検証は pin 済み cache と明示 timeout を使う。

## Addresses

- N/A
