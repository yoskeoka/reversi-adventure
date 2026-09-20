/// Per-phase search depth configuration.
#[derive(Debug, Clone, Copy)]
pub struct AiConfig {
    pub opening_depth: u8,
    pub midgame_depth: u8,
    pub endgame_depth: u8,
    /// Number of empty squares at or below which final-disc solving starts.
    pub exact_solver_empty_squares: u32,
}

impl AiConfig {
    pub fn new(opening_depth: u8, midgame_depth: u8, endgame_depth: u8) -> Self {
        Self {
            opening_depth,
            midgame_depth,
            endgame_depth,
            exact_solver_empty_squares: 12,
        }
    }

    /// Overrides the decision-position threshold at which exact solving starts.
    pub fn with_exact_solver_empty_squares(mut self, threshold: u32) -> Self {
        self.exact_solver_empty_squares = threshold;
        self
    }

    /// Candidate settings declared by the versioned strength calibration profile.
    pub fn strong_engine_hcap_v1() -> Self {
        Self::new(12, 12, 12).with_exact_solver_empty_squares(16)
    }

    /// Returns the search depth for the current game phase based on stone count.
    /// Opening: 4-20 stones, Midgame: 21-44, Endgame: 45-64.
    pub fn depth_for_phase(&self, stone_count: u32) -> u8 {
        if stone_count <= 20 {
            self.opening_depth
        } else if stone_count <= 44 {
            self.midgame_depth
        } else {
            self.endgame_depth
        }
    }

    /// Returns a stable identity for score-affecting search configuration.
    pub(crate) fn context_fingerprint(&self) -> u64 {
        crate::eval::stable_context_fingerprint(&[
            0x5345_4152_4348_4346, // "SEARCHCF"
            1,                     // search configuration version
            u64::from(self.opening_depth),
            u64::from(self.midgame_depth),
            u64::from(self.endgame_depth),
            u64::from(self.exact_solver_empty_squares),
        ])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_phase_detection() {
        let config = AiConfig::new(3, 5, 8);
        assert_eq!(config.depth_for_phase(4), 3); // opening
        assert_eq!(config.depth_for_phase(20), 3); // opening boundary
        assert_eq!(config.depth_for_phase(21), 5); // midgame
        assert_eq!(config.depth_for_phase(44), 5); // midgame boundary
        assert_eq!(config.depth_for_phase(45), 8); // endgame
        assert_eq!(config.depth_for_phase(64), 8); // full board
    }

    #[test]
    fn strong_engine_profile_uses_a_uniform_heuristic_depth_and_16_empty_threshold() {
        let config = AiConfig::strong_engine_hcap_v1();
        assert_eq!(config.depth_for_phase(4), 12);
        assert_eq!(config.depth_for_phase(44), 12);
        assert_eq!(config.depth_for_phase(60), 12);
        assert_eq!(config.exact_solver_empty_squares, 16);
    }
}
