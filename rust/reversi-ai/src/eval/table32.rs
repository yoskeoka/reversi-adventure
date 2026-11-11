//! Project-owned table32 evaluator. The catalog is mathematical geometry only.
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::sync::OnceLock;

use reversi_engine::{
    board::Board,
    types::{Color, Position},
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::{stable_context_fingerprint, BoardEvaluator, EvalFactors, EvalResult};

pub const IDENTITY: &str = "reversi-ai-pattern-table32-v1";
pub const PARTIAL_IDENTITY: &str = "reversi-ai-pattern-table32-partial-v1";
pub const PHASE_COUNT: usize = 60;
pub const PARAMETER_COUNT: usize = 612425;
const LIMIT: i64 = 4091;
const OFFSETS: [usize; 17] = [
    0, 6561, 26244, 32805, 52488, 59049, 78732, 80919, 139968, 199017, 258066, 317115, 376164,
    435213, 494262, 553311, 612360,
];

struct Catalog {
    value: Value,
    placements: Vec<Vec<u8>>,
    reverse: Vec<Vec<usize>>,
}

fn catalog() -> &'static Catalog {
    static CATALOG: OnceLock<Catalog> = OnceLock::new();
    CATALOG.get_or_init(|| {
        let value: Value = serde_json::from_str(include_str!("../../data/table32-catalog.json"))
            .expect("versioned mathematical catalog is JSON");
        let tables = value["tables"].as_array().expect("tables");
        let placements = tables
            .iter()
            .flat_map(|t| t["placements"].as_array().unwrap())
            .map(|p| {
                p.as_array()
                    .unwrap()
                    .iter()
                    .map(|c| {
                        let c = c.as_str().unwrap().as_bytes();
                        (c[1] - b'1') * 8 + c[0] - b'a'
                    })
                    .collect()
            })
            .collect();
        let reverse = tables
            .iter()
            .map(|t| {
                t["reverse"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|x| x.as_u64().unwrap() as usize)
                    .collect()
            })
            .collect();
        Catalog {
            value,
            placements,
            reverse,
        }
    })
}

fn digest(value: &Value) -> String {
    format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(value).expect("JSON serializes"))
    )
}

pub fn catalog_digest() -> String {
    digest(&catalog().value)
}

pub fn feature_contract() -> Value {
    json!({"catalog_digest": catalog_digest(), "phase_count":60, "feature_count":65,
        "parameter_count":PARAMETER_COUNT, "scale":32, "parameter_limit":4091,
        "phase":"min(59,occupied-4)"})
}

pub fn phase(board: &Board) -> usize {
    ((board.count(Color::Black) + board.count(Color::White)).saturating_sub(4) as usize).min(59)
}

pub fn extract_features(board: &Board, color: Color) -> [usize; 65] {
    let mut features = [0; 65];
    for (i, placement) in catalog().placements.iter().enumerate() {
        let code = placement.iter().fold(0, |code, &cell| {
            let digit = match board.get(Position::new(cell / 8, cell % 8)) {
                None => 2,
                Some(c) if c == color => 0,
                Some(_) => 1,
            };
            code * 3 + digit
        });
        features[i] = OFFSETS[i / 4] + code;
    }
    features[64] = OFFSETS[16] + board.count(color) as usize;
    features
}

fn reverse_index(index: usize) -> usize {
    let table = OFFSETS.partition_point(|&offset| offset <= index) - 1;
    if table == 16 {
        return index;
    }
    let permutation = &catalog().reverse[table];
    let mut code = index - OFFSETS[table];
    let mut digits = vec![0; permutation.len()];
    for d in digits.iter_mut().rev() {
        *d = code % 3;
        code /= 3;
    }
    OFFSETS[table] + permutation.iter().fold(0, |n, &d| n * 3 + digits[d])
}

pub fn runtime_score(raw: i32) -> i32 {
    let raw = i64::from(raw);
    ((raw
        + if raw > 0 {
            16
        } else if raw < 0 {
            -16
        } else {
            0
        })
        / 32)
        .clamp(-64, 64) as i32
}

fn sha(value: &Value, length: usize) -> bool {
    value.as_str().is_some_and(|s| {
        s.len() == length
            && s.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    })
}

/// Validated sparse tables, sharing addresses across the four placements.
pub struct Table32Evaluator {
    tables: Vec<Option<HashMap<usize, i16>>>,
    context: u64,
}

