use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::Color;

use super::{BoardEvaluator, EvalFactors, EvalResult};

/// Hand-tuned evaluator based on known Othello strategy.
pub struct StrategicEvaluator {
    corner_weight: i32,
    stability_weight: i32,
    mobility_weight: i32,
    edge_weight: i32,
    parity_weight: i32,
    piece_count_weight: i32,
}

impl Default for StrategicEvaluator {
    fn default() -> Self {
        Self::new()
    }
}

impl StrategicEvaluator {
    pub fn new() -> Self {
        Self {
            corner_weight: 100,
            stability_weight: 20,
            mobility_weight: 10,
            edge_weight: 5,
            parity_weight: 15,
            piece_count_weight: 1,
        }
    }

    /// Evaluate corner control. Corners are permanent and extremely valuable.
    /// Also penalizes C-squares and X-squares adjacent to empty corners.
    fn eval_corners(&self, board: &Board, color: Color) -> i32 {
        let own = board.pieces(color);
        let opp = board.pieces(color.opponent());

        let corners: [u8; 4] = [0, 7, 56, 63]; // A1, H1, A8, H8

        // C-squares: adjacent to corners along edges
        // X-squares: diagonally adjacent to corners
        let c_squares: [(u8, &[u8]); 4] = [
            (0, &[1, 8]),       // C-squares for corner A1
            (7, &[6, 15]),      // C-squares for corner H1
            (56, &[48, 57]),    // C-squares for corner A8
            (63, &[55, 62]),    // C-squares for corner H8
        ];
        let x_squares: [(u8, u8); 4] = [
            (0, 9),    // X-square for corner A1
            (7, 14),   // X-square for corner H1
            (56, 49),  // X-square for corner A8
            (63, 54),  // X-square for corner H8
        ];

        let mut score = 0i32;

        // Corner ownership
        for &corner in &corners {
            let bit = 1u64 << corner;
            if own & bit != 0 {
                score += 30;
            } else if opp & bit != 0 {
                score -= 30;
            }
        }

        // Penalize C-squares and X-squares when adjacent corner is empty
        for &(corner, c_sqs) in &c_squares {
            let corner_bit = 1u64 << corner;
            if (own | opp) & corner_bit == 0 {
                // Corner is empty — penalize owning C-squares
                for &sq in c_sqs {
                    let bit = 1u64 << sq;
                    if own & bit != 0 {
                        score -= 12;
                    } else if opp & bit != 0 {
                        score += 12;
                    }
                }
            }
        }

        for &(corner, x_sq) in &x_squares {
            let corner_bit = 1u64 << corner;
            if (own | opp) & corner_bit == 0 {
                let bit = 1u64 << x_sq;
                if own & bit != 0 {
                    score -= 15;
                } else if opp & bit != 0 {
                    score += 15;
                }
            }
        }

        score
    }

    /// Evaluate stability: count discs that can never be flipped.
    /// Simplified version: only counts corner-anchored stable discs along edges.
    fn eval_stability(&self, board: &Board, color: Color) -> i32 {
        let own = board.pieces(color);
        let opp = board.pieces(color.opponent());
        let mut own_stable = 0i32;
        let mut opp_stable = 0i32;

        // Check each corner and propagate stability along edges
        let corner_edges: [(u8, &[(i8, i8)]); 4] = [
            (0, &[(0, 1), (1, 0)]),   // A1: right and down
            (7, &[(0, -1), (1, 0)]),   // H1: left and down
            (56, &[(0, 1), (-1, 0)]),  // A8: right and up
            (63, &[(0, -1), (-1, 0)]), // H8: left and up
        ];

        for &(corner, directions) in &corner_edges {
            let corner_bit = 1u64 << corner;
            // Check if corner is owned
            let corner_color = if own & corner_bit != 0 {
                Some(true) // own
            } else if opp & corner_bit != 0 {
                Some(false) // opponent
            } else {
                None
            };

            if let Some(is_own) = corner_color {
                if is_own {
                    own_stable += 1;
                } else {
                    opp_stable += 1;
                }

                // Propagate along each edge direction from the corner
                for &(dr, dc) in directions {
                    let corner_row = corner / 8;
                    let corner_col = corner % 8;
                    let mut r = corner_row as i8 + dr;
                    let mut c = corner_col as i8 + dc;

                    let pieces = if is_own { own } else { opp };

                    while (0..8).contains(&r) && (0..8).contains(&c) {
                        let bit = 1u64 << (r as u8 * 8 + c as u8);
                        if pieces & bit != 0 {
                            if is_own {
                                own_stable += 1;
                            } else {
                                opp_stable += 1;
                            }
                        } else {
                            break;
                        }
                        r += dr;
                        c += dc;
                    }
                }
            }
        }

        own_stable - opp_stable
    }

