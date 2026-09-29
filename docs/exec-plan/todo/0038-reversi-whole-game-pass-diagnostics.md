# Whole-game benchmark accepts valid forced passes

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## User-visible objective and completion boundary

Allow the 0035 whole-game benchmark to report a legal, nonterminal forced pass
without treating it as an incomplete depth-8 search. Keep the configured-depth
requirement for every position that has a legal move, and keep exact-region
pass results subject to exact-solver verification.

The implementation is complete when measurement-time diagnostic attachment
and offline report verification accept the CLI's documented forced-pass result,
reject malformed pass diagnostics and incomplete legal-move searches, and the
specification and human runbook describe the same contract. Offline regression
tests must exercise those cases without launching the eight-game benchmark.
Plan 0035 remains active until its outstanding human measurements, exact checks,
and self-play setting decision are completed separately.

## Exact references

- `docs/specs/reversi-ai.md:627-675` — whole-game data and diagnostic contract.
- `docs/references/reversi-ai-whole-game-0035.md:1-60` — serial human runbook
  and current incomplete-search failure conditions.
- `tools/reversi-ai-benchmark/whole_game.py:287-305` — `attach_diagnostics`
  currently requires a score and phase depth for a forced pass.
- `tools/reversi-ai-benchmark/whole_game.py:446-490` — `verify` currently
  restricts every score to an integer and requires ordinary depth for a pass.
- `tools/reversi-ai-benchmark/test_whole_game.py:15-49,65-110` — synthetic
  game/report fixtures and offline verification tests; current pass fixtures use
  move-search metadata instead of the CLI's actual pass result.
- `rust/reversi-ai/src/search/negascout.rs:57-74` — a nonterminal heuristic
  root pass returns `Pass`, no score, depth zero, and `exact=false`.
- `rust/reversi-ai/src/search/endgame.rs:330-365` — exact-region pass retains
  an exact score and empty-square depth.
- `Makefile:130-137` — `oracle-test` runs oracle and benchmark Python suites;
  the whole-game measurement itself is explicitly human-operated.

## Reproduction

The focused replay reached `opening-4-seat0-turn27` after 27 placements from
that opening. The board was
`BBBBBBBB.WWBBBBB..WWBWBB.WWWWBBB...WWWBB...WWW.B................`, side `W`,
with 37 occupied squares and no legal moves. The CLI returned `move=pass` with
`elapsed_us=5`, `nodes=0`, `completed_depth=0`, `exact=false`,
`outcome=pass`, `score=null`, and zero cache counters. The measurement guard
expected depth 8 and a non-null score, causing
`incomplete or inconsistent CLI search at opening-4-seat0-turn27`.
This is a nonterminal heuristic-search pass; the opponent has a legal move.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` — define the diagnostic contract for
  heuristic and exact-region forced passes, while keeping depth completion
  mandatory for legal-move searches.
- (MODIFY) `docs/references/reversi-ai-whole-game-0035.md` — distinguish a
  valid forced pass from a search that stopped before its configured depth.
- (MODIFY) `tools/reversi-ai-benchmark/whole_game.py` — apply the pass-specific
  rule in both `attach_diagnostics` and `verify`; preserve strict score, depth,
  exactness, outcome, and cache-counter checks for all other cases.
- (MODIFY) `tools/reversi-ai-benchmark/test_whole_game.py` — make synthetic
  pass diagnostics match the CLI and add positive and negative regression cases
  for measurement attachment and report verification.

## Black-box specification changes

- A nonterminal forced pass in the heuristic-search region is a valid decision
  event when the current side has no legal move and the opponent does. Its CLI
  diagnostic is `outcome=pass`, `score=null`, `completed_depth=0`, and
  `exact=false`; elapsed time, node count, and cache counters remain present and
  nonnegative. It is retained in the game record and its digest.
- A forced pass in the exact-solver region retains the exact solver's result:
  `outcome=pass`, an integer root-side score, `completed_depth` equal to the
  remaining empty squares, and `exact=true`.
- Every legal-move decision still requires a non-null score and the configured
  phase depth (or the exact empty-square depth). A missing score, fallback
  result, or incomplete iteration remains a failed measurement.
- Offline verification independently replays move legality before accepting
  pass metadata. It rejects a pass with legal moves, a move outcome for a pass,
  a score/depth/exactness combination inconsistent with its search region, or a
  legal-move search with incomplete diagnostics.
- Keep the existing report keys, report digest rules, and decision counts.
  `score` is already parsed as nullable by the runner; this change makes
  measurement and verification honor that existing representation.

## Work items and dependencies

1. Update `docs/specs/reversi-ai.md` with the black-box pass contract above.
2. Update `whole_game.py` so measurement attachment and report verification use
   the same region-aware pass rule. Keep exact-region pass semantics unchanged.
3. Update synthetic fixtures and add regression tests for the observed
   `opening-4-seat0-turn27` diagnostic, malformed pass metadata, and incomplete
   legal-move diagnostics. Confirm comparisons still accept equal `null` scores
   for the same forced-pass position.
4. Update the human runbook's stop conditions to reject incomplete legal-move
   searches while accepting valid forced passes.
5. Run `make oracle-test`, `git diff --check`, and applicable workflow lint.
   Do not run the human-operated whole-game measurement as a test.
6. After the fix PR is merged, resume the existing output directory. The failed
   `turn-8` report was never written, so its eight-game sample must be rerun;
   verified reports already present in the directory remain reusable.

The spec update precedes all code changes. These tasks are sequential; there is
no parallel implementation dependency.

## Addresses

- N/A — no linked local or external issue exists; this plan addresses the
  reproducible post-merge measurement failure reported during plan 0035.
