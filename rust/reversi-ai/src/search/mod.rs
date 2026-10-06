pub mod endgame;
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

use self::endgame::{EndgameSolver, ExactCacheDiagnostics, ExactPvsDiagnostics, ExactTable};
use self::negascout::Negascout;
use self::tt::{TranspositionTable, ZobristKeys};
use crate::config::{AiConfig, DecisionMoveConfig};
use crate::eval::{stable_context_fingerprint, BoardEvaluator, EvalResult};
use reversi_engine::moves;

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
    pub exact_pvs: ExactPvsDiagnostics,
    pub exact_cache: ExactCacheDiagnostics,
}

/// Root outcome selected by a bounded search.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SearchOutcome {
    Move(Position),
    Pass,
    GameOver,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnalysisScore {
    pub position: Position,
    pub value: i32,
    pub completed_depth: u8,
    pub exact: bool,
}

#[derive(Debug, Clone)]
pub struct AnalysisResult {
    pub outcome: SearchOutcome,
    pub completed_depth: u8,
    pub exact: bool,
    pub scores: Vec<AnalysisScore>,
    pub config_id: String,
}

/// Caller-provided limits for a single search.
#[derive(Debug, Clone)]
pub struct SearchBudget {
    deadline: Option<Instant>,
    node_limit: Option<u64>,
    cancellation: Option<Arc<AtomicBool>>,
}

impl SearchBudget {
    pub fn new(deadline: Instant) -> Self {
        Self {
            deadline: Some(deadline),
            node_limit: None,
            cancellation: None,
        }
    }

    pub fn with_time_limit(time_limit: Duration) -> Self {
        let now = Instant::now();
        Self::new(now.checked_add(time_limit).unwrap_or(now))
    }

    pub fn with_node_limit(mut self, node_limit: u64) -> Self {
        self.node_limit = Some(node_limit);
        self
    }

    /// Create a deterministic diagnostics budget with only a node ceiling.
    ///
    /// Product callers should use `with_time_limit` so a turn always has a
    /// monotonic deadline. This mode is for reproducible profiling and tests.
    pub fn with_node_limit_only(node_limit: u64) -> Self {
        Self {
            deadline: None,
            node_limit: Some(node_limit),
            cancellation: None,
        }
    }

    pub fn with_cancellation(mut self, cancellation: Arc<AtomicBool>) -> Self {
        self.cancellation = Some(cancellation);
        self
    }

    pub(crate) fn interrupted(&self, nodes_searched: u64) -> bool {
        self.cancellation
            .as_ref()
            .is_some_and(|token| token.load(Ordering::Acquire))
            || self
                .deadline
                .is_some_and(|deadline| Instant::now() >= deadline)
            || self.node_limit.is_some_and(|limit| nodes_searched >= limit)
    }

    pub(crate) fn interrupted_after_completion(&self) -> bool {
        self.cancellation
            .as_ref()
            .is_some_and(|token| token.load(Ordering::Acquire))
            || self
                .deadline
                .is_some_and(|deadline| Instant::now() >= deadline)
    }
}

/// Search engine wrapping Negascout with transposition table.
pub struct SearchEngine {
    tt: TranspositionTable,
    exact_table: ExactTable,
    zobrist: ZobristKeys,
    context_fingerprint: Option<u64>,
    diagnostic_game_exact_cache: bool,
}

const SEARCH_SEMANTICS_VERSION: u64 = 1;

fn search_context_fingerprint<E: BoardEvaluator + ?Sized>(evaluator: &E, config: &AiConfig) -> u64 {
    stable_context_fingerprint(&[
        SEARCH_SEMANTICS_VERSION,
        evaluator.context_fingerprint(),
        config.context_fingerprint(),
    ])
}

fn advisor_identity<E: BoardEvaluator + ?Sized>(
    evaluator: &E,
    config: &DecisionMoveConfig,
) -> (u64, String) {
    let fingerprint = stable_context_fingerprint(&[
        SEARCH_SEMANTICS_VERSION,
        evaluator.context_fingerprint(),
        config.context_fingerprint(),
    ]);
    (
        fingerprint,
        format!("project-ai-advisor-v1:{fingerprint:016x}"),
    )
}

