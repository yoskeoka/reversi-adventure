use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::{Color, Position};

use crate::eval::{BoardEvaluator, EvalResult};
use super::ordering::order_moves;
use super::tt::{Bound, TranspositionTable, TtEntry, ZobristKeys};

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

impl<'a, E: BoardEvaluator + ?Sized> Negascout<'a, E> {
    pub fn new(
        evaluator: &'a E,
        tt: &'a mut TranspositionTable,
        zobrist: &'a ZobristKeys,
    ) -> Self {
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

    /// Run iterative deepening search up to max_depth.
    /// Returns (best_move, score, pv, leaf_eval).
    pub fn search(
        &mut self,
        board: &Board,
        color: Color,
        max_depth: u8,
    ) -> (Position, i32, Vec<Position>, EvalResult) {
        let mut best_move = Position::new(0, 0);
        let mut best_score = i32::MIN;
        let mut best_pv = Vec::new();
        let mut best_leaf = self.evaluator.evaluate(board, color);

        // Find any legal move as fallback
        let legal = moves::legal_moves(board, color);
        if legal == 0 {
            return (best_move, 0, best_pv, best_leaf);
        }

        // Set initial best_move to first legal move
        let first_index = legal.trailing_zeros() as u8;
        best_move = Position::from_bit_index(first_index);

        for depth in 1..=max_depth {
            self.nodes_searched = 0;
            let result = self.negascout(board, color, depth, i32::MIN + 1, i32::MAX - 1);

            if !result.pv.is_empty() {
                best_move = result.pv[0];
                best_score = result.score;
                best_pv = result.pv;
                if let Some(eval) = result.leaf_eval {
                    best_leaf = eval;
                }
            }
        }

        (best_move, best_score, best_pv, best_leaf)
    }

    /// Negascout (PVS) recursive search.
    fn negascout(
        &mut self,
        board: &Board,
        color: Color,
        depth: u8,
        mut alpha: i32,
        beta: i32,
    ) -> NodeResult {
        self.nodes_searched += 1;

        // Leaf node: evaluate
        if depth == 0 {
            let eval = self.evaluator.evaluate(board, color);
            return NodeResult {
                score: eval.score,
                pv: Vec::new(),
                leaf_eval: Some(eval),
            };
        }

        let hash = self.zobrist.hash(board);

        // TT probe
        let tt_move = if let Some(entry) = self.tt.probe(hash) {
            if entry.depth >= depth {
                match entry.bound {
                    Bound::Exact => {
                        return NodeResult {
                            score: entry.score,
                            pv: entry.best_move.into_iter().collect(),
                            leaf_eval: None,
                        };
                    }
                    Bound::LowerBound => {
                        if entry.score >= beta {
                            return NodeResult {
                                score: entry.score,
                                pv: entry.best_move.into_iter().collect(),
                                leaf_eval: None,
                            };
                        }
                        if entry.score > alpha {
                            alpha = entry.score;
                        }
                    }
                    Bound::UpperBound => {
                        if entry.score <= alpha {
                            return NodeResult {
                                score: entry.score,
                                pv: entry.best_move.into_iter().collect(),
                                leaf_eval: None,
                            };
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
                return NodeResult {
                    score: eval.score,
                    pv: Vec::new(),
                    leaf_eval: Some(eval),
                };
            }
            // Pass: search opponent's turn at same depth
            let child = self.negascout(board, color.opponent(), depth, -beta, -alpha);
            return NodeResult {
                score: -child.score,
                pv: child.pv,
                leaf_eval: child.leaf_eval,
            };
        }

        let ordered = order_moves(board, color, legal, tt_move);

        let mut best_score = i32::MIN;
        let mut best_pv = Vec::new();
        let mut best_leaf = None;
        let mut best_move = ordered[0];
        let mut first = true;

        for pos in &ordered {
            let new_board = moves::make_move(board, color, *pos);

            let child = if first {
                // PV node: full window search
                first = false;
                self.negascout(&new_board, color.opponent(), depth - 1, -beta, -alpha)
            } else {
                // Null-window search
                let nw = self.negascout(&new_board, color.opponent(), depth - 1, -alpha - 1, -alpha);
                if -nw.score > alpha && -nw.score < beta {
                    // Fail high: re-search with full window
                    self.negascout(&new_board, color.opponent(), depth - 1, -beta, -alpha)
                } else {
                    nw
                }
            };

            let score = -child.score;

            if score > best_score {
                best_score = score;
                best_move = *pos;

                // Build PV: this move + child's PV
                best_pv = Vec::with_capacity(1 + child.pv.len());
                best_pv.push(*pos);
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
        let bound = if best_score <= alpha {
            Bound::UpperBound
        } else if best_score >= beta {
            Bound::LowerBound
        } else {
            Bound::Exact
        };

        self.tt.store(hash, TtEntry {
            hash,
            depth,
            score: best_score,
            bound,
            best_move: Some(best_move),
        });

        NodeResult {
            score: best_score,
            pv: best_pv,
            leaf_eval: best_leaf,
        }
    }
}
