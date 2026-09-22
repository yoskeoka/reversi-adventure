use std::collections::HashMap;

use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::{Color, Position};

use super::ordering::order_moves;
use super::tt::{Bound, ZobristKeys};
use super::{SearchBudget, SearchOutcome};

#[derive(Clone)]
struct ExactEntry {
    score: i32,
    bound: Bound,
    best_move: Option<Position>,
    pv: Vec<Position>,
}

struct NodeResult {
    score: i32,
    pv: Vec<Position>,
}

/// Completed result from the evaluator-independent exact endgame solver.
pub(crate) struct CompletedEndgame {
    pub outcome: SearchOutcome,
    pub score: Option<i32>,
    pub pv: Vec<Position>,
    pub completed_depth: u8,
    pub exact: bool,
}

/// Exact, pass-aware negamax for the final placements of a game.
///
/// Its transposition entries deliberately live only for one solve. They never
/// share the heuristic search table, whose values have different semantics.
pub(crate) struct EndgameSolver<'a> {
    zobrist: &'a ZobristKeys,
    table: HashMap<u64, ExactEntry>,
    nodes_searched: &'a mut u64,
}

impl<'a> EndgameSolver<'a> {
    pub(crate) fn new(zobrist: &'a ZobristKeys, nodes_searched: &'a mut u64) -> Self {
        Self {
            zobrist,
            table: HashMap::new(),
            nodes_searched,
        }
    }

    pub(crate) fn solve(
        &mut self,
        board: &Board,
        color: Color,
        budget: &SearchBudget,
    ) -> CompletedEndgame {
        let empty_squares = board.empty_cells().count_ones() as u8;
        let legal = moves::legal_moves(board, color);
        if legal == 0 {
            if !moves::has_legal_move(board, color.opponent()) {
                return CompletedEndgame {
                    outcome: SearchOutcome::GameOver,
                    score: Some(disc_difference(board, color)),
                    pv: Vec::new(),
                    completed_depth: empty_squares,
                    exact: true,
                };
            }

            return match self.negamax(board, color.opponent(), -65, 65, budget) {
                Ok(result) if !budget.interrupted_after_completion() => CompletedEndgame {
                    outcome: SearchOutcome::Pass,
                    score: Some(-result.score),
                    pv: result.pv,
                    completed_depth: empty_squares,
                    exact: true,
                },
                _ => CompletedEndgame {
                    outcome: SearchOutcome::Pass,
                    score: None,
                    pv: Vec::new(),
                    completed_depth: 0,
                    exact: false,
                },
            };
        }

        let fallback = Position::from_bit_index(legal.trailing_zeros() as u8);
        match self.negamax(board, color, -65, 65, budget) {
            Ok(result) if !budget.interrupted_after_completion() => CompletedEndgame {
                outcome: SearchOutcome::Move(result.pv[0]),
                score: Some(result.score),
                pv: result.pv,
                completed_depth: empty_squares,
                exact: true,
            },
            _ => CompletedEndgame {
                outcome: SearchOutcome::Move(fallback),
                score: None,
                pv: Vec::new(),
                completed_depth: 0,
                exact: false,
            },
        }
    }

