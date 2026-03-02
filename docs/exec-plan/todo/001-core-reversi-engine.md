# 001: Core Reversi Engine

## Objective

Implement the core Reversi (Othello) game engine in Rust as a godot-rust GDExtension. This is the foundation for all subsequent phases — AI (Phase 2), game modes (Phase 3-5), and UI (Phase 7) will all depend on this engine.

The engine must handle:
- Board state representation (bitboard for performance)
- Legal move generation
- Move execution and piece flipping
- Game-over detection and scoring
- Pass detection (when a player has no legal moves)
- Board serialization/deserialization (for save/load and puzzle systems in Phase 4)

## Spec Changes

Create `docs/specs/reversi-engine.md` covering:
- Board representation (bitboard: two `u64` values for black/white pieces)
- Public API surface exposed to GDScript
- Move validation rules
- Game state lifecycle (new game, make move, pass, game over)
- Coordinate system (row/col mapping to bit positions)
- Serialization format

## Code Changes

### Rust crate: `reversi-engine/`

A Rust library crate at the project root.

```
reversi-engine/
  Cargo.toml
  src/
    lib.rs          # crate root, re-exports
    board.rs        # Board struct, bitboard operations
    game.rs         # Game struct (state machine: turns, passes, game over)
    moves.rs        # legal move generation, move execution, flipping
    types.rs        # Color, Position, Move, GameResult enums
```

### godot-rust GDExtension: `godot/rust/`

Binds the Rust engine to Godot via gdext.

```
godot/rust/
  Cargo.toml       # depends on reversi-engine + godot crate
  src/
    lib.rs          # GDExtension entry point
    bridge.rs       # GDScript-callable wrapper classes
```

### Godot project: `godot/`

Minimal Godot project scaffolding.

```
godot/
  project.godot
  .gdextension     # GDExtension config pointing to Rust library
  rust/             # Rust GDExtension source (above)
```

## Sub-tasks

- [ ] [parallel] Set up Godot project scaffolding (`godot/project.godot`, `.gdextension`)
- [ ] [parallel] Set up Rust workspace (`reversi-engine/` crate + `godot/rust/` GDExtension crate)
- [ ] [parallel] Create spec: `docs/specs/reversi-engine.md`
- [ ] [depends on: Rust workspace] Implement `types.rs` — Color, Position, Move, GameResult
- [ ] [depends on: types] Implement `board.rs` — Board struct with bitboard representation, coordinate mapping, display
- [ ] [depends on: board] Implement `moves.rs` — legal move generation, move execution, flipping logic
- [ ] [depends on: moves] Implement `game.rs` — Game state machine (new, make_move, pass, game_over, score)
- [ ] [depends on: game] Implement serialization (board to/from string representation)
- [ ] [depends on: game] Write Rust unit tests for all core logic
- [ ] [depends on: Rust workspace, game] Implement `bridge.rs` — GDScript-callable wrapper via gdext
- [ ] [depends on: Godot project, bridge] Integration test: call Rust engine from a minimal GDScript scene
- [ ] [depends on: all] Update spec to match final implementation

## Design Decisions

### Bitboard representation

Use two `u64` values (one per color) to represent the 8x8 board. Each bit corresponds to a cell. This enables:
- Fast legal move generation via bitwise operations
- Compact memory footprint (16 bytes for entire board state)
- Natural fit for alpha-beta pruning in Phase 2

This is the standard approach in competitive Reversi/Othello engines.

### Rust workspace layout

Separate `reversi-engine` (pure Rust, no Godot dependency) from `godot/rust/` (GDExtension bridge). This allows:
- Unit testing the engine without Godot
- Potential reuse of the engine outside Godot (CLI tools, web, etc.)
- Clean dependency boundary

### Coordinate system

Row 0 = top, Col 0 = left. Bit index = row * 8 + col. This matches screen coordinates (origin top-left) for straightforward UI mapping in later phases.

## Verification

- `cargo test` in `reversi-engine/` passes all unit tests
- `cargo build` in `godot/rust/` produces a shared library
- A minimal Godot scene can instantiate the Rust engine, make moves, and read board state via GDScript
