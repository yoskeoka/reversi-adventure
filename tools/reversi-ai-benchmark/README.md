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
`reference-v1.jsonl`. It is a reference-analysis artifact, not an evaluator
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
