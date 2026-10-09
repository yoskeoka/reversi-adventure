# Reversi AI benchmark corpus

`positions-v1.jsonl` is a reproducible, versioned input corpus for later
search benchmarking. It is not a performance report, reference analysis, or
acceptance threshold.

The corpus has sixteen positions: 20, 40, 44, and 48 occupied discs from each
of four level-6, bookless, single-thread Console self-play games. Every record
includes the complete coordinate transcript used to replay its board. Console
self-play omits forced passes from that transcript; the validator reconstructs
those legal state transitions while replaying it.

```sh
make benchmark-oracle-setup
make benchmark-corpus
make benchmark-corpus-verify
```

The generator uses six randomized opening plies. Regeneration therefore makes
a new valid corpus, whereas `benchmark-corpus-verify` validates the checked-in
artifact's schema, replay, expected roots, and D4 uniqueness.

## Reference analysis and release comparison

`make benchmark-reference` writes the pinned, canonical
`reference-winner-empty-v1.jsonl` into a new file. The existing
`reference-v1.jsonl` remains frozen. The new file is a reference-analysis artifact, not an evaluator
training target. `make benchmark-reference-verify` checks its profile and
corpus digests, every root evaluation, and the exact 16-empty metadata.

The comparator only accepts explicit, already-built release profiler binaries.
Build `main` and the candidate separately, on the same host, then run:

```sh
make benchmark-compare \
  BENCHMARK_BASELINE=/absolute/path/to/main/reversi-ai-search-profile \
  BENCHMARK_CANDIDATE=/absolute/path/to/candidate/reversi-ai-search-profile \
  BENCHMARK_REPORT=/absolute/path/to/report.json \
  BENCHMARK_PROGRESS_EVERY=1
```

It warms each binary once per board, alternates each measured pair, and records
five repetitions by default. The report is canonical JSON with raw samples,
semantic search results, environment/build data, medians, and workload
geometric means. It rejects incomplete samples. It has no speed threshold:
only a human-run same-host release report is performance evidence.
It writes flushed stderr progress after each complete baseline/candidate
position-repetition pair, and stage boundaries for measurement, aggregation,
and publication. Set the positive `BENCHMARK_PROGRESS_EVERY` interval to limit
pair lines; diagnostics never change the JSON report.

## winner-empty-v1 移行と保存証拠

新規 whole-game は producer `reversi-ai-whole-game-v3`、manifest schema2、
report schema3、Oracle evidence schema2 と `score_contract="winner-empty-v1"`
を記録する。threshold/cache assessment はそれぞれ v2。CLI query ごとの
`score_contract_v1` と search semantics 2 の生出力を照合し、旧 binary の応答を
新しい receipt として扱わない。`score_black` は盤上の実石数差を維持する。
終局 child は勝者へ残り空きを加算し、draw は0。Oracle query の pass 符号は維持する。

`reference-v1.jsonl` と既存の report/receipt は凍結する。新しい reference は別ファイルへ
人間が生成する。移行の回帰は小さい fixture/stub だけで行い、本番 Oracle、whole-game、
長い assessment を agent は起動しない。新契約の独立 root/child 一致や性能の受け入れは
引き続き人間操作の gate であり、本実装で production freeze を解除しない。

旧証拠の検証は明示的な offline 入口のみを使う。

```sh
rtk python3 tools/reversi-ai-benchmark/whole_game.py verify --legacy-offline --report /absolute/old-report.json
rtk python3 tools/reversi-ai-benchmark/whole_game.py verify-oracle-check --legacy-offline --report /absolute/old-report.json --output /absolute/old-evidence.json
rtk python3 tools/reversi-ai-benchmark/prepare-whole-game-measurement.py verify --legacy-offline --manifest /absolute/old-manifest.json
rtk python3 tools/reversi-ai-benchmark/exact_threshold.py verify --legacy-offline --manifest /absolute/old-threshold-manifest.json
rtk python3 tools/reversi-ai-benchmark/exact_cache_verification.py verify --legacy-offline --manifest /absolute/old-cache-manifest.json
rtk python3 tools/reversi-ai-benchmark/compare.py --legacy-offline --verify-report /absolute/old-cost-report.json --corpus tools/reversi-ai-benchmark/positions-v1.jsonl
rtk python3 tools/reversi-ai-oracle/oracle.py verify-benchmark-reference --legacy-offline --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --report tools/reversi-ai-benchmark/reference-v1.jsonl
```

元 producer の Git revision から verifier を隔離して読み込み、保存された harness SHA を
元 revision の bytes と照合する。旧 worktree の絶対パスを current source digest に置換しない。
receipt/input の元パスと保存 binary/artifact の pin は維持する。Git history がない shallow
checkout、元パスの入力欠落、digest 不一致は拒否する。必要な history は `rtk git fetch --unshallow`
で取得する。offline adapter は Git read 以外の workload subprocess を拒否し、旧失敗や未完了を
成功へ変更しない。新 score contract を旧文書の任意階層へ加えた再sealも拒否する。
