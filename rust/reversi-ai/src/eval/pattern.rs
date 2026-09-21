//! Project-owned pattern representation for a future trained evaluator.
//!
//! This module deliberately does not implement [`super::BoardEvaluator`]. A
//! trained runtime and its artifact loader are separate work; these types keep
//! their representation and validation contract deterministic in the meantime.

use reversi_engine::{board::Board, types::Color};

pub const PATTERN_FEATURE_COUNT: usize = 64;
pub const PATTERN_PHASE_COUNT: usize = 60;
pub const PATTERN_FORMAT_VERSION: u16 = 1;
pub const FINAL_DISC_DIFFERENTIAL_MIN: i16 = -64;
pub const FINAL_DISC_DIFFERENTIAL_MAX: i16 = 64;

const MAX_PATTERN_SQUARES: usize = 10;

/// Eight project-defined base patterns, expanded by every board symmetry.
/// `u8::MAX` pads a pattern to ten entries.
const BASE_PATTERNS: [[u8; MAX_PATTERN_SQUARES]; 8] = [
    [0, 1, 2, 8, 9, 16, 17, 18, u8::MAX, u8::MAX],
    [0, 1, 2, 3, 8, 9, 10, 16, 17, 24],
    [0, 1, 2, 3, 4, 5, 6, 7, u8::MAX, u8::MAX],
    [1, 2, 3, 9, 10, 11, 17, 18, 19, 25],
    [2, 3, 4, 10, 11, 12, 18, 19, 20, 26],
    [9, 10, 11, 12, 13, 17, 18, 19, 20, 21],
    [18, 19, 20, 21, 26, 27, 28, 29, 34, 35],
    [3, 4, 11, 12, 19, 20, 27, 28, 35, 36],
];

/// A listed-square-order feature in the fixed 64-entry catalog.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PatternFeature {
    squares: [u8; MAX_PATTERN_SQUARES],
    len: u8,
}

impl PatternFeature {
    pub fn squares(&self) -> &[u8] {
        &self.squares[..usize::from(self.len)]
    }
}

/// A color-relative, symmetry-canonicalized pattern vector.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PatternFeatures {
    pub phase: u8,
    pub values: [u32; PATTERN_FEATURE_COUNT],
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PatternError {
    UnsupportedPhase { occupied: u32 },
    UnsupportedFormatVersion(u16),
    CatalogDigestMismatch,
    InvalidPhaseDefinition,
    InvalidScoreScale,
    WeightDigestMismatch,
    InvalidContribution { value: i16 },
    InvalidFeatureBound { feature: usize, bound: u8 },
    AggregateOutOfRange,
}

/// The only score scale accepted by this artifact format.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PatternScoreScale {
    FinalDiscDifferential,
}

/// Safe provenance identifiers; never raw trainer input data.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PatternProvenance {
    pub trainer_id: String,
    pub input_manifest_digest: u64,
    pub licenses: Vec<String>,
}

/// Immutable metadata and flattened table values for a future trained runtime.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PatternWeightArtifact {
    format_version: u16,
    catalog_digest: u64,
    phase_count: u8,
    score_scale: PatternScoreScale,
    provenance: PatternProvenance,
    weight_digest: u64,
    feature_max_abs: [u8; PATTERN_FEATURE_COUNT],
    weights: Vec<i8>,
}

