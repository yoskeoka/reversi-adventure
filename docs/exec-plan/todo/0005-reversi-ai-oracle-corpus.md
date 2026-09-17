# Measure Reversi AI candidates against a pinned external oracle

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Create the reproducible evidence base used to assess every evaluator and search
candidate. Egaroucid Console is the single development/CI oracle: it scores a
versioned position corpus in WSL2 and Linux CI, while remaining absent from the
product, GDExtension, and release artifacts.

## Existing references

- `docs/issues/0005-trained-evaluator.md:1-36` identifies Egaroucid-style
  evaluation as the reference direction.
- `rust/reversi-ai/src/player.rs:37-121` has only a single self-play assertion.
- `docs/specs/reversi-ai.md:39-147` has no corpus or analysis-result contract.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- define project-owned analysis result
  fields: selected move, score/regret, completed depth, nodes, elapsed time,
  and exactness.
- (NEW) `tools/reversi-ai-oracle/` -- pinned Egaroucid acquisition, SHA-256
  verification, CLI adapter, process timeout, and strict output parser.
- (NEW) versioned corpus and golden normalized reports -- include board,
  side-to-move, legal moves, provenance, and opening/midgame/endgame/pass
  classification.
- (NEW) scoped CI job and local runner documentation -- use Linux/WSL2 only;
  do not check in external binaries or caches.
- (DELETE) this plan after implementation verification and PR preparation.

## Execution steps

1. Pin an Egaroucid Console release URL and SHA-256; fail closed for an
   unavailable, mismatched, or unparsable executable. Do not use its ignored
   time-limit option; enforce a wrapper process timeout.
2. Assemble legal positions across all stone-count phases, forced passes, and
   solved endgames. Preserve source/provenance and side to move.
3. Normalize oracle best move, value, depth, nodes, and exact-search status.
4. Report candidate best-move agreement and selected-move regret per phase at
   a declared budget. This is a measurement gate, not a runtime dependency.

## Verification

- Run the adapter in WSL2 and Linux CI with the same pinned version/SHA.
- Reproduce normalized non-time-limited reports byte-for-byte.
- Verify oracle material is absent from shipping artifacts.

## Addresses

N/A
