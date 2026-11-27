# 固定序盤コーパスのラベル付け

コーパスから 0–9 手の代表局面を測定し、Egaroucid Console の探索値をラベルとして保存する。初期設定は 7.8.1 の level 21、book 無効、1 thread、hash level 25。探索器のバージョン、level、実行ファイルとリソース、ソースの SHA-256 を manifest に保存する。通常の `-solve` に乱数 seed を渡すインターフェースがないため `seed` は null。時間制限は外側のプロセスに適用し、探索器へ `-time` は渡さない。

スコアは盤面の手番視点で、単位は石差。着手可能な側で探索し、強制 pass のときは符号を反転する。終局は `winner-empty-v1` で直接計算する。各 root の初回実行では、実行ファイルが申告するバージョンと、空きマスを残して終わる手計算局面のスコアを照合する。黒の 61–2 は +60、白の 10–53 は −44。強制 pass と終局の白視点はいずれも −60。Console が異なる単位や符号を返した場合は停止する。序盤の探索値は指定した探索の推定値として扱う。

## 準備と小規模測定

### 運用スクリプト

`run-table32-labels.sh` は 7.8.1 level 21 の測定、本番準備、分割・再開、offline検証を行う。
リポジトリのルートで、チェックアウト外の保存先と準備済みの runtime receipt を絶対パスで指定する。

```sh
operator=tools/reversi-ai-training/run-table32-labels.sh
run_directory=/absolute/path/reversi-ai-runs/0058
runtime_receipt=/absolute/path/oracle-runtime/runtime.json

rtk proxy bash "$operator" "$run_directory" measure "$runtime_receipt"
```

`measure` は少数の代表局面を測定し、見積もりを JSON で表示する。同じコマンドで測定を再開できる。
見積もりの `complete` が true になったら、計測値からバッチサイズと１バッチのタイムアウトを決める。
以下の 16 局面・7,200 秒は準備の例で、設定は本番 manifest に固定される。

```sh
LABEL_BATCH_SIZE=16 LABEL_BATCH_TIMEOUT_SECONDS=7200 \
  rtk proxy bash "$operator" "$run_directory" prepare "$runtime_receipt"

# phase 0–7 を順に進める。予算到達時は同じコマンドで再開する。
rtk proxy bash "$operator" "$run_directory" run 0 7

# phase 8 と 9 は各 phase の batch を [開始, 終了) で区切れる。
rtk proxy bash "$operator" "$run_directory" run 8 8 0 64
rtk proxy bash "$operator" "$run_directory" run 8 8 64 128
rtk proxy bash "$operator" "$run_directory" run 9 9 0 64

rtk proxy bash "$operator" "$run_directory" verify
# 残りを実行してから、514,097 件すべての保存済みラベルを照合する。
rtk proxy bash "$operator" "$run_directory" verify --complete
```

`run 8 8` や `run 9 9` を実行すると、完了済みバッチを照合しながら対象 phase の残りを進める。
`JOBS`、`ATTEMPT_WALL_SECONDS`、`MAX_RSS_KIB`、`PROGRESS_EVERY` の既定値は
それぞれ 1、43,200 秒、1,572,864 KiB、128 局面。測定時の並列度は 1 に固定する。
保存先は `$run_directory/labels-v7.8.1-level21`。全件検証は Oracle を起動しない。

### 個別コマンド

リポジトリのルートで実行する。`run_directory` はチェックアウト外に置き、以下では絶対パスに置き換える。準備済みの 7.8.1 runtime receipt があれば再利用できる。新しいランタイムが必要な場合は `prepare-runtime` で新規ディレクトリに用意する。 [Oracle runtime の準備](../reversi-ai-oracle/README.md)

```sh
run_directory=/absolute/path/reversi-ai-runs/0058
corpus_root=data/table32-opening-corpus
label_tool=tools/reversi-ai-training/table32_labels.py
runtime_receipt=/absolute/path/oracle-runtime/runtime.json
measurement_root="$run_directory/measurement-v7.8.1-level21"
production_root="$run_directory/labels-v7.8.1-level21"

rtk python3 "$label_tool" prepare --corpus-root "$corpus_root" \
  --label-root "$measurement_root" --runtime-receipt "$runtime_receipt" \
  --level 21 --measure-per-phase 3 --timeout-seconds 1800
rtk python3 "$label_tool" run --corpus-root "$corpus_root" \
  --label-root "$measurement_root" --jobs 1 --attempt-wall-seconds 43200 \
  --max-rss-kib 1572864
rtk python3 "$label_tool" estimate --corpus-root "$corpus_root" \
  --label-root "$measurement_root"
```

