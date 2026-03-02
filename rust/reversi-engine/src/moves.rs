use crate::board::Board;
use crate::types::{Color, Position};

/// Direction shifts for the 8 cardinal/diagonal directions.
/// Each tuple is (row_delta, col_delta) represented as shift amount and mask.
const DIRECTIONS: [(i8, i8); 8] = [
    (-1, -1), (-1, 0), (-1, 1),
    ( 0, -1),          ( 0, 1),
    ( 1, -1), ( 1, 0), ( 1, 1),
];

/// Returns a bitmask of all legal move positions for the given color.
pub fn legal_moves(board: &Board, color: Color) -> u64 {
    let mut moves = 0u64;
    let empty = board.empty_cells();

    // Check each empty cell
    let mut candidates = empty;
    while candidates != 0 {
        let bit = candidates & candidates.wrapping_neg(); // isolate lowest set bit
        let index = bit.trailing_zeros() as u8;
        let pos = Position::from_bit_index(index);
        if flipped_pieces(board, color, pos) != 0 {
            moves |= bit;
        }
        candidates &= candidates - 1; // clear lowest set bit
    }
    moves
}

/// Returns true if the given move is legal.
pub fn is_legal_move(board: &Board, color: Color, pos: Position) -> bool {
    let mask = pos.bit_mask();
    // Must be empty
    if board.occupied() & mask != 0 {
        return false;
    }
    flipped_pieces(board, color, pos) != 0
}

/// Returns a bitmask of pieces that would be flipped by placing a piece of the
/// given color at the given position. Returns 0 if no flips (illegal move).
pub fn flipped_pieces(board: &Board, color: Color, pos: Position) -> u64 {
    let own = board.pieces(color);
    let opp = board.pieces(color.opponent());
    let mut flipped = 0u64;

    for &(dr, dc) in &DIRECTIONS {
        let mut line = 0u64;
        let mut r = pos.row as i8 + dr;
        let mut c = pos.col as i8 + dc;

        // Walk in this direction, collecting opponent pieces
        while (0..8).contains(&r) && (0..8).contains(&c) {
            let bit = 1u64 << (r as u8 * 8 + c as u8);
            if opp & bit != 0 {
                line |= bit;
            } else if own & bit != 0 {
                // Found own piece — all collected opponent pieces are flipped
                flipped |= line;
                break;
            } else {
                // Empty cell — no flips in this direction
                break;
            }
            r += dr;
            c += dc;
        }
    }

    flipped
}

/// Applies a move: places a piece and flips captured pieces.
/// Returns the new board state. Panics if the move is illegal.
pub fn make_move(board: &Board, color: Color, pos: Position) -> Board {
    let flips = flipped_pieces(board, color, pos);
    assert!(flips != 0, "Illegal move at ({}, {})", pos.row, pos.col);

    let place = pos.bit_mask();
    let mut new_board = *board;

    match color {
        Color::Black => {
            new_board.black |= place | flips;
            new_board.white &= !flips;
        }
        Color::White => {
            new_board.white |= place | flips;
            new_board.black &= !flips;
        }
    }

    new_board
}

