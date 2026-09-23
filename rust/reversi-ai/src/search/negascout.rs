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
    pv: PvScratch,
}

const MAX_SEARCH_PLIES: usize = 64;

struct PvScratch {
    positions: [[Option<Position>; MAX_SEARCH_PLIES]; MAX_SEARCH_PLIES + 1],
    lengths: [u8; MAX_SEARCH_PLIES + 1],
}

impl PvScratch {
    fn clear(&mut self, ply: usize) {
        self.lengths[ply] = 0;
    }
    fn single(&mut self, ply: usize, position: Position) {
        self.positions[ply][0] = Some(position);
        self.lengths[ply] = 1;
    }
    fn copy_child(&mut self, ply: usize) {
        let child = ply + 1;
        let length = self.lengths[child] as usize;
        for index in 0..length {
            self.positions[ply][index] = self.positions[child][index];
        }
        self.lengths[ply] = length as u8;
    }
    fn prepend_child(&mut self, ply: usize, position: Position) {
        let child = ply + 1;
        let length = self.lengths[child] as usize;
        for index in (0..length).rev() {
            self.positions[ply][index + 1] = self.positions[child][index];
        }
        self.positions[ply][0] = Some(position);
        self.lengths[ply] = (length + 1) as u8;
    }
    fn line(&self, ply: usize) -> Vec<Position> {
        self.positions[ply][..self.lengths[ply] as usize]
            .iter()
            .map(|position| position.expect("PV entries are initialized"))
            .collect()
    }
}

/// Internal search result for a single node. Its PV remains in search-owned scratch.
struct NodeResult {
    score: i32,
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
            pv: PvScratch {
                positions: [[None; MAX_SEARCH_PLIES]; MAX_SEARCH_PLIES + 1],
                lengths: [0; MAX_SEARCH_PLIES + 1],
            },
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
            let result =
                match self.negascout(board, color, depth, i32::MIN + 1, i32::MAX - 1, 0, budget) {
                    Ok(result) => result,
                    Err(()) => break,
                };
            if budget.interrupted_after_completion() {
                break;
            }

            if self.pv.lengths[0] != 0 {
                best_move = self.pv.positions[0][0].expect("root PV starts with a move");
                best_score = Some(result.score);
                best_pv = self.pv.line(0);
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
    #[allow(clippy::too_many_arguments)]
    fn negascout(
        &mut self,
        board: &Board,
        color: Color,
        depth: u8,
        mut alpha: i32,
        beta: i32,
        ply: usize,
        budget: &SearchBudget,
    ) -> Result<NodeResult, ()> {
        if budget.interrupted(self.nodes_searched) {
            return Err(());
        }
        self.nodes_searched += 1;
        self.pv.clear(ply);

        // Leaf node: evaluate
        if depth == 0 {
            let eval = self.evaluator.evaluate(board, color);
            return Ok(NodeResult {
                score: eval.score,
                leaf_eval: Some(eval),
            });
        }

        let hash = self.zobrist.hash(board, color);

        // TT probe
        let tt_move = if let Some(entry) = self.tt.probe(hash) {
            if entry.depth >= depth {
                match entry.bound {
                    Bound::Exact => {
                        if let Some(position) = entry.best_move {
                            self.pv.single(ply, position);
                        }
                        return Ok(NodeResult {
                            score: entry.score,
                            leaf_eval: None,
                        });
                    }
                    Bound::LowerBound => {
                        if entry.score >= beta {
                            if let Some(position) = entry.best_move {
                                self.pv.single(ply, position);
                            }
                            return Ok(NodeResult {
                                score: entry.score,
                                leaf_eval: None,
                            });
                        }
                        if entry.score > alpha {
                            alpha = entry.score;
                        }
                    }
                    Bound::UpperBound => {
                        if entry.score <= alpha {
                            if let Some(position) = entry.best_move {
                                self.pv.single(ply, position);
                            }
                            return Ok(NodeResult {
                                score: entry.score,
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
                    leaf_eval: Some(eval),
                });
            }
            // Pass: search opponent's turn at same depth
            let child = self.negascout(
                board,
                color.opponent(),
                depth,
                -beta,
                -alpha,
                ply + 1,
                budget,
            )?;
            self.pv.copy_child(ply);
            return Ok(NodeResult {
                score: -child.score,
                leaf_eval: child.leaf_eval,
            });
        }

        let ordered = order_moves_with_successors(board, color, legal, tt_move, depth);

        let original_alpha = alpha;
        let mut best_score = i32::MIN;
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
                    ply + 1,
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
                    ply + 1,
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
                        ply + 1,
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

                self.pv.prepend_child(ply, pos);
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
            leaf_eval: best_leaf,
        })
    }
}
