use godot::prelude::*;
use reversi_engine::board::Board;
use reversi_engine::game::Game;
use reversi_engine::types::{Color, GameStatus, Position};

/// GDScript-callable wrapper for the Reversi game engine.
#[derive(GodotClass)]
#[class(base=RefCounted)]
pub struct ReversiGame {
    game: Game,
    base: Base<RefCounted>,
}

#[godot_api]
impl IRefCounted for ReversiGame {
    fn init(base: Base<RefCounted>) -> Self {
        Self {
            game: Game::new(),
            base,
        }
    }
}

#[godot_api]
impl ReversiGame {
    /// Returns the cell state: 0=empty, 1=black, 2=white.
    #[func]
    fn get_cell(&self, row: i32, col: i32) -> i32 {
        if row < 0 || row >= 8 || col < 0 || col >= 8 {
            return 0;
        }
        match self.game.board().get(Position::new(row as u8, col as u8)) {
            None => 0,
            Some(Color::Black) => 1,
            Some(Color::White) => 2,
        }
    }

    /// Returns legal moves as an Array of Vector2i (row, col).
    #[func]
    fn get_legal_moves(&self) -> Array<Vector2i> {
        let moves_mask = self.game.legal_moves();
        let mut arr = Array::new();
        let mut bits = moves_mask;
        while bits != 0 {
            let index = bits.trailing_zeros() as u8;
            let pos = Position::from_bit_index(index);
            arr.push(Vector2i::new(pos.row as i32, pos.col as i32));
            bits &= bits - 1;
        }
        arr
    }

    /// Returns the current turn: 1=black, 2=white.
    #[func]
    fn get_current_turn(&self) -> i32 {
        match self.game.current_turn() {
            Color::Black => 1,
            Color::White => 2,
        }
    }

    /// Returns the score as Vector2i (black_count, white_count).
    #[func]
    fn get_score(&self) -> Vector2i {
        let (b, w) = self.game.score();
        Vector2i::new(b as i32, w as i32)
    }

    /// Returns true if the game is over.
    #[func]
    fn is_game_over(&self) -> bool {
        self.game.is_game_over()
    }

    /// Returns the game status: 0=in_progress, 1=passed, 2=game_over.
    #[func]
    fn get_status(&self) -> i32 {
        match self.game.status() {
            GameStatus::InProgress => 0,
            GameStatus::Passed => 1,
            GameStatus::GameOver(_) => 2,
        }
    }

    /// Returns the winner: 0=none/not over, 1=black, 2=white, 3=draw.
    #[func]
    fn get_winner(&self) -> i32 {
        match self.game.winner() {
            None => 0,
            Some(reversi_engine::types::GameResult::Win(Color::Black)) => 1,
            Some(reversi_engine::types::GameResult::Win(Color::White)) => 2,
            Some(reversi_engine::types::GameResult::Draw) => 3,
        }
    }

    /// Makes a move. Returns the status (0/1/2) or -1 on error.
    #[func]
    fn play(&mut self, row: i32, col: i32) -> i32 {
        if row < 0 || row >= 8 || col < 0 || col >= 8 {
            return -1;
        }
        match self.game.play(Position::new(row as u8, col as u8)) {
            Ok(status) => match status {
                GameStatus::InProgress => 0,
                GameStatus::Passed => 1,
                GameStatus::GameOver(_) => 2,
            },
            Err(_) => -1,
        }
    }

    /// Passes the current player's turn. Returns status or -1 on error.
    #[func]
    fn pass_turn(&mut self) -> i32 {
        match self.game.pass_turn() {
            Ok(status) => match status {
                GameStatus::InProgress => 0,
                GameStatus::Passed => 1,
                GameStatus::GameOver(_) => 2,
            },
            Err(_) => -1,
        }
    }

    /// Returns the board as an 8-line string (B=black, W=white, .=empty).
    #[func]
    fn get_board_string(&self) -> GString {
        GString::from(&self.game.board().to_board_string())
    }

    /// Sets the board from a string. Returns true on success.
    #[func]
    fn set_board_from_string(&mut self, s: GString) -> bool {
        match Board::from_string(&s.to_string()) {
            Ok(board) => {
                self.game = Game::from_board(board, self.game.current_turn());
                true
            }
            Err(_) => false,
        }
    }

    /// Returns the number of moves played.
    #[func]
    fn get_move_count(&self) -> i32 {
        self.game.move_history().len() as i32
    }

    /// Returns the move history as a comma-separated string.
    #[func]
    fn get_move_history(&self) -> GString {
        GString::from(&self.game.move_history_string())
    }
}
