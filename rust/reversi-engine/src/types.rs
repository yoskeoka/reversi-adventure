/// Represents a player color.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Color {
    Black,
    White,
}

impl Color {
    /// Returns the opposite color.
    pub fn opponent(self) -> Color {
        match self {
            Color::Black => Color::White,
            Color::White => Color::Black,
        }
    }
}

/// Represents a position on the 8x8 board.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Position {
    pub row: u8,
    pub col: u8,
}

impl Position {
    pub fn new(row: u8, col: u8) -> Self {
        debug_assert!(row < 8 && col < 8, "Position out of bounds: ({}, {})", row, col);
        Self { row, col }
    }

    /// Returns the bit index (0..64) for this position.
    pub fn bit_index(self) -> u8 {
        self.row * 8 + self.col
    }

    /// Creates a Position from a bit index (0..64).
    pub fn from_bit_index(index: u8) -> Self {
        debug_assert!(index < 64, "Bit index out of bounds: {}", index);
        Self {
            row: index / 8,
            col: index % 8,
        }
    }

    /// Returns the bitmask with a single bit set at this position.
    pub fn bit_mask(self) -> u64 {
        1u64 << self.bit_index()
    }
}

/// Result of a completed game.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GameResult {
    Win(Color),
    Draw,
}

/// Current status of the game.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GameStatus {
    InProgress,
    Passed,
    GameOver(GameResult),
}

/// Errors that can occur when making a move.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MoveError {
    InvalidPosition,
    CellOccupied,
    NoFlips,
    GameAlreadyOver,
}

impl std::fmt::Display for MoveError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            MoveError::InvalidPosition => write!(f, "invalid position"),
            MoveError::CellOccupied => write!(f, "cell is occupied"),
            MoveError::NoFlips => write!(f, "move does not flip any pieces"),
            MoveError::GameAlreadyOver => write!(f, "game is already over"),
        }
    }
}

impl std::error::Error for MoveError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_color_opponent() {
        assert_eq!(Color::Black.opponent(), Color::White);
        assert_eq!(Color::White.opponent(), Color::Black);
    }

    #[test]
    fn test_position_bit_index() {
        assert_eq!(Position::new(0, 0).bit_index(), 0);
        assert_eq!(Position::new(0, 7).bit_index(), 7);
        assert_eq!(Position::new(7, 7).bit_index(), 63);
        assert_eq!(Position::new(3, 4).bit_index(), 28);
    }

    #[test]
    fn test_position_from_bit_index() {
        let pos = Position::from_bit_index(28);
        assert_eq!(pos.row, 3);
        assert_eq!(pos.col, 4);
    }

    #[test]
    fn test_position_bit_mask() {
        assert_eq!(Position::new(0, 0).bit_mask(), 1);
        assert_eq!(Position::new(0, 1).bit_mask(), 2);
        assert_eq!(Position::new(7, 7).bit_mask(), 1u64 << 63);
    }
}
