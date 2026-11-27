//! One placement frontier for the fixed Table32 corpus.
use reversi_engine::{
    board::Board,
    moves::{generated_moves, has_legal_move, make_move_with_flips},
    types::Color,
};
use std::collections::HashSet;
use std::io::{self, BufRead, BufWriter, Write};

type Position = (u64, u64, bool, bool);
type SymmetryTable = [[[u64; 256]; 8]; 8];

fn min_image(table: &SymmetryTable, board: Board) -> (u64, u64) {
    table
        .iter()
        .map(|rows| {
            let mut black = 0;
            let mut white = 0;
            for (row, (black_byte, white_byte)) in rows.iter().zip(
                board
                    .black
                    .to_le_bytes()
                    .into_iter()
                    .zip(board.white.to_le_bytes()),
            ) {
                black |= row[usize::from(black_byte)];
                white |= row[usize::from(white_byte)];
            }
            (black, white)
        })
        .min()
        .unwrap()
}

fn symmetry_table() -> SymmetryTable {
    let mut table = [[[0; 256]; 8]; 8];
    for (symmetry, rows) in table.iter_mut().enumerate() {
        for (row, bytes) in rows.iter_mut().enumerate() {
            for (byte, bits) in bytes.iter_mut().enumerate() {
                for col in 0..8 {
                    if byte & (1 << col) == 0 {
                        continue;
                    }
                    let (mut r, mut c) = if symmetry & 4 == 0 {
                        (row, col)
                    } else {
                        (col, row)
                    };
                    if symmetry & 2 != 0 {
                        r = 7 - r;
                    }
                    if symmetry & 1 != 0 {
                        c = 7 - c;
                    }
                    *bits |= 1 << (8 * r + c);
                }
            }
        }
    }
    table
}

fn expand(
    board: Board,
    white_to_move: bool,
    table: &SymmetryTable,
    output: &mut HashSet<Position>,
) {
    let color = if white_to_move {
        Color::White
    } else {
        Color::Black
    };
    let opponent = color.opponent();
    for step in generated_moves(&board, color) {
        let next = make_move_with_flips(&board, color, step.position, step.flips);
        let (white, terminal) = if has_legal_move(&next, opponent) {
            (!white_to_move, false)
        } else {
            (white_to_move, !has_legal_move(&next, color))
        };
        let (black_mask, white_mask) = min_image(table, next);
        output.insert((black_mask, white_mask, white, terminal));
    }
}

// The verifier walks coordinate rays from the mover's stones to candidate
// empty endpoints. It does not invoke the engine's bitboard move operations.
fn scalar_moves(board: &[i8; 64], color: i8) -> [u64; 64] {
    let mut moves = [0; 64];
    for (square, &stone) in board.iter().enumerate() {
        if stone != color {
            continue;
        }
        let row = (square / 8) as i32;
        let col = (square % 8) as i32;
        for dr in -1..=1 {
            for dc in -1..=1 {
                if dr == 0 && dc == 0 {
                    continue;
                }
                let (mut r, mut c) = (row + dr, col + dc);
                let mut flips = 0;
                while (0..8).contains(&r) && (0..8).contains(&c) {
                    let index = (8 * r + c) as usize;
                    if board[index] != -color {
                        if board[index] == 0 {
                            moves[index] |= flips;
                        }
                        break;
                    }
                    flips |= 1 << index;
                    r += dr;
                    c += dc;
                }
            }
        }
    }
    moves
}

fn scalar_image(black: u64, white: u64) -> (u64, u64) {
    // Rotate four times with and without reflection, independently of the
    // generator's transpose/mirror lookup table.
    let mut images = [[(0, 0); 2]; 4];
    let mut occupied = black | white;
    while occupied != 0 {
        let square = occupied.trailing_zeros();
        let mut row = square / 8;
        let mut col = square % 8;
        let is_black = black & (1 << square) != 0;
        for rotation in &mut images {
            let direct = 1 << (8 * row + col);
            let mirror = 1 << (8 * row + (7 - col));
            if is_black {
                rotation[0].0 |= direct;
                rotation[1].0 |= mirror;
            } else {
                rotation[0].1 |= direct;
                rotation[1].1 |= mirror;
            }
            (row, col) = (col, 7 - row);
        }
        occupied &= occupied - 1;
    }
    images.into_iter().flatten().min().unwrap()
}

fn scalar_board(black: u64, white: u64) -> [i8; 64] {
    std::array::from_fn(|index| {
        let square = 1 << index;
        if black & square != 0 {
            1
        } else if white & square != 0 {
            -1
        } else {
            0
        }
    })
}

