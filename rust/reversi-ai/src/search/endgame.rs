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
    diagnostics: ExactPvsDiagnostics,
}

/// Counters for exact null-window probes and their outcomes.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ExactPvsDiagnostics {
    pub null_window_calls: u64,
    pub fail_highs: u64,
    pub full_researches: u64,
}

impl<'a> EndgameSolver<'a> {
    pub(crate) fn new(zobrist: &'a ZobristKeys, nodes_searched: &'a mut u64) -> Self {
        Self {
            zobrist,
            table: HashMap::new(),
            nodes_searched,
            diagnostics: ExactPvsDiagnostics::default(),
        }
    }

    pub(crate) fn diagnostics(&self) -> ExactPvsDiagnostics {
        self.diagnostics
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
        if let Some(entry) = self.table.get(&hash) {
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
        // Probe searches visit extra cache states. Keep equal-score move
        // selection independent of those states so the complete PV is stable.
        let ordered = order_endgame_moves(board, color, legal, None);
        let generated = moves::generated_moves(board, color);
        let mut best_score = -65;
        let mut best_pv = Vec::new();

        for (index, position) in ordered.into_iter().enumerate() {
            let generated_move = generated
                .iter()
                .find(|generated_move| generated_move.position == position)
                .expect("ordered move must have a generated descriptor");
            let successor =
                moves::make_move_with_flips(board, color, position, generated_move.flips);
            let child = if index == 0 {
                self.negamax(&successor, color.opponent(), -beta, -alpha, budget)?
            } else {
                self.diagnostics.null_window_calls += 1;
                let probe =
                    self.negamax(&successor, color.opponent(), -alpha - 1, -alpha, budget)?;
                let probe_score = -probe.score;
                if probe_score > alpha {
                    self.diagnostics.fail_highs += 1;
                }
                if probe_score > alpha && probe_score < beta {
                    self.diagnostics.full_researches += 1;
                    self.negamax(&successor, color.opponent(), -beta, -alpha, budget)?
                } else {
                    probe
                }
            };
            let score = -child.score;
            if score > best_score {
                best_score = score;
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

    fn full_window_reference(board: &Board, color: Color) -> NodeResult {
        let legal = moves::legal_moves(board, color);
        if legal == 0 {
            if !moves::has_legal_move(board, color.opponent()) {
                return NodeResult {
                    score: disc_difference(board, color),
                    pv: Vec::new(),
                };
            }
            let child = full_window_reference(board, color.opponent());
            return NodeResult {
                score: -child.score,
                pv: child.pv,
            };
        }
        let mut best = NodeResult {
            score: -65,
            pv: Vec::new(),
        };
        for position in order_endgame_moves(board, color, legal, None) {
            let child =
                full_window_reference(&moves::make_move(board, color, position), color.opponent());
            let score = -child.score;
            if score > best.score {
                best.score = score;
                best.pv = vec![position];
                best.pv.extend(child.pv);
            }
        }
        best
    }

    #[test]
    fn pvs_matches_full_window_reference_on_reachable_endgames() {
        let root = sixteen_empty_board();
        for choice in [0usize, 1, 2, 3] {
            let mut board = root;
            let mut color = Color::Black;
            while board.empty_cells().count_ones() > 6 {
                let mut legal = moves::legal_moves(&board, color);
                if legal == 0 {
                    color = color.opponent();
                    legal = moves::legal_moves(&board, color);
                    if legal == 0 {
                        break;
                    }
                }
                let ordered = order_endgame_moves(&board, color, legal, None);
                let position = ordered[choice % ordered.len()];
                board = moves::make_move(&board, color, position);
                color = color.opponent();
            }
            let reference = full_window_reference(&board, color);
            let (result, _) = solve(&board, color);
            assert!(result.exact);
            assert_eq!(result.score, Some(reference.score), "choice {choice}");
            assert_eq!(result.pv, reference.pv, "choice {choice}");
        }
    }

    #[test]
    fn pvs_matches_reference_for_every_reachable_four_empty_position() {
        use std::collections::HashSet;

        let mut board = sixteen_empty_board();
        let mut color = Color::Black;
        while board.empty_cells().count_ones() > 4 {
            let legal = moves::legal_moves(&board, color);
            if legal == 0 {
                color = color.opponent();
                continue;
            }
            let position = order_endgame_moves(&board, color, legal, None)[0];
            board = moves::make_move(&board, color, position);
            color = color.opponent();
        }

        fn check_all(board: Board, color: Color, seen: &mut HashSet<(Board, Color)>) {
            if !seen.insert((board, color)) {
                return;
            }
            let reference = full_window_reference(&board, color);
            let (result, _) = solve(&board, color);
            assert!(result.exact);
            assert_eq!(result.score, Some(reference.score));
            assert_eq!(result.pv, reference.pv);
            let legal = moves::legal_moves(&board, color);
            if legal == 0 {
                if moves::has_legal_move(&board, color.opponent()) {
                    check_all(board, color.opponent(), seen);
                }
            } else {
                for position in order_endgame_moves(&board, color, legal, None) {
                    check_all(
                        moves::make_move(&board, color, position),
                        color.opponent(),
                        seen,
                    );
                }
            }
        }

        let mut seen = HashSet::new();
        check_all(board, color, &mut seen);
        assert!(seen.len() > 10);
    }

    #[test]
    fn null_window_diagnostics_include_research() {
        let board = sixteen_empty_board();
        let keys = ZobristKeys::new();
        let mut nodes = 0;
        let mut solver = EndgameSolver::new(&keys, &mut nodes);
        let completed = solver.solve(
            &board,
            Color::Black,
            &SearchBudget::with_time_limit(Duration::from_secs(30)),
        );
        let diagnostics = solver.diagnostics();
        assert!(completed.exact);
        assert!(diagnostics.null_window_calls > 0);
        assert!(diagnostics.fail_highs >= diagnostics.full_researches);
        assert!(diagnostics.full_researches > 0);
    }

    #[test]
    fn interruption_after_research_started_discards_exact_attempt() {
        let board = sixteen_empty_board();
        let keys = ZobristKeys::new();
        let mut nodes = 0;
        let mut solver = EndgameSolver::new(&keys, &mut nodes);
        let result = solver.solve(
            &board,
            Color::Black,
            &SearchBudget::with_node_limit_only(10_000),
        );
        assert!(solver.diagnostics().full_researches > 0);
        assert!(!result.exact);
        assert_eq!(result.score, None);
        assert!(result.pv.is_empty());
    }

    #[test]
    fn null_window_cache_bound_is_safe_for_full_window_reuse() {
        let board = Board::from_string(
            "WWWWWWW.\nWWWWWWW.\nWWWWWWB.\nWWWWWB..\nWWWWWB..\nWWWWWB..\nWWWWWB..\nBBBBBBB.",
        )
        .unwrap();
        let keys = ZobristKeys::new();
        let mut nodes = 0;
        let mut solver = EndgameSolver::new(&keys, &mut nodes);
        let budget = SearchBudget::with_time_limit(Duration::from_secs(30));
        solver
            .negamax(&board, Color::Black, -1, 0, &budget)
            .unwrap();
        let entry = solver.table.get(&keys.hash(&board, Color::Black)).unwrap();
        assert_ne!(entry.bound, Bound::Exact);
        assert!(entry.pv.is_empty());
        let complete = solver
            .negamax(&board, Color::Black, -65, 65, &budget)
            .unwrap();
        assert_eq!(complete.score, -28);
        assert_eq!(complete.pv.len(), 12);
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
            if empty_squares == 16 {
                assert!(nodes <= 1_000_000, "16-empty fixture used {nodes} nodes");
            }
        }
    }

    #[test]
    fn benchmark_exact_roots_match_checked_oracle_scores_and_optimal_moves() {
        use serde_json::Value;

        let corpus = include_str!("../../../../tools/reversi-ai-benchmark/positions-v1.jsonl");
        let reference = include_str!("../../../../tools/reversi-ai-benchmark/reference-v1.jsonl");
        let positions: Vec<Value> = corpus
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
        let reports: Vec<Value> = reference
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
        let baseline_pvs = [
            "a6 f1 g2 a4 c1 d1 g1 b2 a1 b1 a2 h1 h2 a7 a8 b7",
            "d1 c1 a6 a1 b1 b2 g2 e7 h1 b7 h8 h7 g8 f8 b8 a8",
            "a8 c8 a7 h8 g7 h3 g3 g2 h1 h2 b1 b2 a2 a4 a1 a3",
            "a3 a4 b3 e1 h8 a1 b7 a8 h7 b2 a2 g2 g1 h1 h2 f1",
        ];
        let mut checked = 0;
        for (position, report) in positions.iter().zip(&reports) {
            if report["workload"] != "exact-16" {
                continue;
            }
            assert_eq!(position["position_id"], report["position_id"]);
            let board =
                Board::from_string(&format_board(position["board"].as_str().unwrap())).unwrap();
            let color = if position["side_to_move"] == "B" {
                Color::Black
            } else {
                Color::White
            };
            let (result, _) = solve(&board, color);
            assert!(result.exact);
            assert_eq!(result.completed_depth, 16);
            assert_eq!(
                result.score,
                report["analysis"]["best_value"].as_i64().map(|v| v as i32)
            );
            let SearchOutcome::Move(best_move) = result.outcome else {
                panic!("exact reference root must have a move");
            };
            let best_name = format!("{}{}", (b'a' + best_move.col) as char, best_move.row + 1);
            assert!(report["analysis"]["optimal_moves"]
                .as_array()
                .unwrap()
                .iter()
                .any(|name| name == &best_name));
            let actual_pv = result
                .pv
                .iter()
                .map(|move_| format!("{}{}", (b'a' + move_.col) as char, move_.row + 1))
                .collect::<Vec<_>>();
            assert_eq!(
                actual_pv,
                baseline_pvs[checked].split_whitespace().collect::<Vec<_>>()
            );
            checked += 1;
        }
        assert_eq!(checked, 4);
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
