# Child plan: try principal-variation search in the exact solver

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Reduce the exact 16-empty search tree by searching the first ordered child with
the full alpha-beta window and later children with a null window followed by a
full re-search only on an in-window improvement. Accept only if all exact
scores/PVs remain deterministic and the 0021 exact timing gate passes.

This is an exhaustive, nonselective exact search. It does not add ProbCut,
heuristic evaluation, approximate bounds, threshold changes, or parallelism.

Record both workload ratios and the report digest in parent 0020. The user
decides whether to retain the experiment; CPU comparison is wall-clock based,
with peak memory and the configured wall-clock deadline as resource limits.

## Existing references

- `rust/reversi-ai/src/search/endgame.rs:108-210` currently searches every
  exact child with the full current alpha-beta window.
- `rust/reversi-ai/src/search/negascout.rs:222-256` is the project's existing
  full-window-first/null-window PVS pattern for heuristic search.
- `docs/specs/reversi-ai.md:384-402` defines exact final-disc scores, complete
  PVs, pass behavior, and interruption fallback.
- Egaroucid separates exact full-window and NWS entry points in
  `src/engine/endsearch.hpp` and `src/engine/endsearch_nws.hpp`:
  <https://github.com/Nyanyan/Egaroucid>.
- Edax exact NWS/PVS implementations are in `src/endgame.c`:
  <https://github.com/abulmo/edax-reversi/blob/master/src/endgame.c>.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` and performance evidence -- exact PVS
  window/re-search semantics, counters, and accepted/rejected result.
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs` -- explicit exact PV and
  null-window paths, re-search, and compatible cache bounds.
- (MODIFY) focused exact-solver tests and diagnostic benchmark output.

## Black-box contract and work

1. Preserve the first move's full-window search. Search every later move with
   the mathematically equivalent negated null window and re-search it with the
   full window only when its result can improve alpha without proving beta
   cutoff. Handle the closed integer final-disc range without overflow.
2. Cache only bounds valid for the actual window searched. A null-window hit
   may cause a sound cutoff but must not be reported as an exact root score or
   used to fabricate a completed PV.
3. Count null-window calls, fail-highs, and full re-searches in diagnostics.
   Preserve move order and `>` tie-breaking so equal optimal moves retain the
   same root move/PV.
4. Every initial and retry call polls the same deadline/node/cancellation
   budget. Interruption drops the entire exact attempt and exposes no partial
   score or PV.
5. Require the same exact outcomes, root-side scores, full PVs, completed
   depths, and exact flags for the 0021 suite and issue fixture. Node counts may
   decrease. Apply the exact timing gate and shared midgame allowance.

## Dependencies and sequencing

- Depends on completed 0023 and starts the exact optimization track.
- May run in parallel with 0024, then blocks 0027 and 0028.

## Verification

- Differential exact solves against an explicit full-window reference for all
  reachable positions up to a bounded empty count plus the oracle-checked
  13--16-empty fixtures.
- Tests for fail-low, fail-high, re-search, equal-score tie-breaking, forced
  pass, game over, cache bound reuse, node-limit interruption, deadline, and
  cancellation.
- Verify every 0021 exact score/optimal move against oracle metadata, apply the
  timing gate, and rerun the 20-empty `+26` fixture for five minutes.
- Rust tests, Clippy, GDExtension build, workflow lint, and `git diff --check`.

## Addresses

- N/A; parent 0020 owns `docs/issues/0011-exact-solver-20-performance.md`.
