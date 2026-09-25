use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::{Color, Position};

use super::endgame::terminal_score;
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
                score: (outcome == SearchOutcome::GameOver).then(|| terminal_score(board, color)),
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
            let result =
                match self.negascout(board, color, depth, i32::MIN + 1, i32::MAX - 1, budget) {
                    Ok(result) => result,
                    Err(()) => break,
                };
            if budget.interrupted_after_completion() {
                break;
            }

            if !result.pv.is_empty() {
                best_move = result.pv[0];
                best_score = Some(result.score);
                best_pv = result.pv;
                best_leaf = result.leaf_eval;
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
        #[cfg(feature = "cost-diagnostics")]
        crate::cost_diagnostics::event(
            1,
            &[
                board.pieces(color),
                board.pieces(color.opponent()),
                u64::from(depth),
                alpha as u64,
                beta as u64,
            ],
        );

        #[cfg(feature = "cost-diagnostics")]
        let legal = crate::cost_diagnostics::measure("heuristic_legal", || {
            moves::legal_moves(board, color)
        });
        #[cfg(not(feature = "cost-diagnostics"))]
        let legal = moves::legal_moves(board, color);
        if legal == 0 && !moves::has_legal_move(board, color.opponent()) {
            return Ok(NodeResult {
                score: terminal_score(board, color),
                pv: Vec::new(),
                leaf_eval: None,
            });
        }

        // Leaf node: evaluate
        if depth == 0 {
            #[cfg(feature = "cost-diagnostics")]
            let eval = crate::cost_diagnostics::measure("heuristic_leaf_eval", || {
                self.evaluator.evaluate(board, color)
            });
            #[cfg(not(feature = "cost-diagnostics"))]
            let eval = self.evaluator.evaluate(board, color);
            return Ok(NodeResult {
                score: eval.score,
                pv: Vec::new(),
                leaf_eval: Some(eval),
            });
        }

        #[cfg(feature = "cost-diagnostics")]
        let hash =
            crate::cost_diagnostics::measure("heuristic_hash", || self.zobrist.hash(board, color));
        #[cfg(not(feature = "cost-diagnostics"))]
        let hash = self.zobrist.hash(board, color);

        // TT probe
        #[cfg(feature = "cost-diagnostics")]
        let probe = crate::cost_diagnostics::measure("heuristic_tt_probe", || self.tt.probe(hash));
        #[cfg(not(feature = "cost-diagnostics"))]
        let probe = self.tt.probe(hash);
        #[cfg(feature = "cost-diagnostics")]
        crate::cost_diagnostics::event(
            2,
            &[
                hash,
                self.tt.diagnostic_slot_hash(hash).unwrap_or(0),
                u64::from(probe.is_some()),
                probe.map_or(0, |entry| u64::from(entry.depth)),
                probe.map_or(0, |entry| entry.score as u64),
                probe.map_or(0, |entry| match entry.bound {
                    Bound::Exact => 1,
                    Bound::LowerBound => 2,
                    Bound::UpperBound => 3,
                }),
            ],
        );
        let tt_move = if let Some(entry) = probe {
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

        // No legal moves: pass or game over
        if legal == 0 {
            #[cfg(feature = "cost-diagnostics")]
            crate::cost_diagnostics::event(3, &[]);
            // Pass: search opponent's turn at same depth
            let child = self.negascout(board, color.opponent(), depth, -beta, -alpha, budget)?;
            return Ok(NodeResult {
                score: -child.score,
                pv: child.pv,
                leaf_eval: child.leaf_eval,
            });
        }

        #[cfg(feature = "cost-diagnostics")]
        let ordered = crate::cost_diagnostics::measure("heuristic_ordering", || {
            order_moves_with_successors(board, color, legal, tt_move, depth)
        });
        #[cfg(not(feature = "cost-diagnostics"))]
        let ordered = order_moves_with_successors(board, color, legal, tt_move, depth);
        #[cfg(feature = "cost-diagnostics")]
        crate::cost_diagnostics::event(
            4,
            &ordered
                .iter()
                .map(|item| u64::from(item.position.bit_index()))
                .collect::<Vec<_>>(),
        );

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
                    #[cfg(feature = "cost-diagnostics")]
                    crate::cost_diagnostics::event(5, &[u64::from(pos.bit_index())]);
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
                #[cfg(feature = "cost-diagnostics")]
                crate::cost_diagnostics::event(6, &[u64::from(pos.bit_index())]);
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

        #[cfg(feature = "cost-diagnostics")]
        crate::cost_diagnostics::event(
            7,
            &[
                hash,
                u64::from(depth),
                best_score as u64,
                u64::from(best_move.bit_index()),
            ],
        );
        #[cfg(feature = "cost-diagnostics")]
        crate::cost_diagnostics::measure("heuristic_tt_store", || {
            self.tt.store(
                hash,
                TtEntry {
                    hash,
                    depth,
                    score: best_score,
                    bound,
                    best_move: Some(best_move),
                },
            )
        });
        #[cfg(not(feature = "cost-diagnostics"))]
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
