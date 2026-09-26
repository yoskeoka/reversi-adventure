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
fatal. Each invocation derives the expected source-tree digest from that
verified archive, verifies the cached source against it, and rebuilds the
executable in a fresh temporary CMake build directory before use. The cache
also records source-tree and executable digests for post-build consistency
checks; the executable is never accepted solely because of those mutable cache
records.

## Commands

From the repository root:

```sh
make oracle-test
make oracle-verify
make oracle-golden
make oracle-match
make oracle-evaluate
make oracle-ci
make oracle-calibration
```

`oracle-verify` analyzes the versioned corpus and compares its stable
projection with `golden.jsonl`. Runtime reports include `elapsed_ms`; the
golden projection removes that machine-dependent field while retaining score,
depth, node count, and exactness. No oracle time-limit option is passed. The
adapter's subprocess timeout is the only wall-clock limit.

The harness accepts only named, versioned profiles. `ci-smoke-v1` is the small
bounded default used by the checked-in corpus/golden gate. It is deliberately
not strength evidence. `strong-engine-hcap-v1` pins bookless Egaroucid v7.8.1
to one thread, hash level 25, no evaluation override, and 100%-probability
fixed depths 8 for decision moves 1--41 and 12 for moves 42--60. It records
the candidate's uniform heuristic depth 12 and its 16-empty-square exact-solver
threshold in every report. The command line never passes Egaroucid `-time`.

`oracle-golden` is the explicit maintainer command for refreshing the checked-in
golden projection after changing the pinned oracle, corpus, or named profile.

`oracle-match` plays two games from the standard opening, alternating colors,
between the project `reversi-ai-cli` and Egaroucid. `oracle-evaluate` analyzes
the corpus and includes the project CLI's selected move, oracle value, and
regret in a report under `/tmp` by default. Override `ORACLE_PROFILE`,
`ORACLE_TIMEOUT`, `ORACLE_MATCH_TIMEOUT`, `ORACLE_REPORT`, and the `AI_*` Make
variables as needed. `oracle-calibration` runs the declared stronger profile
and emits regret plus alternating-color results, but it is a baseline report,
not a final 50% strength assertion.

`oracle-ci` performs normalized corpus verification and the match in one oracle
process, so CI builds the pinned external source once while retaining the same
verification and match gates.

Long-running oracle analysis commands write flushed stderr stage start/done
lines around external solve batches. `oracle-match` and `oracle-ci` additionally
write a completed terminal-game line by default; pass `--progress-every N`
(positive) to retain each Nth game and the final game. These diagnostics do not
alter stdout, corpus, golden, or report bytes and do not turn a failed run into
valid evidence.

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
