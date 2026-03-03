use reversi_engine::board::Board;
use reversi_engine::types::Color;

use crate::config::AiConfig;
use crate::eval::BoardEvaluator;
use crate::explain::{self, MoveExplanation};
use crate::search::{SearchEngine, SearchResult};

/// AI player combining an evaluator with search configuration.
pub struct AiPlayer {
    evaluator: Box<dyn BoardEvaluator>,
    config: AiConfig,
    engine: SearchEngine,
}

impl AiPlayer {
    pub fn new(evaluator: Box<dyn BoardEvaluator>, config: AiConfig) -> Self {
        Self {
            evaluator,
            config,
            engine: SearchEngine::new(),
        }
    }

    /// Run search and return the best move with PV and evaluation.
    pub fn think(&mut self, board: &Board, color: Color) -> SearchResult {
        self.engine.search(board, color, self.evaluator.as_ref(), &self.config)
    }

    /// Run search and generate a human-readable explanation.
    pub fn explain(&mut self, board: &Board, color: Color) -> MoveExplanation {
        let result = self.think(board, color);
        explain::generate_explanation(board, color, &result, self.evaluator.as_ref())
    }

    /// Returns the name of the evaluator.
    pub fn evaluator_name(&self) -> &str {
        self.evaluator.name()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::eval::strategic::StrategicEvaluator;
    use crate::eval::novice::NoviceEvaluator;
    use reversi_engine::moves;

    #[test]
    fn test_ai_player_think() {
        let evaluator = Box::new(StrategicEvaluator::new());
        let config = AiConfig::new(3, 3, 3);
        let mut player = AiPlayer::new(evaluator, config);

        let board = Board::new();
        let result = player.think(&board, Color::Black);

        let legal = moves::legal_moves(&board, Color::Black);
        assert!(legal & result.best_move.bit_mask() != 0);
    }

    #[test]
    fn test_ai_player_explain() {
        let evaluator = Box::new(StrategicEvaluator::new());
        let config = AiConfig::new(3, 3, 3);
        let mut player = AiPlayer::new(evaluator, config);

        let board = Board::new();
        let explanation = player.explain(&board, Color::Black);

        let legal = moves::legal_moves(&board, Color::Black);
        assert!(legal & explanation.best_move.bit_mask() != 0);
        assert!(!explanation.pv.is_empty());
    }

    #[test]
    fn test_strategic_beats_novice() {
        // Play a full game: strategic (black) vs novice (white)
        let mut strategic_player = AiPlayer::new(
            Box::new(StrategicEvaluator::new()),
            AiConfig::new(3, 4, 5),
        );
        let mut novice_player = AiPlayer::new(
            Box::new(NoviceEvaluator::new()),
            AiConfig::new(2, 3, 3),
        );

        let mut game = reversi_engine::game::Game::new();
        let mut pass_count = 0;

        while !game.is_game_over() {
            let board = game.board().clone();
            let color = game.current_turn();

            if !moves::has_legal_move(&board, color) {
                game.pass_turn().unwrap();
                pass_count += 1;
                if pass_count >= 2 {
                    break;
                }
                continue;
            }
            pass_count = 0;

            let result = match color {
                Color::Black => strategic_player.think(&board, color),
                Color::White => novice_player.think(&board, color),
            };

            game.play(result.best_move).unwrap();
        }

        let (black, white) = game.score();
        // Strategic should beat novice
        assert!(
            black > white,
            "Strategic (black={}) should beat novice (white={})",
            black,
            white
        );
    }

    #[test]
    fn test_evaluator_name() {
        let player = AiPlayer::new(
            Box::new(StrategicEvaluator::new()),
            AiConfig::new(1, 1, 1),
        );
        assert_eq!(player.evaluator_name(), "strategic");

        let player = AiPlayer::new(
            Box::new(NoviceEvaluator::new()),
            AiConfig::new(1, 1, 1),
        );
        assert_eq!(player.evaluator_name(), "novice");
    }
}
