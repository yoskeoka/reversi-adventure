pub mod negascout;
pub mod ordering;
pub mod tt;

use reversi_engine::board::Board;
use reversi_engine::types::{Color, Position};

use crate::config::AiConfig;
use crate::eval::{BoardEvaluator, EvalResult};
use self::negascout::Negascout;
use self::tt::{TranspositionTable, ZobristKeys};

/// Search result with PV and explanation data.
#[derive(Debug, Clone)]
pub struct SearchResult {
    pub best_move: Position,
    pub score: i32,
    pub pv: Vec<Position>,
    pub leaf_eval: EvalResult,
}

/// Search engine wrapping Negascout with transposition table.
pub struct SearchEngine {
    tt: TranspositionTable,
    zobrist: ZobristKeys,
}

impl SearchEngine {
    pub fn new() -> Self {
        Self {
            tt: TranspositionTable::new(1 << 20), // ~1M entries
            zobrist: ZobristKeys::new(),
        }
    }

    /// Run search and return the best move with PV and evaluation.
    pub fn search<E: BoardEvaluator + ?Sized>(
        &mut self,
        board: &Board,
        color: Color,
        evaluator: &E,
        config: &AiConfig,
    ) -> SearchResult {
        let stone_count = board.count(Color::Black) + board.count(Color::White);
        let max_depth = config.depth_for_phase(stone_count);

        let mut search = Negascout::new(evaluator, &mut self.tt, &self.zobrist);
        let (best_move, score, pv, leaf_eval) = search.search(board, color, max_depth);

        SearchResult {
            best_move,
            score,
            pv,
            leaf_eval,
        }
    }

    /// Clear the transposition table.
    pub fn clear_tt(&mut self) {
        self.tt.clear();
    }
}

impl Default for SearchEngine {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::eval::strategic::StrategicEvaluator;

    #[test]
    fn test_search_returns_legal_move() {
        let mut engine = SearchEngine::new();
        let board = Board::new();
        let evaluator = StrategicEvaluator::new();
        let config = AiConfig::new(3, 3, 3);

        let result = engine.search(&board, Color::Black, &evaluator, &config);

        // Verify the returned move is legal
        let legal = reversi_engine::moves::legal_moves(&board, Color::Black);
        assert!(legal & result.best_move.bit_mask() != 0);
    }

    #[test]
    fn test_search_pv_not_empty() {
        let mut engine = SearchEngine::new();
        let board = Board::new();
        let evaluator = StrategicEvaluator::new();
        let config = AiConfig::new(3, 3, 3);

        let result = engine.search(&board, Color::Black, &evaluator, &config);
        assert!(!result.pv.is_empty());
    }

    #[test]
    fn test_search_depth_1() {
        let mut engine = SearchEngine::new();
        let board = Board::new();
        let evaluator = StrategicEvaluator::new();
        let config = AiConfig::new(1, 1, 1);

        let result = engine.search(&board, Color::Black, &evaluator, &config);
        let legal = reversi_engine::moves::legal_moves(&board, Color::Black);
        assert!(legal & result.best_move.bit_mask() != 0);
    }

    #[test]
    fn test_search_takes_corner_when_available() {
        let mut board = Board::empty();
        // Set up position where corner A1 is available and clearly best
        board.set(Position::new(0, 1), Color::White);
        board.set(Position::new(0, 2), Color::Black);
        board.set(Position::new(1, 0), Color::White);
        board.set(Position::new(2, 0), Color::Black);
        // Add some pieces in the center to make the game non-trivial
        board.set(Position::new(3, 3), Color::White);
        board.set(Position::new(3, 4), Color::Black);
        board.set(Position::new(4, 3), Color::Black);
        board.set(Position::new(4, 4), Color::White);

        let mut engine = SearchEngine::new();
        let evaluator = StrategicEvaluator::new();
        let config = AiConfig::new(4, 4, 4);

        let legal = reversi_engine::moves::legal_moves(&board, Color::Black);
        if legal & 1 != 0 {
            // Corner A1 is legal
            let result = engine.search(&board, Color::Black, &evaluator, &config);
            assert_eq!(result.best_move, Position::new(0, 0));
        }
    }
}
