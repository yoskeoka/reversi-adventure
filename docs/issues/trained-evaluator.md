# Trained BoardEvaluator (ML/RL-based)

## Description

Implement a `TrainedEvaluator` that uses pattern weights trained from game data, following the Egaroucid/Logistello approach. This would be the strongest evaluator, providing the best learning insights for players.

## References

- Egaroucid technology explanation: https://www.egaroucid.nyanyan.dev/ja/technology/explanation/
- Logistello pattern evaluation approach

## Why

- Hand-tuned evaluators (Phase 2) are good for initial opponents but have a strength ceiling
- A trained evaluator provides "ground truth" analysis for the best learning experience
- Players studying endgame or advanced strategy need accurate position assessment
- Pattern-based evaluation (Egaroucid-style) is proven to reach world-class strength in Othello

## Approach (tentative)

- Phase-based pattern evaluation (multiple phases indexed by stone count)
- Train pattern weights from professional game records or self-play
- Requires training pipeline (data collection, optimizer, validation)
- Implements the same `BoardEvaluator` trait from Phase 2 — drop-in replacement

## Scope

- Training data collection or generation
- Pattern feature extraction
- Weight training pipeline (possibly GPU-accelerated)
- `TrainedEvaluator` struct implementing `BoardEvaluator`
- Validation against known game positions

## Priority

Medium — not blocking Phase 2. Can be planned after the trait-based AI architecture is in place.
