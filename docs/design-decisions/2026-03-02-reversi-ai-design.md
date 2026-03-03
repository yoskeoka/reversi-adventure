# Reversi AI Design (Phase 2)

## Overview

AI engine for Reversi Adventure with pluggable evaluation strategies and move explanation. Built as a separate `reversi-ai` crate using Negascout search with hand-tuned evaluators. Designed for configurable difficulty and educational move explanation.

## Architecture

Three layers in the `reversi-ai` crate:

1. **BoardEvaluator trait** — pluggable evaluation interface. Each implementation returns a score with factor breakdown for explanation.
2. **Search engine (Negascout)** — generic over any BoardEvaluator. Configurable depth per game phase. Produces best move, PV (expected line), and evaluation breakdown.
3. **AiPlayer facade** — combines evaluator + search config into a single callable unit for the GDExtension bridge.

### Dependency Graph

```
reversi-engine (Board, moves, Game)
       ^
reversi-ai (BoardEvaluator trait, search, evaluators, AiPlayer)
       ^
reversi-godot (GDExtension bridge)
```

## Core Types

### Evaluation

```rust
/// Score breakdown for human-readable explanation.
struct EvalFactors {
    corner_control: i32,
    stability: i32,
    mobility: i32,
    edge_control: i32,
    parity: i32,
    piece_count: i32,
}

/// Evaluation result: score + explanation factors.
struct EvalResult {
    score: i32,
    factors: EvalFactors,
}

/// Pluggable board evaluation strategy.
trait BoardEvaluator {
    fn evaluate(&self, board: &Board, color: Color) -> EvalResult;
    fn name(&self) -> &str;
}
```

### Search

```rust
/// Search result with PV and explanation data.
struct SearchResult {
    best_move: Position,
    score: i32,
    pv: Vec<Position>,
    leaf_eval: EvalResult,
}

/// Per-phase depth configuration.
struct AiConfig {
    opening_depth: u8,    // stone count 0-20
    midgame_depth: u8,    // stone count 21-44
    endgame_depth: u8,    // stone count 45-64
}
```

### Explanation

```rust
struct MoveExplanation {
    best_move: Position,
    pv: Vec<Position>,
    score: i32,
    factors: EvalFactors,
    primary_reason: ExplainTag,
}

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

### AiPlayer Facade

```rust
struct AiPlayer {
    evaluator: Box<dyn BoardEvaluator>,
    config: AiConfig,
}

impl AiPlayer {
    fn new(evaluator: Box<dyn BoardEvaluator>, config: AiConfig) -> Self;
    fn think(&self, board: &Board, color: Color) -> SearchResult;
    fn explain(&self, board: &Board, color: Color) -> MoveExplanation;
}
```

## Search Engine

### Algorithm: Negascout with Iterative Deepening

- **Iterative deepening**: search depth 1, 2, 3... up to configured depth for current phase. Provides best move at any interruption and improves move ordering.
- **Negascout**: search PV move with full window [alpha, beta], remaining moves with null window [alpha, alpha+1]. Re-search on fail high. Strictly better than plain alpha-beta.
- **PV extraction**: collect principal variation during search. This becomes the expected line (読み筋) in explanation.

### Move Ordering

Critical for pruning efficiency. Order by:

1. TT best move (from previous iteration)
2. Corner moves
3. Moves that minimize opponent mobility
4. Static positional value

### Transposition Table

Simple hash map storing: best move, score, depth, bound type (exact/lower/upper). Avoids re-evaluating positions reached via different move orders.

### Board Copy Strategy

Board is two `u64` values (16 bytes). Copy per search node — negligible cost compared to evaluation. No mutate+unmake needed. Simpler and less bug-prone.

### Phase Detection

Count total pieces on board. Map to opening (0-20), midgame (21-44), endgame (45-64). Use corresponding depth from AiConfig.

## Evaluator Implementations

### StrategicEvaluator (master opponent)

Hand-tuned weights based on known Othello strategy:

- **Corner control**: corners are permanent. Penalize C-squares and X-squares adjacent to empty corners.
- **Stability**: count discs that can never be flipped (corner-anchored lines, full edges).
- **Mobility**: count of legal moves for each side. Most important midgame factor.
- **Edge control**: evaluate edge patterns (balanced edges, wedges).
- **Parity**: last-move advantage in endgame regions.
- **Piece count**: only significant in endgame. Fewer pieces is often better in opening/midgame.

### NoviceEvaluator (beginner opponent)

Simulates a player who doesn't know Othello strategy:

- Heavily weights piece count (more pieces = "winning")
- Grabs edges eagerly (ignores C-square/X-square danger)
- Ignores mobility entirely
- No stability calculation
- Slight randomness for inconsistent play

## Explanation System

Generated after search completes, from SearchResult:

1. Search produces SearchResult with PV and leaf_eval.factors
2. Compare factors between current position and PV leaf position
3. Factor with largest positive change becomes primary_reason
4. ExplainTag enum maps to localized display text in GDScript (no strings from Rust)

Player sees: best move highlighted, expected line as numbered moves, short text explaining the dominant strategic reason.

## GDExtension Bridge Additions

```gdscript
# AI setup
game.set_ai(evaluator_name: String, config: Dictionary) -> bool

# AI move
game.ai_think() -> Vector2i

# AI explanation
game.ai_explain_move() -> Dictionary
# {
#   "best_move": Vector2i,
#   "pv": Array[Vector2i],
#   "score": int,
#   "primary_reason": String,
#   "factors": Dictionary,
# }
```

### Difficulty Presets (defined in GDScript)

- "beginner": NoviceEvaluator + depth 1/2/3
- "intermediate": StrategicEvaluator + depth 3/4/6
- "master": StrategicEvaluator + depth 6/8/12

## File Layout

```
rust/reversi-ai/
  Cargo.toml
  src/
    lib.rs
    eval/
      mod.rs          # BoardEvaluator trait, EvalResult, EvalFactors
      strategic.rs    # StrategicEvaluator
      novice.rs       # NoviceEvaluator
    search/
      mod.rs          # SearchEngine, SearchResult
      negascout.rs    # Negascout + iterative deepening
      tt.rs           # TranspositionTable
      ordering.rs     # move ordering heuristics
    explain.rs        # MoveExplanation, ExplainTag, explanation generation
    player.rs         # AiPlayer facade
    config.rs         # AiConfig, difficulty presets
```

## Testing Strategy

- Unit tests per module (evaluator correctness, search depth, TT hits)
- Integration tests: known positions with expected best moves
- Evaluator comparison: StrategicEvaluator should beat NoviceEvaluator in self-play

## Deferred (logged as issues)

- **Endgame solver**: perfect play in final N moves (docs/issues/endgame-solver.md)
- **Trained evaluator**: ML/RL-based pattern evaluation (docs/issues/trained-evaluator.md)

## References

- Egaroucid technology: https://www.egaroucid.nyanyan.dev/ja/technology/explanation/
- Logistello pattern evaluation approach
