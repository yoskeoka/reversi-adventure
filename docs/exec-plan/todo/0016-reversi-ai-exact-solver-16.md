# Child plan: extend exact solving to 16 empty squares

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Raise the project exact-solver start threshold from 12 to 16 remaining empty
squares only when it can meet the candidate resource profile safely. Completion
proves final-disc correctness and interruptibility at the new boundary. It does
not call a depth-limited heuristic result exact.

## Existing references

- `docs/specs/reversi-ai.md:92-96,254-271` -- current threshold and exactness.
- `rust/reversi-ai/src/search/endgame.rs` and `negascout.rs`.
- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:70-97`.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- threshold 16, resource limits, and
  unchanged timeout/result contract.
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs`, `search/mod.rs`, and tests.
- (NEW) legal 13--16-empty-square exact fixtures with independently checked
  final scores and pass cases.

## Black-box contract and work

1. Make 16 an explicit named profile threshold, never an `AiConfig` late-game
   heuristic depth.
2. Profile the 13--16-empty search tree and implement only sound ordering,
   parity, cache, or stability improvements that retain exhaustive proof.
3. Preserve root-side final disc differential, legal PV, and exact-cache
   isolation. A deadline, node limit, or cancellation returns the prior legal
   fallback/complete result with `exact = false` and no partial exact score.
4. Add a practical resource ceiling to the profile evidence. If it cannot be
   met, retain 12 and record a larger handicap proposal rather than weakening
   correctness.

Depends on 0011; can proceed in parallel with evaluator and search children.

## Verification

- Exact fixture scores/PVs for 12 through 16 empties, including pass and
  terminal positions.
- Deadline, node-limit, and cancellation tests at 16 empties.
- `cargo test -p reversi-ai`, Clippy, oracle regression report, and diff check.