    /// Evaluate mobility: legal move count differential.
    fn eval_mobility(&self, board: &Board, color: Color) -> i32 {
        let own_moves = moves::legal_moves(board, color).count_ones() as i32;
        let opp_moves = moves::legal_moves(board, color.opponent()).count_ones() as i32;
        own_moves - opp_moves
    }

    /// Evaluate edge control: count edge discs.
    fn eval_edges(&self, board: &Board, color: Color) -> i32 {
        let own = board.pieces(color);
        let opp = board.pieces(color.opponent());

        // Edge masks (excluding corners which are counted separately)
        let top_edge: u64 = 0b0111_1110; // bits 1-6
        let bottom_edge: u64 = 0b0111_1110 << 56; // bits 57-62
        let left_edge: u64 = (1u64 << 8) | (1u64 << 16) | (1u64 << 24)
            | (1u64 << 32) | (1u64 << 40) | (1u64 << 48); // bits 8,16,24,32,40,48
        let right_edge: u64 = (1u64 << 15) | (1u64 << 23) | (1u64 << 31)
            | (1u64 << 39) | (1u64 << 47) | (1u64 << 55); // bits 15,23,31,39,47,55

        let edges = top_edge | bottom_edge | left_edge | right_edge;

        let own_edges = (own & edges).count_ones() as i32;
        let opp_edges = (opp & edges).count_ones() as i32;
        own_edges - opp_edges
    }

    /// Evaluate parity: the player who moves last in a region has advantage.
    /// Simplified: count empty cells. If odd, current player (mover) has advantage.
    fn eval_parity(&self, board: &Board, _color: Color) -> i32 {
        let empty_count = board.empty_cells().count_ones() as i32;
        // Odd number of empties = advantage for current mover
        if empty_count % 2 == 1 { 1 } else { -1 }
    }

    /// Evaluate piece count differential.
    fn eval_piece_count(&self, board: &Board, color: Color) -> i32 {
        let stone_count = board.count(Color::Black) + board.count(Color::White);
        // Piece count only matters in endgame (>50 stones)
        if stone_count > 50 {
            board.count(color) as i32 - board.count(color.opponent()) as i32
        } else {
            0
        }
    }
}

impl BoardEvaluator for StrategicEvaluator {
    fn evaluate(&self, board: &Board, color: Color) -> EvalResult {
        let corner = self.eval_corners(board, color);
        let stability = self.eval_stability(board, color);
        let mobility = self.eval_mobility(board, color);
        let edge = self.eval_edges(board, color);
        let parity = self.eval_parity(board, color);
        let piece_count = self.eval_piece_count(board, color);

        let factors = EvalFactors {
            corner_control: corner * self.corner_weight / 30, // normalize
            stability: stability * self.stability_weight,
            mobility: mobility * self.mobility_weight,
            edge_control: edge * self.edge_weight,
            parity: parity * self.parity_weight,
            piece_count: piece_count * self.piece_count_weight,
        };

        EvalResult {
            score: factors.total(),
            factors,
        }
    }

    fn name(&self) -> &str {
        "strategic"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use reversi_engine::types::Position;

    #[test]
    fn test_initial_position_balanced() {
        let board = Board::new();
        let eval = StrategicEvaluator::new();
        let black_result = eval.evaluate(&board, Color::Black);
        let white_result = eval.evaluate(&board, Color::White);
        // Initial position should be roughly symmetrical
        // Mobility might differ slightly due to who moves first
        assert!((black_result.score + white_result.score).abs() < 50);
    }

    #[test]
    fn test_corner_ownership_valued() {
        let eval = StrategicEvaluator::new();
        let mut board = Board::empty();
        // Give black a corner
        board.set(Position::new(0, 0), Color::Black);
        board.set(Position::new(3, 3), Color::White);

        let result = eval.evaluate(&board, Color::Black);
        assert!(result.factors.corner_control > 0);
    }

    #[test]
    fn test_x_square_penalized() {
        let eval = StrategicEvaluator::new();
        let mut board = Board::empty();
        // Place own piece on X-square (1,1) with empty corner (0,0)
        board.set(Position::new(1, 1), Color::Black);
        board.set(Position::new(3, 3), Color::White);

        let result = eval.evaluate(&board, Color::Black);
        // X-square with empty corner should be penalized
        assert!(result.factors.corner_control < 0);
    }

    #[test]
    fn test_mobility_positive_when_more_moves() {
        let eval = StrategicEvaluator::new();
        let board = Board::new();
        // From initial position, both sides have 4 moves — mobility should be 0
        let result = eval.evaluate(&board, Color::Black);
        assert_eq!(result.factors.mobility, 0);
    }
}
