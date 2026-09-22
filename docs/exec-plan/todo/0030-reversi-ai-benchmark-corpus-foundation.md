# Child plan: publish the reproducible search benchmark corpus

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

After 0029 is merged, extract the corpus-only portion of preserved commit
`a14eab2` into a focused PR: the pinned level-6 Console self-play generator,
the checked-in 16-position corpus, and its replay/D4 validation. No profiler,
oracle reference analysis, comparator, baseline, or timing claim is included.

## Change map

- (MODIFY) `tools/reversi-ai-oracle/oracle.py` -- versioned self-play profile,
  transcript replay, canonical corpus generation, and validation.
- (MODIFY) `Makefile` -- setup, generate, and validate targets.
- (NEW) `tools/reversi-ai-benchmark/positions-v1.jsonl` -- four games at 20,
  40, 44, and 48 occupied discs.
- (NEW) focused oracle unit tests and corpus README.

## Contract and verification

Start each game at the initial board, randomize only its first six plies at
level 6, replay every transcript legally (including implicit Console passes),
and reject malformed, non-16-record, duplicate, or D4-equivalent output.
Run generator twice for canonical-byte comparison, corpus verification,
`make oracle-test`, and `git diff --check`.

## Dependencies

- Requires merged 0029 only for sequencing; it does not call the profiler.
- Its merge is the evidence boundary required before updating 0021.

## Addresses

- N/A.
