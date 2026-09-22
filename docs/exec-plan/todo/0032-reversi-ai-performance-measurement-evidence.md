# Child plan: produce reproducible Reversi search measurement evidence

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

After the revised 0021 merges, implement its residual work: reference-analysis
provenance, workload-selecting comparator, same-host true-main release
baseline, CI schema/arithmetic tests without speed assertions, and immutable
documentation evidence.

## Dependencies

- Merged 0029 timing profiler, 0030 corpus foundation, and 0031 amended 0021.

## Verification

Validate corpus/report digests and replay legality; run five alternating
release repetitions on baseline/candidate binaries; record raw samples and
environment; run Rust/Python tests and `git diff --check`.

## Addresses

- N/A.