impl Table32Evaluator {
    pub fn from_path(path: impl AsRef<Path>) -> Result<Self, String> {
        let bytes = fs::read(path).map_err(|e| format!("cannot read table32 artifact: {e}"))?;
        let artifact =
            serde_json::from_slice(&bytes).map_err(|e| format!("invalid table32 JSON: {e}"))?;
        Self::from_json_value(artifact)
    }

    pub fn from_json_value(artifact: Value) -> Result<Self, String> {
        Self::parse(artifact, false)
    }

    fn parse(artifact: Value, partial: bool) -> Result<Self, String> {
        let invalid = || "invalid table32 artifact".to_owned();
        if artifact["identity"] != if partial { PARTIAL_IDENTITY } else { IDENTITY }
            || artifact["score_contract"] != crate::search::SCORE_CONTRACT
            || artifact["feature_contract"] != feature_contract()
        {
            return Err("table32 identity/feature/score contract mismatch".into());
        }
        let provenance = &artifact["provenance"];
        if provenance["trainer_version"] != "reversi-ai-table32-training-v1"
            || provenance["optimizer"] != "table32_full_batch_adam_v1"
            || provenance["source_kind"] != "project-owned"
            || provenance["seed"].as_u64().is_none()
            || !sha(&provenance["input_manifest_digest"], 64)
            || !sha(&provenance["producer_commit"], 40)
        {
            return Err("invalid table32 provenance".into());
        }
        let weights = artifact["weights"].as_object().ok_or_else(invalid)?;
        if (!partial && weights.len() != 60) || weights.is_empty() || weights.len() > 60 {
            return Err("table32 requires all 60 learned phases".into());
        }
        for key in weights.keys() {
            let index = key.parse::<usize>().map_err(|_| invalid())?;
            if index >= 60 || index.to_string() != *key {
                return Err(invalid());
            }
        }
        let mut tables = Vec::with_capacity(60);
        for phase in 0..60 {
            let Some(value) = weights.get(&phase.to_string()) else {
                tables.push(None);
                continue;
            };
            let mut table = HashMap::new();
            for (key, weight) in value.as_object().ok_or_else(invalid)? {
                let index = key.parse::<usize>().map_err(|_| invalid())?;
                let weight = weight.as_i64().ok_or_else(invalid)?;
                if index >= PARAMETER_COUNT
                    || index.to_string() != *key
                    || weight == 0
                    || !(-LIMIT..=LIMIT).contains(&weight)
                {
                    return Err("invalid table32 parameter/weight".into());
                }
                table.insert(index, weight as i16);
            }
            for (&index, &weight) in &table {
                if table.get(&reverse_index(index)).copied().unwrap_or(0) != weight {
                    return Err("table32 reverse sharing mismatch".into());
                }
            }
            tables.push(Some(table));
        }
        if artifact["weight_digest"].as_str() != Some(digest(&artifact["weights"]).as_str()) {
            return Err("table32 weight digest mismatch".into());
        }
        let mut content = artifact.as_object().ok_or_else(invalid)?.clone();
        content.remove("artifact_digest");
        let artifact_digest = digest(&Value::Object(content));
        if artifact["artifact_digest"].as_str() != Some(artifact_digest.as_str()) {
            return Err("table32 artifact digest mismatch".into());
        }
        let hash = Sha256::digest(artifact_digest.as_bytes());
        let context = stable_context_fingerprint(&[
            0x7461626c65333201,
            u64::from_le_bytes(hash[..8].try_into().expect("SHA length")),
        ]);
        Ok(Self { tables, context })
    }
}

impl BoardEvaluator for Table32Evaluator {
    fn evaluate(&self, board: &Board, color: Color) -> EvalResult {
        let table = self.tables[phase(board)]
            .as_ref()
            .expect("full table32 phase");
        let raw: i32 = extract_features(board, color)
            .iter()
            .map(|i| i32::from(table.get(i).copied().unwrap_or(0)))
            .sum();
        EvalResult {
            score: runtime_score(raw),
            factors: EvalFactors::default(),
        }
    }
    fn name(&self) -> &str {
        "trained-table32"
    }
    fn context_fingerprint(&self) -> u64 {
        self.context
    }
}

