use crate::types::{Color, Position};
use std::fmt;

/// Bitboard representation of a Reversi board.
/// Each color is stored as a u64 bitmask where bit `row*8+col` indicates a piece.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Board {
    pub black: u64,
    pub white: u64,
}

impl Board {
    /// Creates a board with the standard Reversi starting position.
    pub fn new() -> Self {
        // Initial: White at (3,3),(4,4); Black at (3,4),(4,3)
        let white = (1u64 << 27) | (1u64 << 36); // (3,3) and (4,4)
        let black = (1u64 << 28) | (1u64 << 35); // (3,4) and (4,3)
        Self { black, white }
    }

    /// Creates an empty board.
    pub fn empty() -> Self {
        Self { black: 0, white: 0 }
    }

    /// Returns the bitmask for the given color.
    pub fn pieces(&self, color: Color) -> u64 {
        match color {
            Color::Black => self.black,
            Color::White => self.white,
        }
    }

    /// Returns the bitmask of all occupied cells.
    pub fn occupied(&self) -> u64 {
        self.black | self.white
    }

    /// Returns the bitmask of all empty cells.
    pub fn empty_cells(&self) -> u64 {
        !self.occupied()
    }

    /// Gets the color of the piece at the given position, or None if empty.
    pub fn get(&self, pos: Position) -> Option<Color> {
        let mask = pos.bit_mask();
        if self.black & mask != 0 {
            Some(Color::Black)
        } else if self.white & mask != 0 {
            Some(Color::White)
        } else {
            None
        }
    }

    /// Sets a piece at the given position. Used for board setup, not normal play.
    pub fn set(&mut self, pos: Position, color: Color) {
        let mask = pos.bit_mask();
        // Clear both colors first
        self.black &= !mask;
        self.white &= !mask;
        // Set the requested color
        match color {
            Color::Black => self.black |= mask,
            Color::White => self.white |= mask,
        }
    }

    /// Removes a piece at the given position.
    pub fn remove(&mut self, pos: Position) {
        let mask = pos.bit_mask();
        self.black &= !mask;
        self.white &= !mask;
    }

    /// Counts pieces of the given color.
    pub fn count(&self, color: Color) -> u32 {
        self.pieces(color).count_ones()
    }

    /// Returns true if all 64 cells are occupied.
    pub fn is_full(&self) -> bool {
        self.occupied() == u64::MAX
    }

    /// Parses a board from an 8-line string.
    /// Each line has 8 characters: 'B'=black, 'W'=white, '.'=empty.
    pub fn from_string(s: &str) -> Result<Self, String> {
        let mut board = Board::empty();
        let lines: Vec<&str> = s.lines().collect();
        if lines.len() != 8 {
            return Err(format!("expected 8 lines, got {}", lines.len()));
        }
        for (row, line) in lines.iter().enumerate() {
            let chars: Vec<char> = line.chars().collect();
            if chars.len() != 8 {
                return Err(format!("line {} has {} chars, expected 8", row, chars.len()));
            }
            for (col, &ch) in chars.iter().enumerate() {
                let pos = Position::new(row as u8, col as u8);
                match ch {
                    'B' => board.set(pos, Color::Black),
                    'W' => board.set(pos, Color::White),
                    '.' => {}
                    _ => return Err(format!("invalid char '{}' at ({}, {})", ch, row, col)),
                }
            }
        }
        Ok(board)
    }

    /// Serializes the board to an 8-line string.
    pub fn to_board_string(&self) -> String {
        let mut s = String::with_capacity(8 * 9); // 8 chars + newline per row
        for row in 0..8u8 {
            for col in 0..8u8 {
                let pos = Position::new(row, col);
                match self.get(pos) {
                    Some(Color::Black) => s.push('B'),
                    Some(Color::White) => s.push('W'),
                    None => s.push('.'),
                }
            }
            if row < 7 {
                s.push('\n');
            }
        }
        s
    }
}

impl Default for Board {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for Board {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.to_board_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_board() {
        let board = Board::new();
        assert_eq!(board.get(Position::new(3, 3)), Some(Color::White));
        assert_eq!(board.get(Position::new(3, 4)), Some(Color::Black));
        assert_eq!(board.get(Position::new(4, 3)), Some(Color::Black));
        assert_eq!(board.get(Position::new(4, 4)), Some(Color::White));
        assert_eq!(board.get(Position::new(0, 0)), None);
        assert_eq!(board.count(Color::Black), 2);
        assert_eq!(board.count(Color::White), 2);
    }

    #[test]
    fn test_empty_board() {
        let board = Board::empty();
        assert_eq!(board.count(Color::Black), 0);
        assert_eq!(board.count(Color::White), 0);
        assert_eq!(board.occupied(), 0);
    }

    #[test]
    fn test_set_and_get() {
        let mut board = Board::empty();
        let pos = Position::new(2, 3);
        assert_eq!(board.get(pos), None);
        board.set(pos, Color::Black);
        assert_eq!(board.get(pos), Some(Color::Black));
        board.set(pos, Color::White);
        assert_eq!(board.get(pos), Some(Color::White));
    }

    #[test]
    fn test_remove() {
        let mut board = Board::new();
        let pos = Position::new(3, 3);
        assert_eq!(board.get(pos), Some(Color::White));
        board.remove(pos);
        assert_eq!(board.get(pos), None);
    }

    #[test]
    fn test_serialization_roundtrip() {
        let board = Board::new();
        let s = board.to_board_string();
        let parsed = Board::from_string(&s).unwrap();
        assert_eq!(board, parsed);
    }

    #[test]
    fn test_board_string_format() {
        let board = Board::new();
        let s = board.to_board_string();
        let expected = "\
........\n\
........\n\
........\n\
...WB...\n\
...BW...\n\
........\n\
........\n\
........";
        assert_eq!(s, expected);
    }

    #[test]
    fn test_is_full() {
        let board = Board { black: u64::MAX, white: 0 };
        assert!(board.is_full());
        assert!(!Board::new().is_full());
    }
}
