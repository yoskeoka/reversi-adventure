use reversi_engine::board::Board;
use reversi_engine::types::Color;

// Edge discs cannot be an interior member of a horizontal, vertical, or
// diagonal flip line except along the edge itself. An occupied corner anchors
// a same-color run, and a filled edge has no future placement on that line.
const EDGES: [[u8; 8]; 4] = [
    [0, 1, 2, 3, 4, 5, 6, 7],
    [56, 57, 58, 59, 60, 61, 62, 63],
    [0, 8, 16, 24, 32, 40, 48, 56],
    [7, 15, 23, 31, 39, 47, 55, 63],
];

pub(super) fn proven_discs(board: &Board) -> (u64, u64) {
    let black = board.pieces(Color::Black);
    let white = board.pieces(Color::White);
    let mut stable_black = 0;
    let mut stable_white = 0;
    for edge in EDGES {
        let mask = edge.iter().fold(0, |mask, &index| mask | (1u64 << index));
        if (black | white) & mask == mask {
            stable_black |= black & mask;
            stable_white |= white & mask;
            continue;
        }
        let mut reversed = edge;
        reversed.reverse();
        for ordered in [edge, reversed] {
            let corner = 1u64 << ordered[0];
            let (owned, stable) = if black & corner != 0 {
                (black, &mut stable_black)
            } else if white & corner != 0 {
                (white, &mut stable_white)
            } else {
                continue;
            };
            for index in ordered {
                let bit = 1u64 << index;
                if owned & bit == 0 {
                    break;
                }
                *stable |= bit;
            }
        }
    }
    (stable_black, stable_white)
}

pub(super) fn score_interval(board: &Board, color: Color) -> (i32, i32, u32) {
    let (black, white) = proven_discs(board);
    let (own, opponent) = if color == Color::Black {
        (black, white)
    } else {
        (white, black)
    };
    let own_count = own.count_ones() as i32;
    let opponent_count = opponent.count_ones() as i32;
    (
        2 * own_count - 64,
        64 - 2 * opponent_count,
        (own_count + opponent_count) as u32,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use reversi_engine::moves;
    use std::collections::HashSet;

    fn terminals(
        board: Board,
        color: Color,
        seen: &mut HashSet<(Board, Color)>,
        out: &mut Vec<Board>,
    ) {
        if !seen.insert((board, color)) {
            return;
        }
        let mut legal = moves::legal_moves(&board, color);
        if legal == 0 {
            if moves::has_legal_move(&board, color.opponent()) {
                terminals(board, color.opponent(), seen, out);
            } else {
                out.push(board);
            }
            return;
        }
        while legal != 0 {
            let index = legal.trailing_zeros() as u8;
            legal &= legal - 1;
            let position = reversi_engine::types::Position::from_bit_index(index);
            terminals(
                moves::make_move(&board, color, position),
                color.opponent(),
                seen,
                out,
            );
        }
    }

    #[test]
    fn proven_discs_and_score_interval_hold_for_every_legal_continuation() {
        let start = Board::from_string(
            "..B.W.....BBW.WB.B.WWWBW.WWWBBWWB.WBBWWWWWWWWBW.WWBWBBB.BBBBBBB."
                .as_bytes()
                .chunks(8)
                .map(|row| std::str::from_utf8(row).unwrap())
                .collect::<Vec<_>>()
                .join("\n")
                .as_str(),
        )
        .unwrap();
        let mut board = start;
        let mut color = Color::Black;
        while board.empty_cells().count_ones() > 5 {
            let legal = moves::legal_moves(&board, color);
            if legal == 0 {
                color = color.opponent();
                continue;
            }
            let position =
                reversi_engine::types::Position::from_bit_index(legal.trailing_zeros() as u8);
            board = moves::make_move(&board, color, position);
            color = color.opponent();
        }
        let mut seen = HashSet::new();
        let mut final_boards = Vec::new();
        terminals(board, color, &mut seen, &mut final_boards);
        assert!(seen.len() > 10);
        for (node, side) in seen {
            let (stable_black, stable_white) = proven_discs(&node);
            let (lower, upper, _) = score_interval(&node, side);
            let mut node_seen = HashSet::new();
            let mut descendants = Vec::new();
            terminals(node, side, &mut node_seen, &mut descendants);
            for terminal in descendants {
                assert_eq!(stable_black & !terminal.pieces(Color::Black), 0);
                assert_eq!(stable_white & !terminal.pieces(Color::White), 0);
                let score = terminal.count(side) as i32 - terminal.count(side.opponent()) as i32;
                assert!((lower..=upper).contains(&score));
            }
        }
        let forced_pass = Board::from_string(
            "BBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBWB.",
        )
        .unwrap();
        let (black_lower, black_upper, _) = score_interval(&forced_pass, Color::Black);
        let (white_lower, white_upper, _) = score_interval(&forced_pass, Color::White);
        assert_eq!((black_lower, black_upper), (-white_upper, -white_lower));
        let mut pass_seen = HashSet::new();
        let mut pass_terminals = Vec::new();
        terminals(
            forced_pass,
            Color::Black,
            &mut pass_seen,
            &mut pass_terminals,
        );
        assert!(!pass_terminals.is_empty());
        for terminal in pass_terminals {
            let score = terminal.count(Color::Black) as i32 - terminal.count(Color::White) as i32;
            assert!((black_lower..=black_upper).contains(&score));
            assert!((white_lower..=white_upper).contains(&-score));
        }
    }
}
