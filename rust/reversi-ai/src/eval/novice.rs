use reversi_engine::board::Board;
use reversi_engine::types::Color;

use super::{BoardEvaluator, EvalFactors, EvalResult};

/// Evaluator simulating a beginner player who doesn't know Othello strategy.
pub struct NoviceEvaluator {
    seed: u64,
}

impl Default for NoviceEvaluator {
    fn default() -> Self {
        Self::new()
    }
}

impl NoviceEvaluator {
    pub fn new() -> Self {
        Self { seed: 12345 }
    }

    pub fn with_seed(seed: u64) -> Self {
        Self { seed }
    }

    /// Simple pseudo-random number for score perturbation.
    fn random_perturbation(&self, board: &Board) -> i32 {
        // Use board state as additional entropy
        let hash = board.pieces(Color::Black)
            .wrapping_mul(0x9E3779B97F4A7C15)
            ^ board.pieces(Color::White)
                .wrapping_mul(0x517CC1B727220A95)
            ^ self.seed;
        // Map to small range [-3, 3]
        ((hash % 7) as i32) - 3
    }
}

impl BoardEvaluator for NoviceEvaluator {
    fn evaluate(&self, board: &Board, color: Color) -> EvalResult {
        let own_count = board.count(color) as i32;
        let opp_count = board.count(color.opponent()) as i32;
        let piece_diff = own_count - opp_count;

        // Novice heavily values piece count
        let piece_score = piece_diff * 10;

        // Novice grabs edges eagerly (doesn't understand C/X-square danger)
        let own = board.pieces(color);
        let opp = board.pieces(color.opponent());

        let all_edges: u64 = 0xFF | (0xFF << 56)
            | 0x0101_0101_0101_0101
            | 0x8080_8080_8080_8080;
        let edge_score = ((own & all_edges).count_ones() as i32
            - (opp & all_edges).count_ones() as i32) * 5;

        let noise = self.random_perturbation(board);

        let factors = EvalFactors {
            corner_control: 0,    // novice doesn't think about corners specifically
            stability: 0,         // novice doesn't understand stability
            mobility: 0,          // novice ignores mobility
            edge_control: edge_score,
            parity: 0,            // novice doesn't understand parity
            piece_count: piece_score,
        };

        EvalResult {
            score: factors.total() + noise,
            factors,
        }
    }

    fn name(&self) -> &str {
        "novice"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use reversi_engine::types::Position;

    #[test]
    fn test_novice_values_piece_count() {
        let eval = NoviceEvaluator::new();
        let mut board = Board::empty();
        // Black has 3 pieces, white has 1
        board.set(Position::new(0, 0), Color::Black);
        board.set(Position::new(0, 1), Color::Black);
        board.set(Position::new(0, 2), Color::Black);
        board.set(Position::new(4, 4), Color::White);

        let result = eval.evaluate(&board, Color::Black);
        // piece_count should dominate: (3-1)*10 = 20
        assert!(result.factors.piece_count > 0);
    }

    #[test]
    fn test_novice_ignores_mobility() {
        let eval = NoviceEvaluator::new();
        let board = Board::new();
        let result = eval.evaluate(&board, Color::Black);
        assert_eq!(result.factors.mobility, 0);
    }

    #[test]
    fn test_novice_ignores_stability() {
        let eval = NoviceEvaluator::new();
        let board = Board::new();
        let result = eval.evaluate(&board, Color::Black);
        assert_eq!(result.factors.stability, 0);
    }
}
