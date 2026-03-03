use godot::prelude::*;
use reversi_engine::board::Board;
use reversi_engine::game::Game;
use reversi_engine::types::{Color, GameStatus, Position};
use reversi_ai::config::AiConfig;
use reversi_ai::eval::novice::NoviceEvaluator;
use reversi_ai::eval::strategic::StrategicEvaluator;
use reversi_ai::player::AiPlayer;

/// GDScript-callable wrapper for the Reversi game engine.
#[derive(GodotClass)]
#[class(base=RefCounted)]
pub struct ReversiGame {
    game: Game,
    ai: Option<AiPlayer>,
    base: Base<RefCounted>,
}

#[godot_api]
impl IRefCounted for ReversiGame {
    fn init(base: Base<RefCounted>) -> Self {
        Self {
            game: Game::new(),
            ai: None,
            base,
        }
    }
}

#[godot_api]
impl ReversiGame {
    /// Returns the cell state: 0=empty, 1=black, 2=white.
    #[func]
    fn get_cell(&self, row: i32, col: i32) -> i32 {
        if !(0..8).contains(&row) || !(0..8).contains(&col) {
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
        if !(0..8).contains(&row) || !(0..8).contains(&col) {
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

    /// Returns the move history in standard Othello notation.
    #[func]
    fn get_move_history(&self) -> GString {
        GString::from(&self.game.move_history_string())
    }

    /// Sets up the AI with the given evaluator and depth configuration.
    /// evaluator_name: "strategic" or "novice".
    /// Returns false if evaluator_name is unknown.
    #[func]
    fn set_ai(
        &mut self,
        evaluator_name: GString,
        opening_depth: i32,
        midgame_depth: i32,
        endgame_depth: i32,
    ) -> bool {
        let name = evaluator_name.to_string();
        let config = AiConfig::new(
            opening_depth as u8,
            midgame_depth as u8,
            endgame_depth as u8,
        );
        let evaluator: Box<dyn reversi_ai::eval::BoardEvaluator> = match name.as_str() {
            "strategic" => Box::new(StrategicEvaluator::new()),
            "novice" => Box::new(NoviceEvaluator::new()),
            _ => return false,
        };
        self.ai = Some(AiPlayer::new(evaluator, config));
        true
    }

    /// Returns the AI's best move as Vector2i (row, col).
    /// Returns (-1, -1) if no AI is set or game is over.
    #[func]
    fn ai_think(&mut self) -> Vector2i {
        let Some(ai) = &mut self.ai else {
            return Vector2i::new(-1, -1);
        };
        if self.game.is_game_over() {
            return Vector2i::new(-1, -1);
        }
        let board = *self.game.board();
        let color = self.game.current_turn();
        let result = ai.think(&board, color);
        Vector2i::new(result.best_move.row as i32, result.best_move.col as i32)
    }

    /// Returns the AI's move explanation as a VarDictionary.
    /// Returns empty VarDictionary if no AI is set or game is over.
    #[func]
    fn ai_explain_move(&mut self) -> VarDictionary {
        let Some(ai) = &mut self.ai else {
            return VarDictionary::new();
        };
        if self.game.is_game_over() {
            return VarDictionary::new();
        }
        let board = *self.game.board();
        let color = self.game.current_turn();
        let explanation = ai.explain(&board, color);

        let mut pv_arr = Array::<Vector2i>::new();
        for pos in &explanation.pv {
            pv_arr.push(Vector2i::new(pos.row as i32, pos.col as i32));
        }

        let mut factors = VarDictionary::new();
        factors.set("corner_control", explanation.factors.corner_control);
        factors.set("stability", explanation.factors.stability);
        factors.set("mobility", explanation.factors.mobility);
        factors.set("edge_control", explanation.factors.edge_control);
        factors.set("parity", explanation.factors.parity);
        factors.set("piece_count", explanation.factors.piece_count);

        let mut dict = VarDictionary::new();
        dict.set(
            "best_move",
            Vector2i::new(
                explanation.best_move.row as i32,
                explanation.best_move.col as i32,
            ),
        );
        dict.set("pv", pv_arr);
        dict.set("score", explanation.score);
        dict.set(
            "primary_reason",
            GString::from(explanation.primary_reason.as_str()),
        );
        dict.set("factors", factors);
        dict
    }
}
