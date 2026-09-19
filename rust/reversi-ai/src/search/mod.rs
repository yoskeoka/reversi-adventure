pub mod negascout;
pub mod ordering;
pub mod tt;

use reversi_engine::board::Board;
use reversi_engine::types::{Color, Position};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::{Duration, Instant};

use self::negascout::Negascout;
use self::tt::{TranspositionTable, ZobristKeys};
use crate::config::AiConfig;
use crate::eval::{stable_context_fingerprint, BoardEvaluator, EvalResult};

/// Search result with PV and explanation data.
#[derive(Debug, Clone)]
pub struct SearchResult {
    pub outcome: SearchOutcome,
    pub score: Option<i32>,
    pub pv: Vec<Position>,
    pub leaf_eval: Option<EvalResult>,
    pub completed_depth: u8,
    pub nodes_searched: u64,
    pub elapsed: Duration,
    pub exact: bool,
}

/// Root outcome selected by a bounded search.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SearchOutcome {
    Move(Position),
    Pass,
    GameOver,
}

/// Caller-provided limits for a single search.
#[derive(Debug, Clone)]
pub struct SearchBudget {
    deadline: Instant,
    node_limit: Option<u64>,
    cancellation: Option<Arc<AtomicBool>>,
}

impl SearchBudget {
    pub fn new(deadline: Instant) -> Self {
        Self {
            deadline,
            node_limit: None,
            cancellation: None,
        }
    }

    pub fn with_time_limit(time_limit: Duration) -> Self {
        Self::new(Instant::now() + time_limit)
    }

    pub fn with_node_limit(mut self, node_limit: u64) -> Self {
        self.node_limit = Some(node_limit);
        self
    }

    pub fn with_cancellation(mut self, cancellation: Arc<AtomicBool>) -> Self {
        self.cancellation = Some(cancellation);
        self
    }

    pub(crate) fn interrupted(&self, nodes_searched: u64) -> bool {
        self.cancellation
            .as_ref()
            .is_some_and(|token| token.load(Ordering::Acquire))
            || Instant::now() >= self.deadline
            || self.node_limit.is_some_and(|limit| nodes_searched >= limit)
    }
}

/// Search engine wrapping Negascout with transposition table.
pub struct SearchEngine {
    tt: TranspositionTable,
    zobrist: ZobristKeys,
    context_fingerprint: Option<u64>,
}

const SEARCH_SEMANTICS_VERSION: u64 = 1;

fn search_context_fingerprint<E: BoardEvaluator + ?Sized>(evaluator: &E, config: &AiConfig) -> u64 {
    stable_context_fingerprint(&[
        SEARCH_SEMANTICS_VERSION,
        evaluator.context_fingerprint(),
        config.context_fingerprint(),
    ])
}

impl SearchEngine {
    pub fn new() -> Self {
        Self {
            tt: TranspositionTable::new(1 << 20), // ~1M entries
            zobrist: ZobristKeys::new(),
            context_fingerprint: None,
        }
    }

    /// Run search and return the best move with PV and evaluation.
    pub fn search_with_budget<E: BoardEvaluator + ?Sized>(
        &mut self,
        board: &Board,
        color: Color,
        evaluator: &E,
        config: &AiConfig,
        budget: &SearchBudget,
    ) -> SearchResult {
        let context_fingerprint = search_context_fingerprint(evaluator, config);
        if self.context_fingerprint != Some(context_fingerprint) {
            self.tt.clear();
            self.context_fingerprint = Some(context_fingerprint);
        }

        let stone_count = board.count(Color::Black) + board.count(Color::White);
        let max_depth = config.depth_for_phase(stone_count);

        let mut search = Negascout::new(evaluator, &mut self.tt, &self.zobrist);
        let started = Instant::now();
        let completed = search.search(board, color, max_depth, budget);

        SearchResult {
            outcome: completed.outcome,
            score: completed.score,
            pv: completed.pv,
            leaf_eval: completed.leaf_eval,
            completed_depth: completed.completed_depth,
            nodes_searched: search.nodes_searched(),
            elapsed: started.elapsed(),
            exact: completed.exact,
        }
    }

