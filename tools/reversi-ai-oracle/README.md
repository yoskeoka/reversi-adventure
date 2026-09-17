# Reversi AI oracle harness

This directory contains the development-only harness for comparing the
project AI with a pinned Egaroucid Console oracle. Egaroucid is downloaded,
built, and cached outside the checkout. It is never a Cargo dependency and is
not included in product or release artifacts.

The supported host environments are Linux and WSL2. The default cache is
`$XDG_CACHE_HOME/reversi-adventure/egaroucid/7.8.1`, or
`$HOME/.cache/reversi-adventure/egaroucid/7.8.1` when `XDG_CACHE_HOME` is not
set. Set `REVERSI_ADVENTURE_ORACLE_CACHE` to use another task-specific cache.
The source archive URL and SHA-256 are constants in `oracle.py`; a mismatch is
fatal. The cache also records source-tree and executable digests, so cache
tampering fails closed.

## Commands

From the repository root:

```sh
make oracle-test
make oracle-verify
make oracle-golden
make oracle-match
make oracle-evaluate
```

`oracle-verify` analyzes the versioned corpus and compares its stable
projection with `golden.jsonl`. Runtime reports include `elapsed_ms`; the
golden projection removes that machine-dependent field while retaining score,
depth, node count, and exactness. No oracle time-limit option is passed. The
adapter's subprocess timeout is the only wall-clock limit.

`oracle-golden` is the explicit maintainer command for refreshing the checked-in
golden projection after changing the pinned oracle, corpus, or search level.

`oracle-match` plays two games from the standard opening, alternating colors,
between the project `reversi-ai-cli` and Egaroucid. `oracle-evaluate` analyzes
the corpus and includes the project CLI's selected move, oracle value, and
regret in a report under `/tmp` by default. Override `ORACLE_LEVEL`,
`ORACLE_TIMEOUT`, `ORACLE_MATCH_LEVEL`, `ORACLE_MATCH_TIMEOUT`,
`ORACLE_REPORT`, and the `AI_*` Make variables as needed. The Make match target
uses a deliberately small default level/depth so CI is bounded; strength
comparisons should set a declared higher budget explicitly.

The candidate protocol is line-oriented and intentionally independent of the
oracle:

```text
position_id<TAB>64-character-board<TAB>B|W
position_id<TAB>move|pass
```

The board uses row-major `a1` through `h8` cells with `B`, `W`, and `.`.
For Egaroucid `-solve`, the adapter translates this to its current-player-relative
`X`/`O`/`-` problem format and appends `X` for the side to move.

To regenerate the deterministic corpus after changing its generator:

```sh
python3 tools/reversi-ai-oracle/oracle.py generate-corpus
```

Do not commit the downloaded source, executable, build tree, or mutable cache.