fn expand_independently(
    black: u64,
    white: u64,
    white_to_move: bool,
    output: &mut HashSet<Position>,
) {
    let color = if white_to_move { -1 } else { 1 };
    for (square, flips) in scalar_moves(&scalar_board(black, white), color)
        .into_iter()
        .enumerate()
    {
        if flips == 0 {
            continue;
        }
        let placed = flips | 1 << square;
        let (next_black, next_white) = if white_to_move {
            (black & !flips, white | placed)
        } else {
            (black | placed, white & !flips)
        };
        let next = scalar_board(next_black, next_white);
        let opponent_can_play = scalar_moves(&next, -color).iter().any(|&mask| mask != 0);
        let terminal =
            !opponent_can_play && scalar_moves(&next, color).iter().all(|&mask| mask == 0);
        let next_white_to_move = white_to_move ^ opponent_can_play;
        let (black_mask, white_mask) = scalar_image(next_black, next_white);
        output.insert((black_mask, white_mask, next_white_to_move, terminal));
    }
}

fn read_position(line: &str) -> Option<Position> {
    let mut fields = line.split_ascii_whitespace();
    let black = u64::from_str_radix(fields.next()?, 16).ok()?;
    let white = u64::from_str_radix(fields.next()?, 16).ok()?;
    let white_to_move = match fields.next()? {
        "B" => false,
        "W" => true,
        _ => return None,
    };
    let terminal = match fields.next()? {
        "0" => false,
        "1" => true,
        _ => return None,
    };
    (fields.next().is_none() && black & white == 0).then_some((
        black,
        white,
        white_to_move,
        terminal,
    ))
}

fn main() -> io::Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let [implementation, phase]: &[String] = arguments.as_slice() else {
        return Err(io::Error::other("expected engine|scalar PHASE"));
    };
    let independent = match implementation.as_str() {
        "engine" => false,
        "scalar" => true,
        _ => return Err(io::Error::other("expected engine|scalar")),
    };
    let phase: u32 = phase.parse().map_err(io::Error::other)?;
    let table = symmetry_table();
    let mut output = HashSet::new();
    if phase == 0 {
        let (black, white) = if independent {
            scalar_image((1 << 28) | (1 << 35), (1 << 27) | (1 << 36))
        } else {
            min_image(&table, Board::new())
        };
        output.insert((black, white, false, false));
    } else {
        for line in io::stdin().lock().lines() {
            let (black, white, white_to_move, terminal) =
                read_position(&line?).ok_or_else(|| io::Error::other("invalid prior position"))?;
            if (black | white).count_ones() != phase + 3 {
                return Err(io::Error::other("invalid prior position phase"));
            }
            if terminal {
                continue;
            }
            if independent {
                expand_independently(black, white, white_to_move, &mut output);
            } else {
                expand(Board { black, white }, white_to_move, &table, &mut output);
            }
        }
    }
    let mut positions: Vec<_> = output.into_iter().collect();
    positions.sort_unstable();
    let mut out = BufWriter::new(io::stdout().lock());
    for (black, white, white_to_move, terminal) in positions {
        let turn = if white_to_move { 'W' } else { 'B' };
        writeln!(
            out,
            "{black:016x} {white:016x} {turn} {}",
            u8::from(terminal)
        )?;
    }
    out.flush()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transpose_has_the_same_color_preserving_representative() {
        let expected = (0x818080000, 0x1000000000);
        let transpose = Board {
            black: 0x81c000000,
            white: 0x1000000000,
        };
        assert_eq!(min_image(&symmetry_table(), transpose), expected);
        assert_eq!(scalar_image(transpose.black, transpose.white), expected);
    }

    #[test]
    fn forced_pass_and_terminal_preserve_placement_counts() {
        // B plays c1. W cannot move, while B can still play c3 against b3.
        // B then plays c3 and eliminates W. A gap prevents other captures.
        let black = (1 << 0) | (1 << 16);
        let white = (1 << 1) | (1 << 17);
        let table = symmetry_table();
        let mut fast = HashSet::new();
        let mut independent = HashSet::new();
        expand(Board { black, white }, false, &table, &mut fast);
        expand_independently(black, white, false, &mut independent);
        assert_eq!(fast, independent);
        let pass_board = min_image(
            &table,
            Board {
                black: black | (1 << 1) | (1 << 2),
                white: 1 << 17,
            },
        );
        let passed = (pass_board.0, pass_board.1, false, false);
        assert!(fast.contains(&passed));
        fast.clear();
        independent.clear();
        expand(
            Board {
                black: passed.0,
                white: passed.1,
            },
            false,
            &table,
            &mut fast,
        );
        expand_independently(passed.0, passed.1, false, &mut independent);
        assert_eq!(fast, independent);
        assert!(fast
            .iter()
            .any(|&(b, w, turn, terminal)| b.count_ones() == 6 && w == 0 && !turn && terminal));
    }
}
