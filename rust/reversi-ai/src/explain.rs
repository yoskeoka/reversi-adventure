use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::{Color, Position};

use crate::eval::{BoardEvaluator, EvalFactors};
use crate::search::SearchResult;

/// Tags for the primary strategic reason behind a move.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExplainTag {
    CornerGrab,
    CornerSetup,
    MobilityGain,
    StabilityGain,
    EdgeControl,
    ParityAdvantage,
    PieceAdvantage,
    ForcedMove,
}

impl ExplainTag {
    /// Returns the tag as a lowercase string for GDScript bridge.
    pub fn as_str(&self) -> &'static str {
        match self {
            ExplainTag::CornerGrab => "corner_grab",
            ExplainTag::CornerSetup => "corner_setup",
            ExplainTag::MobilityGain => "mobility_gain",
            ExplainTag::StabilityGain => "stability_gain",
            ExplainTag::EdgeControl => "edge_control",
            ExplainTag::ParityAdvantage => "parity_advantage",
            ExplainTag::PieceAdvantage => "piece_advantage",
            ExplainTag::ForcedMove => "forced_move",
        }
    }
}

/// Move explanation with PV and factor breakdown.
#[derive(Debug, Clone)]
pub struct MoveExplanation {
    pub best_move: Position,
    pub pv: Vec<Position>,
    pub score: i32,
    pub factors: EvalFactors,
    pub primary_reason: ExplainTag,
}

/// Corner bit indices.
const CORNERS: [u8; 4] = [0, 7, 56, 63];

/// Generate explanation for a search result.
pub fn generate_explanation(
    board: &Board,
    color: Color,
    search_result: &SearchResult,
    evaluator: &dyn BoardEvaluator,
) -> MoveExplanation {
    let best = search_result.best_move;
    let legal = moves::legal_moves(board, color);

    // Check for forced move (only one legal move)
    if legal.count_ones() == 1 {
        return MoveExplanation {
            best_move: best,
            pv: search_result.pv.clone(),
            score: search_result.score,
            factors: search_result.leaf_eval.factors,
            primary_reason: ExplainTag::ForcedMove,
        };
    }

    // Check if best move is a corner
    if CORNERS.contains(&best.bit_index()) {
        return MoveExplanation {
            best_move: best,
            pv: search_result.pv.clone(),
            score: search_result.score,
            factors: search_result.leaf_eval.factors,
            primary_reason: ExplainTag::CornerGrab,
        };
    }

    // Check if PV leads to a corner take (corner setup)
    for pv_move in &search_result.pv {
        if CORNERS.contains(&pv_move.bit_index()) {
            return MoveExplanation {
                best_move: best,
                pv: search_result.pv.clone(),
                score: search_result.score,
                factors: search_result.leaf_eval.factors,
                primary_reason: ExplainTag::CornerSetup,
            };
        }
    }

    // Compare factors: current position vs PV leaf
    let current_eval = evaluator.evaluate(board, color);
    let delta = search_result.leaf_eval.factors - current_eval.factors;

    // Find the factor with the largest positive delta
    let primary_reason = determine_primary_reason(&delta);

    MoveExplanation {
        best_move: best,
        pv: search_result.pv.clone(),
        score: search_result.score,
        factors: search_result.leaf_eval.factors,
        primary_reason,
    }
}

fn determine_primary_reason(delta: &EvalFactors) -> ExplainTag {
    let candidates = [
        (delta.corner_control, ExplainTag::CornerGrab),
        (delta.stability, ExplainTag::StabilityGain),
        (delta.mobility, ExplainTag::MobilityGain),
        (delta.edge_control, ExplainTag::EdgeControl),
        (delta.parity, ExplainTag::ParityAdvantage),
        (delta.piece_count, ExplainTag::PieceAdvantage),
    ];

    candidates
        .iter()
        .max_by_key(|(value, _)| *value)
        .map(|(_, tag)| *tag)
        .unwrap_or(ExplainTag::MobilityGain)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::eval::EvalResult;

    #[test]
    fn test_forced_move() {
        let mut board = Board::empty();
        board.set(Position::new(0, 0), Color::Black);
        board.set(Position::new(0, 1), Color::White);
        // Only one legal move for black (if any)

        let _search_result = SearchResult {
            best_move: Position::new(0, 2),
            score: 10,
            pv: vec![Position::new(0, 2)],
            leaf_eval: EvalResult {
                score: 10,
                factors: EvalFactors::default(),
            },
        };

        // Simulate forced move: legal_moves has exactly 1 bit set
        // This test verifies the tag mapping
        let tag = ExplainTag::ForcedMove;
        assert_eq!(tag.as_str(), "forced_move");
    }

    #[test]
    fn test_corner_grab_tag() {
        let tag = ExplainTag::CornerGrab;
        assert_eq!(tag.as_str(), "corner_grab");
    }

    #[test]
    fn test_determine_primary_reason() {
        let delta = EvalFactors {
            corner_control: 5,
            stability: 20,
            mobility: 10,
            edge_control: 3,
            parity: 1,
            piece_count: 0,
        };
        assert_eq!(determine_primary_reason(&delta), ExplainTag::StabilityGain);
    }

    #[test]
    fn test_determine_primary_reason_mobility() {
        let delta = EvalFactors {
            corner_control: 0,
            stability: 0,
            mobility: 15,
            edge_control: 0,
            parity: 0,
            piece_count: 0,
        };
        assert_eq!(determine_primary_reason(&delta), ExplainTag::MobilityGain);
    }
}
