/// Per-phase search depth configuration.
#[derive(Debug, Clone, Copy)]
pub struct AiConfig {
    pub opening_depth: u8,
    pub midgame_depth: u8,
    pub endgame_depth: u8,
}

impl AiConfig {
    pub fn new(opening_depth: u8, midgame_depth: u8, endgame_depth: u8) -> Self {
        Self {
            opening_depth,
            midgame_depth,
            endgame_depth,
        }
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
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_phase_detection() {
        let config = AiConfig::new(3, 5, 8);
        assert_eq!(config.depth_for_phase(4), 3);   // opening
        assert_eq!(config.depth_for_phase(20), 3);   // opening boundary
        assert_eq!(config.depth_for_phase(21), 5);   // midgame
        assert_eq!(config.depth_for_phase(44), 5);   // midgame boundary
        assert_eq!(config.depth_for_phase(45), 8);   // endgame
        assert_eq!(config.depth_for_phase(64), 8);   // full board
    }
}