impl PatternWeightArtifact {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        format_version: u16,
        catalog_digest: u64,
        phase_count: u8,
        score_scale: PatternScoreScale,
        provenance: PatternProvenance,
        weight_digest: u64,
        feature_max_abs: [u8; PATTERN_FEATURE_COUNT],
        weights: Vec<i8>,
    ) -> Result<Self, PatternError> {
        let artifact = Self {
            format_version,
            catalog_digest,
            phase_count,
            score_scale,
            provenance,
            weight_digest,
            feature_max_abs,
            weights,
        };
        artifact.validate()?;
        Ok(artifact)
    }

    pub fn catalog_digest(&self) -> u64 {
        self.catalog_digest
    }

    pub fn provenance(&self) -> &PatternProvenance {
        &self.provenance
    }

    /// Stable identity for fields that change a future evaluator's score.
    pub fn context_components(&self) -> [u64; 5] {
        [
            u64::from(self.format_version),
            self.catalog_digest,
            u64::from(self.phase_count),
            self.score_scale as u64,
            self.weight_digest,
        ]
    }

    pub fn validate(&self) -> Result<(), PatternError> {
        if self.format_version != PATTERN_FORMAT_VERSION {
            return Err(PatternError::UnsupportedFormatVersion(self.format_version));
        }
        if self.catalog_digest != catalog_digest() {
            return Err(PatternError::CatalogDigestMismatch);
        }
        if usize::from(self.phase_count) != PATTERN_PHASE_COUNT {
            return Err(PatternError::InvalidPhaseDefinition);
        }
        if self.score_scale != PatternScoreScale::FinalDiscDifferential {
            return Err(PatternError::InvalidScoreScale);
        }
        if self.weight_digest != digest_weights(&self.weights) {
            return Err(PatternError::WeightDigestMismatch);
        }

        accumulate_final_disc_score(
            &self
                .weights
                .iter()
                .map(|&weight| i16::from(weight))
                .collect::<Vec<_>>(),
        )?;

        let aggregate =
            self.feature_max_abs
                .iter()
                .enumerate()
                .try_fold(0i16, |sum, (feature, &bound)| {
                    if bound > FINAL_DISC_DIFFERENTIAL_MAX as u8 {
                        return Err(PatternError::InvalidFeatureBound { feature, bound });
                    }
                    sum.checked_add(i16::from(bound))
                        .ok_or(PatternError::AggregateOutOfRange)
                })?;
        if aggregate > FINAL_DISC_DIFFERENTIAL_MAX {
            return Err(PatternError::AggregateOutOfRange);
        }
        Ok(())
    }
}

/// Returns the deterministic digest of the fixed catalog serialization.
pub fn catalog_digest() -> u64 {
    const FNV_OFFSET_BASIS: u64 = 0xcbf2_9ce4_8422_2325;
    const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;
    (0..PATTERN_FEATURE_COUNT).fold(FNV_OFFSET_BASIS, |mut digest, index| {
        let pattern = feature(index);
        digest ^= u64::from(pattern.len);
        digest = digest.wrapping_mul(FNV_PRIME);
        for &square in pattern.squares() {
            digest ^= u64::from(square);
            digest = digest.wrapping_mul(FNV_PRIME);
        }
        digest
    })
}

/// Returns one of the catalog's eight-symmetry-expanded features.
pub fn feature(index: usize) -> PatternFeature {
    assert!(index < PATTERN_FEATURE_COUNT, "feature index out of range");
    let base = BASE_PATTERNS[index / 8];
    let symmetry = index % 8;
    let mut squares = [u8::MAX; MAX_PATTERN_SQUARES];
    let mut len = 0;
    for square in base.into_iter().take_while(|square| *square != u8::MAX) {
        squares[len] = transform_square(square, symmetry);
        len += 1;
    }
    PatternFeature {
        squares,
        len: len as u8,
    }
}

/// Maps an occupied count to its non-interpolated pattern-table phase.
pub fn phase_for_occupied(occupied: u32) -> Result<u8, PatternError> {
    if !(4..=63).contains(&occupied) {
        return Err(PatternError::UnsupportedPhase { occupied });
    }
    Ok((occupied - 4) as u8)
}

/// Deterministically accumulates selected table contributions on the required
/// final-disc-difference scale.
pub fn accumulate_final_disc_score(contributions: &[i16]) -> Result<i16, PatternError> {
    let score = contributions.iter().try_fold(0i64, |sum, &contribution| {
        if !(FINAL_DISC_DIFFERENTIAL_MIN..=FINAL_DISC_DIFFERENTIAL_MAX).contains(&contribution) {
            return Err(PatternError::InvalidContribution {
                value: contribution,
            });
        }
        sum.checked_add(i64::from(contribution))
            .ok_or(PatternError::AggregateOutOfRange)
    })?;
    if !(i64::from(FINAL_DISC_DIFFERENTIAL_MIN)..=i64::from(FINAL_DISC_DIFFERENTIAL_MAX))
        .contains(&score)
    {
        return Err(PatternError::AggregateOutOfRange);
    }
    Ok(score as i16)
}

