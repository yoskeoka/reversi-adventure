use std::io::{self, BufRead, Write};

use reversi_ai::config::AiConfig;
use reversi_ai::eval::novice::NoviceEvaluator;
use reversi_ai::eval::strategic::StrategicEvaluator;
use reversi_ai::eval::trained::TrainedEvaluator;
use reversi_ai::eval::BoardEvaluator;
use reversi_ai::search::{SearchBudget, SearchEngine, SearchOutcome};
use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::{Color, Position};
use std::time::Duration;

fn usage() -> &'static str {
    "usage: reversi-ai-cli [--evaluator strategic|novice|trained] [--trained-artifact PATH] [--opening-depth N] \
--midgame-depth N --endgame-depth N [--exact-solver-empty-squares N] \
[--profile strong-engine-hcap-v1] [--time-limit-ms N] [--node-limit N]\n\nstdin/stdout protocol: position_id<TAB>64-char-board<TAB>B|W -> position_id<TAB>move|pass"
}

fn parse_u8(value: &str, option: &str) -> Result<u8, String> {
    let parsed = value
        .parse::<u8>()
        .map_err(|_| format!("{option} expects a positive unsigned 8-bit integer"))?;
    if parsed == 0 {
        return Err(format!(
            "{option} expects a positive unsigned 8-bit integer"
        ));
    }
    Ok(parsed)
}

fn parse_u32(value: &str, option: &str) -> Result<u32, String> {
    value
        .parse::<u32>()
        .map_err(|_| format!("{option} expects an unsigned 32-bit integer"))
}

fn parse_u64(value: &str, option: &str) -> Result<u64, String> {
    value
        .parse::<u64>()
        .map_err(|_| format!("{option} expects an unsigned 64-bit integer"))
}

struct CliArgs {
    evaluator: String,
    trained_artifact: Option<String>,
    config: AiConfig,
    time_limit: Duration,
    node_limit: Option<u64>,
}

fn parse_args() -> Result<CliArgs, String> {
    let mut evaluator = String::from("strategic");
    let mut opening_depth = 3;
    let mut midgame_depth = 4;
    let mut endgame_depth = 6;
    let mut exact_solver_empty_squares = 12;
    let mut time_limit = Duration::from_secs(30);
    let mut node_limit = None;
    let mut profile = None;
    let mut has_explicit_config = false;
    let mut trained_artifact = None;
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
            "--evaluator" => evaluator = value()?,
            "--opening-depth" => {
                opening_depth = parse_u8(&value()?, "--opening-depth")?;
                has_explicit_config = true;
            }
            "--midgame-depth" => {
                midgame_depth = parse_u8(&value()?, "--midgame-depth")?;
                has_explicit_config = true;
            }
            "--endgame-depth" => {
                endgame_depth = parse_u8(&value()?, "--endgame-depth")?;
                has_explicit_config = true;
            }
            "--exact-solver-empty-squares" => {
                exact_solver_empty_squares = parse_u32(&value()?, "--exact-solver-empty-squares")?;
                has_explicit_config = true;
            }
            "--trained-artifact" => trained_artifact = Some(value()?),
            "--time-limit-ms" => {
                time_limit = Duration::from_millis(parse_u64(&value()?, "--time-limit-ms")?)
            }
            "--node-limit" => node_limit = Some(parse_u64(&value()?, "--node-limit")?),
            "--profile" => profile = Some(value()?),
            _ => return Err(format!("unknown option {option}\n{}", usage())),
        }
    }

    if !matches!(evaluator.as_str(), "strategic" | "novice" | "trained") {
        return Err(format!("unknown evaluator {evaluator:?}"));
    }
    if evaluator == "trained" && trained_artifact.is_none() {
        return Err("--evaluator trained requires --trained-artifact PATH".to_string());
    }
    if evaluator != "trained" && trained_artifact.is_some() {
        return Err("--trained-artifact requires --evaluator trained".to_string());
    }
    let config = match profile.as_deref() {
        None => AiConfig::new(opening_depth, midgame_depth, endgame_depth)
            .with_exact_solver_empty_squares(exact_solver_empty_squares),
        Some("strong-engine-hcap-v1") if has_explicit_config => {
            return Err("--profile strong-engine-hcap-v1 conflicts with explicit depth or exact-solver settings".to_string())
        }
        Some("strong-engine-hcap-v1") => AiConfig::strong_engine_hcap_v1(),
        Some(name) => return Err(format!("unknown profile {name:?}")),
    };
    Ok(CliArgs {
        evaluator,
        trained_artifact,
        config,
        time_limit,
        node_limit,
    })
}

fn parse_color(value: &str) -> Result<Color, String> {
    match value {
        "B" => Ok(Color::Black),
        "W" => Ok(Color::White),
        _ => Err(format!("side must be B or W, got {value:?}")),
    }
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

fn move_name(position: Position) -> String {
    format!("{}{}", (b'a' + position.col) as char, position.row + 1)
}

fn choose_move<E: BoardEvaluator + ?Sized>(
    engine: &mut SearchEngine,
    evaluator: &E,
    board: &Board,
    color: Color,
    config: &AiConfig,
    time_limit: Duration,
    node_limit: Option<u64>,
) -> String {
    if !moves::has_legal_move(board, color) {
        return "pass".to_string();
    }

    let mut budget = SearchBudget::with_time_limit(time_limit);
    if let Some(limit) = node_limit {
        budget = budget.with_node_limit(limit);
    }
    match engine
        .search_with_budget(board, color, evaluator, config, &budget)
        .outcome
    {
        SearchOutcome::Move(position) => move_name(position),
        SearchOutcome::Pass | SearchOutcome::GameOver => "pass".to_string(),
    }
}

fn main() -> Result<(), String> {
    let args = parse_args()?;
    let evaluator: Box<dyn BoardEvaluator> = match args.evaluator.as_str() {
        "strategic" => Box::new(StrategicEvaluator::new()),
        "novice" => Box::new(NoviceEvaluator::new()),
        "trained" => Box::new(
            TrainedEvaluator::from_path(
                args.trained_artifact
                    .as_deref()
                    .expect("trained path was validated"),
            )
            .map_err(|error| error.to_string())?,
        ),
        _ => unreachable!("evaluator was checked while parsing arguments"),
    };
    let mut engine = SearchEngine::new();
    let stdin = io::stdin();
    let mut stdout = io::BufWriter::new(io::stdout().lock());

    for (line_number, line) in stdin.lock().lines().enumerate() {
        let line = line.map_err(|error| format!("stdin line {}: {error}", line_number + 1))?;
        if line.trim().is_empty() {
            continue;
        }
        let fields = line.split('\t').collect::<Vec<_>>();
        if fields.len() != 3
            || fields[0].is_empty()
            || fields[0].contains('\r')
            || fields[0].contains('\n')
        {
            return Err(format!(
                "stdin line {} must be position_id<TAB>board<TAB>side",
                line_number + 1
            ));
        }
        let board = board_from_flat_string(fields[1])?;
        let color = parse_color(fields[2])?;
        let move_name = choose_move(
            &mut engine,
            evaluator.as_ref(),
            &board,
            color,
            &args.config,
            args.time_limit,
            args.node_limit,
        );
        writeln!(stdout, "{}\t{}", fields[0], move_name)
            .map_err(|error| format!("stdout: {error}"))?;
        stdout.flush().map_err(|error| format!("stdout: {error}"))?;
    }
    Ok(())
}
