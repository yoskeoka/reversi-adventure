# table32 序盤固定コーパス

標準初期盤（黒先）から0–9着手で到達するD4同値類を通常Gitに保存する。局面には黒白の盤面、
手番、終局フラグ、phase内の固定IDを含む。教師スコアは別のラベル成果物に格納する。

| 着手数 | 局面数 |
| ---: | ---: |
| 0 | 1 |
| 1 | 1 |
| 2 | 3 |
| 3 | 14 |
| 4 | 60 |
| 5 | 322 |
| 6 | 1,773 |
| 7 | 10,649 |
| 8 | 67,245 |
| 9 | 434,029 |
| 合計 | 514,097 |

着手数は盤上の石数から初期4石を引いた値。強制パスは自動処理し、着手可能な側を記録する。
両者が着手できない局面は最後に着手した側と終局フラグを記録して、その先へ展開しない。
最短終局は9着手で、9着手目に36局面が終局する。盤面はa1を最下位ビットとする行優先の黒・白の64 bitマスクで表し、色と
手番を保ったままD4の8変換から数値順で最小の `(black, white)` を代表にする。代表の盤面座標は
元棋譜の座標から回転・反転している場合がある。phase別件数はEgaroucidの報告と一致する。
[山名琢翔「Egaroucid 技術解説」](https://www.egaroucid.nyanyan.dev/ja/technology/explanation/)

phase内を `(black, white, turn)` 順で整列し、0始まりの `pNN-NNNNNN` を振る。
1 shardは同じphaseの最大4,096行。`manifest.json` は版、規則、件数、終局数、ID範囲、
各圧縮shardのSHA-256を記録し、manifest全体のdigestは `digest` 自身を除いた正規JSONで計算する。
gzipはファイル名なし・mtime 0で生成する。

## 検証と復元

リポジトリのルートで次を実行する。生成器はReversi engineのビットボード合法手を使い、
検証器は独立した座標走査・D4変換で各phaseの展開を再計算し、全レコードを照合する。

```bash
cargo build --release -p reversi-engine --example table32_opening_corpus
python3 tools/reversi-ai-training/table32_corpus.py verify \
  --root data/table32-opening-corpus \
  --enumerator target/release/examples/table32_opening_corpus
```

再生成する場合は新しい作業rootを使い、`generate` の後に同じrootを `verify` に渡す。
通常Gitへ保存する生成物は `manifest.json` と `shards/`。作業rootには再開用のcheckpointと実行記録も残る。

```bash
python3 tools/reversi-ai-training/table32_corpus.py generate \
  --root /tmp/table32-opening-corpus-rebuild \
  --enumerator target/release/examples/table32_opening_corpus \
  --progress-every 16
```

中断時は同じ指定に `--resume` を追加する。完成shardを照合して続行し、
未完了shardを生成する。試行ごとの壁時計上限は `--attempt-wall-seconds`、
生成側と列挙器のRSS上限は `--producer-rss-kib` と `--child-rss-kib` で指定する。
壁時計とRSSの上限は再開時にも指定できる。列挙器のidentityや対象phaseを変更する場合は新rootを作る。
