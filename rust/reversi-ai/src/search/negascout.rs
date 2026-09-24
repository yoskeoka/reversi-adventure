use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::{Color, Position};

use super::ordering::order_moves_with_successors;
use super::tt::{Bound, TranspositionTable, TtEntry, ZobristKeys};
use super::{SearchBudget, SearchOutcome};
use crate::eval::{BoardEvaluator, EvalResult};

/// Negascout search with iterative deepening.
pub struct Negascout<'a, E: BoardEvaluator + ?Sized> {
    evaluator: &'a E,
    tt: &'a mut TranspositionTable,
    zobrist: &'a ZobristKeys,
    nodes_searched: u64,
}

/// Internal search result for a single node.
struct NodeResult {
    score: i32,
    pv: Vec<Position>,
    leaf_eval: Option<EvalResult>,
}

pub(crate) struct CompletedSearch {
    pub outcome: SearchOutcome,
    pub score: Option<i32>,
    pub pv: Vec<Position>,
    pub leaf_eval: Option<EvalResult>,
    pub completed_depth: u8,
    pub exact: bool,
}

const FULL_ALPHA: i32 = i32::MIN + 1;
const FULL_BETA: i32 = i32::MAX - 1;
const INITIAL_ASPIRATION_DELTA: i64 = 64;

fn aspiration_window(center: i32, delta: i64) -> (i32, i32) {
    let center = i64::from(center);
    (
        (center - delta).max(i64::from(FULL_ALPHA)) as i32,
        (center + delta).min(i64::from(FULL_BETA)) as i32,
    )
}

impl<'a, E: BoardEvaluator + ?Sized> Negascout<'a, E> {
    pub fn new(evaluator: &'a E, tt: &'a mut TranspositionTable, zobrist: &'a ZobristKeys) -> Self {
        Self {
            evaluator,
            tt,
            zobrist,
            nodes_searched: 0,
        }
    }

    pub fn nodes_searched(&self) -> u64 {
        self.nodes_searched
    }

    /// Run iterative deepening search up to max_depth within budget.
    /// Returns the last wholly completed iteration or a root-state outcome.
    pub(crate) fn search(
        &mut self,
        board: &Board,
        color: Color,
        max_depth: u8,
        budget: &SearchBudget,
    ) -> CompletedSearch {
        self.search_with_mode(board, color, max_depth, budget, true)
    }

    fn search_with_mode(
        &mut self,
        board: &Board,
        color: Color,
        max_depth: u8,
        budget: &SearchBudget,
        aspiration: bool,
    ) -> CompletedSearch {
        let mut best_pv = Vec::new();

        let legal = moves::legal_moves(board, color);
        if legal == 0 {
            let outcome = if moves::has_legal_move(board, color.opponent()) {
                SearchOutcome::Pass
            } else {
                SearchOutcome::GameOver
            };
            return CompletedSearch {
                outcome,
                score: None,
                pv: best_pv,
                leaf_eval: None,
                completed_depth: 0,
                exact: false,
            };
        }

        let first_index = legal.trailing_zeros() as u8;
        let fallback = Position::from_bit_index(first_index);
        let mut best_move = fallback;
        let mut best_score = None;
        let mut best_leaf = None;
        let mut completed_depth = 0;

        for depth in 1..=max_depth {
            let mut delta = INITIAL_ASPIRATION_DELTA;
            let result = loop {
                let (alpha, beta) = if aspiration && depth > 1 {
                    aspiration_window(best_score.expect("previous depth completed"), delta)
                } else {
                    (FULL_ALPHA, FULL_BETA)
                };
                let result = match self.negascout(board, color, depth, alpha, beta, budget) {
                    Ok(result) => result,
                    Err(()) => break None,
                };
                if budget.interrupted_after_completion() {
                    break None;
                }
                if (result.score > alpha && result.score < beta)
                    || (alpha == FULL_ALPHA && beta == FULL_BETA)
                {
                    break Some(result);
                }
                delta = delta.saturating_mul(2);
            };
            let Some(result) = result else { break };
            if budget.interrupted_after_completion() {
                break;
            }

            if !result.pv.is_empty() {
                best_move = result.pv[0];
                best_score = Some(result.score);
                best_pv = result.pv;
                if let Some(leaf_eval) = result.leaf_eval {
                    best_leaf = Some(leaf_eval);
                }
                completed_depth = depth;
            }
        }

        CompletedSearch {
            outcome: SearchOutcome::Move(best_move),
            score: best_score,
            pv: best_pv,
            leaf_eval: best_leaf,
            completed_depth,
            // A completed heuristic depth is useful, but it is not a proof of
            // final disc difference. Only the endgame solver reports exact.
            exact: false,
        }
    }