    /// Run search with a compatibility budget for callers that do not control a turn clock.
    pub fn search<E: BoardEvaluator + ?Sized>(
        &mut self,
        board: &Board,
        color: Color,
        evaluator: &E,
        config: &AiConfig,
    ) -> SearchResult {
        self.search_with_budget(
            board,
            color,
            evaluator,
            config,
            &SearchBudget::with_time_limit(Duration::from_secs(30)),
        )
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
    use crate::eval::{strategic::StrategicEvaluator, EvalFactors};
    use std::sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc,
    };
    use std::time::Duration;

    struct ContextEvaluator {
        score: i32,
        context_fingerprint: u64,
    }

    impl BoardEvaluator for ContextEvaluator {
        fn evaluate(&self, _board: &Board, _color: Color) -> EvalResult {
            EvalResult {
                score: self.score,
                factors: EvalFactors::default(),
            }
        }

        fn name(&self) -> &str {
            "test"
        }

        fn context_fingerprint(&self) -> u64 {
            self.context_fingerprint
        }
    }

    struct CountingEvaluator {
        evaluations: Arc<AtomicUsize>,
    }

    impl BoardEvaluator for CountingEvaluator {
        fn evaluate(&self, _board: &Board, _color: Color) -> EvalResult {
            self.evaluations.fetch_add(1, Ordering::Relaxed);
            EvalResult {
                score: 10,
                factors: EvalFactors::default(),
            }
        }

        fn name(&self) -> &str {
            "counting"
        }

        fn context_fingerprint(&self) -> u64 {
            3
        }
    }

    #[test]
    fn test_search_returns_legal_move() {
        let mut engine = SearchEngine::new();
        let board = Board::new();
        let evaluator = StrategicEvaluator::new();
        let config = AiConfig::new(3, 3, 3);

        let result = engine.search(&board, Color::Black, &evaluator, &config);

        // Verify the returned move is legal
        let legal = reversi_engine::moves::legal_moves(&board, Color::Black);
        assert!(
            matches!(result.outcome, SearchOutcome::Move(position) if legal & position.bit_mask() != 0)
        );
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
        assert!(
            matches!(result.outcome, SearchOutcome::Move(position) if legal & position.bit_mask() != 0)
        );
    }

    #[test]
    fn test_search_clears_tt_when_evaluator_context_changes() {
        let mut engine = SearchEngine::new();
        let board = Board::new();
        let config = AiConfig::new(1, 1, 1);

        let first = engine.search(
            &board,
            Color::Black,
            &ContextEvaluator {
                score: 10,
                context_fingerprint: 1,
            },
            &config,
        );
        let second = engine.search(
            &board,
            Color::Black,
            &ContextEvaluator {
                score: 20,
                context_fingerprint: 2,
            },
            &config,
        );
        let mut fresh_engine = SearchEngine::new();
        let fresh = fresh_engine.search(
            &board,
            Color::Black,
            &ContextEvaluator {
                score: 20,
                context_fingerprint: 2,
            },
            &config,
        );

        assert_ne!(first.score, second.score);
        assert_eq!(second.score, fresh.score);
    }

    #[test]
    fn test_search_clears_tt_when_search_config_changes() {
        let board = Board::new();
        let first_config = AiConfig::new(1, 1, 1);
        let second_config = AiConfig::new(1, 2, 1);
        let evaluations = Arc::new(AtomicUsize::new(0));
        let mut engine = SearchEngine::new();

        engine.search(
            &board,
            Color::Black,
            &CountingEvaluator {
                evaluations: Arc::clone(&evaluations),
            },
            &first_config,
        );
        evaluations.store(0, Ordering::Relaxed);
        let second = engine.search(
            &board,
            Color::Black,
            &CountingEvaluator {
                evaluations: Arc::clone(&evaluations),
            },
            &second_config,
        );
        let second_evaluations = evaluations.load(Ordering::Relaxed);

        let fresh_evaluations = Arc::new(AtomicUsize::new(0));
        let mut fresh_engine = SearchEngine::new();
        let fresh = fresh_engine.search(
            &board,
            Color::Black,
            &CountingEvaluator {
                evaluations: Arc::clone(&fresh_evaluations),
            },
            &second_config,
        );

        assert_eq!(second.score, fresh.score);
        assert_eq!(
            second_evaluations,
            fresh_evaluations.load(Ordering::Relaxed)
        );
        assert!(second_evaluations > 1);
    }

