# Reversi AI search performance evidence v1

This is the immutable baseline evidence for the versioned sixteen-position
search corpus. It is performance evidence only; it does not set a CI speed
threshold or assert engine strength.

## Inputs

- Current `main`: `6dd60aacae7d54273c2224cbc5de160fa2932b2b`.
- Reference analysis: `tools/reversi-ai-benchmark/reference-v1.jsonl`, SHA-256
  `c6fd798ad0644d8e2b7263135b789efd3d12d87f5cfd2153e6e2a9d6b9e6ec0b`.
- Raw same-host report: `reversi-ai-search-performance-v1.raw.json`, SHA-256
  `d8b92a8e3855e02d69d22ac3ab094091f8b0a5bc15ee461b372f770ee97433a2`.

The baseline and candidate were separately built release profiler binaries
from that same source commit. Their binary SHA-256 was
`25e00e704b1383200d87d8ddac02d13efddcc0fda36ff6488295a4529e255641`.

## Measurement

One warm-up per binary and position preceded five measured alternating
repetitions. Every sample completed depth 12 for the 20/40/44-occupied
heuristic roots or a complete exact solve for the 48-occupied roots. The raw
report retains all 160 timing and semantic samples.

Host: Intel Core i7-1065G7, x86_64, WSL2 Linux 6.18.33.2, Rust
1.98.1, with no `RUSTFLAGS`.

| Workload | Positions | Candidate / baseline geometric mean |
| --- | ---: | ---: |
| heuristic-depth-12 | 12 | 0.998880690492877 |
| exact-16 | 4 | 1.0068596557573135 |

Because both binaries have identical source and binary digests, these ratios
are baseline measurement noise, not an optimization claim. Future candidate
changes use the same corpus, reference report, runner, and five-repetition
protocol for a comparable same-host result.