    /// Negascout (PVS) recursive search.
    fn negascout(
        &mut self,
        board: &Board,
        color: Color,
        depth: u8,
        mut alpha: i32,
        beta: i32,
        budget: &SearchBudget,
    ) -> Result<NodeResult, ()> {
        if budget.interrupted(self.nodes_searched) {
            return Err(());
        }
        self.nodes_searched += 1;

        // Leaf node: evaluate
        if depth == 0 {
            let eval = self.evaluator.evaluate(board, color);
            return Ok(NodeResult {
                score: eval.score,
                pv: Vec::new(),
                leaf_eval: Some(eval),
            });
        }

        let hash = self.zobrist.hash(board, color);

        // TT probe
        let tt_move = if let Some(entry) = self.tt.probe(hash) {
            if entry.depth >= depth {
                match entry.bound {
                    Bound::Exact => {
                        return Ok(NodeResult {
                            score: entry.score,
                            pv: entry.best_move.into_iter().collect(),
                            leaf_eval: None,
                        });
                    }
                    Bound::LowerBound => {
                        if entry.score >= beta {
                            return Ok(NodeResult {
                                score: entry.score,
                                pv: entry.best_move.into_iter().collect(),
                                leaf_eval: None,
                            });
                        }
                        if entry.score > alpha {
                            alpha = entry.score;
                        }
                    }
                    Bound::UpperBound => {
                        if entry.score <= alpha {
                            return Ok(NodeResult {
                                score: entry.score,
                                pv: entry.best_move.into_iter().collect(),
                                leaf_eval: None,
                            });
                        }
                    }
                }
            }
            entry.best_move
        } else {
            None
        };

        let legal = moves::legal_moves(board, color);

        // No legal moves: pass or game over
        if legal == 0 {
            if !moves::has_legal_move(board, color.opponent()) {
                // Game over — evaluate final position
                let eval = self.evaluator.evaluate(board, color);
                return Ok(NodeResult {
                    score: eval.score,
                    pv: Vec::new(),
                    leaf_eval: Some(eval),
                });
            }
            // Pass: search opponent's turn at same depth
            let child = self.negascout(board, color.opponent(), depth, -beta, -alpha, budget)?;
            return Ok(NodeResult {
                score: -child.score,
                pv: child.pv,
                leaf_eval: child.leaf_eval,
            });
        }

        let ordered = order_moves_with_successors(board, color, legal, tt_move, depth);

        let original_alpha = alpha;
        let mut best_score = i32::MIN;
        let mut best_pv = Vec::new();
        let mut best_leaf = None;
        let mut best_move = ordered[0].position;
        let mut first = true;

        for ordered_move in &ordered {
            if budget.interrupted(self.nodes_searched) {
                return Err(());
            }
            let pos = ordered_move.position;
            let new_board = ordered_move.successor.unwrap_or_else(|| {
                moves::make_move_with_flips(board, color, pos, ordered_move.flips)
            });

            let child = if first {
                // PV node: full window search
                first = false;
                self.negascout(
                    &new_board,
                    color.opponent(),
                    depth - 1,
                    -beta,
                    -alpha,
                    budget,
                )?
            } else {
                // Null-window search
                let nw = self.negascout(
                    &new_board,
                    color.opponent(),
                    depth - 1,
                    -alpha - 1,
                    -alpha,
                    budget,
                )?;
                if -nw.score > alpha && -nw.score < beta {
                    // Fail high: re-search with full window
                    self.negascout(
                        &new_board,
                        color.opponent(),
                        depth - 1,
                        -beta,
                        -alpha,
                        budget,
                    )?
                } else {
                    nw
                }
            };

            let score = -child.score;

            if score > best_score {
                best_score = score;
                best_move = pos;

                // Build PV: this move + child's PV
                best_pv = Vec::with_capacity(1 + child.pv.len());
                best_pv.push(pos);
                best_pv.extend_from_slice(&child.pv);
                best_leaf = child.leaf_eval;
            }

            if score > alpha {
                alpha = score;
            }

            if alpha >= beta {
                break; // Beta cutoff
            }
        }

        // Store in TT
        let bound = if best_score <= original_alpha {
            Bound::UpperBound
        } else if best_score >= beta {
            Bound::LowerBound
        } else {
            Bound::Exact
        };

        self.tt.store(
            hash,
            TtEntry {
                hash,
                depth,
                score: best_score,
                bound,
                best_move: Some(best_move),
            },
        );

        Ok(NodeResult {
            score: best_score,
            pv: best_pv,
            leaf_eval: best_leaf,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::eval::{strategic::StrategicEvaluator, EvalFactors};

    struct ConstantEvaluator;

    impl BoardEvaluator for ConstantEvaluator {
        fn evaluate(&self, _board: &Board, _color: Color) -> EvalResult {
            EvalResult {
                score: 1000,
                factors: EvalFactors::default(),
            }
        }

        fn name(&self) -> &str {
            "constant"
        }

        fn context_fingerprint(&self) -> u64 {
            1
        }
    }

    fn run<E: BoardEvaluator>(
        evaluator: &E,
        depth: u8,
        budget: &SearchBudget,
        aspiration: bool,
    ) -> (CompletedSearch, u64) {
        run_on_board(
            &Board::new(),
            Color::Black,
            evaluator,
            depth,
            budget,
            aspiration,
        )
    }

    fn run_on_board<E: BoardEvaluator>(
        board: &Board,
        color: Color,
        evaluator: &E,
        depth: u8,
        budget: &SearchBudget,
        aspiration: bool,
    ) -> (CompletedSearch, u64) {
        let mut tt = TranspositionTable::new(1 << 16);
        let zobrist = ZobristKeys::new();
        let mut search = Negascout::new(evaluator, &mut tt, &zobrist);
        let result = search.search_with_mode(board, color, depth, budget, aspiration);
        (result, search.nodes_searched())
    }

    #[test]
    fn aspiration_window_clamps_at_both_score_limits() {
        assert_eq!(aspiration_window(i32::MIN, 64), (FULL_ALPHA, i32::MIN + 64));
        assert_eq!(aspiration_window(i32::MAX, 64), (i32::MAX - 64, FULL_BETA));
        assert_eq!(aspiration_window(0, 1_i64 << 32), (FULL_ALPHA, FULL_BETA));
    }

    #[test]
    fn retries_count_nodes_and_preserve_the_full_window_result() {
        let budget = SearchBudget::with_node_limit_only(u64::MAX);
        let (candidate, candidate_nodes) = run(&ConstantEvaluator, 3, &budget, true);
        let (baseline, baseline_nodes) = run(&ConstantEvaluator, 3, &budget, false);
        assert_eq!(candidate.score, baseline.score);
        assert_eq!(candidate.pv, baseline.pv);
        assert_eq!(candidate.completed_depth, 3);
        assert!(candidate_nodes > baseline_nodes);
    }

    #[test]
    fn failed_windows_store_their_proven_bounds() {
        let board = Board::new();
        let hash = ZobristKeys::new().hash(&board, Color::Black);
        let budget = SearchBudget::with_node_limit_only(u64::MAX);
        for (depth, center, expected) in
            [(2, -1000, Bound::LowerBound), (3, 1000, Bound::UpperBound)]
        {
            let mut tt = TranspositionTable::new(1 << 16);
            let zobrist = ZobristKeys::new();
            let mut search = Negascout::new(&ConstantEvaluator, &mut tt, &zobrist);
            let (alpha, beta) = aspiration_window(center, INITIAL_ASPIRATION_DELTA);
            search
                .negascout(&board, Color::Black, depth, alpha, beta, &budget)
                .unwrap();
            assert_eq!(tt.probe(hash).unwrap().bound, expected);
        }
    }

    #[test]
    fn interruption_in_retry_keeps_previous_depth() {
        let budget = SearchBudget::with_node_limit_only(u64::MAX);
        let (first, first_nodes) = run(&ConstantEvaluator, 1, &budget, true);
        let (_, complete_nodes) = run(&ConstantEvaluator, 2, &budget, true);
        assert!(complete_nodes > first_nodes + 1);
        for limit in first_nodes..complete_nodes {
            let (interrupted, nodes) = run(
                &ConstantEvaluator,
                2,
                &SearchBudget::with_node_limit_only(limit),
                true,
            );
            assert_eq!(interrupted.completed_depth, 1, "limit {limit}");
            assert_eq!(interrupted.score, first.score, "limit {limit}");
            assert_eq!(interrupted.pv, first.pv, "limit {limit}");
            assert_eq!(nodes, limit);
        }
    }

    #[test]
    fn starting_position_matches_full_window_at_several_depths() {
        let budget = SearchBudget::with_node_limit_only(u64::MAX);
        for depth in 1..=6 {
            let (candidate, _) = run(&StrategicEvaluator::new(), depth, &budget, true);
            let (baseline, _) = run(&StrategicEvaluator::new(), depth, &budget, false);
            assert_eq!(candidate.score, baseline.score, "depth {depth}");
            assert_eq!(candidate.pv, baseline.pv, "depth {depth}");
            assert_eq!(candidate.completed_depth, baseline.completed_depth);
        }
    }

    #[test]
    fn benchmark_positions_match_full_window_at_short_depth() {
        let corpus = include_str!("../../../../tools/reversi-ai-benchmark/positions-v1.jsonl");
        let evaluator = StrategicEvaluator::new();
        let budget = SearchBudget::with_node_limit_only(u64::MAX);
        for line in corpus.lines() {
            let record: serde_json::Value = serde_json::from_str(line).unwrap();
            let cells = record["board"].as_str().unwrap().as_bytes();
            let mut board = Board::empty();
            for (index, cell) in cells.iter().enumerate() {
                let color = match cell {
                    b'B' => Some(Color::Black),
                    b'W' => Some(Color::White),
                    _ => None,
                };
                if let Some(color) = color {
                    board.set(Position::from_bit_index(index as u8), color);
                }
            }
            let color = if record["side_to_move"] == "B" {
                Color::Black
            } else {
                Color::White
            };
            let (candidate, _) = run_on_board(&board, color, &evaluator, 4, &budget, true);
            let (baseline, _) = run_on_board(&board, color, &evaluator, 4, &budget, false);
            let id = record["position_id"].as_str().unwrap();
            assert_eq!(candidate.outcome, baseline.outcome, "{id}");
            assert_eq!(candidate.score, baseline.score, "{id}");
            assert_eq!(candidate.pv, baseline.pv, "{id}");
            assert_eq!(candidate.completed_depth, baseline.completed_depth, "{id}");
        }
    }
}
