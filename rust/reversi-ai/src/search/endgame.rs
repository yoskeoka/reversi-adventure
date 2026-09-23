use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::{Color, Position};

use super::ordering::order_moves;
use super::tt::{Bound, ZobristKeys};
use super::{SearchBudget, SearchOutcome};

const EXACT_TABLE_CAPACITY: usize = 1 << 21;

#[derive(Clone, Copy)]
struct ExactEntry {
    hash: u64,
    black: u64,
    white: u64,
    color: Color,
    depth: u8,
    score: i32,
    bound: Bound,
    best_move: Option<Position>,
}

struct NodeResult {
    score: i32,
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
    table: Vec<Option<ExactEntry>>,
    nodes_searched: &'a mut u64,
}

impl<'a> EndgameSolver<'a> {
    pub(crate) fn new(zobrist: &'a ZobristKeys, nodes_searched: &'a mut u64) -> Self {
        Self {
            zobrist,
            table: vec![None; EXACT_TABLE_CAPACITY],
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
                Ok(result) if !budget.interrupted_after_completion() => self.complete(
                    board,
                    color,
                    -result.score,
                    empty_squares,
                    budget,
                    SearchOutcome::Pass,
                ),
                _ => self.incomplete(SearchOutcome::Pass),
            };
        }

        let fallback = Position::from_bit_index(legal.trailing_zeros() as u8);
        match self.negamax(board, color, -65, 65, budget) {
            Ok(result) if !budget.interrupted_after_completion() => self.complete(
                board,
                color,
                result.score,
                empty_squares,
                budget,
                SearchOutcome::Move(fallback),
            ),
            _ => self.incomplete(SearchOutcome::Move(fallback)),
        }
    }

    fn incomplete(&self, outcome: SearchOutcome) -> CompletedEndgame {
        CompletedEndgame {
            outcome,
            score: None,
            pv: Vec::new(),
            completed_depth: 0,
            exact: false,
        }
    }

    fn complete(
        &mut self,
        board: &Board,
        color: Color,
        score: i32,
        depth: u8,
        budget: &SearchBudget,
        fallback: SearchOutcome,
    ) -> CompletedEndgame {
        match self.reconstruct(board, color, score, budget) {
            Ok(pv) if !budget.interrupted_after_completion() => CompletedEndgame {
                outcome: match fallback {
                    SearchOutcome::Move(_) => SearchOutcome::Move(pv[0]),
                    other => other,
                },
                score: Some(score),
                pv,
                completed_depth: depth,
                exact: true,
            },
            _ => self.incomplete(fallback),
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
        if let Some(entry) = self.probe(hash, board, color) {
            tt_move = entry.best_move;
            match entry.bound {
                Bound::Exact => {
                    return Ok(NodeResult { score: entry.score });
                }
                Bound::LowerBound if entry.score >= beta => {
                    return Ok(NodeResult { score: entry.score });
                }
                Bound::UpperBound if entry.score <= alpha => {
                    return Ok(NodeResult { score: entry.score });
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
                });
            }
            let child = self.negamax(board, color.opponent(), -beta, -alpha, budget)?;
            return Ok(NodeResult {
                score: -child.score,
            });
        }

        let original_alpha = alpha;
        let ordered = order_endgame_moves(board, color, legal, tt_move);
        let generated = moves::generated_moves(board, color);
        let mut best_score = -65;
        let mut best_move = ordered[0];

        for position in ordered {
            let generated_move = generated
                .iter()
                .find(|generated_move| generated_move.position == position)
                .expect("ordered move must have a generated descriptor");
            let child = self.negamax(
                &moves::make_move_with_flips(board, color, position, generated_move.flips),
                color.opponent(),
                -beta,
                -alpha,
                budget,
            )?;
            let score = -child.score;
            if score > best_score {
                best_score = score;
                best_move = position;
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
        self.store(
            hash,
            board,
            color,
            ExactEntry {
                hash,
                black: board.pieces(Color::Black),
                white: board.pieces(Color::White),
                color,
                depth: board.empty_cells().count_ones() as u8,
                score: best_score,
                bound,
                best_move: Some(best_move),
            },
        );
        Ok(NodeResult { score: best_score })
    }

    fn probe(&self, hash: u64, board: &Board, color: Color) -> Option<ExactEntry> {
        self.table[(hash as usize) % EXACT_TABLE_CAPACITY].filter(|entry| {
            entry.hash == hash
                && entry.black == board.pieces(Color::Black)
                && entry.white == board.pieces(Color::White)
                && entry.color == color
        })
    }
    fn store(&mut self, hash: u64, _board: &Board, _color: Color, entry: ExactEntry) {
        let index = (hash as usize) % EXACT_TABLE_CAPACITY;
        if self.table[index].is_none_or(|old| {
            entry.depth > old.depth
                || (entry.depth == old.depth
                    && entry.bound == Bound::Exact
                    && old.bound != Bound::Exact)
        }) {
            self.table[index] = Some(entry);
        }
    }
    fn reconstruct(
        &mut self,
        board: &Board,
        color: Color,
        score: i32,
        budget: &SearchBudget,
    ) -> Result<Vec<Position>, ()> {
        let (mut board, mut color, mut score) = (*board, color, score);
        let mut pv = Vec::with_capacity(board.empty_cells().count_ones() as usize);
        loop {
            if budget.interrupted(*self.nodes_searched) {
                return Err(());
            }
            let legal = moves::legal_moves(&board, color);
            if legal == 0 {
                if !moves::has_legal_move(&board, color.opponent()) {
                    return (disc_difference(&board, color) == score)
                        .then_some(pv)
                        .ok_or(());
                }
                color = color.opponent();
                score = -score;
                continue;
            }
            let hash = self.zobrist.hash(&board, color);
            let tt_move = self
                .probe(hash, &board, color)
                .and_then(|entry| entry.best_move);
            let generated = moves::generated_moves(&board, color);
            let mut selected = None;
            for position in order_endgame_moves(&board, color, legal, tt_move) {
                let generated_move = generated
                    .iter()
                    .find(|item| item.position == position)
                    .expect("ordered move must have a descriptor");
                let child =
                    moves::make_move_with_flips(&board, color, position, generated_move.flips);
                if -self
                    .negamax(&child, color.opponent(), -65, 65, budget)?
                    .score
                    == score
                {
                    selected = Some((position, child));
                    break;
                }
            }
            let (position, child) = selected.ok_or(())?;
            pv.push(position);
            board = child;
            color = color.opponent();
            score = -score;
        }
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
        // Independent fixed-depth solving reports these root-side final disc
        // differentials. The fixtures are legal positions from one
        // deterministic game, not synthetic board shapes.
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
            let _ = nodes;
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
