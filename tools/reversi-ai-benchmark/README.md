# Reversi AI search performance benchmark

This release-only runner compares explicit baseline and candidate profile binaries
on the immutable `positions-v1.jsonl` suite. It warms each binary once, then
alternates binary order for at least five repetitions. CI validates the report
shape and arithmetic only; elapsed-time conclusions require the same host.

```sh
python3 tools/reversi-ai-benchmark/compare.py \
  --corpus tools/reversi-ai-benchmark/positions-v1.jsonl \
  --baseline /path/to/baseline/reversi-ai-search-profile \
  --candidate target/release/reversi-ai-search-profile \
  --timeout-ms 60000 --output /tmp/reversi-ai-performance.json
```

The profiler rejects node limits in this full-depth mode. A timeout or partial
search is a failed run, never a zero or partial timing result.
