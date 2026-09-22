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
    fn context_fingerprint(&self) -> u64;
}
```

Implementations must return evaluation from the perspective of `color` (positive = good for `color`).

`context_fingerprint()` must:

- stay stable for the same score context;
- include the evaluator version and all score-affecting parameters;
- exclude object addresses and other process-local state.

`StrategicEvaluator` includes its version and evaluation weights.
`NoviceEvaluator` includes its version and seed.

### Pattern-evaluator artifact contract

The project-owned trained-pattern evaluator is a future `BoardEvaluator`
implementation. This contract defines its input representation only; it does
not change the strategic or novice evaluators, invoke an explanatory
evaluator, or assign human-readable factors to a pattern score.

- The catalog contains exactly 64 features: eight project-defined base square
  patterns expanded through all eight dihedral symmetries of the 8-by-8 board.
  Every feature contains at most ten squares. The catalog digest identifies
  both the square order and this expansion order.
- A square is ternary encoded from the requested color's perspective: empty
  is `0`, the requested color is `1`, and the opponent is `2`. A feature code
  is the square values accumulated in listed-square order as a base-three
  integer.
- Before extraction, the board is put in the lexicographically smallest of its
  eight absolute-color symmetry orientations (ties use the lowest symmetry
  number). Ternary codes remain relative to the requested color. Consequently
  symmetric positions produce the same 64 feature codes, in catalog order, and
  changing requested color swaps ternary `1` and `2` without changing feature
  alignment.
- There are exactly 60 discrete phase tables. Their indexes are the occupied
  disc count minus four, covering occupied counts `4..=63`. A pass leaves the
  phase unchanged; terminal 64-disc positions have no pattern phase. Scores
  must not interpolate between phase tables.
- A trained pattern score predicts the requested color's final disc
  differential. It is an integer in inclusive range `-64..=64`. Accumulation
  is deterministic integer arithmetic and an artifact is rejected when any
  contribution, declared aggregate bound, or checked aggregate cannot satisfy
  that range without overflow.
- A weight artifact is immutable and identifies its format version, catalog
  digest, phase definition, final-disc-difference score scale, safe source
  provenance, and weight digest. Provenance may name a reproducible trainer,
  input-manifest digest, and licenses; it must not embed private input data.
  Its catalog, phase, scale, version, and weight identity are score-affecting
  context and therefore enter the future evaluator's
  `context_fingerprint()`.

Pattern scores have no human-factor attribution and must not be combined with
the explanatory evaluator or its explanation path.

### Trained evaluator runtime

`TrainedEvaluator` loads only the canonical JSON artifact emitted by the
project-owned training tool.  Loading validates the complete feature contract,
safe non-empty provenance, all 64 feature bounds, the sparse 60-phase table
shape and canonical decimal codes, every weight and aggregate score bound, and
the SHA-256 `weight_digest` and `artifact_digest` identities.  A load or
validation failure is a clear error; it never selects a fallback evaluator.

The evaluator sums the 64 sparse entries selected by `extract_features()` for
the board phase and requested color, returning a final-disc-difference score
with default (empty) `EvalFactors`.  Its context fingerprint includes a
trained-runtime version plus the artifact's immutable identity, so retained
transposition-table entries cannot cross artifacts or feature contracts.

The oracle candidate CLI selects this evaluator only with `--evaluator trained
--trained-artifact PATH`.  It uses `SearchEngine` directly, remains bookless,
and preserves all four `AiConfig` controls.  A named profile supplies all four
controls and rejects any explicit control rather than ignoring it.  Trained
mode neither constructs `AiPlayer` nor exposes explanation output.

### Pattern-evaluator training contract

`tools/reversi-ai-training` is an offline, manifest-driven producer of a
future pattern-weight artifact. It is not loaded by the game or GDExtension,
and neither its datasets nor caches are runtime dependencies.

- A version-1 input record is JSON Lines and states a record id, source id,
  SPDX license, source digest, 64-character row-major `B`/`W`/`.` board,
  side (`B` or `W`), final-disc-difference target for that side, and one of
  `train`, `validation`, or `held_out`. Optional candidate positions state the
  same board, side, and target fields and permit move-quality measurement.
  Targets are finite integers in `-64..=64`; the only accepted target semantic
  is `final_disc_difference_for_side`.
- A versioned manifest pins each input pathname, SHA-256 digest, license,
  trainer version, random seed, feature-contract digest, optimizer parameters,
  and split names. The manifest digest is the SHA-256 of its canonical JSON
  serialization. Records with a missing license, an input digest mismatch, an
  invalid board/schema, non-finite number, or incompatible feature contract
  are rejected.
- The canonical absolute-color D4 board key, together with side to move,
  identifies a position for split checking. A duplicate key anywhere in the
  inputs, including a symmetry-equivalent position in another split, is a
  leakage error. Calibration and acceptance corpora are held-out inputs and
  are never training or optimizer-tuning inputs.
- The trainer consumes the fixed 64 features and 60 discrete phases above and
  emits a sparse JSON artifact plus a JSON validation report. The report uses
  only `held_out` records (never `validation`) and records the manifest digest,
  trainer version, seed, feature-contract digest, optimizer parameters, input
  licenses, per-phase loss, and candidate top-target agreement. Its sparse
  per-phase/per-feature tables use integer weights; each
  feature's declared absolute bound is at most one and all 64 bounds sum to at
  most 64, so every selected aggregate is representable on the required
  `-64..=64` scale without overflow.
- Artifact metadata includes a canonical weight digest and artifact digest.
  Validation recomputes both, validates the feature contract, phase count,
  score scale, provenance, bounds, and every feature-vector prediction. A
  rerun with identical manifest and input bytes must produce identical declared
  artifact and report digests. Corruption, NaN, overflow, or a contract-mismatched
  artifact fails closed.

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
    exact_solver_empty_squares: u32,
}
```

