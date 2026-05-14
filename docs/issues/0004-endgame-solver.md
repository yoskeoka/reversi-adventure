# Endgame Solver

## Description

Add a perfect endgame solver that computes exact stone differential when few empty squares remain. This replaces heuristic evaluation with perfect play in the final moves.

## References

- Egaroucid endgame solver: https://www.egaroucid.nyanyan.dev/ja/technology/explanation/
- Specialized 1-4 empty square solvers with parity-based move ordering

## Why

- Endgame is where precise play matters most — heuristic evaluation introduces error
- Othello's branching factor drops significantly in endgame, making complete search feasible
- Egaroucid solves perfectly from 24+ empty squares at higher levels
- Important for teaching players correct endgame technique

## Scope

- Complete solver for N empty squares (start with N=16, extend later)
- Specialized fast solvers for 1-4 empty squares
- Parity-based move ordering for endgame
- Integration with search engine (switch from heuristic to solver when empty count threshold is reached)

## Priority

Medium — Phase 2 uses heuristic evaluation at all depths. Endgame solver improves strength significantly but is not required for initial AI opponents.