impl SearchEngine {
    /// Return the exact identity emitted by advisor analysis for these settings.
    pub fn advisor_config_id<E: BoardEvaluator + ?Sized>(
        evaluator: &E,
        config: &DecisionMoveConfig,
    ) -> String {
        advisor_identity(evaluator, config).1
    }

    pub fn analyze_with_budget<E: BoardEvaluator + ?Sized>(
        &mut self,
        board: &Board,
        color: Color,
        evaluator: &E,
        config: &DecisionMoveConfig,
        budget: &SearchBudget,
    ) -> Result<AnalysisResult, String> {
        // Suspend reuse across decisions while retaining reuse within this call.
        self.exact_table.clear();
        let (fingerprint, config_id) = advisor_identity(evaluator, config);
        if self.context_fingerprint != Some(fingerprint) {
            self.tt.clear();
            self.context_fingerprint = Some(fingerprint);
        }
        let legal = moves::legal_moves(board, color);
        if legal == 0 {
            let outcome = if moves::has_legal_move(board, color.opponent()) {
                SearchOutcome::Pass
            } else {
                SearchOutcome::GameOver
            };
            return Ok(AnalysisResult {
                outcome,
                completed_depth: 0,
                exact: false,
                scores: Vec::new(),
                config_id,
            });
        }
        let empty = board.empty_cells().count_ones();
        let (completed_depth, scores) = if empty <= config.exact_solver_empty_squares {
            let mut nodes = 0;
            let mut solver = EndgameSolver::new(&self.zobrist, &mut self.exact_table, &mut nodes);
            let scores = solver.analyze_all(board, color, budget).map_err(|_| {
                "advisor exact analysis did not complete all legal moves".to_string()
            })?;
            (empty as u8, scores)
        } else {
            let stones = board.count(Color::Black) + board.count(Color::White);
            let depth = config.depth_for_stones(stones);
            let mut search = Negascout::new(evaluator, &mut self.tt, &self.zobrist);
            search
                .analyze_all(board, color, depth, budget)
                .map_err(|_| "advisor analysis did not complete a full depth".to_string())?
        };
        let exact = scores.iter().all(|score| score.exact);
        Ok(AnalysisResult {
            outcome: SearchOutcome::Move(scores[0].position),
            completed_depth,
            exact,
            scores,
            config_id,
        })
    }
    pub fn new() -> Self {
        Self {
            tt: TranspositionTable::new(1 << 20), // ~1M entries
            exact_table: ExactTable::new(1 << 18),
            zobrist: ZobristKeys::new(),
            context_fingerprint: None,
            diagnostic_game_exact_cache: false,
        }
    }