/// Extracts all 64 pattern codes after choosing a canonical board symmetry.
pub fn extract_features(board: &Board, color: Color) -> Result<PatternFeatures, PatternError> {
    let phase = phase_for_occupied(board.occupied().count_ones())?;
    let symmetry = canonical_symmetry(board);
    let inverse = inverse_symmetry(symmetry);
    let mut values = [0; PATTERN_FEATURE_COUNT];
    for (index, value) in values.iter_mut().enumerate() {
        *value = feature(index).squares().iter().fold(0, |code, &square| {
            code * 3
                + u32::from(square_value(
                    board,
                    color,
                    transform_square(square, inverse),
                ))
        });
    }
    Ok(PatternFeatures { phase, values })
}

fn canonical_symmetry(board: &Board) -> usize {
    (1..8).fold(0, |best, candidate| {
        if board_key(board, candidate) < board_key(board, best) {
            candidate
        } else {
            best
        }
    })
}

fn board_key(board: &Board, symmetry: usize) -> [u8; 64] {
    let inverse = inverse_symmetry(symmetry);
    std::array::from_fn(|square| {
        let mask = 1u64 << transform_square(square as u8, inverse);
        if board.black & mask != 0 {
            1
        } else if board.white & mask != 0 {
            2
        } else {
            0
        }
    })
}

fn square_value(board: &Board, color: Color, square: u8) -> u8 {
    let mask = 1u64 << square;
    if board.pieces(color) & mask != 0 {
        1
    } else if board.pieces(color.opponent()) & mask != 0 {
        2
    } else {
        0
    }
}

fn inverse_symmetry(symmetry: usize) -> usize {
    match symmetry {
        0 => 0,
        1 => 3,
        2 => 2,
        3 => 1,
        4..=7 => symmetry,
        _ => unreachable!("invalid symmetry"),
    }
}

fn transform_square(square: u8, symmetry: usize) -> u8 {
    let row = square / 8;
    let col = square % 8;
    let (row, col) = match symmetry {
        0 => (row, col),         // identity
        1 => (col, 7 - row),     // rotate 90 degrees clockwise
        2 => (7 - row, 7 - col), // rotate 180 degrees
        3 => (7 - col, row),     // rotate 270 degrees clockwise
        4 => (row, 7 - col),     // reflect vertically
        5 => (7 - row, col),     // reflect horizontally
        6 => (col, row),         // reflect main diagonal
        7 => (7 - col, 7 - row), // reflect anti-diagonal
        _ => unreachable!("invalid symmetry"),
    };
    row * 8 + col
}

