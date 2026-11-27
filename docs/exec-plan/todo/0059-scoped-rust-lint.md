# 0059 担当 crate に絞った Rust lint

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

[ワークスペース計画 0048](https://github.com/yoskeoka/vibe-coding-workspace/pull/172) の先行実装として、Reversi Adventure の Rust 差分を担当したエージェントが、影響する crate の Clippy を引き渡し前に実行できるようにする。エンジンと AI の選択で Godot がコンパイルされないことをローカルで確認し、実装 PR の最新コミットで全ワークスペースの全ターゲットの Clippy と既存 CI ゲートが通った時点を完了とする。

## 仕様と変更箇所

Addresses: docs/issues/0013-reversi-ai-clippy-clone-on-copy.md

- (NEW) `docs/specs/rust-quality-gates.md` にローカル lint と CI の契約を記す。
  - Rust ソース、マニフェスト、ビルドスクリプト、crate が取り込む入力の変更は影響先の crate を選ぶ。共有入力は影響先をすべて含める。共有依存やツールチェーン設定の影響を絞れない場合はローカルで確認した代表範囲と CI に委ねた範囲を記録する。Rust に影響しない差分では Rust lint を省く。
  - `make rust-clippy-local CLIPPY_PACKAGES="reversi-engine reversi-ai"` は通常の lib／bin を検査する。テスト、example、bench、または対応する条件付きコードの変更には `CLIPPY_ALL_TARGETS=1` を付ける。必要な非デフォルト feature は `CARGO_BUILD_JOBS=2 cargo clippy -p <package> --features <feature> -- --no-deps -D warnings` の形で明示する。
  - `CLIPPY_PACKAGES` は空白区切りの完全な workspace package 名とする。空、未知の名前、バージョン付きやパスなどの package spec は Cargo の lint 起動前に失敗する。Cargo に package ごとの `-p` と `-- --no-deps -D warnings` を渡し、必要な依存のコンパイルは Cargo に任せる。ローカル入口の `CARGO_BUILD_JOBS` は未指定時に `2` とし、指定済みの値を尊重する。worktree のビルドディレクトリとキャッシュを再利用し、同じビルドディレクトリへの Cargo 実行は直列に行う。
  - 引き渡しには対象 crate、該当するターゲットと feature、結果を記録する。PR 最新コミットで CI の全ターゲット lint、エンジン・AI テスト、GDExtension ビルド、Oracle ジョブの結果を確認する。
- (MODIFY) `docs/specs/README.md` の仕様一覧と `AGENTS.md:105–110` の Build & Lint Commands から新仕様に誘導する。代表例に `reversi-engine`、`reversi-ai`、`reversi-godot` を示し、既存のテスト・ビルド入口を案内する。
- (MODIFY) `Makefile:32` の `CARGO` 定義付近に `rust-clippy-local` を追加する。`Cargo.toml:1–7` の workspace メンバーに対応する完全な package 名の許可リストを使い、メンバー変更時に同期する。無効入力は Cargo 呼び出し前に拒否する。`rust/reversi-godot/Cargo.toml:10–13` の依存方向に沿い、エンジンと AI を選んだときは Godot を選択しない。
- (MODIFY) `.github/workflows/ci.yml:21–22` の Run clippy を `cargo clippy --workspace --all-targets -- -D warnings` にする。既存のテスト、GDExtension および Oracle のジョブを維持する。
- (MODIFY) `rust/reversi-ai/src/player.rs:127` と `rust/reversi-ai/src/search/endgame.rs:1337,1567` で報告された全ターゲット lint の警告を、テストの意味を保ったまま解消する。対象は Copy 型の clone、固定長のバイト分割、末尾の不要な return。
- (DELETE) 検証後、完了した計画と解決したローカル issue 0013 を削除する。

## 実施順序と依存

1. この計画のマージ後、仕様と仕様索引を更新する。
2. ローカル入口、エージェント指示、CI を更新する。引数検証と CI 定義の確認は独立して実施できる。同じビルドディレクトリを使う実 Cargo コマンドは順番に実行する。
3. 検証結果を実装 PR に記録して、この計画を削除する。最新コミットの CI と選択式入口の結果をワークスペース計画 0048 に引き渡す。Arena 2件の子計画はこの結果を前提とする。

## 検証

- 記録用の代替 `CARGO` で、複数 crate と全ターゲットの引数、既定・上書き時のジョブ数、空・未知・完全名以外の指定で Cargo を起動しないこと、Cargo の失敗が make の失敗になることを確認する。
- `make rust-clippy-local CLIPPY_PACKAGES=reversi-ai` を実行する。新しい実装 worktree の Cargo 詳細ログで `reversi-engine` と `reversi-ai` の選択実行に Godot 関連コンパイルが含まれないことを確認する。
- `cargo clippy --workspace --all-targets -- -D warnings`、`cargo test -p reversi-engine`、`cargo test -p reversi-ai`、`cargo build -p reversi-godot` を実行する。実装 PR の最新コミットで全ターゲット lint、既存テスト、共有ライブラリ確認、Oracle の各結果を確認する。
- 計画 PR はドキュメントの差分、構造、workflow lint を確認する。実装 PR では workflow lint と `actionlint` も確認する。
