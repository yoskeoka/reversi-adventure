use reversi_engine::board::Board;
use reversi_engine::types::{Color, Position};

/// Bound type for transposition table entries.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Bound {
    Exact,
    LowerBound,
    UpperBound,
}

/// Transposition table entry.
#[derive(Debug, Clone, Copy)]
pub struct TtEntry {
    pub hash: u64,
    pub depth: u8,
    pub score: i32,
    pub bound: Bound,
    pub best_move: Option<Position>,
}

/// Zobrist hash keys for board positions.
pub struct ZobristKeys {
    keys: [[u64; 64]; 2],   // [color][square]
    side_to_move: [u64; 2], // [side to move]
}

impl ZobristKeys {
    pub fn new() -> Self {
        let mut keys = [[0u64; 64]; 2];
        // Deterministic pseudo-random generation using a simple LCG
        let mut state: u64 = 0x12345678_9ABCDEF0;
        for color_keys in &mut keys {
            for square in color_keys.iter_mut() {
                state = state
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                *square = state;
            }
        }
        let mut side_to_move = [0u64; 2];
        for key in &mut side_to_move {
            state = state
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            *key = state;
        }
        Self { keys, side_to_move }
    }

    /// Compute Zobrist hash for a board position and side to move.
    pub fn hash(&self, board: &Board, color: Color) -> u64 {
        let mut h = 0u64;
        let black = board.pieces(Color::Black);
        let white = board.pieces(Color::White);

        let mut bits = black;
        while bits != 0 {
            let sq = bits.trailing_zeros() as usize;
            h ^= self.keys[0][sq];
            bits &= bits - 1;
        }

        let mut bits = white;
        while bits != 0 {
            let sq = bits.trailing_zeros() as usize;
            h ^= self.keys[1][sq];
            bits &= bits - 1;
        }

        h ^ self.side_to_move[match color {
            Color::Black => 0,
            Color::White => 1,
        }]
    }
}

impl Default for ZobristKeys {
    fn default() -> Self {
        Self::new()
    }
}

/// Transposition table using open addressing.
pub struct TranspositionTable {
    entries: Vec<Option<TtEntry>>,
    capacity: usize,
}

impl TranspositionTable {
    pub fn new(capacity: usize) -> Self {
        Self {
            entries: vec![None; capacity],
            capacity,
        }
    }

    /// Look up an entry by hash.
    pub fn probe(&self, hash: u64) -> Option<&TtEntry> {
        let index = (hash as usize) % self.capacity;
        self.entries[index]
            .as_ref()
            .filter(|entry| entry.hash == hash)
    }

    /// Store an entry. Replaces existing entry if new depth >= existing depth.
    pub fn store(&mut self, hash: u64, entry: TtEntry) {
        let index = (hash as usize) % self.capacity;
        let should_replace = match &self.entries[index] {
            None => true,
            Some(existing) => existing.hash != hash || entry.depth >= existing.depth,
        };
        if should_replace {
            self.entries[index] = Some(entry);
        }
    }

    /// Clear all entries.
    pub fn clear(&mut self) {
        self.entries.fill(None);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_zobrist_deterministic() {
        let keys = ZobristKeys::new();
        let board = Board::new();
        let h1 = keys.hash(&board, Color::Black);
        let h2 = keys.hash(&board, Color::Black);
        assert_eq!(h1, h2);
    }

    #[test]
    fn test_zobrist_different_boards() {
        let keys = ZobristKeys::new();
        let board1 = Board::new();
        let mut board2 = Board::new();
        board2.set(Position::new(0, 0), Color::Black);
        assert_ne!(
            keys.hash(&board1, Color::Black),
            keys.hash(&board2, Color::Black)
        );
    }

    #[test]
    fn test_zobrist_distinguishes_side_to_move_in_pass_position() {
        let keys = ZobristKeys::new();
        let mut board = Board::empty();
        board.set(Position::new(0, 0), Color::Black);
        board.set(Position::new(0, 1), Color::White);

        assert_eq!(reversi_engine::moves::legal_moves(&board, Color::White), 0);
        assert_ne!(reversi_engine::moves::legal_moves(&board, Color::Black), 0);
        assert_ne!(
            keys.hash(&board, Color::Black),
            keys.hash(&board, Color::White)
        );

        let mut tt = TranspositionTable::new(1024);
        let black_hash = keys.hash(&board, Color::Black);
        let white_hash = keys.hash(&board, Color::White);
        tt.store(
            black_hash,
            TtEntry {
                hash: black_hash,
                depth: 1,
                score: 100,
                bound: Bound::Exact,
                best_move: None,
            },
        );
        assert!(tt.probe(white_hash).is_none());
    }

    #[test]
    fn test_tt_store_and_probe() {
        let mut tt = TranspositionTable::new(1024);
        let entry = TtEntry {
            hash: 42,
            depth: 5,
            score: 100,
            bound: Bound::Exact,
            best_move: Some(Position::new(2, 3)),
        };
        tt.store(42, entry);
        let result = tt.probe(42).unwrap();
        assert_eq!(result.score, 100);
        assert_eq!(result.depth, 5);
    }

    #[test]
    fn test_tt_miss() {
        let tt = TranspositionTable::new(1024);
        assert!(tt.probe(42).is_none());
    }

    #[test]
    fn test_tt_replace_deeper() {
        let mut tt = TranspositionTable::new(1024);
        let entry1 = TtEntry {
            hash: 42,
            depth: 3,
            score: 50,
            bound: Bound::Exact,
            best_move: None,
        };
        let entry2 = TtEntry {
            hash: 42,
            depth: 5,
            score: 100,
            bound: Bound::Exact,
            best_move: None,
        };
        tt.store(42, entry1);
        tt.store(42, entry2);
        assert_eq!(tt.probe(42).unwrap().score, 100);
    }
}