測定は phase ごとに ID 順を等分した区間の中央から選び、各局面を単独プロセスで探索する。各 phase の見積もりは標本の wall time を全件数に外挿した直列時間で、観測した最小・最大値の外挿を併記する。単独プロセスの初期化時間も含む。少数標本での経験的な範囲であり、並列の速度や所要時間を保証する範囲ではない。欠測の phase があると全体見積もりは null。失敗と timeout は `attempts`、観測済み peak RSS は `completion.peak_resources` に残る。Linux のサンプリングで観測できなかった RSS は `rss_incomplete_samples` で確認する。

測定 root は学習入力にできない。別 level や設定を測るときは新しい測定 root を指定する。別バージョンは `--runtime-receipt` の代わりに `--version`、`--binary`、`--cwd`、`--source-archive`、`--source-sha256`、`--source-url` を指定する。`--cwd` は Console の `resources/` を含む作業ディレクトリ。ソース配布元の SHA-256 を指定し、対応するソースから作った実行ファイルを選ぶ。別バージョンでも同じ `-solve` 仕様とスコア校正を満たす必要がある。runtime receipt を使った場合は検証済みのビルド情報も参照できる。

## 本番の準備、分割実行、再開

測定後に batch サイズ、並列度、予算を決める。`--timeout-seconds` は一つの Console 起動全体を制限する。`--batch-size` が 16 なら最大 16 局面を含むため、一局面の時間で決めない。`--jobs` は同時に起動する Console 数で、各 Console の thread 数は `prepare --threads` が決める。`--max-rss-kib` は producer の RSS と子プロセス合算 RSS のそれぞれに適用される。以下は phase 0 の最初の shard を開始してから phase 0–1 を再開する例。

```sh
rtk python3 "$label_tool" prepare --corpus-root "$corpus_root" \
  --label-root "$production_root" --runtime-receipt "$runtime_receipt" \
  --level 21 --batch-size 16 --timeout-seconds 7200
rtk python3 "$label_tool" run --corpus-root "$corpus_root" \
  --label-root "$production_root" --phase-start 0 --phase-end 0 \
  --batch-stop 1 --jobs 1 --attempt-wall-seconds 43200 --max-rss-kib 1572864
rtk python3 "$label_tool" run --resume --corpus-root "$corpus_root" \
  --label-root "$production_root" --phase-start 0 --phase-end 1 \
  --jobs 1 --attempt-wall-seconds 43200 --max-rss-kib 1572864
rtk python3 "$label_tool" verify --corpus-root "$corpus_root" \
  --label-root "$production_root"
```

phase は両端を含む。`--batch-start` と `--batch-stop` は選んだ phase 範囲内での 0-based の shard 番号。`--batch-stop` は終端の一つ手前まで含む。通常は同じ範囲を `--resume` に渡せばよい。完成した shard は raw 出力と局面を照合して再利用する。未完成の shard だけを再試行する。進捗は stderr に出る。`phase` は `00`–`09`、`unit` は phase 内の開始局面番号で、`completed` と `total` はその実行範囲の局面数。`--progress-every N` で前回表示から N 局面以上進んだ shard 完了時に表示する。既定は 1。開始、終了、失敗は常に表示する。

```text
table32 phase=00 unit=000000 completed=1 total=1 elapsed_seconds=1.000 status=saved
```

各実行の予算、設定、失敗と観測 RSS は `slices/<番号>/attempts/0000/` を確認する。wall time、RSS、並列度、処理範囲は `run --resume` で調整できる。level、timeout、batch サイズ、runtime、コーパスが変わった場合は元の root を保持し、新しい root で準備する。設定違いを既存ラベルに混ぜない。人間の中断や supervisor による停止でも、原子的に発行された shard は保持される。

## 保存と復元

本番ラベルの `manifest.json`、`calibration.json`、`batches/*.json.gz` を version/level が分かるディレクトリに保存する。時間と予算の根拠が必要なときは `slices/` の receipts と `estimate` の JSON も保存する。圧縮 shard は局面 ID、元コーパスの shard digest、raw Console 出力、ラベル、digest を持つ。まず通常 Git で phase/batch 単位に保存し、保持した範囲を記録する。復元したディレクトリに対する `verify` は manifest と校正値、保存済み shard の局面 ID、合法手、ラベル、digest をオフラインで照合する。全量の保管を確かめる場合は `verify --complete` を使う。

学習側は固定ラベル入力を明示指定する。選んだ局面集合に必要な全 shard が揃ってから学習を始める。既存 0054/0056 データと 0019 採用モデルはそのまま使用できる。0018 の予約局面は学習入力の選定時に除外する。