    fn negamax(
        &mut self,
        board: &Board,
        color: Color,
        mut alpha: i32,
        beta: i32,
        budget: &SearchBudget,
    ) -> Result<NodeResult, ()> {
        if budget.interrupted(*self.nodes_searched) {
            return Err(());
        }
        *self.nodes_searched += 1;

        let hash = self.zobrist.hash(board, color);
        let mut tt_move = None;
        if let Some(entry) = self.table.get(&hash) {
            tt_move = entry.best_move;
            match entry.bound {
                Bound::Exact => {
                    return Ok(NodeResult {
                        score: entry.score,
                        pv: entry.pv.clone(),
                    });
                }
                Bound::LowerBound if entry.score >= beta => {
                    return Ok(NodeResult {
                        score: entry.score,
                        pv: Vec::new(),
                    });
                }
                Bound::UpperBound if entry.score <= alpha => {
                    return Ok(NodeResult {
                        score: entry.score,
                        pv: Vec::new(),
                    });
                }
                Bound::LowerBound if entry.score > alpha => alpha = entry.score,
                _ => {}
            }
        }

        let legal = moves::legal_moves(board, color);
        if legal == 0 {
            if !moves::has_legal_move(board, color.opponent()) {
                return Ok(NodeResult {
                    score: disc_difference(board, color),
                    pv: Vec::new(),
                });
            }
            let child = self.negamax(board, color.opponent(), -beta, -alpha, budget)?;
            return Ok(NodeResult {
                score: -child.score,
                pv: child.pv,
            });
        }

        let original_alpha = alpha;
        let ordered = order_endgame_moves(board, color, legal, tt_move);
        let mut best_score = -65;
        let mut best_move = ordered[0];
        let mut best_pv = Vec::new();

        for position in ordered {
            let child = self.negamax(
                &moves::make_move(board, color, position),
                color.opponent(),
                -beta,
                -alpha,
                budget,
            )?;
            let score = -child.score;
            if score > best_score {
                best_score = score;
                best_move = position;
                best_pv = Vec::with_capacity(1 + child.pv.len());
                best_pv.push(position);
                best_pv.extend(child.pv);
            }
            alpha = alpha.max(score);
            if alpha >= beta {
                break;
            }
        }

        let bound = if best_score <= original_alpha {
            Bound::UpperBound
        } else if best_score >= beta {
            Bound::LowerBound
        } else {
            Bound::Exact
        };
        self.table.insert(
            hash,
            ExactEntry {
                score: best_score,
                bound,
                best_move: Some(best_move),
                pv: if bound == Bound::Exact {
                    best_pv.clone()
                } else {
                    Vec::new()
                },
            },
        );
        Ok(NodeResult {
            score: best_score,
            pv: best_pv,
        })
    }
}

fn disc_difference(board: &Board, color: Color) -> i32 {
    board.count(color) as i32 - board.count(color.opponent()) as i32
}

fn order_endgame_moves(
    board: &Board,
    color: Color,
    legal: u64,
    tt_move: Option<Position>,
) -> Vec<Position> {
    let mut ordered = order_moves(board, color, legal, tt_move, 4);
    ordered.sort_by_key(|position| {
        // Playing in an odd region first preserves the usual endgame parity
        // advantage. Keep the normal ordering as the stable tie breaker.
        std::cmp::Reverse(region_size(board.empty_cells(), *position) % 2)
    });
    ordered
}

