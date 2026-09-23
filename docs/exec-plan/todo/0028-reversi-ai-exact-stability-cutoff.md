# Child plan: try conservative stability cutoffs in exact search

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Prune exact nodes only when a mathematically sound final-disc score interval
derived from proven stable discs lies outside the current alpha-beta window.
Accept only if exhaustive differential checks preserve exact results and the
0021 exact timing gate passes. An unsound, noisy, or ineffective candidate is
fully removed and recorded as rejected.

This plan does not reuse a heuristic stability score as proof, estimate future
stability, add selectivity, or change the 16-empty supported threshold.

Record both workload ratios, report digest, and the accepted/rejected outcome
in parent 0020. Retain the change when either workload improves by at least 5%.

## Existing references

- `rust/reversi-ai/src/search/endgame.rs:108-218` has no board-derived score
  bound before move expansion.
- `rust/reversi-ai/src/eval/strategic.rs:93-158` computes an explanatory
  stability feature; it is not currently an exact-search proof contract.
- `docs/specs/reversi-ai.md:384-402` requires final-disc correctness and exact
  flag semantics.
- Edax applies stability cutoffs in its exact and midgame paths, including
  `src/endgame.c:279-300`:
  <https://github.com/abulmo/edax-reversi/blob/master/src/endgame.c>.
- Egaroucid enables end-search stability cuts separately from parity and MPC in
  `src/engine/setting.hpp` and its end-search sources:
  <https://github.com/Nyanyan/Egaroucid>.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` and performance evidence -- formal stable
  subset definition, score-bound proof, cutoff scope/counters, and outcome.
- (NEW) an internal exact-search stability/bound module if separation from the
  explanatory evaluator is needed.
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs` -- conservative bound check
  before expansion at a frozen remaining-empty threshold.
- (MODIFY) exact differential, stability, cutoff, and profiler tests.

## Black-box contract and work

1. Define a conservative set of discs that cannot change color under any legal
   continuation. Start with provable corner-anchored/full-line cases; unknown
   discs remain unstable. Do not call `StrategicEvaluator` or treat its feature
   value as exact evidence.
2. At each `negamax(board, color, alpha, beta)` node, derive bounds in that
   node's current-`color` score perspective. If `own_stable` and
   `opponent_stable` are proven counts, the inclusive interval is
   `[2 * own_stable - 64, 64 - 2 * opponent_stable]`. Compare only that
   interval with the node's alpha/beta window and store the matching bound in
   the same perspective. A pass recurses with the opponent color and negated
   window/result exactly like the existing solver; never compare a root-side
   interval directly inside a child node.
3. Freeze the maximum remaining-empty count at which computing stability is
   attempted, based on pre-measurement cost data, then record attempts, proven
   discs, and cutoffs. No benchmark-position-specific rule is allowed.
4. Preserve exact score/PV at the root, deterministic tie-breaks, pass
   polarity, PVS re-search behavior from 0026 when accepted, and all budget
   polling. A bound cutoff cannot itself become a completed exact root result.
5. Require identical exact outputs on differential corpora and oracle fixtures
   before applying the timing gate and 20-empty check.

## Dependencies and sequencing

- Depends on the accepted/rejected outcome of 0027 and completes the planned
  exact track.
- Parent 0020 may close only after this outcome, the accumulated report, and
  the five-minute 20-empty condition are all satisfied.

## Verification

- Exhaustively enumerate legal continuations for a tractable low-empty corpus
  and prove every disc labeled stable remains owned at all terminals.
- For each tested node and side to move, compare the current-color bounds with
  the true exhaustive current-color score and assert inclusion. Include the
  same unchanged board before and after a forced pass to verify sign/window/TT
  polarity before enabling any cutoff.
- Differential solver tests across reachable boards, forced passes, terminal
  positions, narrow/full windows, cache reuse, deadline, node limit, and
  cancellation.
- Verify 0021 exact oracle metadata, apply the timing gate, and rerun the
  20-empty `+26` fixture for five minutes.
- Rust tests, Clippy, GDExtension build, workflow lint, and `git diff --check`.

## Addresses

- N/A; parent 0020 owns `docs/issues/0011-exact-solver-20-performance.md`.
