//! Runtime loader and evaluator for project-owned trained pattern artifacts.

use std::collections::HashMap;
use std::fmt;
use std::fs;
use std::path::Path;

use reversi_engine::{board::Board, types::Color};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use super::{stable_context_fingerprint, BoardEvaluator, EvalFactors, EvalResult};
use crate::eval::pattern::{
    catalog_digest, extract_features, feature, FINAL_DISC_DIFFERENTIAL_MAX, PATTERN_FEATURE_COUNT,
    PATTERN_FORMAT_VERSION, PATTERN_PHASE_COUNT,
};

const TRAINED_EVALUATOR_VERSION: u64 = 1;
const TRAINER_VERSION: &str = "reversi-ai-pattern-training-v1";

#[derive(Debug)]
pub enum TrainedEvaluatorError {
    Read(std::io::Error),
    Json(serde_json::Error),
    Invalid(String),
}

impl fmt::Display for TrainedEvaluatorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Read(error) => write!(formatter, "cannot read trained artifact: {error}"),
            Self::Json(error) => write!(formatter, "invalid trained artifact JSON: {error}"),
            Self::Invalid(message) => write!(formatter, "invalid trained artifact: {message}"),
        }
    }
}

impl std::error::Error for TrainedEvaluatorError {}

/// A validated sparse pattern artifact with no explanation attribution.
pub struct TrainedEvaluator {
    tables: Vec<Vec<HashMap<u32, i8>>>,
    context_fingerprint: u64,
}

impl TrainedEvaluator {
    pub fn from_path(path: impl AsRef<Path>) -> Result<Self, TrainedEvaluatorError> {
        let bytes = fs::read(path).map_err(TrainedEvaluatorError::Read)?;
        let value = serde_json::from_slice(&bytes).map_err(TrainedEvaluatorError::Json)?;
        Self::from_json_value(value)
    }

    fn from_json_value(value: Value) -> Result<Self, TrainedEvaluatorError> {
        let artifact = object(&value, "artifact")?;
        let format_version = u64_value(artifact, "format_version")?;
        if format_version != u64::from(PATTERN_FORMAT_VERSION) {
            return invalid("unsupported format version");
        }
        let feature_contract = object_value(artifact, "feature_contract")?;
        validate_feature_contract(feature_contract)?;
        validate_provenance(object_value(artifact, "provenance")?)?;

        let bounds = array(
            object_value(artifact, "feature_max_abs")?,
            "feature_max_abs",
        )?;
        if bounds.len() != PATTERN_FEATURE_COUNT {
            return invalid("feature_max_abs must contain 64 entries");
        }
        let bounds = bounds
            .iter()
            .enumerate()
            .map(|(index, value)| {
                let bound = value.as_u64().ok_or_else(|| {
                    TrainedEvaluatorError::Invalid(format!(
                        "feature bound {index} must be an integer"
                    ))
                })?;
                if bound > 1 {
                    return invalid("feature bounds must be in 0..=1");
                }
                Ok(bound as i8)
            })
            .collect::<Result<Vec<_>, _>>()?;
        if bounds.iter().map(|bound| i16::from(*bound)).sum::<i16>() > FINAL_DISC_DIFFERENTIAL_MAX {
            return invalid("feature bounds exceed final-disc score range");
        }

        let weights = object_value(artifact, "weights")?;
        let expected_weight_digest = string(artifact, "weight_digest")?;
        validate_sha256(expected_weight_digest, "weight digest")?;
        if digest(weights) != expected_weight_digest {
            return invalid("weight digest mismatch");
        }
        let mut without_artifact_digest = artifact.clone();
        let artifact_digest = without_artifact_digest
            .remove("artifact_digest")
            .and_then(|value| value.as_str().map(str::to_owned))
            .ok_or_else(|| TrainedEvaluatorError::Invalid("missing artifact_digest".into()))?;
        validate_sha256(&artifact_digest, "artifact digest")?;
        if digest(&Value::Object(without_artifact_digest)) != artifact_digest {
            return invalid("artifact digest mismatch");
        }

        let mut tables = (0..PATTERN_PHASE_COUNT)
            .map(|_| (0..PATTERN_FEATURE_COUNT).map(|_| HashMap::new()).collect())
            .collect::<Vec<Vec<HashMap<u32, i8>>>>();
        for (phase_key, phase_value) in object(weights, "weights")? {
            let phase = decimal_key(phase_key, PATTERN_PHASE_COUNT - 1, "weight phase")?;
            let features = array(phase_value, "weight phase tables")?;
            if features.len() != PATTERN_FEATURE_COUNT {
                return invalid("weight phase must contain 64 feature tables");
            }
            for (feature_index, feature_value) in features.iter().enumerate() {
                let table = object(feature_value, "weight feature table")?;
                let max_code = 3u32.pow(feature(feature_index).squares().len() as u32) - 1;
                for (code_key, weight_value) in table {
                    let code = decimal_key(code_key, max_code as usize, "feature code")? as u32;
                    let weight = weight_value.as_i64().ok_or_else(|| {
                        TrainedEvaluatorError::Invalid("weight must be an integer".into())
                    })?;
                    if weight < -i64::from(bounds[feature_index])
                        || weight > i64::from(bounds[feature_index])
                    {
                        return invalid("weight is outside its feature bound");
                    }
                    tables[phase][feature_index].insert(code, weight as i8);
                }
            }
        }

        Ok(Self {
            tables,
            context_fingerprint: stable_context_fingerprint(&[
                TRAINED_EVALUATOR_VERSION,
                format_version,
                parse_hex_u64(
                    string(
                        object(feature_contract, "feature contract")?,
                        "catalog_digest",
                    )?,
                    "catalog digest",
                )?,
                u64::from(PATTERN_PHASE_COUNT as u8),
                digest_u64(expected_weight_digest),
                digest_u64(&artifact_digest),
            ]),
        })
    }
}

