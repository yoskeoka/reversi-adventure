use reversi_ai::config::AiConfig;
use reversi_ai::eval::strategic::StrategicEvaluator;
use reversi_ai::search::{SearchBudget, SearchEngine, SearchOutcome};
use reversi_engine::board::Board;
use reversi_engine::types::{Color, Position};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::{self, BufRead};
use std::time::Duration;

enum BudgetMode {
    NodeLimit(u64),
    TimeLimit(Duration),
}

struct Args {
    corpus: String,
    budget: BudgetMode,
    config: AiConfig,
}

fn usage() -> &'static str {
    "usage: reversi-ai-search-profile --corpus PATH (--node-limit N | --time-limit-ms N) [--opening-depth N --midgame-depth N --endgame-depth N --exact-solver-empty-squares N]"
}

fn parse_u8(value: &str, option: &str) -> Result<u8, String> {
    value
        .parse::<u8>()
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| format!("{option} expects a positive unsigned 8-bit integer"))
}

fn parse_u32(value: &str, option: &str) -> Result<u32, String> {
    value
        .parse::<u32>()
        .map_err(|_| format!("{option} expects an unsigned 32-bit integer"))
}

fn parse_u64(value: &str, option: &str) -> Result<u64, String> {
    value
        .parse::<u64>()
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| format!("{option} expects a positive unsigned 64-bit integer"))
}

fn parse_args() -> Result<Args, String> {
    let mut corpus = None;
    let mut node_limit = None;
    let mut time_limit_ms = None;
    let mut opening_depth = 8;
    let mut midgame_depth = 8;
    let mut endgame_depth = 8;
    let mut exact_solver_empty_squares = AiConfig::DEFAULT_EXACT_SOLVER_EMPTY_SQUARES;
    let mut args = std::env::args().skip(1);

    while let Some(option) = args.next() {
        let mut value = || {
            args.next()
                .ok_or_else(|| format!("{option} requires a value"))
        };
        match option.as_str() {
            "--help" | "-h" => {
                println!("{}", usage());
                std::process::exit(0);
            }
            "--corpus" => corpus = Some(value()?),
            "--node-limit" => node_limit = Some(parse_u64(&value()?, "--node-limit")?),
            "--time-limit-ms" => time_limit_ms = Some(parse_u64(&value()?, "--time-limit-ms")?),
            "--opening-depth" => opening_depth = parse_u8(&value()?, "--opening-depth")?,
            "--midgame-depth" => midgame_depth = parse_u8(&value()?, "--midgame-depth")?,
            "--endgame-depth" => endgame_depth = parse_u8(&value()?, "--endgame-depth")?,
            "--exact-solver-empty-squares" => {
                exact_solver_empty_squares = parse_u32(&value()?, "--exact-solver-empty-squares")?
            }
            _ => return Err(format!("unknown option {option}\n{}", usage())),
        }
    }

    let budget = match (node_limit, time_limit_ms) {
        (Some(limit), None) => BudgetMode::NodeLimit(limit),
        (None, Some(limit)) => BudgetMode::TimeLimit(Duration::from_millis(limit)),
        (None, None) => {
            return Err(format!(
                "exactly one of --node-limit or --time-limit-ms is required\n{}",
                usage()
            ))
        }
        (Some(_), Some(_)) => {
            return Err(format!(
                "--node-limit and --time-limit-ms are mutually exclusive\n{}",
                usage()
            ))
        }
    };

    Ok(Args {
        corpus: corpus.ok_or_else(|| format!("--corpus is required\n{}", usage()))?,
        budget,
        config: AiConfig::new(opening_depth, midgame_depth, endgame_depth)
            .with_exact_solver_empty_squares(exact_solver_empty_squares),
    })
}

fn board_from_flat_string(flat: &str) -> Result<Board, String> {
    if flat.len() != 64 || !flat.chars().all(|cell| matches!(cell, 'B' | 'W' | '.')) {
        return Err("board must contain exactly 64 characters from B, W, and .".to_string());
    }
    let rows = flat
        .as_bytes()
        .chunks(8)
        .map(|row| std::str::from_utf8(row).expect("board was validated"))
        .collect::<Vec<_>>()
        .join("\n");
    Board::from_string(&rows)
}

