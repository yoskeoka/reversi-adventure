# Spec-Code Parity Gaps in reversi-ai

## Summary

Several public APIs in the `reversi-ai` crate are not documented in `docs/specs/reversi-ai.md`.

## Details

Missing from spec:

- `NoviceEvaluator::with_seed(seed: u64)` — public constructor for deterministic testing (`rust/reversi-ai/src/eval/novice.rs:22-24`)
- `Negascout` struct and `nodes_searched()` method — public search internals (`rust/reversi-ai/src/search/negascout.rs`)
- `ZobristKeys::new()` and `hash()` — public Zobrist interface (`rust/reversi-ai/src/search/tt.rs:27-62`)
- `AiPlayer::evaluator_name()` — accessor method (`rust/reversi-ai/src/player.rs:37-39`)
- `SearchEngine::clear_tt()` — TT management utility (`rust/reversi-ai/src/search/mod.rs:59-61`)

## Proposed Solution

1. Add a "Search Internals" subsection documenting `Negascout`, `ZobristKeys`, and `SearchEngine::clear_tt()`
2. Add `with_seed()` to the NoviceEvaluator section
3. Add `evaluator_name()` to the AiPlayer section
4. Consider making `Negascout` and `ZobristKeys` `pub(crate)` if they aren't meant to be part of the public API

## Priority

Low — functionality works correctly, only documentation is incomplete.

## Related

- GitHub Issue: https://github.com/yoskeoka/reversi-adventure/issues/9