fn digest_weights(weights: &[i8]) -> u64 {
    const FNV_OFFSET_BASIS: u64 = 0xcbf2_9ce4_8422_2325;
    const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;
    weights.iter().fold(FNV_OFFSET_BASIS, |digest, weight| {
        (digest ^ u64::from(*weight as u8)).wrapping_mul(FNV_PRIME)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use reversi_engine::types::Position;

    fn artifact(bounds: [u8; PATTERN_FEATURE_COUNT], weights: Vec<i8>) -> PatternWeightArtifact {
        PatternWeightArtifact::new(
            PATTERN_FORMAT_VERSION,
            catalog_digest(),
            PATTERN_PHASE_COUNT as u8,
            PatternScoreScale::FinalDiscDifferential,
            PatternProvenance {
                trainer_id: "fixture-trainer-v1".into(),
                input_manifest_digest: 7,
                licenses: vec!["CC-BY-4.0".into()],
            },
            digest_weights(&weights),
            bounds,
            weights,
        )
        .unwrap()
    }

    fn transformed(board: &Board, symmetry: usize) -> Board {
        let mut result = Board::empty();
        for square in 0..64 {
            let target = transform_square(square, symmetry);
            let position = Position::from_bit_index(target);
            if board.black & (1u64 << square) != 0 {
                result.set(position, Color::Black);
            } else if board.white & (1u64 << square) != 0 {
                result.set(position, Color::White);
            }
        }
        result
    }

    #[test]
    fn catalog_has_64_features_with_at_most_ten_squares() {
        assert_eq!(PATTERN_FEATURE_COUNT, 64);
        for index in 0..PATTERN_FEATURE_COUNT {
            assert!(!feature(index).squares().is_empty());
            assert!(feature(index).squares().len() <= MAX_PATTERN_SQUARES);
        }
    }

    #[test]
    fn phase_boundaries_are_exact_and_passes_do_not_change_them() {
        for occupied in 4..=63 {
            assert_eq!(phase_for_occupied(occupied), Ok((occupied - 4) as u8));
        }
        assert_eq!(
            phase_for_occupied(3),
            Err(PatternError::UnsupportedPhase { occupied: 3 })
        );
        assert_eq!(
            phase_for_occupied(64),
            Err(PatternError::UnsupportedPhase { occupied: 64 })
        );
    }

    #[test]
    fn golden_corner_and_edge_vector() {
        let mut board = Board::new();
        board.set(Position::new(0, 0), Color::Black);
        board.set(Position::new(0, 1), Color::White);
        let features = extract_features(&board, Color::Black).unwrap();
        assert_eq!(features.phase, 2);
        assert_eq!(&features.values[..8], &[0, 0, 0, 2349, 0, 3645, 0, 0]);
    }

    #[test]
    fn every_symmetry_has_the_same_canonical_vector() {
        let mut board = Board::new();
        board.set(Position::new(0, 0), Color::Black);
        board.set(Position::new(0, 1), Color::White);
        board.set(Position::new(2, 5), Color::Black);
        let expected = extract_features(&board, Color::Black).unwrap();
        for symmetry in 0..8 {
            assert_eq!(
                extract_features(&transformed(&board, symmetry), Color::Black),
                Ok(expected.clone())
            );
        }
    }

    #[test]
    fn color_perspective_is_antisymmetric() {
        let mut board = Board::new();
        board.set(Position::new(0, 0), Color::Black);
        board.set(Position::new(0, 1), Color::White);
        let black = extract_features(&board, Color::Black).unwrap();
        let white = extract_features(&board, Color::White).unwrap();
        assert_eq!(black.phase, white.phase);
        assert_ne!(black.values, white.values);
        for (index, (&black_code, &white_code)) in
            black.values.iter().zip(white.values.iter()).enumerate()
        {
            assert_eq!(
                swap_ternary_perspective(black_code, feature(index).squares().len()),
                white_code
            );
        }
    }

    #[test]
    fn rejects_corrupt_artifacts_and_unsafe_aggregate() {
        let valid = artifact([0; PATTERN_FEATURE_COUNT], vec![1, -1]);
        assert_eq!(valid.context_components()[1], catalog_digest());
        assert!(PatternWeightArtifact::new(
            PATTERN_FORMAT_VERSION,
            0,
            PATTERN_PHASE_COUNT as u8,
            PatternScoreScale::FinalDiscDifferential,
            valid.provenance().clone(),
            0,
            [0; PATTERN_FEATURE_COUNT],
            vec![],
        )
        .is_err());
        assert_eq!(accumulate_final_disc_score(&[20, -10]), Ok(10));
        assert_eq!(
            accumulate_final_disc_score(&[64, 1]),
            Err(PatternError::AggregateOutOfRange)
        );
        assert_eq!(
            accumulate_final_disc_score(&[65]),
            Err(PatternError::InvalidContribution { value: 65 })
        );
        assert!(PatternWeightArtifact::new(
            PATTERN_FORMAT_VERSION,
            catalog_digest(),
            PATTERN_PHASE_COUNT as u8,
            PatternScoreScale::FinalDiscDifferential,
            valid.provenance().clone(),
            digest_weights(&[]),
            [2; PATTERN_FEATURE_COUNT],
            vec![],
        )
        .is_err());
    }

    fn swap_ternary_perspective(value: u32, len: usize) -> u32 {
        (0..len).rev().fold(0, |code, exponent| {
            let digit = (value / 3u32.pow(exponent as u32)) % 3;
            code * 3
                + match digit {
                    1 => 2,
                    2 => 1,
                    _ => 0,
                }
        })
    }
}