fn parse_color(value: &str) -> Result<Color, String> {
    match value {
        "B" => Ok(Color::Black),
        "W" => Ok(Color::White),
        _ => Err(format!("side_to_move must be B or W, got {value:?}")),
    }
}

fn move_name(position: Position) -> String {
    format!("{}{}", (b'a' + position.col) as char, position.row + 1)
}

fn outcome_json(outcome: SearchOutcome) -> Value {
    match outcome {
        SearchOutcome::Move(position) => json!({ "kind": "move", "move": move_name(position) }),
        SearchOutcome::Pass => json!({ "kind": "pass" }),
        SearchOutcome::GameOver => json!({ "kind": "game_over" }),
    }
}

fn required_string<'a>(
    record: &'a Value,
    key: &str,
    line_number: usize,
) -> Result<&'a str, String> {
    record[key]
        .as_str()
        .ok_or_else(|| format!("corpus line {line_number} requires string {key:?}"))
}

fn main() -> Result<(), String> {
    let args = parse_args()?;
    let reader: Box<dyn BufRead> = if args.corpus == "-" {
        Box::new(io::BufReader::new(io::stdin().lock()))
    } else {
        Box::new(io::BufReader::new(
            File::open(&args.corpus).map_err(|error| format!("{}: {error}", args.corpus))?,
        ))
    };
    let evaluator = StrategicEvaluator::new();

    for (line_index, line) in reader.lines().enumerate() {
        let line_number = line_index + 1;
        let line = line.map_err(|error| format!("corpus line {line_number}: {error}"))?;
        if line.trim().is_empty() {
            continue;
        }
        let record: Value = serde_json::from_str(&line)
            .map_err(|error| format!("corpus line {line_number}: {error}"))?;
        let position_id = required_string(&record, "position_id", line_number)?;
        let board_flat = required_string(&record, "board", line_number)?;
        let board = board_from_flat_string(board_flat)
            .map_err(|error| format!("corpus line {line_number}: {error}"))?;
        let color = parse_color(required_string(&record, "side_to_move", line_number)?)
            .map_err(|error| format!("corpus line {line_number}: {error}"))?;
        let mut engine = SearchEngine::new();
        let budget = match args.budget {
            BudgetMode::NodeLimit(limit) => SearchBudget::with_node_limit_only(limit),
            BudgetMode::TimeLimit(limit) => SearchBudget::with_time_limit(limit),
        };
        let result = engine.search_with_budget(&board, color, &evaluator, &args.config, &budget);
        let board_digest = format!("{:x}", Sha256::digest(board_flat.as_bytes()));
        let pv = result.pv.into_iter().map(move_name).collect::<Vec<_>>();
        let mut output = json!({
            "board_digest": board_digest,
            "completed_depth": result.completed_depth,
            "elapsed_ns": result.elapsed.as_nanos(),
            "exact": result.exact,
            "nodes_searched": result.nodes_searched,
            "outcome": outcome_json(result.outcome),
            "position_id": position_id,
            "pv": pv,
            "score": result.score,
        });
        match args.budget {
            BudgetMode::NodeLimit(limit) => output["node_limit"] = json!(limit),
            BudgetMode::TimeLimit(limit) => {
                let stone_count = board.count(Color::Black) + board.count(Color::White);
                let expected_exact = args.config.exact_solver_empty_squares > 0
                    && board.empty_cells().count_ones() <= args.config.exact_solver_empty_squares;
                let expected_depth = args.config.depth_for_phase(stone_count);
                let success =
                    result.completed_depth == expected_depth && result.exact == expected_exact;
                output["time_limit_ms"] = json!(limit.as_millis());
                output["timing_success"] = json!(success);
                output["timing_failure_reason"] = if success {
                    Value::Null
                } else if result.completed_depth != expected_depth {
                    json!("incomplete_depth")
                } else {
                    json!("unexpected_exactness")
                };
            }
        }
        println!("{output}");
    }
    Ok(())
}
