pub mod novice;
pub mod strategic;

use reversi_engine::board::Board;
use reversi_engine::types::Color;

/// Score breakdown for human-readable explanation.
#[derive(Debug, Clone, Copy, Default)]
pub struct EvalFactors {
    pub corner_control: i32,
    pub stability: i32,
    pub mobility: i32,
    pub edge_control: i32,
    pub parity: i32,
    pub piece_count: i32,
}

impl EvalFactors {
    /// Returns the sum of all factors.
    pub fn total(&self) -> i32 {
        self.corner_control
            + self.stability
            + self.mobility
            + self.edge_control
            + self.parity
            + self.piece_count
    }
}

impl std::ops::Sub for EvalFactors {
    type Output = EvalFactors;

    fn sub(self, rhs: EvalFactors) -> EvalFactors {
        EvalFactors {
            corner_control: self.corner_control - rhs.corner_control,
            stability: self.stability - rhs.stability,
            mobility: self.mobility - rhs.mobility,
            edge_control: self.edge_control - rhs.edge_control,
            parity: self.parity - rhs.parity,
            piece_count: self.piece_count - rhs.piece_count,
        }
    }
}

/// Evaluation result: score + explanation factors.
#[derive(Debug, Clone, Copy)]
pub struct EvalResult {
    pub score: i32,
    pub factors: EvalFactors,
}

/// Pluggable board evaluation strategy.
pub trait BoardEvaluator: Send + Sync {
    /// Evaluate the board from the perspective of `color`.
    /// Positive score = good for `color`.
    fn evaluate(&self, board: &Board, color: Color) -> EvalResult;

    /// Returns the name of this evaluator.
    fn name(&self) -> &str;
}