impl BoardEvaluator for TrainedEvaluator {
    fn evaluate(&self, board: &Board, color: Color) -> EvalResult {
        let score = if board.empty_cells().count_ones() == 0 {
            board.count(color) as i32 - board.count(color.opponent()) as i32
        } else {
            let features =
                extract_features(board, color).expect("non-terminal boards have a pattern phase");
            self.tables[usize::from(features.phase)]
                .iter()
                .zip(features.values)
                .map(|(table, code)| i32::from(*table.get(&code).unwrap_or(&0)))
                .sum()
        };
        EvalResult {
            score,
            factors: EvalFactors::default(),
        }
    }

    fn name(&self) -> &str {
        "trained"
    }

    fn context_fingerprint(&self) -> u64 {
        self.context_fingerprint
    }
}

fn validate_feature_contract(value: &Value) -> Result<(), TrainedEvaluatorError> {
    let contract = object(value, "feature_contract")?;
    if u64_value(contract, "format_version")? != u64::from(PATTERN_FORMAT_VERSION)
        || string(contract, "catalog_digest")? != format!("{:016x}", catalog_digest())
        || u64_value(contract, "phase_count")? != PATTERN_PHASE_COUNT as u64
        || string(contract, "score_scale")? != "final_disc_difference"
    {
        return invalid("feature contract mismatch");
    }
    Ok(())
}

fn validate_provenance(value: &Value) -> Result<(), TrainedEvaluatorError> {
    let provenance = object(value, "provenance")?;
    if string(provenance, "trainer_version")? != TRAINER_VERSION
        || u64_value(provenance, "seed").is_err()
    {
        return invalid("provenance is incomplete");
    }
    validate_sha256(
        string(provenance, "input_manifest_digest")?,
        "input manifest digest",
    )?;
    let optimizer = object(object_value(provenance, "optimizer")?, "optimizer")?;
    if string(optimizer, "name")? != "sparse_mean_v1"
        || u64_value(optimizer, "normalization_divisor")? != PATTERN_FEATURE_COUNT as u64
    {
        return invalid("provenance has an unsupported optimizer");
    }
    let licenses = array(object_value(provenance, "licenses")?, "licenses")?;
    if licenses.is_empty()
        || licenses
            .iter()
            .any(|value| value.as_str().is_none_or(str::is_empty))
    {
        return invalid("provenance licenses are invalid");
    }
    Ok(())
}

fn digest(value: &Value) -> String {
    let bytes = serde_json::to_vec(value).expect("JSON value serializes");
    format!("{:x}", Sha256::digest(bytes))
}

fn digest_u64(digest: &str) -> u64 {
    let mut hasher = Sha256::new();
    hasher.update(digest.as_bytes());
    let output = hasher.finalize();
    u64::from_le_bytes(output[..8].try_into().expect("SHA-256 is 32 bytes"))
}

fn parse_hex_u64(value: &str, name: &str) -> Result<u64, TrainedEvaluatorError> {
    u64::from_str_radix(value, 16)
        .map_err(|_| TrainedEvaluatorError::Invalid(format!("invalid {name}")))
}

