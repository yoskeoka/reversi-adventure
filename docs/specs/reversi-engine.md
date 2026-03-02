# Reversi Engine Specification

## Overview

Pure Rust library implementing core Reversi (Othello) game logic. No UI, no Godot dependency. Exposed to GDScript via a separate godot-rust GDExtension bridge.

## Coordinate System

- 8x8 board. Rows 0-7 (top to bottom), columns 0-7 (left to right).
- Bit index = `row * 8 + col`. Bit 0 = top-left (0,0), bit 63 = bottom-right (7,7).
- Position is represented as `(row, col)` tuple where both are `u8` in range `0..8`.

## Board Representation

Bitboard using two `u64` values:

```
Board {
    black: u64,  // 1-bit = black piece present
    white: u64,  // 1-bit = white piece present
}
```

Invariant: `black & white == 0` (no cell can contain both colors).

### Initial Position

Standard Reversi starting position:

```
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . W B . . .
. . . B W . . .
. . . . . . . .
. . . . . . . .
. . . . . . . .
```

- White at (3,3) and (4,4): bits 27 and 36.
- Black at (3,4) and (4,3): bits 28 and 35.

### Board Methods

- `new()` — Create board with initial position.
- `empty()` — Create empty board (for puzzle setups).
- `get(pos: Position)` — Returns `Option<Color>` for the cell.
- `set(pos: Position, color: Color)` — Place a piece (for board setup, not normal play).
- `remove(pos: Position)` — Remove a piece (for board setup).
- `pieces(color: Color)` — Returns `u64` bitmask for the given color.
- `count(color: Color)` — Count pieces of given color.
- `is_full()` — True if all 64 cells are occupied.
- `occupied()` — Returns `u64` bitmask of all occupied cells.
- `empty_cells()` — Returns `u64` bitmask of all empty cells.

## Types

### Color

```
enum Color {
    Black,
    White,
}
```

- `Color::opponent()` — Returns the opposite color.

### Position

```
struct Position {
    row: u8,  // 0..8
    col: u8,  // 0..8
}
```

- `Position::new(row: u8, col: u8)` — Constructor.
- `Position::bit_index()` — Returns `row * 8 + col`.
- `Position::from_bit_index(index: u8)` — Inverse mapping.
- `Position::bit_mask()` — Returns `1u64 << bit_index()`.

### GameResult

```
enum GameResult {
    Win(Color),
    Draw,
}
```

### GameStatus

```
enum GameStatus {
    InProgress,
    Passed,      // opponent had no legal moves, current player continues
    GameOver(GameResult),
}
```

## Move Generation

### Legal Moves

A move is legal if:
1. The target cell is empty.
2. Placing a piece there flips at least one opponent piece.

Flipping occurs along 8 directions (N, NE, E, SE, S, SW, W, NW). A direction produces a flip if there is a contiguous line of opponent pieces ending at a piece of the current player's color.

- `legal_moves(board, color)` — Returns a `u64` bitmask of all legal move positions.
- `is_legal_move(board, color, position)` — Check a single position.
- `has_legal_move(board, color)` — Returns true if any legal move exists.
- `flipped_pieces(board, color, position)` — Returns a `u64` bitmask of pieces that would be flipped.

### Move Execution

- `make_move(board, color, position)` — Returns a new `Board` with the move applied and pieces flipped. Panics if the move is illegal.

## Game State Machine

```
Game {
    board: Board,
    current_turn: Color,
    status: GameStatus,
    move_history: Vec<Option<Position>>,  // None = pass
}
```

### Lifecycle

1. `Game::new()` — New game, black moves first. Status = InProgress.
2. `Game::play(position)` — Make a move for the current player.
   - Validates the move is legal.
   - Applies the move.
   - Checks if the opponent has legal moves:
     - Yes → switch turn, status = InProgress.
     - No → check if current player has legal moves:
       - Yes → opponent passes, stay on same player, status = Passed.
       - No → game over, status = GameOver(result).
   - Appends to move_history.
   - Returns `Result<GameStatus, MoveError>`.
3. `Game::pass_turn()` — Explicit pass (only valid when current player has no legal moves).

### MoveError

```
enum MoveError {
    InvalidPosition,
    CellOccupied,
    NoFlips,
    GameAlreadyOver,
}
```

### Game Queries

- `Game::board()` — Returns a reference to the board.
- `Game::current_turn()` — Returns the current player's color.
- `Game::status()` — Returns the current game status.
- `Game::legal_moves()` — Legal moves bitmask for current player.
- `Game::score()` — Returns `(black_count, white_count)`.
- `Game::is_game_over()` — Shorthand for checking status.
- `Game::winner()` — Returns `Option<GameResult>` if game is over.
- `Game::move_history()` — Returns the move history slice.
- `Game::move_history_string()` — Serializes move history to comma-separated format.
- `Game::from_board(board, current_turn)` — Creates a game from a custom board state.

## Serialization

### Board String Format

8 lines of 8 characters. `B` = black, `W` = white, `.` = empty.

```
........
........
........
...WB...
...BW...
........
........
........
```

- `Board::to_board_string()` — Serialize board to this format. Also available via `Display` trait (`to_string()`).
- `Board::from_string(s: &str)` — Parse board from this format. Returns `Result<Board, String>`.

### Move History Format

Standard Othello notation. Each move is 2 characters: column letter (A-H) + row number (1-8). Moves are concatenated without separators. Pass = `PS`.

Example: `F5D6C3D3C4` (five moves, no passes)
Example with pass: `F5D6C3PSC4`

Column A = left (col 0), column H = right (col 7). Row 1 = top (row 0), row 8 = bottom (row 7).

## GDScript Bridge API

The bridge exposes the engine to GDScript via a `ReversiGame` class (GDExtension RefCounted).

### ReversiGame (GDScript class)

```gdscript
# Construction
var game = ReversiGame.new()

# Queries
game.get_cell(row: int, col: int) -> int  # 0=empty, 1=black, 2=white
game.get_legal_moves() -> Array[Vector2i]  # list of (row, col)
game.get_current_turn() -> int             # 1=black, 2=white
game.get_score() -> Vector2i               # (black_count, white_count)
game.is_game_over() -> bool
game.get_status() -> int                   # 0=in_progress, 1=passed, 2=game_over
game.get_winner() -> int                   # 0=none, 1=black, 2=white, 3=draw

# Actions
game.play(row: int, col: int) -> int       # returns status, or -1 on error
game.pass_turn() -> int                    # returns status, or -1 on error

# Serialization
game.get_board_string() -> String
game.set_board_from_string(s: String) -> bool

# History
game.get_move_count() -> int
game.get_move_history() -> String          # comma-separated "rc" format
```
