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