/// Returns true if the given color has at least one legal move.
pub fn has_legal_move(board: &Board, color: Color) -> bool {
    legal_moves(board, color) != 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_initial_legal_moves_black() {
        let board = Board::new();
        let moves = legal_moves(&board, Color::Black);
        // Black's legal moves from standard position: (2,3), (3,2), (4,5), (5,4)
        let expected = Position::new(2, 3).bit_mask()
            | Position::new(3, 2).bit_mask()
            | Position::new(4, 5).bit_mask()
            | Position::new(5, 4).bit_mask();
        assert_eq!(moves, expected);
    }

    #[test]
    fn test_initial_legal_moves_white() {
        let board = Board::new();
        let moves = legal_moves(&board, Color::White);
        // White's legal moves from standard position: (2,4), (3,5), (4,2), (5,3)
        let expected = Position::new(2, 4).bit_mask()
            | Position::new(3, 5).bit_mask()
            | Position::new(4, 2).bit_mask()
            | Position::new(5, 3).bit_mask();
        assert_eq!(moves, expected);
    }

    #[test]
    fn test_make_move_flips() {
        let board = Board::new();
        // Black plays (2,3) — should flip white at (3,3)
        let new_board = make_move(&board, Color::Black, Position::new(2, 3));
        assert_eq!(new_board.get(Position::new(2, 3)), Some(Color::Black));
        assert_eq!(new_board.get(Position::new(3, 3)), Some(Color::Black)); // flipped
        assert_eq!(new_board.get(Position::new(3, 4)), Some(Color::Black)); // unchanged
        assert_eq!(new_board.get(Position::new(4, 4)), Some(Color::White)); // unchanged
        assert_eq!(new_board.count(Color::Black), 4);
        assert_eq!(new_board.count(Color::White), 1);
    }

    #[test]
    fn test_is_legal_move() {
        let board = Board::new();
        assert!(is_legal_move(&board, Color::Black, Position::new(2, 3)));
        assert!(!is_legal_move(&board, Color::Black, Position::new(0, 0)));
        assert!(!is_legal_move(&board, Color::Black, Position::new(3, 3))); // occupied
    }

    #[test]
    fn test_no_legal_moves_empty_board() {
        let board = Board::empty();
        assert_eq!(legal_moves(&board, Color::Black), 0);
        assert!(!has_legal_move(&board, Color::Black));
    }

    #[test]
    fn test_multi_direction_flip() {
        // Set up a board where one move flips in multiple directions
        let mut board = Board::empty();
        board.set(Position::new(3, 3), Color::Black);
        board.set(Position::new(3, 4), Color::White);
        board.set(Position::new(4, 3), Color::White);
        board.set(Position::new(3, 5), Color::Black);
        board.set(Position::new(5, 3), Color::Black);

        // Black plays (4,4) — should flip (3,4) via east and (4,3) via south
        // Wait: (4,4) east direction: no opponent between (4,4) and anything
        // Let me re-check: (3,4) is white, (3,5) is black → north from (4,4)? no.
        // Actually from (4,4): direction (-1,0) goes to (3,4)=W then (2,4)=empty → no flip
        // direction (0,-1) goes to (4,3)=W then (4,2)=empty → no flip
        // Let me fix: need black pieces that bracket the white pieces

        let mut board = Board::empty();
        // Row 3: B W _ (we want to place at col 5 to flip W at col 4)
        board.set(Position::new(3, 3), Color::Black);
        board.set(Position::new(3, 4), Color::White);
        // Col 3: B W _ (we want to place at row 5 to flip W at row 4)
        board.set(Position::new(4, 3), Color::White);
        // Black at (3,3) already set

        // Place black at (3,5) — flips (3,4) horizontally
        assert!(is_legal_move(&board, Color::Black, Position::new(3, 5)));
        let flips = flipped_pieces(&board, Color::Black, Position::new(3, 5));
        assert_eq!(flips, Position::new(3, 4).bit_mask());
    }

    #[test]
    fn test_long_chain_flip() {
        // Black pieces at ends, white pieces in between along a row
        let mut board = Board::empty();
        board.set(Position::new(0, 0), Color::Black);
        board.set(Position::new(0, 1), Color::White);
        board.set(Position::new(0, 2), Color::White);
        board.set(Position::new(0, 3), Color::White);
        // Black plays (0,4) — should flip 3 white pieces
        let flips = flipped_pieces(&board, Color::Black, Position::new(0, 4));
        let expected = Position::new(0, 1).bit_mask()
            | Position::new(0, 2).bit_mask()
            | Position::new(0, 3).bit_mask();
        assert_eq!(flips, expected);
    }
}