fn validate_sha256(value: &str, name: &str) -> Result<(), TrainedEvaluatorError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return invalid(&format!("invalid {name}"));
    }
    Ok(())
}

fn object<'a>(
    value: &'a Value,
    name: &str,
) -> Result<&'a Map<String, Value>, TrainedEvaluatorError> {
    value
        .as_object()
        .ok_or_else(|| TrainedEvaluatorError::Invalid(format!("{name} must be an object")))
}

fn object_value<'a>(
    object: &'a Map<String, Value>,
    key: &str,
) -> Result<&'a Value, TrainedEvaluatorError> {
    object
        .get(key)
        .ok_or_else(|| TrainedEvaluatorError::Invalid(format!("missing {key}")))
}

fn array<'a>(value: &'a Value, name: &str) -> Result<&'a Vec<Value>, TrainedEvaluatorError> {
    value
        .as_array()
        .ok_or_else(|| TrainedEvaluatorError::Invalid(format!("{name} must be an array")))
}

fn string<'a>(object: &'a Map<String, Value>, key: &str) -> Result<&'a str, TrainedEvaluatorError> {
    object_value(object, key)?
        .as_str()
        .ok_or_else(|| TrainedEvaluatorError::Invalid(format!("{key} must be a string")))
}

fn u64_value(object: &Map<String, Value>, key: &str) -> Result<u64, TrainedEvaluatorError> {
    object_value(object, key)?
        .as_u64()
        .ok_or_else(|| TrainedEvaluatorError::Invalid(format!("{key} must be an integer")))
}

fn decimal_key(value: &str, maximum: usize, name: &str) -> Result<usize, TrainedEvaluatorError> {
    if value.is_empty()
        || (value.len() > 1 && value.starts_with('0'))
        || !value.bytes().all(|byte| byte.is_ascii_digit())
    {
        return invalid(&format!("{name} must be a canonical decimal key"));
    }
    let number = value
        .parse::<usize>()
        .map_err(|_| TrainedEvaluatorError::Invalid(format!("invalid {name}")))?;
    if number > maximum {
        return invalid(&format!("{name} is outside the allowed range"));
    }
    Ok(number)
}

fn invalid<T>(message: &str) -> Result<T, TrainedEvaluatorError> {
    Err(TrainedEvaluatorError::Invalid(message.into()))
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn artifact(weight: i8) -> Value {
        let board = Board::new();
        let code = extract_features(&board, Color::Black).unwrap().values[0];
        let mut tables = (0..PATTERN_FEATURE_COUNT)
            .map(|_| json!({}))
            .collect::<Vec<_>>();
        tables[0] = json!({ code.to_string(): weight });
        let weights = json!({ "0": tables });
        let mut value = json!({
            "format_version": PATTERN_FORMAT_VERSION,
            "feature_contract": {
                "format_version": PATTERN_FORMAT_VERSION,
                "catalog_digest": format!("{:016x}", catalog_digest()),
                "phase_count": PATTERN_PHASE_COUNT,
                "score_scale": "final_disc_difference",
            },
            "provenance": {
                "trainer_version": TRAINER_VERSION,
                "input_manifest_digest": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "licenses": ["CC0-1.0"],
                "seed": 7,
                "optimizer": { "name": "sparse_mean_v1", "normalization_divisor": PATTERN_FEATURE_COUNT },
            },
            "feature_max_abs": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "weights": weights,
        });
        let weight_digest = digest(value.get("weights").unwrap());
        value
            .as_object_mut()
            .unwrap()
            .insert("weight_digest".into(), json!(weight_digest));
        let artifact_digest = digest(&value);
        value
            .as_object_mut()
            .unwrap()
            .insert("artifact_digest".into(), json!(artifact_digest));
        value
    }

    #[test]
    fn evaluates_valid_sparse_artifact_without_explanation_factors() {
        let evaluator = TrainedEvaluator::from_json_value(artifact(1)).unwrap();
        let result = evaluator.evaluate(&Board::new(), Color::Black);
        assert_eq!(result.score, 1);
        assert_eq!(result.factors.total(), 0);
    }

    #[test]
    fn rejects_tampered_artifact_and_scopes_context_to_weights() {
        let mut tampered = artifact(1);
        tampered["provenance"]["seed"] = json!(8);
        assert!(TrainedEvaluator::from_json_value(tampered).is_err());

        let one = TrainedEvaluator::from_json_value(artifact(1)).unwrap();
        let minus_one = TrainedEvaluator::from_json_value(artifact(-1)).unwrap();
        assert_ne!(one.context_fingerprint(), minus_one.context_fingerprint());
    }
}