/// Evaluates using a later learned phase when needed, then the legacy evaluator.
pub struct PartialTable32Evaluator {
    partial: Table32Evaluator,
    fallback: Box<dyn BoardEvaluator>,
    context: u64,
}

impl PartialTable32Evaluator {
    pub fn from_path(
        path: impl AsRef<Path>,
        fallback: Box<dyn BoardEvaluator>,
    ) -> Result<Self, String> {
        let bytes =
            fs::read(path).map_err(|e| format!("cannot read partial table32 artifact: {e}"))?;
        let artifact =
            serde_json::from_slice(&bytes).map_err(|e| format!("invalid table32 JSON: {e}"))?;
        Self::from_json_value(artifact, fallback)
    }

    pub fn from_json_value(
        artifact: Value,
        fallback: Box<dyn BoardEvaluator>,
    ) -> Result<Self, String> {
        let partial = Table32Evaluator::parse(artifact, true)?;
        let context = stable_context_fingerprint(&[
            0x7061727469616c01,
            partial.context,
            fallback.context_fingerprint(),
        ]);
        Ok(Self {
            partial,
            fallback,
            context,
        })
    }
}

impl BoardEvaluator for PartialTable32Evaluator {
    fn evaluate(&self, board: &Board, color: Color) -> EvalResult {
        let selected = self.partial.tables[phase(board)..]
            .iter()
            .find_map(Option::as_ref);
        match selected {
            Some(table) => {
                let raw = extract_features(board, color)
                    .iter()
                    .map(|index| i32::from(table.get(index).copied().unwrap_or(0)))
                    .sum();
                EvalResult {
                    score: runtime_score(raw),
                    factors: EvalFactors::default(),
                }
            }
            None => self.fallback.evaluate(board, color),
        }
    }
    fn name(&self) -> &str {
        "trained-table32-partial"
    }
    fn context_fingerprint(&self) -> u64 {
        self.context
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fallback(u64);
    impl BoardEvaluator for Fallback {
        fn evaluate(&self, _: &Board, _: Color) -> EvalResult {
            EvalResult {
                score: 17,
                factors: EvalFactors::default(),
            }
        }
        fn name(&self) -> &str {
            "test-fallback"
        }
        fn context_fingerprint(&self) -> u64 {
            self.0
        }
    }
    fn partial_fixture(phases: &[usize]) -> Value {
        let mut artifact = fixture()["artifact"].clone();
        artifact["identity"] = json!(PARTIAL_IDENTITY);
        let weights = phases.iter().map(|p| (p.to_string(), json!({}))).collect();
        artifact["weights"] = Value::Object(weights);
        artifact["weight_digest"] = json!(digest(&artifact["weights"]));
        let mut content = artifact.as_object().unwrap().clone();
        content.remove("artifact_digest");
        artifact["artifact_digest"] = json!(digest(&Value::Object(content)));
        artifact
    }
    fn fixture() -> Value {
        serde_json::from_str(include_str!("../../data/table32-fixture.json")).unwrap()
    }
    #[test]
    fn partial_uses_nearest_later_learned_phase_and_falls_back_after_it() {
        let mut artifact = partial_fixture(&[10, 30]);
        artifact["weights"]["10"] = json!({(OFFSETS[16] + 2).to_string(): 32});
        artifact["weights"]["30"] = json!({(OFFSETS[16] + 2).to_string(): 64});
        artifact["weight_digest"] = json!(digest(&artifact["weights"]));
        let mut content = artifact.as_object().unwrap().clone();
        content.remove("artifact_digest");
        artifact["artifact_digest"] = json!(digest(&Value::Object(content)));
        assert!(Table32Evaluator::from_json_value(artifact.clone()).is_err());
        let evaluator =
            PartialTable32Evaluator::from_json_value(artifact.clone(), Box::new(Fallback(1)))
                .unwrap();
        let initial = Board::from_string(
            "........\n........\n........\n...WB...\n...BW...\n........\n........\n........",
        )
        .unwrap();
        assert_eq!(evaluator.evaluate(&initial, Color::Black).score, 1);
        let middle = Board::from_string(
            "BBWWWWWW\nWWWWWWWW\nWWW.....\n........\n........\n........\n........\n........",
        )
        .unwrap();
        assert_eq!(phase(&middle), 15);
        assert_eq!(evaluator.evaluate(&middle, Color::Black).score, 2);
        let later = Board::from_string(
            "BBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\nBBBBBBBB\n........\n........",
        )
        .unwrap();
        assert_eq!(phase(&later), 44);
        assert_eq!(evaluator.evaluate(&later, Color::Black).score, 17);
        let other =
            PartialTable32Evaluator::from_json_value(artifact, Box::new(Fallback(2))).unwrap();
        assert_ne!(evaluator.context_fingerprint(), other.context_fingerprint());
        assert!(PartialTable32Evaluator::from_json_value(
            partial_fixture(&[]),
            Box::new(Fallback(1))
        )
        .is_err());
    }
    #[test]
    fn shared_python_fixture_matches_geometry_prediction_and_digest() {
        let fixture = fixture();
        assert_eq!(
            catalog_digest(),
            fixture["catalog_digest"].as_str().unwrap()
        );
        let evaluator = Table32Evaluator::from_json_value(fixture["artifact"].clone()).unwrap();
        for case in fixture["cases"].as_array().unwrap() {
            let flat = case["board"].as_str().unwrap();
            let rows = flat
                .as_bytes()
                .chunks(8)
                .map(|b| std::str::from_utf8(b).unwrap())
                .collect::<Vec<_>>()
                .join("\n");
            let board = Board::from_string(&rows).unwrap();
            let side = if case["side"] == "B" {
                Color::Black
            } else {
                Color::White
            };
            let expected: Vec<usize> = case["features"]
                .as_array()
                .unwrap()
                .iter()
                .map(|i| i.as_u64().unwrap() as usize)
                .collect();
            assert_eq!(extract_features(&board, side).to_vec(), expected);
            assert_eq!(phase(&board) as u64, case["phase"].as_u64().unwrap());
            assert_eq!(
                i64::from(evaluator.evaluate(&board, side).score),
                case["score"].as_i64().unwrap()
            );
        }
    }
    #[test]
    fn raw_sum_rounding_and_clipping() {
        for (raw, expected) in [
            (15, 0),
            (-15, 0),
            (16, 1),
            (-16, -1),
            (31, 1),
            (-31, -1),
            (266000, 64),
            (-266000, -64),
        ] {
            assert_eq!(runtime_score(raw), expected);
        }
        assert_eq!(runtime_score(15 + 15), 1);
        assert_eq!(runtime_score(15) + runtime_score(15), 0);
    }
    #[test]
    fn loader_rejects_legacy_contract_and_tampering() {
        for key in [
            "identity",
            "score_contract",
            "feature_contract",
            "provenance",
            "weight_digest",
            "artifact_digest",
        ] {
            let mut artifact = fixture()["artifact"].clone();
            artifact.as_object_mut().unwrap().remove(key);
            assert!(
                Table32Evaluator::from_json_value(artifact).is_err(),
                "{key}"
            );
        }
        let mut artifact = fixture()["artifact"].clone();
        artifact["weights"]["0"]["0"] = json!(4092);
        assert!(Table32Evaluator::from_json_value(artifact).is_err());
    }
    #[test]
    fn reverse_is_involution_and_never_leaves_table() {
        for index in 0..PARAMETER_COUNT {
            let reversed = reverse_index(index);
            assert_eq!(reverse_index(reversed), index);
            assert_eq!(
                OFFSETS.partition_point(|&x| x <= index),
                OFFSETS.partition_point(|&x| x <= reversed)
            );
        }
    }
    #[test]
    fn context_isolated_from_legacy_and_changes_with_artifact() {
        let artifact = fixture()["artifact"].clone();
        let evaluator = Table32Evaluator::from_json_value(artifact.clone()).unwrap();
        let legacy = crate::eval::trained::TrainedEvaluator::from_path(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../models/trained/0019-20261020-02.json"),
        )
        .unwrap();
        assert_ne!(
            evaluator.context_fingerprint(),
            legacy.context_fingerprint()
        );
        let mut other = artifact;
        other["provenance"]["seed"] = json!(2026110102);
        let mut content = other.as_object().unwrap().clone();
        content.remove("artifact_digest");
        other["artifact_digest"] = json!(digest(&Value::Object(content)));
        let other = Table32Evaluator::from_json_value(other).unwrap();
        assert_ne!(evaluator.context_fingerprint(), other.context_fingerprint());
    }
}
