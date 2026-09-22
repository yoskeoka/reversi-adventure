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

/// A move and, when full ordering was used, the successor it already generated.
#[derive(Clone, Copy)]
pub(crate) struct OrderedMove {
    pub position: Position,
    pub successor: Option<Board>,
}

/// Order moves for maximum pruning efficiency.
/// Returns positions sorted by priority (best first).
/// `depth` controls how expensive the ordering heuristics are:
/// - depth >= 3: full ordering with opponent mobility calculation
/// - depth < 3: lightweight ordering using only static weights and TT/corner bonuses
pub fn order_moves(
    board: &Board,
    color: Color,
    moves_mask: u64,
    tt_move: Option<Position>,
    depth: u8,
) -> Vec<Position> {
    order_moves_with_successors(board, color, moves_mask, tt_move, depth)
        .into_iter()
        .map(|ordered| ordered.position)
        .collect()
}

/// Order moves and retain successors already needed for full mobility ordering.
///
/// This is internal to heuristic Negascout. Exact endgame solving continues to
/// use `order_moves`, so its cache and tie-break behavior remain isolated.
pub(crate) fn order_moves_with_successors(
    board: &Board,
    color: Color,
    moves_mask: u64,
    tt_move: Option<Position>,
    depth: u8,
) -> Vec<OrderedMove> {
    let mut scored_moves: Vec<(OrderedMove, i32)> =
        Vec::with_capacity(moves_mask.count_ones() as usize);

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
        // Only compute at depth >= 3 to avoid expensive make_move + legal_moves at leaf-adjacent nodes
        let successor = if depth >= 3 {
            let new_board = moves::make_move(board, color, pos);
            let opp_mobility = moves::legal_moves(&new_board, color.opponent()).count_ones() as i32;
            priority -= opp_mobility * 100;
            Some(new_board)
        } else {
            None
        };

        // Static positional value
        priority += POSITION_WEIGHTS[index as usize];

        scored_moves.push((
            OrderedMove {
                position: pos,
                successor,
            },
            priority,
        ));

        bits &= !bit;
    }

    // Sort descending by priority
    scored_moves.sort_by_key(|entry| std::cmp::Reverse(entry.1));
    scored_moves
        .into_iter()
        .map(|(ordered, _)| ordered)
        .collect()
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
            let ordered = order_moves(&board, Color::Black, legal, None, 4);
            // Corner should be first
            assert_eq!(ordered[0], Position::new(0, 0));
        }
    }

    #[test]
    fn test_tt_move_first() {
        let board = Board::new();
        let legal = moves::legal_moves(&board, Color::Black);
        let tt_move = Position::new(2, 3); // D3
        let ordered = order_moves(&board, Color::Black, legal, Some(tt_move), 4);
        assert_eq!(ordered[0], tt_move);
    }

    #[test]
    fn test_position_weights_corners_highest() {
        assert_eq!(POSITION_WEIGHTS[0], 120); // A1
        assert_eq!(POSITION_WEIGHTS[7], 120); // H1
        assert_eq!(POSITION_WEIGHTS[56], 120); // A8
        assert_eq!(POSITION_WEIGHTS[63], 120); // H8
    }

    #[test]
    fn test_position_weights_x_squares_lowest() {
        assert_eq!(POSITION_WEIGHTS[9], -40); // B2 (X-square of A1)
        assert_eq!(POSITION_WEIGHTS[14], -40); // G2 (X-square of H1)
        assert_eq!(POSITION_WEIGHTS[49], -40); // B7 (X-square of A8)
        assert_eq!(POSITION_WEIGHTS[54], -40); // G7 (X-square of H8)
    }

    #[test]
    fn full_ordering_retains_the_same_successors_used_by_search() {
        let board = Board::new();
        let legal = moves::legal_moves(&board, Color::Black);
        let ordered = order_moves_with_successors(&board, Color::Black, legal, None, 3);

        assert_eq!(
            ordered
                .iter()
                .map(|entry| entry.position)
                .collect::<Vec<_>>(),
            order_moves(&board, Color::Black, legal, None, 3)
        );
        for entry in ordered {
            assert_eq!(
                entry.successor,
                Some(moves::make_move(&board, Color::Black, entry.position))
            );
        }
    }

    #[test]
    fn lightweight_ordering_does_not_precompute_successors() {
        let board = Board::new();
        let legal = moves::legal_moves(&board, Color::Black);
        assert!(
            order_moves_with_successors(&board, Color::Black, legal, None, 2)
                .iter()
                .all(|entry| entry.successor.is_none())
        );
    }
}
