# Egaroucid Technology Explanation

Source: https://www.egaroucid.nyanyan.dev/ja/technology/explanation/

Egaroucid is one of the strongest Othello AIs. This document summarizes its architecture as a reference for Reversi Adventure's AI design (Phase 2).

## Search Algorithm: Negascout (minimax-based)

Chose minimax-derived Negascout over MCTS for several reasons:

- Pattern-based evaluation functions are accurate enough to make minimax viable
- Othello's branching factor is ~10 legal moves on average — feasible for minimax
- Othello rewards maximizing final stone differential (score-maximization), which minimax naturally optimizes. MCTS traditionally targets win/loss, not score-maximization
- Othello endgames can be solved perfectly within reasonable time — only possible with minimax

## Board Representation: Bitboard + SIMD

- Two 64-bit integers (player/opponent), 128 bits total
- SIMD (AVX2) acceleration provides ~1.5x speedup
- Differential pattern evaluation: update only affected features on move, not full recalculation

## Evaluation Function: Phase-Based Pattern Evaluation

- 60 independent evaluation functions (one per game phase, indexed by stone count)
- 64 distinct pattern features from all 3+ stone continuous linear patterns
- Trained on 1.8 billion positions using Adam optimizer (GPU)
- Egaroucid 7.x removed mobility-based patterns for speed, relying on enhanced training data
- NNUE (small neural network) experiment underperformed pattern evaluation (MAE 5.4 vs 3.5 stones)

## Move Ordering

1. Shallow search results (from TT / previous iteration)
2. Endgame-specific lightweight 4-pattern evaluation
3. Opponent legal move count (minimize opponent mobility)
4. Potential mobility (limit empty squares adjacent to own pieces)
5. Parity ordering (quasi-even theory, 4x4 quadrant parity)
6. Static positional value (corner/edge preference as tiebreaker)

## Pruning and Optimization

- **Transposition Table (TT)**: stores eval bounds, depth, MPC probability, recency. Per-thread tables for shallow endgame, shared table with locking for deep search
- **Enhanced Transposition Cutoff (ETC)**: one-ply TT lookahead to narrow search windows before move ordering
- **Stability Cutoff**: identifies stable (unfippable) stones to bound endgame evaluation
- **Multi-ProbCut (MPC)**: forward pruning rejecting moves below threshold (Logistello-originated, Buro 1997)

## Endgame Solver

- Specialized functions for 1-4 empty squares (skip board updates, pre-indexed tables)
- Perfect solve from ~24 empty squares at higher difficulty levels
- Parity-based move ordering via SIMD

## Parallelization

- **YBWC (Young Brothers Wait Concept)**: serialize PV, parallelize siblings after PV completion
- **Lazy SMP**: simultaneous variable-depth searches sharing transposition table
- Endgame uses YBWC only (Lazy SMP less effective)

## Game Complexity

- Average branching factor: ~10 legal moves
- Average flips per move: 2.244 stones
- Game tree size: ~6.47 x 10^54
- Legal position count: ~10^25-26

## Relevance to Reversi Adventure

Our Phase 2 design adopts:
- Negascout search (same algorithm choice, same reasoning)
- Bitboard representation (already implemented in reversi-engine)
- Hand-tuned evaluation first (simpler than Egaroucid's trained patterns)
- Move ordering heuristics (subset of Egaroucid's approach)

Deferred for future enhancement:
- Trained pattern evaluation (docs/issues/trained-evaluator.md)
- Endgame solver (docs/issues/endgame-solver.md)
- SIMD optimization
- Parallelization
