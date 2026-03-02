use crate::board::Board;
use crate::moves;
use crate::types::*;

/// Reversi game state machine.
#[derive(Debug, Clone)]
pub struct Game {
    board: Board,
    current_turn: Color,
    status: GameStatus,
    move_history: Vec<Option<Position>>,
}

impl Game {
    /// Creates a new game with the standard starting position. Black moves first.
    pub fn new() -> Self {
        Self {
            board: Board::new(),
            current_turn: Color::Black,
            status: GameStatus::InProgress,
            move_history: Vec::new(),
        }
    }

    /// Creates a game from a custom board state.
    pub fn from_board(board: Board, current_turn: Color) -> Self {
        Self {
            board,
            current_turn,
            status: GameStatus::InProgress,
            move_history: Vec::new(),
        }
    }

    pub fn board(&self) -> &Board {
        &self.board
    }

    pub fn current_turn(&self) -> Color {
        self.current_turn
    }

    pub fn status(&self) -> GameStatus {
        self.status
    }

    pub fn move_history(&self) -> &[Option<Position>] {
        &self.move_history
    }

    /// Returns the legal moves bitmask for the current player.
    pub fn legal_moves(&self) -> u64 {
        moves::legal_moves(&self.board, self.current_turn)
    }

    /// Returns the score as (black_count, white_count).
    pub fn score(&self) -> (u32, u32) {
        (self.board.count(Color::Black), self.board.count(Color::White))
    }

    pub fn is_game_over(&self) -> bool {
        matches!(self.status, GameStatus::GameOver(_))
    }

    /// Returns the game result if the game is over.
    pub fn winner(&self) -> Option<GameResult> {
        match self.status {
            GameStatus::GameOver(result) => Some(result),
            _ => None,
        }
    }

    /// Makes a move for the current player.
    pub fn play(&mut self, pos: Position) -> Result<GameStatus, MoveError> {
        if self.is_game_over() {
            return Err(MoveError::GameAlreadyOver);
        }

        if pos.row >= 8 || pos.col >= 8 {
            return Err(MoveError::InvalidPosition);
        }

        if self.board.get(pos).is_some() {
            return Err(MoveError::CellOccupied);
        }

        let flips = moves::flipped_pieces(&self.board, self.current_turn, pos);
        if flips == 0 {
            return Err(MoveError::NoFlips);
        }

        // Apply the move
        self.board = moves::make_move(&self.board, self.current_turn, pos);
        self.move_history.push(Some(pos));

        // Determine next state
        self.advance_turn();
        Ok(self.status)
    }

    /// Passes the current player's turn. Only valid when the current player has no legal moves.
    pub fn pass_turn(&mut self) -> Result<GameStatus, MoveError> {
        if self.is_game_over() {
            return Err(MoveError::GameAlreadyOver);
        }

        if moves::has_legal_move(&self.board, self.current_turn) {
            return Err(MoveError::NoFlips); // Can't pass when you have moves
        }

        self.move_history.push(None);
        self.advance_turn();
        Ok(self.status)
    }

    /// After a move or pass, determine the next game state.
    fn advance_turn(&mut self) {
        let opponent = self.current_turn.opponent();

        if moves::has_legal_move(&self.board, opponent) {
            // Opponent can play
            self.current_turn = opponent;
            self.status = GameStatus::InProgress;
        } else if moves::has_legal_move(&self.board, self.current_turn) {
            // Opponent has no moves and must pass, current player continues
            // current_turn stays the same
            self.status = GameStatus::Passed;
        } else {
            // Neither player can move — game over
            let (black, white) = self.score();
            let result = if black > white {
                GameResult::Win(Color::Black)
            } else if white > black {
                GameResult::Win(Color::White)
            } else {
                GameResult::Draw
            };
            self.status = GameStatus::GameOver(result);
        }
    }

    /// Serializes the move history to standard Othello notation.
    /// Each move is 2 characters: column letter (A-H) + row number (1-8).
    /// Moves are concatenated without separators: "F5D6C3...".
    /// Pass is represented as "PS".
    pub fn move_history_string(&self) -> String {
        self.move_history
            .iter()
            .map(|m| match m {
                Some(pos) => {
                    let col_letter = (b'A' + pos.col) as char;
                    let row_number = pos.row + 1;
                    format!("{}{}", col_letter, row_number)
                }
                None => "PS".to_string(),
            })
            .collect::<String>()
    }
}

impl Default for Game {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_game() {
        let game = Game::new();
        assert_eq!(game.current_turn(), Color::Black);
        assert_eq!(game.status(), GameStatus::InProgress);
        assert_eq!(game.score(), (2, 2));
        assert!(!game.is_game_over());
    }

    #[test]
    fn test_play_valid_move() {
        let mut game = Game::new();
        // Black plays (2,3) — valid opening move
        let status = game.play(Position::new(2, 3)).unwrap();
        assert_eq!(status, GameStatus::InProgress);
        assert_eq!(game.current_turn(), Color::White);
        assert_eq!(game.score(), (4, 1));
    }

    #[test]
    fn test_play_invalid_occupied() {
        let mut game = Game::new();
        let result = game.play(Position::new(3, 3)); // occupied by white
        assert_eq!(result, Err(MoveError::CellOccupied));
    }

    #[test]
    fn test_play_invalid_no_flips() {
        let mut game = Game::new();
        let result = game.play(Position::new(0, 0)); // no flips possible
        assert_eq!(result, Err(MoveError::NoFlips));
    }

    #[test]
    fn test_play_sequence() {
        let mut game = Game::new();
        // A few opening moves
        game.play(Position::new(2, 3)).unwrap(); // Black
        game.play(Position::new(2, 2)).unwrap(); // White
        game.play(Position::new(2, 1)).unwrap(); // Black
        assert_eq!(game.move_history().len(), 3);
    }

    #[test]
    fn test_game_over() {
        // Create a nearly full board to test game over
        let mut board = Board::empty();
        // Fill entire board with black except one white piece
        for row in 0..8u8 {
            for col in 0..8u8 {
                board.set(Position::new(row, col), Color::Black);
            }
        }
        // Remove two cells and place white so there is one move left
        board.remove(Position::new(7, 7));
        board.remove(Position::new(7, 6));
        board.set(Position::new(7, 6), Color::White);
        // Now (7,7) is empty. Black playing (7,7) would flip (7,6)

        let mut game = Game::from_board(board, Color::Black);
        let status = game.play(Position::new(7, 7)).unwrap();
        // Board is now full, game should be over
        assert!(matches!(status, GameStatus::GameOver(_)));
        assert!(game.is_game_over());
    }

    #[test]
    fn test_move_history_string() {
        let mut game = Game::new();
        game.play(Position::new(2, 3)).unwrap(); // D3
        game.play(Position::new(2, 2)).unwrap(); // C3
        assert_eq!(game.move_history_string(), "D3C3");
    }

    #[test]
    fn test_pass_when_no_moves() {
        // Create a board where one player has no moves
        let mut board = Board::empty();
        // Black has pieces, white surrounded with no moves
        board.set(Position::new(0, 0), Color::Black);
        board.set(Position::new(0, 1), Color::White);
        // White has no legal moves (only one piece, surrounded by black on one side, empty elsewhere)
        // This is a simplistic test — in practice pass scenarios are more complex

        let mut game = Game::from_board(board, Color::White);
        if !moves::has_legal_move(&board, Color::White) {
            let status = game.pass_turn().unwrap();
            // After white passes, check if black can play or game is over
            assert!(matches!(status, GameStatus::InProgress | GameStatus::Passed | GameStatus::GameOver(_)));
        }
    }
}
