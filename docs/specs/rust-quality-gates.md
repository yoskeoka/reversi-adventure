# Rust の品質ゲート

## ローカルで検査する範囲

Rust ソース、Cargo マニフェスト、ビルドスクリプト、crate が取り込む入力を変更したら、影響する crate を選んで Clippy を実行する。共有入力を変更した場合は、その入力の影響先をすべて選ぶ。共有依存やツールチェーン設定の変更で影響範囲を絞れない場合は、ローカルで検査した代表範囲と CI に委ねた範囲を記録する。Rust に影響しない差分ではローカルの Rust lint を省く。

```sh
make rust-clippy-local CLIPPY_PACKAGES="reversi-engine reversi-ai"
make rust-clippy-local CLIPPY_PACKAGES=reversi-godot CLIPPY_ALL_TARGETS=1
```

`CLIPPY_PACKAGES` には空白区切りで workspace package の完全名を指定する。空の指定、未知の名前、バージョン付きの指定、パスなどは Cargo の起動前に拒否する。選択した package ごとに `-p` を渡し、Clippy には `-- --no-deps -D warnings` を渡す。依存のコンパイルは Cargo が行う。上のエンジンと AI の組み合わせには Godot のコンパイルは含まれない。

既定では通常の lib と bin を検査する。テスト、example、bench、またはそれらに対応する条件付きコードを変更した場合は `CLIPPY_ALL_TARGETS=1` を指定する。非デフォルト feature の検査が必要な場合は、対象の feature を明示する。

```sh
CARGO_BUILD_JOBS=2 cargo clippy -p <package> --features <feature> -- --no-deps -D warnings
```

ローカルの make ターゲットは `CARGO_BUILD_JOBS` の既定値を `2` とし、指定済みの値を使う。worktree の Cargo ビルドディレクトリとキャッシュを再利用し、同じビルドディレクトリを使う Cargo コマンドは直列に実行する。

## PR で確認する範囲

引き渡し時にはローカルで検査した crate、ターゲット、feature と結果を記録する。PR の最新コミットで `cargo clippy --workspace --all-targets -- -D warnings`、エンジンと AI のテスト、GDExtension のビルドと共有ライブラリの確認、Oracle ジョブが成功したことを確認する。
