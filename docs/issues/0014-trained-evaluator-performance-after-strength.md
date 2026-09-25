# Optimize TrainedEvaluator after strength acceptance

## What happened

The 0020 search-performance series and 0032 implementation-cost experiment
measured the strategic evaluator workload. The 0032 plan excluded trained
feature extraction because its tiny fixture is not a representative artifact.
No measured result from those experiments establishes a speedup for the final
trained engine.

## Evidence

- `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md` selects
  and validates a candidate artifact before 0018 freezes it.
- `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md` owns the
  held-out strength result. Its acceptance run must finish before performance
  tuning of the accepted trained configuration.
- `docs/references/reversi-ai-rust-cost-0031.md` records that trained feature
  extraction was expensive under a tiny diagnostic artifact. That fixture is
  insufficient for an adoption decision.
- `docs/references/reversi-ai-search-performance-0020-closeout.md` and
  [the retained 0032 experiment](https://github.com/yoskeoka/reversi-adventure/pull/218)
  provide the search and implementation-cost comparison methods. The unsafe
  TT candidate from 0032 was not adopted.

## Effect

The accepted trained engine may have a different cost profile from the
strategic benchmark. Its search and feature-extraction costs have no separate
post-acceptance optimization evidence yet.

## Next

After 0018 records an accepted strength result, create a focused execution
plan for trained-mode performance. Freeze the accepted source, artifact digest,
search settings, and representative boards before measuring. Profile search
and feature extraction, then evaluate one bounded candidate at a time using
the 0020/0032 discipline: identical results and ordered fixed-node traces,
same-host release comparisons, and reported elapsed time, CPU time, and peak
RSS. Preserve any rejected candidate and its evidence. Keep performance
experiments separate from the frozen strength-acceptance run; set no CI speed
threshold. An `unsafe` candidate needs its own local safety proof and measured
benefit over an otherwise identical safe version.

## Priority

Deferred until the trained engine satisfies the 0018 strength contract.