`exact_solver_empty_squares` is the exact-solver start threshold. When the
decision position has at most this many empty squares, every evaluator is
bypassed and the engine attempts a complete final-disc solve. It is not an
endgame search depth. The default remains `12`; the named
`strong-engine-hcap-v1` candidate profile uses `16`.

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

Each TT entry is scoped to:

- the board;
- the side to move;
- the evaluator and search context that produced it.

`SearchEngine` combines the evaluator's `context_fingerprint()` with the active
`AiConfig` and search-semantics version. It clears the TT when that context
changes. Scores, bounds, and best moves must not cross context boundaries.

### Zobrist Hashing

```rust
struct ZobristKeys {
    // pre-computed random u64 values: 2 colors × 64 squares + 2 side keys
}
```

Board and side-to-move hashing for transposition table lookup.

- Pre-computed random `u64` values for each (position, color) combination plus one value for each side to move: 128 board values + 2 side keys.
- Hash computed incrementally: XOR in/out pieces as moves are made.
- `ZobristKeys::new()` — Generate a new set of random Zobrist keys.
- `ZobristKeys::hash(&self, board: &Board, color: Color) -> u64` — Compute hash from scratch for the given board position and side to move. The same discs with different sides to move produce different keys.

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
- `Negascout::search(board: &Board, color: Color, max_depth: u8, budget: &SearchBudget)` — Internal budgeted iterative deepening search. Returns the root outcome and the last wholly completed iteration.
- TT probes and stores use a Zobrist key that includes the current `color`, including when a pass keeps the board unchanged.
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
    context_fingerprint: Option<u64>,
}
```

- `SearchEngine::new()` — Create with default TT capacity (~1M entries).
- `SearchEngine::search_with_budget<E: BoardEvaluator + ?Sized>(board: &Board, color: Color, evaluator: &E, config: &AiConfig, budget: &SearchBudget)` — Run iterative deepening search within the supplied budget. Returns `SearchResult`.
- `SearchEngine::clear_tt()` — Clear all entries in the transposition table. Useful between games to avoid cross-game contamination.

### SearchBudget

```rust
struct SearchBudget {
    deadline: Instant,
    node_limit: Option<u64>,
    cancellation: Option<Arc<AtomicBool>>,
}
```

- The deadline is monotonic and is the primary turn budget. `SearchBudget::with_time_limit` creates it from the current monotonic clock. A duration beyond the platform deadline range becomes an immediate deadline.
- `node_limit` is an optional secondary, deterministic ceiling for tests, CI, corpus, and tuning runs. A fixed node limit must reproduce the result metadata, PV, and completed depth for the same search context.
- `cancellation` is an optional, cloneable token owned by the caller. Another thread may set its `AtomicBool`; the search only reads it and owns no callback or worker.
- Search polls all three limits during expansion. Reaching a deadline or node limit, or observing cancellation, interrupts the current iteration.

### SearchResult

```rust
struct SearchResult {
    outcome: SearchOutcome,
    score: Option<i32>,
    pv: Vec<Position>,
    leaf_eval: Option<EvalResult>,
    completed_depth: u8,
    nodes_searched: u64,
    elapsed: Duration,
    exact: bool,
}

