# Reversi AI Clippy rejects an existing clone of a Copy board

## What happened

The required `cargo +1.98.1 clippy -p reversi-ai --all-targets -- -D warnings`
gate fails before this timing-profiler change is analyzed.

## Evidence

- `rust/reversi-ai/src/player.rs:102` calls `game.board().clone()` although
  `Board` implements `Copy`.
- Clippy 1.98.1 reports `clippy::clone_on_copy` and suggests dereferencing the
  returned board reference instead.
- The same source is present on `main` at
  `4710824988fb51efe4974e0768474e4efef655c4`.

## Effect

The focused profiler tests pass, but the all-target Reversi AI Clippy gate is
currently blocked by an unrelated pre-existing warning.

## Next

Create a focused plan to remove the redundant clone and re-run the affected
quality gate. Keep this timing-profiler execution scoped to its approved
contract.

## Priority

Low. This is a local quality-gate blocker without a runtime behavior change.
