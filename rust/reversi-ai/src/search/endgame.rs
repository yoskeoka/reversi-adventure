use std::collections::HashMap;

use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::{Color, Position};

#[cfg(test)]
use super::ordering::order_moves;
use super::tt::{Bound, ZobristKeys};
use super::{SearchBudget, SearchOutcome};

const NOT_A_FILE: u64 = 0xfefefefefefefefe;
const NOT_H_FILE: u64 = 0x7f7f7f7f7f7f7f7f;

// Keep in step with the secondary ordering in search/ordering.rs. The exact
// solver needs its scores without allocating the heuristic move vector.
#[rustfmt::skip]
const POSITION_WEIGHTS: [i32; 64] = [
    120, -20,  20,   5,   5,  20, -20, 120,
    -20, -40,  -5,  -5,  -5,  -5, -40, -20,
     20,  -5,  15,   3,   3,  15,  -5,  20,
      5,  -5,   3,   3,   3,   3,  -5,   5,
      5,  -5,   3,   3,   3,   3,  -5,   5,
     20,  -5,  15,   3,   3,  15,  -5,  20,
    -20, -40,  -5,  -5,  -5,  -5, -40, -20,
    120, -20,  20,   5,   5,  20, -20, 120,
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct EmptyRegions {
    empty: u64,
    component: [u64; 64],
}

impl EmptyRegions {
    fn new(empty: u64) -> Self {
        let mut state = Self {
            empty,
            component: [0; 64],
        };
        let mut unseen = empty;
        while unseen != 0 {
            let region = flood(unseen.isolate_lowest_one(), empty);
            state.assign(region);
            unseen &= !region;
        }
        state
    }

    fn assign(&mut self, mut region: u64) {
        let mask = region;
        while region != 0 {
            let index = region.trailing_zeros() as usize;
            self.component[index] = mask;
            region &= region - 1;
        }
    }

    fn after_placement(mut self, position: Position) -> Self {
        let bit = position.bit_mask();
        let former = self.component[position.bit_index() as usize] & !bit;
        self.empty &= !bit;
        self.component[position.bit_index() as usize] = 0;
        let mut remaining = former;
        while remaining != 0 {
            let region = flood(remaining.isolate_lowest_one(), former);
            self.assign(region);
            remaining &= !region;
        }
        self
    }

    fn is_odd(&self, position: Position) -> bool {
        self.component[position.bit_index() as usize].count_ones() & 1 != 0
    }
}

fn flood(seed: u64, allowed: u64) -> u64 {
    let mut region = seed;
    loop {
        let adjacent = (region << 8)
            | (region >> 8)
            | ((region & NOT_H_FILE) << 1)
            | ((region & NOT_A_FILE) >> 1);
        let next = region | (adjacent & allowed);
        if next == region {
            return region;
        }
        region = next;
    }
}

#[derive(Clone, Copy)]
struct ExactMove {
    position: Position,
    successor: Board,
    priority: i32,
    odd: bool,
}

fn ordered_exact_moves<const CAP: usize>(
    board: &Board,
    color: Color,
    legal: u64,
    regions: &EmptyRegions,
    tt_move: Option<Position>,
) -> ([ExactMove; CAP], usize) {
    let blank = ExactMove {
        position: Position::new(0, 0),
        successor: *board,
        priority: 0,
        odd: false,
    };
    let mut result = [blank; CAP];
    let mut len = 0;
    let mut remaining = legal;
    while remaining != 0 {
        let index = remaining.trailing_zeros() as u8;
        remaining &= remaining - 1;
        debug_assert!(len < CAP);
        let position = Position::from_bit_index(index);
        let flips = moves::flipped_pieces(board, color, position);
        let successor = moves::make_move_with_flips(board, color, position, flips);
        let priority = if CAP == 1 {
            0
        } else {
            let mobility = moves::legal_moves(&successor, color.opponent()).count_ones() as i32;
            (if tt_move == Some(position) { 10_000 } else { 0 })
                + if [0, 7, 56, 63].contains(&index) {
                    5_000
                } else {
                    0
                }
                - mobility * 100
                + POSITION_WEIGHTS[index as usize]
        };
        let item = ExactMove {
            position,
            successor,
            priority,
            odd: regions.is_odd(position),
        };
        // Stable insertion: equal priorities retain ascending bit-index order.
        let mut insertion = len;
        while insertion > 0
            && (tt_move == Some(item.position), item.odd, item.priority)
                > (
                    tt_move == Some(result[insertion - 1].position),
                    result[insertion - 1].odd,
                    result[insertion - 1].priority,
                )
        {
            result[insertion] = result[insertion - 1];
            insertion -= 1;
        }
        result[insertion] = item;
        len += 1;
    }
    (result, len)
}

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

#[derive(Clone, Copy)]
struct SmallResult {
    score: i32,
    pv: [Position; 4],
    len: u8,
}

impl SmallResult {
    fn empty(score: i32) -> Self {
        Self {
            score,
            pv: [Position::new(0, 0); 4],
            len: 0,
        }
    }

    fn prepend(score: i32, position: Position, child: Self) -> Self {
        let mut result = Self::empty(score);
        result.pv[0] = position;
        result.pv[1..1 + child.len as usize].copy_from_slice(&child.pv[..child.len as usize]);
        result.len = child.len + 1;
        result
    }

    fn into_node(self) -> NodeResult {
        NodeResult {
            score: self.score,
            pv: self.pv[..self.len as usize].to_vec(),
        }
    }
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
                    score: Some(terminal_score(board, color)),
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
        alpha: i32,
        beta: i32,
        budget: &SearchBudget,
    ) -> Result<NodeResult, ()> {
        self.negamax_with_regions(
            board,
            color,
            alpha,
            beta,
            budget,
            EmptyRegions::new(board.empty_cells()),
        )
    }

    fn negamax_with_regions(
        &mut self,
        board: &Board,
        color: Color,
        alpha: i32,
        beta: i32,
        budget: &SearchBudget,
        regions: EmptyRegions,
    ) -> Result<NodeResult, ()> {
        // The four final placement counts enter distinct scalar paths. A pass
        // preserves the count and the empty-region state.
        match regions.empty.count_ones() {
            1 => self.last_one(board, color, alpha, beta, budget, regions),
            2 => self.last_two(board, color, alpha, beta, budget, regions),
            3 => self.last_three(board, color, alpha, beta, budget, regions),
            4 => self.last_four(board, color, alpha, beta, budget, regions),
            5..=16 => self.search_node::<16>(board, color, alpha, beta, budget, regions),
            17..=32 => self.search_node::<32>(board, color, alpha, beta, budget, regions),
            _ => self.search_node::<64>(board, color, alpha, beta, budget, regions),
        }
    }

    fn last_one(
        &mut self,
        board: &Board,
        color: Color,
        alpha: i32,
        beta: i32,
        budget: &SearchBudget,
        regions: EmptyRegions,
    ) -> Result<NodeResult, ()> {
        self.search_small::<1>(board, color, alpha, beta, budget, regions)
            .map(SmallResult::into_node)
    }

    fn last_two(
        &mut self,
        board: &Board,
        color: Color,
        alpha: i32,
        beta: i32,
        budget: &SearchBudget,
        regions: EmptyRegions,
    ) -> Result<NodeResult, ()> {
        self.search_small::<2>(board, color, alpha, beta, budget, regions)
            .map(SmallResult::into_node)
    }

    fn last_three(
        &mut self,
        board: &Board,
        color: Color,
        alpha: i32,
        beta: i32,
        budget: &SearchBudget,
        regions: EmptyRegions,
    ) -> Result<NodeResult, ()> {
        self.search_small::<3>(board, color, alpha, beta, budget, regions)
            .map(SmallResult::into_node)
    }

    fn last_four(
        &mut self,
        board: &Board,
        color: Color,
        alpha: i32,
        beta: i32,
        budget: &SearchBudget,
        regions: EmptyRegions,
    ) -> Result<NodeResult, ()> {
        self.search_small::<4>(board, color, alpha, beta, budget, regions)
            .map(SmallResult::into_node)
    }

    fn small_with_regions(
        &mut self,
        board: &Board,
        color: Color,
        alpha: i32,
        beta: i32,
        budget: &SearchBudget,
        regions: EmptyRegions,
    ) -> Result<SmallResult, ()> {
        match regions.empty.count_ones() {
            0 | 1 => self.search_small::<1>(board, color, alpha, beta, budget, regions),
            2 => self.search_small::<2>(board, color, alpha, beta, budget, regions),
            3 => self.search_small::<3>(board, color, alpha, beta, budget, regions),
            4 => self.search_small::<4>(board, color, alpha, beta, budget, regions),
            _ => unreachable!("small search has at most four empties"),
        }
    }

    fn search_small<const CAP: usize>(
        &mut self,
        board: &Board,
        color: Color,
        mut alpha: i32,
        beta: i32,
        budget: &SearchBudget,
        regions: EmptyRegions,
    ) -> Result<SmallResult, ()> {
        // Count every scalar invocation, including passes, probes, re-searches,
        // and the terminal call. This is the same budget boundary as search_node.
        if budget.interrupted(*self.nodes_searched) {
            return Err(());
        }
        *self.nodes_searched += 1;

        let legal = moves::legal_moves(board, color);
        if legal == 0 {
            if !moves::has_legal_move(board, color.opponent()) {
                return Ok(SmallResult::empty(terminal_score(board, color)));
            }
            let child =
                self.small_with_regions(board, color.opponent(), -beta, -alpha, budget, regions)?;
            return Ok(SmallResult {
                score: -child.score,
                ..child
            });
        }

        let (ordered, move_count) = ordered_exact_moves::<CAP>(board, color, legal, &regions, None);
        let mut best = SmallResult::empty(-65);
        for (index, item) in ordered[..move_count].iter().enumerate() {
            let child_regions = regions.after_placement(item.position);
            let child = if index == 0 {
                self.small_with_regions(
                    &item.successor,
                    color.opponent(),
                    -beta,
                    -alpha,
                    budget,
                    child_regions,
                )?
            } else {
                self.diagnostics.null_window_calls += 1;
                let probe = self.small_with_regions(
                    &item.successor,
                    color.opponent(),
                    -alpha - 1,
                    -alpha,
                    budget,
                    child_regions,
                )?;
                let probe_score = -probe.score;
                if probe_score > alpha {
                    self.diagnostics.fail_highs += 1;
                }
                if probe_score > alpha && probe_score < beta {
                    self.diagnostics.full_researches += 1;
                    self.small_with_regions(
                        &item.successor,
                        color.opponent(),
                        -beta,
                        -alpha,
                        budget,
                        child_regions,
                    )?
                } else {
                    probe
                }
            };
            let score = -child.score;
            if score > best.score {
                best = SmallResult::prepend(score, item.position, child);
            }
            alpha = alpha.max(score);
            if alpha >= beta {
                break;
            }
        }
        Ok(best)
    }

    fn search_node<const CAP: usize>(
        &mut self,
        board: &Board,
        color: Color,
        mut alpha: i32,
        beta: i32,
        budget: &SearchBudget,
        regions: EmptyRegions,
    ) -> Result<NodeResult, ()> {
        // A node is one call, including TT hits, passes, null-window probes,
        // and re-searches. Poll before counting it, including at the last ply.
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
                    score: terminal_score(board, color),
                    pv: Vec::new(),
                });
            }
            let child =
                self.negamax_with_regions(board, color.opponent(), -beta, -alpha, budget, regions)?;
            return Ok(NodeResult {
                score: -child.score,
                pv: child.pv,
            });
        }

        let original_alpha = alpha;
        // Probe searches visit extra cache states. Keep equal-score move
        // selection independent of those states so the complete PV is stable.
        let (ordered, move_count) = ordered_exact_moves::<CAP>(board, color, legal, &regions, None);
        let mut best_score = -65;
        let mut best_pv = Vec::new();

        for (index, ordered_move) in ordered[..move_count].iter().enumerate() {
            let position = ordered_move.position;
            let successor = &ordered_move.successor;
            let child_regions = regions.after_placement(position);
            let child = if index == 0 {
                self.negamax_with_regions(
                    successor,
                    color.opponent(),
                    -beta,
                    -alpha,
                    budget,
                    child_regions,
                )?
            } else {
                self.diagnostics.null_window_calls += 1;
                let probe = self.negamax_with_regions(
                    successor,
                    color.opponent(),
                    -alpha - 1,
                    -alpha,
                    budget,
                    child_regions,
                )?;
                let probe_score = -probe.score;
                if probe_score > alpha {
                    self.diagnostics.fail_highs += 1;
                }
                if probe_score > alpha && probe_score < beta {
                    self.diagnostics.full_researches += 1;
                    self.negamax_with_regions(
                        successor,
                        color.opponent(),
                        -beta,
                        -alpha,
                        budget,
                        child_regions,
                    )?
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

pub(crate) fn terminal_score(board: &Board, color: Color) -> i32 {
    let own = board.count(color) as i32;
    let opponent = board.count(color.opponent()) as i32;
    if own == 0 && opponent > 0 {
        -64
    } else if opponent == 0 && own > 0 {
        64
    } else {
        own - opponent
    }
}

#[cfg(test)]
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

#[cfg(test)]
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

    #[test]
    fn removing_bridge_rebuilds_split_components_and_preserves_parent() {
        let left = Position::new(3, 2);
        let bridge = Position::new(3, 3);
        let right = Position::new(3, 4);
        let isolated = Position::new(7, 7);
        let empty = left.bit_mask() | bridge.bit_mask() | right.bit_mask() | isolated.bit_mask();
        let parent = EmptyRegions::new(empty);
        assert_eq!(parent.component[left.bit_index() as usize].count_ones(), 3);
        assert!(parent.is_odd(left));
        let child = parent.after_placement(bridge);
        assert_eq!(child.empty, empty & !bridge.bit_mask());
        for position in [left, right, isolated] {
            assert_eq!(
                child.component[position.bit_index() as usize],
                position.bit_mask()
            );
            assert!(child.is_odd(position));
        }
        assert_eq!(child.component[bridge.bit_index() as usize], 0);
        assert_eq!(parent, EmptyRegions::new(empty));
        assert_eq!(child, EmptyRegions::new(child.empty));
        // A pass carries the exact same region state.
        let passed = child;
        assert_eq!(passed, child);
    }

    #[test]
    fn fixed_order_matches_previous_stable_vec_order() {
        for board in [Board::new(), sixteen_empty_board()] {
            for color in [Color::Black, Color::White] {
                let legal = moves::legal_moves(&board, color);
                if legal == 0 {
                    continue;
                }
                let regions = EmptyRegions::new(board.empty_cells());
                let first = Some(Position::from_bit_index(legal.trailing_zeros() as u8));
                for tt_move in [None, first] {
                    let expected = order_endgame_moves(&board, color, legal, None);
                    let (actual, len) =
                        ordered_exact_moves::<64>(&board, color, legal, &regions, tt_move);
                    let positions = actual[..len]
                        .iter()
                        .map(|entry| entry.position)
                        .collect::<Vec<_>>();
                    if let Some(first) = tt_move {
                        assert_eq!(positions[0], first);
                        assert_eq!(
                            positions[1..],
                            expected
                                .into_iter()
                                .filter(|p| *p != first)
                                .collect::<Vec<_>>()
                        );
                    } else {
                        assert_eq!(positions, expected);
                    }
                }
            }
        }
    }

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
    fn early_wipeout_has_fixed_scores_from_either_root_side() {
        let board = Board::from_string(
            "BBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBB.",
        )
        .unwrap();
        assert_eq!(board.count(Color::Black), 63);
        assert_eq!(board.count(Color::White), 0);
        assert_eq!(board.empty_cells().count_ones(), 1);
        for (color, score) in [(Color::Black, 64), (Color::White, -64)] {
            assert_eq!(moves::legal_moves(&board, color), 0);
            let (result, _) = solve(&board, color);
            assert_eq!(result.outcome, SearchOutcome::GameOver);
            assert_eq!(result.score, Some(score));
            assert!(result.exact);
            assert!(result.pv.is_empty());
        }
    }

    #[test]
    fn exact_move_can_wipe_out_before_board_fills() {
        let mut board = Board::empty();
        for row in 0..8 {
            for col in 0..8 {
                board.set(Position::new(row, col), Color::Black);
            }
        }
        board.remove(Position::new(0, 0));
        board.remove(Position::new(7, 7));
        board.set(Position::new(7, 6), Color::White);
        let (result, _) = solve(&board, Color::Black);
        assert_eq!(result.outcome, SearchOutcome::Move(Position::new(7, 7)));
        assert_eq!(result.score, Some(64));
        assert!(result.exact);
        let final_board = moves::make_move(&board, Color::Black, Position::new(7, 7));
        assert_eq!(final_board.empty_cells().count_ones(), 1);
        assert_eq!(final_board.count(Color::Black), 63);
        assert_eq!(final_board.count(Color::White), 0);
    }

    #[test]
    fn ordinary_terminal_and_empty_board_use_actual_disc_difference() {
        let board = Board::from_string(
            "BBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBWW",
        )
        .unwrap();
        assert_eq!(solve(&board, Color::Black).0.score, Some(60));
        assert_eq!(solve(&board, Color::White).0.score, Some(-60));
        assert_eq!(solve(&Board::empty(), Color::Black).0.score, Some(0));
    }

    fn full_window_reference(board: &Board, color: Color) -> NodeResult {
        let legal = moves::legal_moves(board, color);
        if legal == 0 {
            if !moves::has_legal_move(board, color.opponent()) {
                return NodeResult {
                    score: terminal_score(board, color),
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

        fn check_all(
            board: Board,
            color: Color,
            seen: &mut HashSet<(Board, Color)>,
            counts: &mut [bool; 5],
            outcomes: &mut [bool; 3],
        ) {
            if !seen.insert((board, color)) {
                return;
            }
            let empties = board.empty_cells().count_ones() as usize;
            if empties <= 4 {
                counts[empties] = true;
            }
            let reference = full_window_reference(&board, color);
            let (result, _) = solve(&board, color);
            assert!(result.exact);
            assert_eq!(result.score, Some(reference.score));
            assert_eq!(result.pv, reference.pv);
            let legal = moves::legal_moves(&board, color);
            let expected_outcome = if legal != 0 {
                SearchOutcome::Move(reference.pv[0])
            } else if moves::has_legal_move(&board, color.opponent()) {
                SearchOutcome::Pass
            } else {
                SearchOutcome::GameOver
            };
            assert_eq!(result.outcome, expected_outcome);
            outcomes[match expected_outcome {
                SearchOutcome::Move(_) => 0,
                SearchOutcome::Pass => 1,
                SearchOutcome::GameOver => 2,
            }] = true;
            // Check both sides at every reached board, including forced passes.
            check_all(board, color.opponent(), seen, counts, outcomes);
            if legal == 0 {
                return;
            } else {
                for position in order_endgame_moves(&board, color, legal, None) {
                    check_all(
                        moves::make_move(&board, color, position),
                        color.opponent(),
                        seen,
                        counts,
                        outcomes,
                    );
                }
            }
        }

        let mut seen = HashSet::new();
        let mut counts = [false; 5];
        let mut outcomes = [false; 3];
        check_all(board, color, &mut seen, &mut counts, &mut outcomes);
        let forced_pass = Board::from_string(
            "BBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBWB.",
        )
        .unwrap();
        check_all(
            forced_pass,
            Color::Black,
            &mut seen,
            &mut counts,
            &mut outcomes,
        );
        let early_terminal = Board::from_string(
            "BBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBB.",
        )
        .unwrap();
        check_all(
            early_terminal,
            Color::Black,
            &mut seen,
            &mut counts,
            &mut outcomes,
        );
        assert!(seen.len() > 10);
        assert!(
            counts[1..=4].iter().all(|seen| *seen),
            "missing empty count: {counts:?}"
        );
        assert!(
            outcomes.iter().all(|seen| *seen),
            "missing outcome: {outcomes:?}"
        );
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