    #[test]
    fn test_search_context_includes_each_phase_depth() {
        let base = AiConfig::new(1, 2, 3).context_fingerprint();

        assert_ne!(base, AiConfig::new(2, 2, 3).context_fingerprint());
        assert_ne!(base, AiConfig::new(1, 3, 3).context_fingerprint());
        assert_ne!(base, AiConfig::new(1, 2, 4).context_fingerprint());
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
            assert_eq!(result.outcome, SearchOutcome::Move(Position::new(0, 0)));
        }
    }

    #[test]
    fn interrupted_before_depth_one_returns_legal_fallback_without_score() {
        let board = Board::new();
        let evaluator = StrategicEvaluator::new();
        let config = AiConfig::new(3, 3, 3);
        let result = SearchEngine::new().search_with_budget(
            &board,
            Color::Black,
            &evaluator,
            &config,
            &SearchBudget::with_time_limit(Duration::from_secs(1)).with_node_limit(0),
        );

        let legal = reversi_engine::moves::legal_moves(&board, Color::Black);
        assert!(
            matches!(result.outcome, SearchOutcome::Move(position) if legal & position.bit_mask() != 0)
        );
        assert!(result.pv.is_empty());
        assert_eq!(result.score, None);
        assert_eq!(result.completed_depth, 0);
        assert!(!result.exact);
    }

    #[test]
    fn cancellation_returns_the_documented_fallback() {
        let board = Board::new();
        let evaluator = StrategicEvaluator::new();
        let cancelled = Arc::new(AtomicBool::new(true));
        let result = SearchEngine::new().search_with_budget(
            &board,
            Color::Black,
            &evaluator,
            &AiConfig::new(3, 3, 3),
            &SearchBudget::with_time_limit(Duration::from_secs(1)).with_cancellation(cancelled),
        );

        assert_eq!(result.completed_depth, 0);
        assert!(result.score.is_none());
        assert!(result.pv.is_empty());
    }

    #[test]
    fn expired_deadline_returns_the_documented_fallback() {
        let board = Board::new();
        let evaluator = StrategicEvaluator::new();
        let result = SearchEngine::new().search_with_budget(
            &board,
            Color::Black,
            &evaluator,
            &AiConfig::new(3, 3, 3),
            &SearchBudget::new(Instant::now()),
        );

        assert_eq!(result.completed_depth, 0);
        assert!(result.score.is_none());
        assert!(result.pv.is_empty());
        assert!(!result.exact);
    }

    #[test]
    fn no_move_states_are_explicit() {
        let evaluator = StrategicEvaluator::new();
        let config = AiConfig::new(3, 3, 3);
        let budget = SearchBudget::with_time_limit(Duration::from_secs(1));
        let mut pass_board = Board::empty();
        pass_board.set(Position::new(0, 0), Color::Black);
        pass_board.set(Position::new(0, 1), Color::White);

        let pass = SearchEngine::new().search_with_budget(
            &pass_board,
            Color::White,
            &evaluator,
            &config,
            &budget,
        );
        let game_over = SearchEngine::new().search_with_budget(
            &Board::empty(),
            Color::Black,
            &evaluator,
            &config,
            &budget,
        );

        assert_eq!(pass.outcome, SearchOutcome::Pass);
        assert_eq!(game_over.outcome, SearchOutcome::GameOver);
        assert!(pass.score.is_none() && game_over.score.is_none());
    }

    #[test]
    fn fixed_node_limit_is_deterministic() {
        let board = Board::new();
        let evaluator = StrategicEvaluator::new();
        let config = AiConfig::new(4, 4, 4);
        let run = || {
            SearchEngine::new().search_with_budget(
                &board,
                Color::Black,
                &evaluator,
                &config,
                &SearchBudget::with_time_limit(Duration::from_secs(1)).with_node_limit(20),
            )
        };

        let first = run();
        let second = run();
        assert_eq!(first.outcome, second.outcome);
        assert_eq!(first.pv, second.pv);
        assert_eq!(first.completed_depth, second.completed_depth);
        assert_eq!(first.nodes_searched, second.nodes_searched);
    }
}
