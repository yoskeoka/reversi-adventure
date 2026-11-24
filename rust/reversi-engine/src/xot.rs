//! Selection and replay of eight-move XOT openings from the original lists.

use std::fmt;

use rand::Rng;

use crate::game::Game;
use crate::types::{GameStatus, Position};

const MOVE_COUNT: usize = 8;
const ROW_WIDTH: usize = MOVE_COUNT * 2 + 1;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum XotList {
    #[default]
    Large,
    Small,
}

impl XotList {
    fn corpus(self) -> &'static str {
        match self {
            Self::Large => include_str!("../data/xot/openingslarge.txt"),
            Self::Small => include_str!("../data/xot/openingssmall.txt"),
        }
    }

    pub fn row_count(self) -> usize {
        self.corpus().len() / ROW_WIDTH
    }

    /// Choose uniformly using the thread-local random source.
    pub fn random(self) -> Result<XotOpening, XotError> {
        self.sample(&mut rand::rng())
    }

    /// Choose uniformly among the original rows using the caller's random source.
    pub fn sample(self, rng: &mut impl Rng) -> Result<XotOpening, XotError> {
        self.at(rng.random_range(0..self.row_count()))
    }

    /// Replay a zero-based row of the original list.
    pub fn at(self, index: usize) -> Result<XotOpening, XotError> {
        if index >= self.row_count() {
            return Err(XotError::IndexOutOfRange(index));
        }
        // Build-time digest verification pins ASCII rows of exactly ROW_WIDTH bytes.
        let start = index * ROW_WIDTH;
        XotOpening::replay(&self.corpus()[start..start + ROW_WIDTH - 1])
    }
}

#[derive(Debug)]
pub struct XotOpening {
    notation: String,
    moves: [Position; MOVE_COUNT],
    game: Game,
}

impl XotOpening {
    /// Replay exactly eight alternating placements from the standard position.
    pub fn replay(notation: &str) -> Result<Self, XotError> {
        if notation.len() != MOVE_COUNT * 2 {
            return Err(XotError::InvalidLength);
        }

        let mut game = Game::new();
        let mut moves = [Position::new(0, 0); MOVE_COUNT];
        let (pairs, _) = notation.as_bytes().as_chunks::<2>();
        for (index, &[col, row]) in pairs.iter().enumerate() {
            let ply = index + 1;
            if !(b'a'..=b'h').contains(&col) || !(b'1'..=b'8').contains(&row) {
                return Err(XotError::InvalidCoordinate(ply));
            }
            let position = Position::new(row - b'1', col - b'a');
            match game.play(position) {
                Ok(GameStatus::InProgress) => moves[index] = position,
                Ok(_) => return Err(XotError::InterruptedGame(ply)),
                Err(error) => return Err(XotError::IllegalMove(ply, error)),
            }
        }
        Ok(Self {
            notation: notation.to_owned(),
            moves,
            game,
        })
    }

    pub fn notation(&self) -> &str {
        &self.notation
    }

    pub fn moves(&self) -> &[Position; MOVE_COUNT] {
        &self.moves
    }

    pub fn game(&self) -> &Game {
        &self.game
    }

    pub fn into_game(self) -> Game {
        self.game
    }
}

#[derive(Debug, Eq, PartialEq)]
pub enum XotError {
    IndexOutOfRange(usize),
    InvalidLength,
    InvalidCoordinate(usize),
    IllegalMove(usize, crate::types::MoveError),
    InterruptedGame(usize),
}

impl fmt::Display for XotError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::IndexOutOfRange(index) => write!(f, "XOT row index {index} is out of range"),
            Self::InvalidLength => {
                write!(f, "an XOT opening must contain exactly eight coordinates")
            }
            Self::InvalidCoordinate(ply) => write!(f, "invalid XOT coordinate at move {ply}"),
            Self::IllegalMove(ply, error) => write!(f, "illegal XOT move {ply}: {error}"),
            Self::InterruptedGame(ply) => write!(f, "XOT opening passes or ends at move {ply}"),
        }
    }
}

impl std::error::Error for XotError {}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use rand::{rngs::StdRng, SeedableRng};

    use crate::types::{Color, MoveError};

    use super::*;

    #[test]
    fn embedded_lists_have_distinct_legal_rows_and_positions() {
        for (list, count) in [(XotList::Large, 10_784), (XotList::Small, 3_623)] {
            assert_eq!(list.row_count(), count);
            assert_eq!(list.corpus().lines().count(), count);
            let mut rows = HashSet::new();
            let mut boards = HashSet::new();
            for (index, row) in list.corpus().lines().enumerate() {
                let opening = list
                    .at(index)
                    .unwrap_or_else(|error| panic!("{list:?} row {} ({row}): {error}", index + 1));
                assert_eq!(opening.notation(), row);
                assert!(rows.insert(row), "duplicate {list:?} opening {row}");
                let game = opening.game();
                assert_eq!(game.current_turn(), Color::Black);
                assert_eq!(game.board().occupied().count_ones(), 12);
                assert!(
                    boards.insert(*game.board()),
                    "duplicate {list:?} board at {row}"
                );
                assert!(game.move_history().iter().copied().eq(opening
                    .moves()
                    .iter()
                    .copied()
                    .map(Some)));
            }
            assert_eq!(
                list.at(count).unwrap_err(),
                XotError::IndexOutOfRange(count)
            );
        }
    }

    #[test]
    fn seeded_sampling_and_replay_produce_the_same_game() {
        assert_eq!(XotList::default(), XotList::Large);
        for list in [XotList::Large, XotList::Small] {
            let opening = list.sample(&mut StdRng::seed_from_u64(42)).unwrap();
            let repeat = list.sample(&mut StdRng::seed_from_u64(42)).unwrap();
            assert_eq!(repeat.notation(), opening.notation());
            assert!(list.corpus().lines().any(|row| row == opening.notation()));
            let replay = XotOpening::replay(opening.notation()).unwrap().into_game();
            assert_eq!(replay.board(), opening.game().board());
            assert_eq!(replay.current_turn(), opening.game().current_turn());
        }
    }

    #[test]
    fn replay_rejects_malformed_and_illegal_openings() {
        assert_eq!(
            XotOpening::replay("f5").unwrap_err(),
            XotError::InvalidLength
        );
        assert_eq!(
            XotOpening::replay("F5d6c4d3c2b3b4b5").unwrap_err(),
            XotError::InvalidCoordinate(1)
        );
        assert_eq!(
            XotOpening::replay("f5f5c4d3c2b3b4b5").unwrap_err(),
            XotError::IllegalMove(2, MoveError::CellOccupied)
        );
    }
}
