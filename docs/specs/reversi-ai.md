# Reversi AI Specification

## Overview

Reversi AI engine providing pluggable evaluation strategies, Negascout search with iterative deepening, and move explanation. Lives in the `reversi-ai` crate, depends on `reversi-engine`.

## Evaluation

### EvalFactors

Score breakdown for human-readable explanation.

```rust
struct EvalFactors {
    corner_control: i32,
    stability: i32,
    mobility: i32,
    edge_control: i32,
    parity: i32,
    piece_count: i32,
}
```

- `EvalFactors::total()` — Returns the sum of all factors.

### EvalResult

```rust
struct EvalResult {
    score: i32,
    factors: EvalFactors,
}
```

### BoardEvaluator Trait

```rust
trait BoardEvaluator {
    fn evaluate(&self, board: &Board, color: Color) -> EvalResult;
    fn name(&self) -> &str;
}
```

Implementations must return evaluation from the perspective of `color` (positive = good for `color`).

### StrategicEvaluator

Hand-tuned weights based on known Othello strategy. Evaluates:

- **Corner control**: +/- for each corner owned/opponent-owned. Penalizes C-squares and X-squares adjacent to empty corners.
- **Stability**: Counts stable discs (can never be flipped). Corner-anchored stability propagation.
- **Mobility**: Legal move count differential. Most important midgame factor.
- **Edge control**: Edge disc patterns. Rewards controlled edges.
- **Parity**: Empty region parity. Last-move advantage in endgame.
- **Piece count**: Disc differential. Only significant in endgame (stone count > 50).

### NoviceEvaluator

Simulates a beginner player:

- Heavily weights piece count (more discs = "winning").
- Grabs edges eagerly (positive edge weight, ignores C/X-square danger).
- Ignores mobility (weight = 0).
- No stability calculation (weight = 0).
- Adds slight randomness (small random perturbation to score).

- `NoviceEvaluator::new()` — Constructor with default seed `12345`.
- `NoviceEvaluator::with_seed(seed: u64)` — Constructor with explicit seed for deterministic testing.

## Configuration

### AiConfig

```rust
struct AiConfig {
    opening_depth: u8,    // stone count 4-20
    midgame_depth: u8,    // stone count 21-44
    endgame_depth: u8,    // stone count 45-64
}
```

- `AiConfig::depth_for_phase(stone_count: u32)` — Returns the appropriate depth based on stone count.

### Game Phase Detection

Phase is determined by total stone count on the board:
- Opening: 4-20 stones
- Midgame: 21-44 stones
- Endgame: 45-64 stones

## Search

### TranspositionTable

Hash table storing previously evaluated positions.

```rust
struct TtEntry {
    hash: u64,
    depth: u8,
    score: i32,
    bound: Bound,       // Exact, LowerBound, UpperBound
    best_move: Option<Position>,
}

enum Bound {
    Exact,
    LowerBound,
    UpperBound,
}
```

- `TranspositionTable::new(capacity: usize)` — Create with given capacity.
- `TranspositionTable::probe(hash: u64)` — Look up entry. Returns `Option<&TtEntry>`.
- `TranspositionTable::store(hash: u64, entry: TtEntry)` — Store entry. Replaces if new depth >= existing depth.
- `TranspositionTable::clear()` — Clear all entries.

### Zobrist Hashing

```rust
struct ZobristKeys {
    // pre-computed random u64 values: 2 colors × 64 squares = 128 values
}
```

Board hashing for transposition table lookup.

- Pre-computed random `u64` values for each (position, color) combination: 2 colors × 64 squares = 128 values.
- Hash computed incrementally: XOR in/out pieces as moves are made.
- `ZobristKeys::new()` — Generate a new set of random Zobrist keys.
- `ZobristKeys::hash(&self, board: &Board) -> u64` — Compute hash from scratch for the given board position.

### Move Ordering

Moves are ordered for maximum pruning efficiency:

1. TT best move (from previous iteration or shallower search)
2. Corner moves (positions 0, 7, 56, 63)
3. Moves sorted by opponent mobility (ascending — fewer opponent moves = better)
4. Static positional value (pre-defined 8x8 weight table)

- `order_moves(board: &Board, color: Color, moves_mask: u64, tt_move: Option<Position>, depth: u8)` — Returns `Vec<Position>` in priority order. When `depth < 3`, the expensive opponent-mobility calculation is skipped.

### Negascout

Negascout (Principal Variation Search) with iterative deepening.