fn region_size(empty: u64, start: Position) -> u32 {
    let mut visited = 0u64;
    let mut frontier = vec![start.bit_index()];
    while let Some(index) = frontier.pop() {
        let bit = 1u64 << index;
        if empty & bit == 0 || visited & bit != 0 {
            continue;
        }
        visited |= bit;
        let row = index / 8;
        let col = index % 8;
        for (row_delta, col_delta) in [(1i8, 0i8), (-1, 0), (0, 1), (0, -1)] {
            let next_row = row as i8 + row_delta;
            let next_col = col as i8 + col_delta;
            if (0..8).contains(&next_row) && (0..8).contains(&next_col) {
                frontier.push((next_row as u8 * 8) + next_col as u8);
            }
        }
    }
    visited.count_ones()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{atomic::AtomicBool, Arc};
    use std::time::Duration;
    use std::time::Instant;

    fn solve(board: &Board, color: Color) -> (CompletedEndgame, u64) {
        let keys = ZobristKeys::new();
        let mut nodes = 0;
        let result = EndgameSolver::new(&keys, &mut nodes).solve(
            board,
            color,
            &SearchBudget::with_time_limit(Duration::from_secs(30)),
        );
        (result, nodes)
    }

    #[test]
    fn solves_twelve_empty_fixture_with_final_margin() {
        let board = Board::from_string(
            "WWWWWWW.\nWWWWWWW.\nWWWWWWB.\nWWWWWB..\nWWWWWB..\nWWWWWB..\nWWWWWB..\nBBBBBBB.",
        )
        .unwrap();
        let (result, _) = solve(&board, Color::Black);
        assert!(result.exact);
        assert_eq!(result.score, Some(-28));
        assert_eq!(result.completed_depth, 12);
        assert_eq!(result.pv.len(), 12);
        assert!(matches!(result.outcome, SearchOutcome::Move(_)));
    }

    #[test]
    fn terminal_score_is_from_root_side() {
        let board = Board::from_string(
            "BBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBWW",
        )
        .unwrap();
        assert_eq!(solve(&board, Color::Black).0.score, Some(60));
        assert_eq!(solve(&board, Color::White).0.score, Some(-60));
    }

    #[test]
    fn forced_root_pass_keeps_the_root_side_score_and_played_pv() {
        let board = Board::from_string(
            "BBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBWB.",
        )
        .unwrap();
        let (result, _) = solve(&board, Color::Black);
        assert_eq!(result.outcome, SearchOutcome::Pass);
        assert!(result.exact);
        assert_eq!(result.score, Some(58));
        assert_eq!(result.pv, vec![Position::new(7, 7)]);
    }

    #[test]
    fn interruption_never_claims_exactness() {
        let board = sixteen_empty_board();
        let keys = ZobristKeys::new();
        let mut nodes = 0;
        let result = EndgameSolver::new(&keys, &mut nodes).solve(
            &board,
            Color::Black,
            &SearchBudget::with_time_limit(Duration::from_secs(30)).with_node_limit(1),
        );
        assert!(!result.exact);
        assert_eq!(result.score, None);
        assert!(result.pv.is_empty());
    }

    #[test]
    fn deadline_and_cancellation_at_sixteen_empty_squares_never_claim_exactness() {
        let board = sixteen_empty_board();
        let interrupted = |budget: SearchBudget| {
            let keys = ZobristKeys::new();
            let mut nodes = 0;
            EndgameSolver::new(&keys, &mut nodes).solve(&board, Color::Black, &budget)
        };

        let expired = interrupted(SearchBudget::new(Instant::now()));
        let cancelled = interrupted(
            SearchBudget::with_time_limit(Duration::from_secs(30))
                .with_cancellation(Arc::new(AtomicBool::new(true))),
        );
        for result in [expired, cancelled] {
            assert!(!result.exact);
            assert_eq!(result.score, None);
            assert!(result.pv.is_empty());
            assert!(
                matches!(result.outcome, SearchOutcome::Move(position) if moves::legal_moves(&board, Color::Black) & position.bit_mask() != 0)
            );
        }
    }

    #[test]
    fn solves_oracle_checked_thirteen_to_sixteen_empty_fixtures() {
        // Egaroucid v7.8.1 `-solve`, fixed depth 20, independently reports
        // these root-side final disc differentials. The fixtures are legal
        // positions from one deterministic game, not synthetic board shapes.
        let fixtures = [
            (
                "..B.W.....BBW.WB.B.WWWBW.WWWBBWWB.WBBWWWWWWWWBW.WWBWBBB.BBBBBBB.",
                Color::Black,
                6,
                16,
            ),
            (
                "..B.W.B...BBW.BB.B.WWWBW.WWWBBWWB.WBBWWWWWWWWBW.WWBWBBB.BBBBBBB.",
                Color::White,
                10,
                15,
            ),
            (
                "..B.W.B...BBW.BB.B.WWWBW.WWWBBWWB.WBWWWWWWWWWWW.WWBWBBW.BBBBBBBW",
                Color::Black,
                -10,
                14,
            ),
            (
                "..B.W.B...BBW.BB.BBBBBBW.BBWBBWWB.BBWWWWWWBWWWW.WWBWBBW.BBBBBBBW",
                Color::White,
                20,
                13,
            ),
        ];

        for (flat, color, expected_score, empty_squares) in fixtures {
            let board = Board::from_string(&format_board(flat)).unwrap();
            let (result, nodes) = solve(&board, color);
            assert!(
                result.exact,
                "{empty_squares}-empty fixture was interrupted"
            );
            assert_eq!(result.score, Some(expected_score));
            assert!(
                matches!(result.outcome, SearchOutcome::Move(position) if moves::legal_moves(&board, color) & position.bit_mask() != 0)
            );
            assert_eq!(result.completed_depth, empty_squares);
            if empty_squares == 16 {
                assert!(nodes <= 1_000_000, "16-empty fixture used {nodes} nodes");
            }
        }
    }

    fn sixteen_empty_board() -> Board {
        Board::from_string(&format_board(
            "..B.W.....BBW.WB.B.WWWBW.WWWBBWWB.WBBWWWWWWWWBW.WWBWBBB.BBBBBBB.",
        ))
        .unwrap()
    }

    fn format_board(flat: &str) -> String {
        flat.as_bytes()
            .chunks(8)
            .map(std::str::from_utf8)
            .collect::<Result<Vec<_>, _>>()
            .unwrap()
            .join("\n")
    }
}
