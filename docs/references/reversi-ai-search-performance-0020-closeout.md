# Reversi search performance series closeout

This is the accumulated before/after measurement for parent plan 0020. It
compares the frozen 0021 baseline directly with the final accepted search
engine on the same sixteen-position corpus. The ratios measure these two
implementations on this host; they are not general speedup estimates for the
individual techniques.

## Frozen inputs

- Baseline source: `6dd60aacae7d54273c2224cbc5de160fa2932b2b`; release
  profiler SHA-256:
  `25e00e704b1383200d87d8ddac02d13efddcc0fda36ff6488295a4529e255641`.
- Final accepted source: `c55047d696d62f81dc333487b7268ae1ee2127b7`;
  release profiler SHA-256:
  `e1cd9ae713fa47c7af4679013d6acea1eb24f908add217ada9ddddfb52eeebd0`.
  Later changes on the documentation branch do not change the engine binary.
- Corpus: `tools/reversi-ai-benchmark/positions-v1.jsonl`, SHA-256
  `5831839527b433b4b92c314331b9f0e613d98e0f82b9b6edb725f8bd6cb97ff8`.
- [Raw comparison report](reversi-ai-search-performance-0020-closeout.json),
  SHA-256 `d8b7aa7c667a9841ddda803d0cf09e2a42d0095dee8be0ee346868328eac0e08`.

## Measurement and result

The human-operated comparator used Rust 1.98.1 release binaries with default
portable target features and no `RUSTFLAGS` on the same Intel Core i7-1065G7
WSL2 host. It ran one unrecorded warm-up per binary and position, followed by
five measured alternating baseline/candidate repetitions. Every sample had a
five-minute monotonic deadline. The five one-repetition fragments remerged
byte-for-byte into the checked-in report.

| Workload | Positions | Candidate / baseline geometric mean of per-position median elapsed time | Reduction |
| --- | ---: | ---: | ---: |
| Heuristic depth 12 | 12 | `0.4079137674489783` | 59.2% |
| Exact 16 empty squares | 4 | `0.2092294536017321` | 79.1% |

All 160 measured samples completed. Every one of the 80 matched
baseline/candidate pairs agreed on outcome, score, principal variation,
completed depth, and exactness. The four exact roots also matched the pinned
independent reference scores and selected optimal moves. Per-position medians
and workload geometric means were independently recomputed from raw samples.
Both workload ratios satisfy the parent's at-least-20% reduction condition.

The other parent condition was met by the accepted exact-search implementation:
the separate 20-empty fixture returned the independent oracle score `+26`
within the five-minute budget, most recently recorded at 12.813 seconds in
the 0027 result. No later accepted change altered that exact-search path.
The default supported threshold remains 16 empty squares.

This closeout comparator measured wall-clock time. CPU time and peak RSS were
not measured here; node counts in the raw report are diagnostic only.