    /// Retain exact proofs between decisions for explicit diagnostic experiments.
    ///
    /// Production and training callers should use `new`; Advisor always clears
    /// its proofs. Call `new_game` at each game boundary.
    pub fn with_diagnostic_game_exact_cache() -> Self {
        Self {
            diagnostic_game_exact_cache: true,
            ..Self::new()
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
        let started = Instant::now();
        if !self.diagnostic_game_exact_cache {
            self.exact_table.clear();
        }
        let context_fingerprint = search_context_fingerprint(evaluator, config);
        if self.context_fingerprint != Some(context_fingerprint) {
            self.tt.clear();
            if self.diagnostic_game_exact_cache {
                self.exact_table.clear();
            }
            self.context_fingerprint = Some(context_fingerprint);
        }

        let stone_count = board.count(Color::Black) + board.count(Color::White);
        let max_depth = config.depth_for_phase(stone_count);

        if board.empty_cells().count_ones() <= config.exact_solver_empty_squares {
            let mut nodes_searched = 0;
            let mut solver =
                EndgameSolver::new(&self.zobrist, &mut self.exact_table, &mut nodes_searched);
            let completed = solver.solve(board, color, budget);
            let exact_pvs = solver.diagnostics();
            let exact_cache = solver.cache_diagnostics();
            return SearchResult {
                outcome: completed.outcome,
                score: completed.score,
                pv: completed.pv,
                leaf_eval: None,
                completed_depth: completed.completed_depth,
                nodes_searched,
                elapsed: started.elapsed(),
                exact: completed.exact,
                exact_pvs,
                exact_cache,
            };
        }

        let mut search = Negascout::new(evaluator, &mut self.tt, &self.zobrist);
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
            exact_pvs: ExactPvsDiagnostics::default(),
            exact_cache: ExactCacheDiagnostics::default(),
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
        self.exact_table.clear();
    }

    /// Start a game with no proofs, heuristic entries, or prior search context.
    pub fn new_game(&mut self) {
        self.clear_tt();
        self.context_fingerprint = None;
    }

    /// Drop exact proofs between diagnostic turns without changing heuristic TT state.
    pub fn clear_exact_cache(&mut self) {
        self.exact_table.clear();
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

    fn small_exact_board() -> Board {
        Board::from_string(
            "..WWWWWW\n.WWWWWWW\n.WWBWWBW\n.WBWBWBW\n.BBBWBWW\nBBBBWWWB\n.BBWBWWB\nBBBBBBWB",
        )
        .unwrap()
    }

    #[test]
    fn advisor_clears_previous_decision_even_on_interruption_and_pass() {
        let evaluator = crate::eval::strategic::StrategicEvaluator::new();
        let config = DecisionMoveConfig::new(1, 1, 16).unwrap();
        let board = small_exact_board();
        let mut engine = SearchEngine::new();
        let budget = SearchBudget::with_node_limit_only(1_000_000);
        let first = engine
            .analyze_with_budget(&board, Color::White, &evaluator, &config, &budget)
            .unwrap();
        assert!(engine.exact_table.occupied() > 0);
        assert!(engine
            .analyze_with_budget(
                &board,
                Color::White,
                &evaluator,
                &config,
                &SearchBudget::with_node_limit_only(0)
            )
            .is_err());
        assert_eq!(engine.exact_table.occupied(), 0);
        let repeated = engine
            .analyze_with_budget(&board, Color::White, &evaluator, &config, &budget)
            .unwrap();
        let fresh = SearchEngine::new()
            .analyze_with_budget(&board, Color::White, &evaluator, &config, &budget)
            .unwrap();
        assert_eq!(first.scores, repeated.scores);
        assert_eq!(repeated.scores, fresh.scores);
        assert_eq!(repeated.outcome, fresh.outcome);
        let mut pass = Board::empty();
        pass.set(Position::new(0, 0), Color::Black);
        pass.set(Position::new(0, 1), Color::White);
        assert_eq!(
            engine
                .analyze_with_budget(&pass, Color::White, &evaluator, &config, &budget)
                .unwrap()
                .outcome,
            SearchOutcome::Pass
        );
        assert_eq!(engine.exact_table.occupied(), 0);
    }

    #[test]
    fn consecutive_child_decisions_match_fresh_tables() {
        let evaluator = crate::eval::strategic::StrategicEvaluator::new();
        let config = AiConfig::new(1, 1, 1);
        let mut engine = SearchEngine::new();
        let mut board = small_exact_board();
        let mut side = Color::White;
        for _ in 0..3 {
            let result = engine.search(&board, side, &evaluator, &config);
            let fresh = SearchEngine::new().search(&board, side, &evaluator, &config);
            assert_eq!(result.outcome, fresh.outcome);
            assert_eq!(result.score, fresh.score);
            assert_eq!(result.pv, fresh.pv);
            assert_eq!(result.nodes_searched, fresh.nodes_searched);
            assert_eq!(result.exact_cache, fresh.exact_cache);
            if let SearchOutcome::Move(position) = result.outcome {
                board = moves::make_move(&board, side, position);
            }
            side = side.opponent();
        }
    }

    #[test]
    fn diagnostic_game_reuses_proofs_and_reset_restores_fresh_search() {
        let board = small_exact_board();
        let evaluator = StrategicEvaluator::new();
        let config = AiConfig::new(1, 1, 1);
        let budget = SearchBudget::with_node_limit_only(100_000);
        let mut engine = SearchEngine::with_diagnostic_game_exact_cache();
        let first = engine.search_with_budget(&board, Color::White, &evaluator, &config, &budget);
        let repeated =
            engine.search_with_budget(&board, Color::White, &evaluator, &config, &budget);
        assert!(first.exact && repeated.exact);
        assert_eq!(first.outcome, repeated.outcome);
        assert_eq!(first.score, repeated.score);
        assert_eq!(first.pv, repeated.pv);
        assert!(repeated.nodes_searched < first.nodes_searched);
        assert!(repeated.exact_cache.hits > 0);
        engine.new_game();
        assert!(engine.diagnostic_game_exact_cache);
        assert_eq!(engine.exact_table.occupied(), 0);
        let reset = engine.search_with_budget(&board, Color::White, &evaluator, &config, &budget);
        assert_eq!(reset.nodes_searched, first.nodes_searched);
        assert_eq!(reset.exact_cache, first.exact_cache);
    }

    #[test]
    fn diagnostic_game_context_changes_and_advisor_clear_proofs() {
        let board = small_exact_board();
        let evaluator = StrategicEvaluator::new();
        let config = AiConfig::new(1, 1, 1);
        let budget = SearchBudget::with_node_limit_only(100_000);
        let interrupted = SearchBudget::with_node_limit_only(0);
        let mut engine = SearchEngine::with_diagnostic_game_exact_cache();
        engine.search_with_budget(&board, Color::White, &evaluator, &config, &budget);
        assert!(engine.exact_table.occupied() > 0);
        engine.search_with_budget(
            &board,
            Color::White,
            &evaluator,
            &AiConfig::new(2, 1, 1),
            &interrupted,
        );
        assert_eq!(engine.exact_table.occupied(), 0);
        engine.search_with_budget(&board, Color::White, &evaluator, &config, &budget);
        assert!(engine.exact_table.occupied() > 0);
        assert!(engine
            .analyze_with_budget(
                &board,
                Color::White,
                &evaluator,
                &DecisionMoveConfig::new(1, 1, 16).unwrap(),
                &interrupted
            )
            .is_err());
        assert_eq!(engine.exact_table.occupied(), 0);
    }
    #[test]
    fn decisions_clear_exact_proofs_and_new_game_resets_heuristic_state() {
        let evaluator = crate::eval::strategic::StrategicEvaluator::new();
        let mut board = Board::new();
        let mut side = Color::Black;
        while board.empty_cells().count_ones() > 8 {
            let legal = moves::legal_moves(&board, side);
            if legal != 0 {
                let square = legal.trailing_zeros() as u8;
                let position = Position::new(square / 8, square % 8);
                board = moves::make_move(&board, side, position);
            }
            side = side.opponent();
            if !moves::has_legal_move(&board, side)
                && !moves::has_legal_move(&board, side.opponent())
            {
                break;
            }
        }
        let mut engine = SearchEngine::new();
        for (position, color, config) in [
            (
                Board::new(),
                Color::Black,
                AiConfig::new(4, 4, 4).with_exact_solver_empty_squares(0),
            ),
            (
                board,
                side,
                AiConfig::new(4, 4, 4).with_exact_solver_empty_squares(16),
            ),
        ] {
            engine.new_game();
            let first = engine.search(&position, color, &evaluator, &config);
            let repeated = engine.search(&position, color, &evaluator, &config);
            if first.exact {
                assert_eq!(repeated.nodes_searched, first.nodes_searched);
                assert_eq!(repeated.exact_cache, first.exact_cache);
                assert_eq!(repeated.pv, first.pv);
                assert!(first.exact_cache.hits > 0, "within-solve reuse survives");
            } else {
                assert!(repeated.nodes_searched < first.nodes_searched);
            }
            assert_eq!(repeated.outcome, first.outcome);
            assert_eq!(repeated.score, first.score);
            engine.new_game();
            assert!(engine.context_fingerprint.is_none());
            let reset = engine.search(&position, color, &evaluator, &config);
            let fresh = SearchEngine::new().search(&position, color, &evaluator, &config);
            for result in [&reset, &fresh] {
                assert_eq!(result.outcome, first.outcome);
                assert_eq!(result.score, first.score);
                assert_eq!(result.completed_depth, first.completed_depth);
                assert_eq!(result.exact, first.exact);
                assert_eq!(result.nodes_searched, first.nodes_searched);
                assert_eq!(result.exact_cache, first.exact_cache);
            }
        }
    }

    #[test]
    fn advisor_returns_complete_common_depth_or_error() {
        let board = Board::new();
        let evaluator = crate::eval::strategic::StrategicEvaluator::new();
        let config = DecisionMoveConfig::new(2, 4, 0).unwrap();
        let mut engine = SearchEngine::new();
        let result = engine
            .analyze_with_budget(
                &board,
                Color::Black,
                &evaluator,
                &config,
                &SearchBudget::with_node_limit_only(100_000),
            )
            .unwrap();
        assert_eq!(
            result.outcome,
            SearchOutcome::Move(result.scores[0].position)
        );
        assert_eq!(result.scores.len(), 4);
        assert_eq!(result.completed_depth, 2);
        assert!(result
            .scores
            .iter()
            .all(|score| score.completed_depth == 2 && !score.exact));
        assert_eq!(
            result
                .scores
                .iter()
                .fold(0u64, |set, score| set | score.position.bit_mask()),
            moves::legal_moves(&board, Color::Black)
        );
        assert!(engine
            .analyze_with_budget(
                &board,
                Color::Black,
                &evaluator,
                &config,
                &SearchBudget::with_node_limit_only(1)
            )
            .is_err());
    }

    #[test]
    fn advisor_exact_and_pass_outcomes() {
        let evaluator = crate::eval::strategic::StrategicEvaluator::new();
        let config = DecisionMoveConfig::new(1, 1, 16).unwrap();
        let flat = "..B.W.B...BBW.BB.B.WWWBW.WWWBBWWB.WBWWWWWWWWWWW.WWBWBBW.BBBBBBBW";
        let board = Board::from_string(
            &flat
                .as_bytes()
                .chunks(8)
                .map(|row| std::str::from_utf8(row).unwrap())
                .collect::<Vec<_>>()
                .join("\n"),
        )
        .unwrap();
        let result = SearchEngine::new()
            .analyze_with_budget(
                &board,
                Color::Black,
                &evaluator,
                &config,
                &SearchBudget::with_time_limit(Duration::from_secs(30)),
            )
            .unwrap();
        assert!(result.exact);
        assert_eq!(result.completed_depth, 14);
        assert!(result.scores.iter().all(|score| score.exact));
        let mut pass_board = Board::empty();
        pass_board.set(Position::new(0, 0), Color::Black);
        pass_board.set(Position::new(0, 1), Color::White);
        let pass = SearchEngine::new()
            .analyze_with_budget(
                &pass_board,
                Color::White,
                &evaluator,
                &config,
                &SearchBudget::with_node_limit_only(0),
            )
            .unwrap();
        assert_eq!(pass.outcome, SearchOutcome::Pass);
        assert!(pass.scores.is_empty());
    }
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

    struct NoTerminalEvaluator;

    impl BoardEvaluator for NoTerminalEvaluator {
        fn evaluate(&self, board: &Board, _color: Color) -> EvalResult {
            assert!(
                reversi_engine::moves::has_legal_move(board, Color::Black)
                    || reversi_engine::moves::has_legal_move(board, Color::White),
                "terminal board must bypass heuristic evaluation"
            );
            EvalResult {
                score: 7,
                factors: EvalFactors::default(),
            }
        }

        fn name(&self) -> &str {
            "no-terminal"
        }

        fn context_fingerprint(&self) -> u64 {
            4
        }
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
    fn zero_depth_never_reports_exact() {
        let result = SearchEngine::new().search_with_budget(
            &Board::new(),
            Color::Black,
            &StrategicEvaluator::new(),
            &AiConfig::new(0, 0, 0),
            &SearchBudget::with_time_limit(Duration::from_secs(1)),
        );

        assert_eq!(result.completed_depth, 0);
        assert!(!result.exact);
        assert!(result.score.is_none());
    }

    #[test]
    fn unrepresentable_time_limit_returns_immediate_fallback() {
        let result = SearchEngine::new().search_with_budget(
            &Board::new(),
            Color::Black,
            &StrategicEvaluator::new(),
            &AiConfig::new(1, 1, 1),
            &SearchBudget::with_time_limit(Duration::MAX),
        );

        assert_eq!(result.completed_depth, 0);
        assert!(result.score.is_none());
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
        assert!(pass.score.is_none());
        assert_eq!(game_over.score, Some(0));
        assert!(game_over.leaf_eval.is_none());
        assert!(game_over.pv.is_empty());
        assert!(!game_over.exact);
    }

    #[test]
    fn heuristic_wipeout_scores_both_root_sides_without_evaluation() {
        let board = Board::from_string(
            "BBB.....\n........\n........\n........\n........\n........\n........\n........",
        )
        .unwrap();
        assert_eq!(board.empty_cells().count_ones(), 61);
        let config = AiConfig::new(2, 2, 2);
        for (color, score) in [(Color::Black, 64), (Color::White, -64)] {
            assert_eq!(reversi_engine::moves::legal_moves(&board, color), 0);
            let result = SearchEngine::new().search_with_budget(
                &board,
                color,
                &NoTerminalEvaluator,
                &config,
                &SearchBudget::with_node_limit_only(100),
            );
            assert_eq!(result.outcome, SearchOutcome::GameOver);
            assert_eq!(result.score, Some(score));
            assert!(result.pv.is_empty());
            assert!(result.leaf_eval.is_none());
            assert!(!result.exact);
        }
    }

    #[test]
    fn heuristic_depth_zero_wipeout_replaces_previous_leaf_evaluation() {
        let board = Board::from_string(
            "BW.W....\n........\n........\n........\n........\n........\n........\n........",
        )
        .unwrap();
        let config = AiConfig::new(2, 2, 2);
        let result = SearchEngine::new().search_with_budget(
            &board,
            Color::Black,
            &NoTerminalEvaluator,
            &config,
            &SearchBudget::with_node_limit_only(100),
        );
        assert_eq!(result.outcome, SearchOutcome::Move(Position::new(0, 2)));
        assert_eq!(result.completed_depth, 2);
        assert_eq!(result.score, Some(64));
        assert_eq!(result.pv, vec![Position::new(0, 2), Position::new(0, 4)]);
        assert!(result.leaf_eval.is_none());
        assert!(!result.exact);
    }

    #[test]
    fn public_exact_search_scores_wipeout_before_board_fills() {
        let board = Board::from_string(
            "BBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBB.",
        )
        .unwrap();
        assert_eq!(board.empty_cells().count_ones(), 1);
        let config = AiConfig::new(2, 2, 2);
        for (color, score) in [(Color::Black, 64), (Color::White, -64)] {
            assert_eq!(reversi_engine::moves::legal_moves(&board, color), 0);
            let result = SearchEngine::new().search_with_budget(
                &board,
                color,
                &NoTerminalEvaluator,
                &config,
                &SearchBudget::with_node_limit_only(100),
            );
            assert_eq!(result.outcome, SearchOutcome::GameOver);
            assert_eq!(result.score, Some(score));
            assert!(result.pv.is_empty());
            assert!(result.leaf_eval.is_none());
            assert!(result.exact);
        }
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

    #[test]
    fn twelve_empty_positions_bypass_every_evaluator() {
        let board = Board::from_string(
            "WWWWWWW.\nWWWWWWW.\nWWWWWWB.\nWWWWWB..\nWWWWWB..\nWWWWWB..\nWWWWWB..\nBBBBBBB.",
        )
        .unwrap();
        let budget = SearchBudget::with_time_limit(Duration::from_secs(30));
        let config = AiConfig::new(1, 1, 1);
        let strategic = SearchEngine::new().search_with_budget(
            &board,
            Color::Black,
            &StrategicEvaluator::new(),
            &config,
            &budget,
        );
        let novice = SearchEngine::new().search_with_budget(
            &board,
            Color::Black,
            &crate::eval::novice::NoviceEvaluator::new(),
            &config,
            &budget,
        );

        assert!(strategic.exact && novice.exact);
        assert_eq!(strategic.score, Some(-28));
        assert_eq!(strategic.outcome, novice.outcome);
        assert_eq!(strategic.score, novice.score);
        assert_eq!(strategic.pv, novice.pv);
    }
}
