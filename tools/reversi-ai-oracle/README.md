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

### Playground advisor analysis

`analyze-position` is an independent, line-oriented advisor command. It uses
the pinned external Egaroucid `-solve` batch and does not change the named
corpus, match, or GTP profiles. Set the opening and midgame depths to 1–12 and
the exact-solver start to 0–16 empty squares:

```sh
python3 tools/reversi-ai-oracle/oracle.py analyze-position \
  --opening-depth 4 --midgame-depth 6 --exact-solver-empty-squares 16 \
  --timeout 300
```

Send one `position_id<TAB>64-character-board<TAB>B|W` request per stdin line.
Each successful request emits one JSON line with `schema_version:1`, the
position ID, board, side, configuration fingerprint, `move|pass|game_over`
outcome, completed root depth, exact flag, and `scores` containing every legal
move exactly once. Scores are from the requested side's perspective. A pass or
game over has an empty score set. Immediately terminal moves carry a proven
value and their own depth. A failed or incomplete solve emits no result for
that request and exits with an error.

The decision move number is occupied discs minus three. Moves 1–20 use the
opening depth and moves 21–60 the midgame depth. The exact threshold replaces
the heuristic depth from move `61 − E`; `E=0` disables the exact range. One
placement is already made in each `-solve` child query, so the generated
child ranges start one move later and search one placement less. The command
uses the Oracle minimum child depth of one for a requested root depth of one
and reports that root depth conservatively. It checks each completed child
depth before publishing the full result. Its
configuration fingerprint includes the pinned Oracle identity and generated
ranges. Values are meaningful within this advisor configuration; they are not
comparable to other evaluators or search regimes. The optional `--timeout`
is an external process wall-clock bound and is not passed to Egaroucid.

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

## winner-empty-v1 の score identity

新規 analysis/golden は schema2 と `score_contract="winner-empty-v1"` を持つ。
Advisor config も schema2 と score contract を hash に含め、`oracle-advisor-v2` を使う。
盤面 corpus は実石数・合法手の schema1 を維持する。terminal child/root は
`own-opponent + sign(own-opponent)*(64-own-opponent)` を返し、実石数を記録する outcome は維持する。

`make oracle-ci` と `make oracle-verify` は別ファイルの小さい
`winner-empty-v1-corpus.jsonl` / `winner-empty-v1-golden.jsonl` を使う。
全 leaf は保存 terminal board から独立に照合でき、golden の作成時に Oracle solve は起動していない。
満盤、空きありの勝敗/draw、wipeout、terminal child を含む。
既存 `corpus.jsonl` と `golden.jsonl`、benchmark `reference-v1.jsonl` は保持する。
本番 golden/reference の全量再生成はこの移行の完了条件に含めない。
生成入口は既存ファイルへの上書きを拒否し、新規出力を要求する。

旧 golden は次の read-only 検証入口を使う。

```sh
rtk python3 tools/reversi-ai-oracle/oracle.py verify --legacy-offline --corpus tools/reversi-ai-oracle/corpus.jsonl --golden tools/reversi-ai-oracle/golden.jsonl
```

元 schema、固定 Oracle source/profile、合法手、保存 terminal の元 raw 実石数差を検証する。
旧 minimax の全 solve は再実行せず、その値の新意味への移植や再受け入れを主張しない。
旧 schema を新 score contract へ暗黙に読み替えること、保存失敗を成功に変更することは拒否する。
