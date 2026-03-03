use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::{Color, Position};

/// Static positional weight table (higher = more desirable position).
/// Corners are highest, X-squares are lowest.
#[rustfmt::skip]
const POSITION_WEIGHTS: [i32; 64] = [
    120, -20,  20,   5,   5,  20, -20, 120,
    -20, -40,  -5,  -5,  -5,  -5, -40, -20,
     20,  -5,  15,   3,   3,  15,  -5,  20,
      5,  -5,   3,   3,   3,   3,  -5,   5,
      5,  -5,   3,   3,   3,   3,  -5,   5,
     20,  -5,  15,   3,   3,  15,  -5,  20,
    -20, -40,  -5,  -5,  -5,  -5, -40, -20,
    120, -20,  20,   5,   5,  20, -20, 120,
];

/// Corner positions (bit indices).
const CORNERS: [u8; 4] = [0, 7, 56, 63];

/// Order moves for maximum pruning efficiency.
/// Returns positions sorted by priority (best first).
pub fn order_moves(
    board: &Board,
    color: Color,
    moves_mask: u64,
    tt_move: Option<Position>,
) -> Vec<Position> {
    let mut scored_moves: Vec<(Position, i32)> = Vec::new();

    let mut bits = moves_mask;
    while bits != 0 {
        let index = bits.trailing_zeros() as u8;
        let pos = Position::from_bit_index(index);
        let bit = 1u64 << index;

        let mut priority = 0i32;

        // Highest priority: TT best move
        if let Some(tt) = tt_move {
            if tt.row == pos.row && tt.col == pos.col {
                priority += 10000;
            }
        }

        // Corner moves
        if CORNERS.contains(&index) {
            priority += 5000;
        }

        // Opponent mobility after this move (fewer = better)
        let new_board = moves::make_move(board, color, pos);
        let opp_mobility = moves::legal_moves(&new_board, color.opponent()).count_ones() as i32;
        priority -= opp_mobility * 100;

        // Static positional value
        priority += POSITION_WEIGHTS[index as usize];

        scored_moves.push((pos, priority));

        bits &= !bit;
    }

    // Sort descending by priority
    scored_moves.sort_by(|a, b| b.1.cmp(&a.1));
    scored_moves.into_iter().map(|(pos, _)| pos).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_corner_prioritized() {
        let mut board = Board::empty();
        // Set up a position where corner A1 (0,0) is a legal move
        board.set(Position::new(0, 1), Color::White);
        board.set(Position::new(0, 2), Color::Black);
        // Also make another move legal
        board.set(Position::new(1, 0), Color::White);
        board.set(Position::new(2, 0), Color::Black);

        let legal = moves::legal_moves(&board, Color::Black);
        if legal & 1 != 0 {
            // Corner is legal
            let ordered = order_moves(&board, Color::Black, legal, None);
            // Corner should be first
            assert_eq!(ordered[0], Position::new(0, 0));
        }
    }

    #[test]
    fn test_tt_move_first() {
        let board = Board::new();
        let legal = moves::legal_moves(&board, Color::Black);
        let tt_move = Position::new(2, 3); // D3
        let ordered = order_moves(&board, Color::Black, legal, Some(tt_move));
        assert_eq!(ordered[0], tt_move);
    }

    #[test]
    fn test_position_weights_corners_highest() {
        assert_eq!(POSITION_WEIGHTS[0], 120);   // A1
        assert_eq!(POSITION_WEIGHTS[7], 120);   // H1
        assert_eq!(POSITION_WEIGHTS[56], 120);  // A8
        assert_eq!(POSITION_WEIGHTS[63], 120);  // H8
    }

    #[test]
    fn test_position_weights_x_squares_lowest() {
        assert_eq!(POSITION_WEIGHTS[9], -40);   // B2 (X-square of A1)
        assert_eq!(POSITION_WEIGHTS[14], -40);  // G2 (X-square of H1)
        assert_eq!(POSITION_WEIGHTS[49], -40);  // B7 (X-square of A8)
        assert_eq!(POSITION_WEIGHTS[54], -40);  // G7 (X-square of H8)
    }
}