```rust
struct Negascout<'a, E: BoardEvaluator + ?Sized> {
    evaluator: &'a E,
    tt: &'a mut TranspositionTable,
    zobrist: &'a ZobristKeys,
}
```

Low-level search implementation. Typically used via `SearchEngine` rather than directly.

- `Negascout::new(evaluator: &'a E, tt: &'a mut TranspositionTable, zobrist: &'a ZobristKeys)` — Constructor.
- `Negascout::nodes_searched(&self) -> u64` — Returns total node count from the last completed search.
- `Negascout::search(board: &Board, color: Color, max_depth: u8)` — Run iterative deepening search. Returns `(best_move, score, pv, leaf_eval)`.
- Internally runs depth 1, 2, ..., up to `max_depth`.
- At each depth: Negascout with alpha-beta window.
  - First move (PV node): search with full window [alpha, beta].
  - Remaining moves: null-window search [alpha, alpha+1]. If fails high, re-search with full window.
- PV extracted by tracking best move at each depth level.

### SearchEngine

Wrapper around `Negascout` managing the transposition table and Zobrist keys.

```rust
struct SearchEngine {
    tt: TranspositionTable,
    zobrist: ZobristKeys,
}
```

- `SearchEngine::new()` — Create with default TT capacity (~1M entries).
- `SearchEngine::search<E: BoardEvaluator + ?Sized>(board: &Board, color: Color, evaluator: &E, config: &AiConfig)` — Run iterative deepening search. Returns `SearchResult`.
- `SearchEngine::clear_tt()` — Clear all entries in the transposition table. Useful between games to avoid cross-game contamination.

### SearchResult

```rust
struct SearchResult {
    best_move: Position,
    score: i32,
    pv: Vec<Position>,
    leaf_eval: EvalResult,
}
```

## Explanation

### ExplainTag

```rust
enum ExplainTag {
    CornerGrab,
    CornerSetup,
    MobilityGain,
    StabilityGain,
    EdgeControl,
    ParityAdvantage,
    PieceAdvantage,
    ForcedMove,
}
```

### MoveExplanation

```rust
struct MoveExplanation {
    best_move: Position,
    pv: Vec<Position>,
    score: i32,
    factors: EvalFactors,
    primary_reason: ExplainTag,
}
```

### Explanation Generation

1. Search produces `SearchResult` with PV and `leaf_eval`.
2. Evaluate the current position to get `current_factors`.
3. Compute factor deltas: `leaf_eval.factors - current_factors`.
4. The factor with the largest positive delta becomes `primary_reason`.
5. Special cases:
   - If only one legal move exists: `ForcedMove`.
   - If best move is a corner: `CornerGrab`.
   - If best move is adjacent to a corner and PV leads to corner take: `CornerSetup`.

- `generate_explanation(board: &Board, color: Color, search_result: &SearchResult, evaluator: &dyn BoardEvaluator)` — Returns `MoveExplanation`.

## AiPlayer Facade

```rust
struct AiPlayer {
    evaluator: Box<dyn BoardEvaluator>,
    config: AiConfig,
    engine: SearchEngine,
}
```

- `AiPlayer::new(evaluator: Box<dyn BoardEvaluator>, config: AiConfig)` — Constructor.
- `AiPlayer::think(&mut self, board: &Board, color: Color)` — Run search and return `SearchResult`. Requires `&mut self` due to TT mutation.
- `AiPlayer::explain(&mut self, board: &Board, color: Color)` — Run search and return `MoveExplanation`. Requires `&mut self` due to TT mutation.
- `AiPlayer::evaluator_name(&self) -> &str` — Returns the name of the current evaluator (e.g. `"strategic"`, `"novice"`).

## GDScript Bridge Additions

Added to the existing `ReversiGame` GDScript class:

```gdscript
# AI setup
game.set_ai(evaluator_name: String, opening_depth: int, midgame_depth: int, endgame_depth: int) -> bool
# evaluator_name: "strategic" or "novice"
# Returns false if evaluator_name is unknown

# AI move
game.ai_think() -> Vector2i
# Returns best move (row, col). Returns (-1, -1) if no AI is set or game is over.

# AI explanation
game.ai_explain_move() -> Dictionary
# Returns:
# {
#   "best_move": Vector2i,
#   "pv": Array[Vector2i],
#   "score": int,
#   "primary_reason": String,   # ExplainTag as lowercase string
#   "factors": {
#     "corner_control": int,
#     "stability": int,
#     "mobility": int,
#     "edge_control": int,
#     "parity": int,
#     "piece_count": int,
#   }
# }
# Returns empty Dictionary if no AI is set or game is over.
```