enum SearchOutcome {
    Move(Position),
    Pass,
    GameOver,
}
```

- A heuristic state without a legal move returns `Pass` when the opponent can
  move and `GameOver` otherwise. It never exposes a sentinel `Position` or
  score. Completed exact endgame states are the documented exception: they
  retain the final root-side score.
- For a legal-move state, search selects a legal root fallback before deeper work. If interrupted before depth 1 completes, it returns that fallback, an empty PV, no score or leaf evaluation, `completed_depth = 0`, and `exact = false`.
- After each wholly completed depth, the result atomically advances to that iteration's move, PV, score, and leaf evaluation. A partial iteration is never returned or stored as the completed PV.
- Heuristic iterative deepening always reports `exact = false`, including when
  its configured maximum depth completes. `exact = true` is reserved for a
  completed final-disc proof from the endgame solver.

### Exact endgame solving

- At or below `AiConfig::exact_solver_empty_squares`, `SearchEngine` uses the
  shared, evaluator-independent endgame solver instead of heuristic iterative
  deepening. The default threshold is 12 empty squares.
- A completed endgame result has `exact = true`, its `score` is the final disc
  differential from the root side's perspective, and its PV contains only
  played positions (a pass is represented by `SearchOutcome::Pass`, never by a
  sentinel position).
- The solver handles forced passes without consuming an empty square and
  returns `GameOver` only when neither side can move. A terminal endgame score
  is exact.
- Exact endgame cache entries are private to the solver and are never read as
  heuristic transposition-table entries. Heuristic TT entries must likewise
  never cause `exact = true`.
- If the supplied `SearchBudget` interrupts an endgame solve, the result keeps
  the legal root fallback or the last wholly completed result, has `exact =
  false`, and exposes no partial PV or partial exact score.

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
    ExactEndgame,
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
   - For an exact endgame result, show its final disc differential and PV with
     `ExactEndgame`; do not derive a heuristic-factor delta.

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
- `AiPlayer::think(&mut self, board: &Board, color: Color, budget: &SearchBudget)` — Run search and return `SearchResult`. Requires `&mut self` due to TT mutation.
- `AiPlayer::explain(&mut self, board: &Board, color: Color, budget: &SearchBudget)` — Run search and return `Option<MoveExplanation>`. It returns `None` when search has no move or no completed evaluation. Requires `&mut self` due to TT mutation.
- `AiPlayer::evaluator_name(&self) -> &str` — Returns the name of the current evaluator (e.g. `"strategic"`, `"novice"`).

## External Oracle Analysis

The project uses a pinned Egaroucid Console build as a development and
evaluation oracle. It is an external tool, not an AI engine dependency:

- No Rust source file may link to, invoke, or embed Egaroucid.
- `reversi-ai`, `reversi-engine`, and `reversi-godot` remain buildable without
  downloading or installing the oracle.
- The oracle executable and its mutable resources/cache are kept outside the
  checkout and are absent from product, GDExtension, and release artifacts.
- Make targets, scripts, and CI may use the oracle to play matches against a
  project AI, to provide an evaluation opponent, and to score a project AI's
  selected move.

The versioned corpus and normalized report use the following wire contract:

- A board is a 64-character row-major string from `a1` through `h8` using `B`,
  `W`, and `.`. `side_to_move` is `B` or `W`.
- `legal_moves` is the complete legal move set in canonical coordinate order
  (ASCII ascending, e.g. `a1`, `a2`, ..., `a8`, `b1`, ..., `h8`).
- `phase` is `opening` for 4–20 stones, `midgame` for 21–44 stones, and
  `endgame` for 45–64 stones.
- `outcome` is `MoveSet` with the legal moves, `Pass` when the side to move
  has no move but the opponent does, or `GameOver` when neither side can move.
- `provenance` identifies how the position was produced and is retained in
  every normalized report.
- Before `-solve`, the adapter converts each query to Egaroucid's
  current-player-relative `X`/`O`/`-` alphabet and appends `X` for the side to
  move, while preserving the canonical `a1` through `h8` cell order.

An oracle analysis reports one record for each legal root move and derives the
full equal-value `optimal_moves` set. Scores are signed Egaroucid search values
from the root side's perspective; when `exact` is true, the value is the final
disc difference, while an incomplete search value is heuristic. A project AI's
selected move may be included as `selected_move`; its `selected_value` is the
corresponding oracle value and `regret` is `best_value - selected_value`. Each
selected/root evaluation contains `completed_depth`, `nodes`, `elapsed_ms`, and
`exact`. `exact` is true only when the reported depth reaches all remaining
placements under Egaroucid's search-depth convention, rather than when the MPC
probability merely reaches a threshold. The pinned Egaroucid search does not
decrement this depth for a forced pass. A move
in `optimal_moves` has zero regret and is an agreement even if it is not the
oracle's displayed first move. The versioned golden projection may omit
`elapsed_ms` (and other runtime-only fields) but retains all score, move, depth,
node-count, and exactness data. The solve parser requires exactly one expected
table header and one terminal `total` summary; its node count and NPS must
match the row aggregates, and its elapsed time must match them within the
oracle's six-significant-digit formatter rounding.

The adapter must fail closed on a missing or hash-mismatched oracle, a modified
cached source or binary, a process timeout, unexpected output, malformed
board/corpus data, or an incomplete root-move set. The expected source digest is
derived from the verified archive rather than from a mutable cache manifest;
the executable is rebuilt from that verified source before use. The adapter
must not pass the oracle's ignored time-limit option; the wrapper process
timeout is the only wall-clock safety limit.

### Versioned strength profiles

`strong-engine-hcap-v1` is the reproducible calibration profile. Every oracle
analysis and match report serializes the complete profile object alongside the
pinned source digest. It fixes Egaroucid Console v7.8.1, source digest,
bookless operation, one thread, hash level 25, no evaluation override, and no
oracle time-control argument. A subprocess timeout is only a safety failure
boundary, never a fairness budget.

Its Egaroucid fixed-depth, 100%-probability ranges are move numbers 1--41 at
depth 8 and 42--60 at depth 12. An Egaroucid move number is `occupied_discs -
3` in the decision position before the move, so the latter range starts at 45
occupied discs. The adapter must reject a legacy numeric-level response when a
custom-depth response is required, and must reject any mismatch of the profile,
source, book/eval setting, hash/thread setting, corpus, or report metadata.

The candidate half of `strong-engine-hcap-v1` uses heuristic depth 12 for every
non-exact decision position (including the opening and the 17--19-empty-square
interval), starts exact solving at at most 16 empty squares, and accepts a
caller-owned monotonic deadline. An optional node ceiling is a deterministic
tuning or CI limit, not the production fairness budget. Interrupted exact
searches retain only a legal fallback or wholly completed result, with
`exact = false` and no partial exact score/PV.

The profile is a calibration baseline, not proof of the final strength target.
That target must be evaluated separately on a declared held-out,
color-swapped, opening-rotated suite and report `wins / all games >= 0.50`
separately from match points (where a draw is 0.5), with a sample-size and
confidence rule. `ci-smoke-v1` remains a distinct small, bounded profile and
cannot be used to assert calibration or final strength.

## GDScript Bridge Additions

Added to the existing `ReversiGame` GDScript class:

```gdscript
# AI setup
game.set_ai(evaluator_name: String, opening_depth: int, midgame_depth: int, endgame_depth: int) -> bool
# evaluator_name: "strategic" or "novice"
# Returns false if evaluator_name is unknown
game.ai_think_with_budget(time_limit_millis: int, node_limit: int) -> Vector2i
# Returns (-1, -1) for Pass, GameOver, or no AI. node_limit <= 0 disables the node cap.

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
