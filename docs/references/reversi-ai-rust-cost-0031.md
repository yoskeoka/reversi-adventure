# Reversi AI Rust cost reassessment (0031)

## Frozen inputs and intervals

- Adopted baseline source: `dff6897d8960dc8ed855f7a4835adb23eb2bb134`.
  Non-instrumented release profiler: `/tmp/reversi-ai-0031-baseline`, SHA-256
  `6a4132fdef02819ba1deafb5b7e08a60250754c52bd4746f3581571b63a6e68f`.
- Original diagnostic source checkpoint: `abc204f675d8e55796112574d93231d769fd0ab5`.
  The trace instrumentation is identical in the original and tuned diagnostic
  builds; it is disabled in the release timing builds.
- Candidate is the same source with the diagnostic harness and one change to
  `search/ordering.rs`: it iterates the already computed legal-move mask and
  computes flips directly, avoiding a second legal-move calculation and the
  temporary `generated_moves` vector. Engine change checkpoint:
  `f2de91929daad7deac20a95c9874a773d7a6a884`. Non-instrumented release profiler
  after the fixed-node output correction: `/tmp/reversi-ai-0031-candidate-v2`,
  SHA-256 `3f40c8941f9f419a24ae18137d3bafdb65957457ca910abff51e9f29c3cb416c`.
- Corpus: `tools/reversi-ai-benchmark/positions-v1.jsonl`, SHA-256
  `5831839527b433b4b92c314331b9f0e613d98e0f82b9b6edb725f8bd6cb97ff8`.
  `make benchmark-corpus-verify` passed. The corpus was not regenerated.
- Build command: `cargo +1.98.1 build --release -p reversi-ai --bin
  reversi-ai-search-profile`, without `RUSTFLAGS` or `--features
  cost-diagnostics`. The comparator records the live host, OS, CPU, flags,
  binary digests, and `linux-wait4` method.
- `search_elapsed_ns` is the profiler's search interval after evaluator
  construction. `process_elapsed_ns`, user/system CPU, and peak RSS cover each
  child process from launch through exit. Trained artifact load is included in
  process metrics; it is excluded from the search interval.

## Diagnosis

The diagnostic-only `cost-diagnostics` feature recorded ordered node/window,
move-order, transposition decision, re-search, cutoff, and store events. The
[machine-readable diagnostic report](reversi-ai-rust-cost-0031-diagnostics.json)
contains the sixteen matching trace digests, node counts, diagnostic input
hashes, and inclusive counters. Original and tuned fixed-node runs used the
same 100,000-node budget for each corpus position.

All sixteen outcomes,
scores, PVs, completed depths, exact flags, node counts, and ordered trace
digests matched. The original report includes 1,200,000 heuristic legal-move
calls and 420,673 heuristic ordering calls. Inclusive ordering time was about
655 ms in the original diagnostic run and 570 ms in the tuned diagnostic run.
These diagnostic times identified the code to tune. Exact ordering, region
update, and table costs are separately counted. The candidate leaves the exact
path unchanged.

Instrumentation itself is material: a serial fixed-node run of the original
implementation took 1.42 s without instrumentation and 3.05 s with it on this
host. Counter intervals can overlap and are never added as total search time.

The trained diagnostic used `tools/reversi-ai-training/fixtures/tiny-manifest.json`
(SHA-256 `95b0590b3741bb704c9e5ffe053e2bf33d99a2bd55fd027b0e985c69be603925`)
and `tools/reversi-ai-training/training.py` from commit
`f1b133965e252bea2a17105e9958a55a08c801d8`.

The generated artifact SHA-256
was `351e1ce8db2a66ec5e84bdb70402f7a30282cca3cf83024f164c379b7bd71c6d`;
the trainer report SHA-256 was
`964cf214801f36faf03453da1faaa2e53a277e03b6923caabf46b9955a21722a`.
The evaluator context was `6368932617396054397`. Loading and validation
took 302,144 ns once for the 16-position diagnostic process.

Across its twelve
heuristic roots, the feature extractor was called 745,085 times and consumed
about 6.50 s inclusive; lookup consumed about 0.23 s. All four exact roots
made zero evaluator calls. The tiny sparse fixture is diagnostic input only;
its ratios do not enter the strategic 5% gate.

The frozen diagnostic commands are:

