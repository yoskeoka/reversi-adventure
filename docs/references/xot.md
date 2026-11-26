# XOT 開始棋譜

XOT は、通常初期盤面から８手を進めた互角に近い局面を選び、序盤の変化を増やす。David Beck が８手の棋譜を使う方法を提案し、Matthias Berg と Borja Moreno が Edax と Ntest を使って２つのリストを作成した。large は各エンジンの level 16 と 20 で８手後の評価値が -2〜+2 の 10,784 件、small は -1〜+1 の 3,623 件。 [About XOT](https://berg.earthlingz.de/xot/aboutxot.php?lang=en)

2026-11-24 に公式配布元から直接取得したファイルを [エンジンのデータディレクトリ](../../rust/reversi-engine/data/xot) に収録した。１行は小文字の座標８組、区切りなしの ASCII 16 バイトと LF。行順と改行を含めて取得時のバイト列を保持する。Arena の PR #57 に収録されたデータとも一致する。 [XOT Downloads](https://berg.earthlingz.de/xot/download.php?lang=en) [Arena PR #57](https://github.com/yoskeoka/reversi-ai-arena/pull/57)

公式サイトは他サイトや実盤での対局用にリストのダウンロードを案内している。About と Download の両ページでは、リストの明示的な再配布ライセンスを確認できなかった。 [About XOT](https://berg.earthlingz.de/xot/aboutxot.php?lang=en) [XOT Downloads](https://berg.earthlingz.de/xot/download.php?lang=en)

## 取得と照合

リポジトリルートから実行する。

~~~sh
set -eu
xot_dir=$(mktemp -d)
curl --fail --location --proto '=https' --output "$xot_dir/openingslarge.txt" \
  https://berg.earthlingz.de/xot/downloads/openingslarge.txt
curl --fail --location --proto '=https' --output "$xot_dir/openingssmall.txt" \
  https://berg.earthlingz.de/xot/downloads/openingssmall.txt
(
  cd "$xot_dir"
  sha256sum --check <<'EOF'
ccbeb0ed7b7ae23de20013a3992b9a6ede77610bbb5cacda82ccbaedaab72530  openingslarge.txt
8a441b077b1093af7b0d1cb55fa5a0d3d1700ce200a1b2d5b6e28d7b17139580  openingssmall.txt
EOF
)
cmp "$xot_dir/openingslarge.txt" rust/reversi-engine/data/xot/openingslarge.txt
cmp "$xot_dir/openingssmall.txt" rust/reversi-engine/data/xot/openingssmall.txt
~~~

ビルド時に両ファイルの SHA-256 を検証する。`cargo test -p reversi-engine xot` は各リスト内の棋譜と再生後の盤面の重複、全手の合法性、８手後に黒が着手できることを検証する。

## Godot 本編からの利用

Rust の GDExtension 側で `reversi_engine::xot::XotList::default().random()` を呼ぶと large を利用できる。small を選んだ場合は `XotList::Small.random()` を使う。固定行の場合は `XotList::at(index)`、保存済み棋譜からの復元は `XotOpening::replay(notation)` を使う。

開始画面で選んだリストと `opening.notation()` を対局メタデータに保存し、`opening.into_game()` を [GDExtension の `ReversiGame.game`](../../rust/reversi-godot/src/bridge.rs) に設定する。これで既存の盤面・手番・合法手・履歴の読み出しを使える。次の着手は黒の９手目。リストは Rust ビルド時に埋め込まれ、Godot のエクスポート設定や実行時に追加のファイル取得は不要。