```sh
rtk python3 tools/reversi-ai-training/training.py train --manifest tools/reversi-ai-training/fixtures/tiny-manifest.json --artifact /tmp/reversi-ai-0031-pattern-artifact.json --report /tmp/reversi-ai-0031-pattern-report.json
rtk python3 tools/reversi-ai-training/training.py validate --artifact /tmp/reversi-ai-0031-pattern-artifact.json
rtk cargo +1.98.1 build --release -p reversi-ai --bin reversi-ai-search-profile --features cost-diagnostics
rtk target/release/reversi-ai-search-profile --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --node-limit 100000 --opening-depth 12 --midgame-depth 12 --endgame-depth 12 --exact-solver-empty-squares 16 > /tmp/reversi-ai-0031-tuned-diag.jsonl
rtk target/release/reversi-ai-search-profile --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --node-limit 100000 --opening-depth 12 --midgame-depth 12 --endgame-depth 12 --exact-solver-empty-squares 16 --evaluator trained --trained-artifact /tmp/reversi-ai-0031-pattern-artifact.json > /tmp/reversi-ai-0031-trained-diag.jsonl
rtk python3 tools/reversi-ai-benchmark/diagnose.py --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --original /tmp/reversi-ai-0031-original-diag.jsonl --tuned /tmp/reversi-ai-0031-tuned-diag.jsonl --trained /tmp/reversi-ai-0031-trained-diag.jsonl --output /tmp/reversi-ai-0031-diagnostics.json
```

The original diagnostic binary was built from checkpoint `abc204f` and saved
as `/tmp/reversi-ai-0031-original-diag`; run it with the tuned diagnostic's
node-only arguments to regenerate the original JSON Lines file. The
diagnostic report is not a release timing report.

## Strategic release comparison and adoption status

The [machine-readable release report](reversi-ai-rust-cost-0031-comparison.json)
has SHA-256 `63ae61bef10fe3752356667526cbfb0df883add66837bed7be2d42877eb5582f`.
It was measured on host `xps`, an Intel Core i7-1065G7 running
`Linux-6.18.33.2-microsoft-standard-WSL2-x86_64`, with Rust 1.98.1 and empty
`RUSTFLAGS`. Host load averaged under 0.6 before the serial run. The binaries
and corpus matched the frozen SHA-256 values above. One warm-up per binary and
board preceded five alternating measured repetitions. All 160 measured
samples completed. All 80 baseline/candidate pairs and repetitions matched on
outcome, score, PV, completed depth, exactness, and nodes. Every sample has
nonnegative user/system CPU time and positive peak RSS from its own Linux
`wait4` result. The saved report passed `--verify-report`, and an independent
`statistics.median`/geometric-mean calculation reproduced both workload ratios.

| Workload | Positions | Search elapsed ratio | CPU ratio | Process elapsed ratio | Peak RSS baseline → candidate |
| --- | ---: | ---: | ---: | ---: | ---: |
| `heuristic-depth-12` | 12 | `0.9406831253153776` | `0.9437905080226138` | `0.9426055582083069` | `26,956 → 27,020 KiB` |
| `exact-16` | 4 | `0.9918580986140435` | `0.9855616496316089` | `0.985672580808073` | `34,852 → 35,080 KiB` |

The heuristic workload is about 5.93% faster by the plan's search elapsed
gate, and CPU time falls about 5.62%. The improvement matches the diagnosed
heuristic ordering path: each ordering call now uses the legal mask already
computed at the node and avoids one temporary move vector. Exact solving does
not call this ordering path; its search elapsed ratio is about 0.82% lower and
does not meet the 5% gate alone. Peak RSS rose by 64 KiB for heuristic and
228 KiB for exact. These are measured maxima, not estimates from node totals.

The candidate meets the plan's numerical gate through heuristic search, with
matching results and trace. It is **proposed for human adoption review** in
PR #216. The exact path and its configuration did not change. If the candidate
is adopted, 0029 starts from this new `main` and reuses the `wait4` comparator;
0030 must measure each rejected search method separately against the then
current `main`. Neither successor may credit this common ordering improvement
to its own method. No `unsafe` was needed for this measured gain.

The frozen measurement command was:

```sh
rtk python3 tools/reversi-ai-benchmark/compare.py --baseline /tmp/reversi-ai-0031-baseline --candidate /tmp/reversi-ai-0031-candidate-v2 --corpus tools/reversi-ai-benchmark/positions-v1.jsonl --output /tmp/reversi-ai-0031-comparison.json --repetitions 5 --time-limit-ms 300000
```

The completed immutable output is validated independently with:

```sh
rtk python3 tools/reversi-ai-benchmark/compare.py --verify-report /tmp/reversi-ai-0031-comparison.json --corpus tools/reversi-ai-benchmark/positions-v1.jsonl
```

The report records the search interval after evaluator construction and the
process interval from launch through exit. The two intervals are reported
separately. The trained fixture results remain outside the adoption gate.
