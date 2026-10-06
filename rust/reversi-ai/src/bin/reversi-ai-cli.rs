use std::io::{self, BufRead, Write};

use reversi_ai::config::{AiConfig, DecisionMoveConfig};
use reversi_ai::eval::novice::NoviceEvaluator;
use reversi_ai::eval::strategic::StrategicEvaluator;
use reversi_ai::eval::trained::TrainedEvaluator;
use reversi_ai::eval::BoardEvaluator;
use reversi_ai::search::{SearchBudget, SearchEngine, SearchOutcome, SearchResult};
use reversi_engine::board::Board;
use reversi_engine::types::{Color, Position};
use std::time::{Duration, Instant};

fn usage() -> &'static str {
    "usage: reversi-ai-cli [--evaluator strategic|novice|trained] [--trained-artifact PATH] [--opening-depth N] \
--midgame-depth N --endgame-depth N [--exact-solver-empty-squares N] \
[--profile strong-engine-hcap-v1] [--time-limit-ms N] [--node-limit N] [--exact-cache-scope turn|game] (default: turn; explicit game is diagnostic only)\n\nadvisor mode: --advisor-analysis [--print-advisor-config-id] --opening-depth N --midgame-depth N --exact-solver-empty-squares N\n\ndecision-move match mode: --decision-move-phases --opening-depth N --midgame-depth N --exact-solver-empty-squares N\n\nstdin/stdout protocol: position_id<TAB>64-char-board<TAB>B|W -> position_id<TAB>move|pass (advisor: JSON v1)"
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
    advisor_config: Option<DecisionMoveConfig>,
    decision_move_config: Option<DecisionMoveConfig>,
    print_advisor_config_id: bool,
    exact_cache_scope: String,
}

fn parse_args() -> Result<CliArgs, String> {
    parse_args_from(std::env::args().skip(1))
}

fn parse_args_from(mut args: impl Iterator<Item = String>) -> Result<CliArgs, String> {
    let mut evaluator = String::from("strategic");
    let mut opening_depth = 3;
    let mut midgame_depth = 4;
    let mut endgame_depth = 6;
    let mut exact_solver_empty_squares = AiConfig::DEFAULT_EXACT_SOLVER_EMPTY_SQUARES;
    let mut time_limit = Duration::from_secs(30);
    let mut node_limit = None;
    let mut exact_cache_scope = String::from("turn");
    let mut profile = None;
    let mut has_explicit_config = false;
    let mut has_endgame_depth = false;
    let mut advisor_analysis = false;
    let mut print_advisor_config_id = false;
    let mut decision_move_phases = false;
    let mut trained_artifact = None;

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
                has_endgame_depth = true;
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
            "--exact-cache-scope" => exact_cache_scope = value()?,
            "--profile" => profile = Some(value()?),
            "--advisor-analysis" => advisor_analysis = true,
            "--print-advisor-config-id" => print_advisor_config_id = true,
            "--decision-move-phases" => decision_move_phases = true,
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
    if !matches!(exact_cache_scope.as_str(), "game" | "turn") {
        return Err("--exact-cache-scope must be game or turn".to_string());
    }
    if exact_cache_scope == "game" && advisor_analysis {
        return Err(
            "advisor mode does not accept diagnostic --exact-cache-scope game; use turn".into(),
        );
    }
    if advisor_analysis && (profile.is_some() || has_endgame_depth) {
        return Err("advisor mode does not accept --profile or --endgame-depth".into());
    }
    if print_advisor_config_id && !advisor_analysis {
        return Err("--print-advisor-config-id requires --advisor-analysis".into());
    }
    if decision_move_phases && (advisor_analysis || profile.is_some() || has_endgame_depth) {
        return Err(
            "--decision-move-phases does not accept --advisor-analysis, --profile, or --endgame-depth"
                .into(),
        );
    }
    let advisor_config = advisor_analysis
        .then(|| DecisionMoveConfig::new(opening_depth, midgame_depth, exact_solver_empty_squares))
        .transpose()?;
    let decision_move_config = decision_move_phases
        .then(|| DecisionMoveConfig::new(opening_depth, midgame_depth, exact_solver_empty_squares))
        .transpose()?;
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
        advisor_config,
        decision_move_config,
        print_advisor_config_id,
        exact_cache_scope,
    })
}

fn match_config_for_board(args: &CliArgs, board: &Board) -> AiConfig {
    if let Some(phases) = args.decision_move_config {
        let stones = board.count(Color::Black) + board.count(Color::White);
        phases.search_config_for_stones(stones)
    } else {
        args.config
    }
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
) -> (String, SearchResult) {
    let mut budget = SearchBudget::with_time_limit(time_limit);
    if let Some(limit) = node_limit {
        budget = budget.with_node_limit(limit);
    }
    let result = engine.search_with_budget(board, color, evaluator, config, &budget);
    let selected = match result.outcome {
        SearchOutcome::Move(position) => move_name(position),
        SearchOutcome::Pass | SearchOutcome::GameOver => "pass".to_string(),
    };
    (selected, result)
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
    if args.print_advisor_config_id {
        let config = args
            .advisor_config
            .as_ref()
            .expect("advisor mode was validated");
        println!(
            "{}",
            SearchEngine::advisor_config_id(evaluator.as_ref(), config)
        );
        return Ok(());
    }
    let mut engine = if args.exact_cache_scope == "game" {
        SearchEngine::with_diagnostic_game_exact_cache()
    } else {
        SearchEngine::new()
    };
    let stdin = io::stdin();
    let mut stdout = io::BufWriter::new(io::stdout().lock());

    for (line_number, line) in stdin.lock().lines().enumerate() {
        let line = line.map_err(|error| format!("stdin line {}: {error}", line_number + 1))?;
        if line.trim().is_empty() {
            continue;
        }
        let fields = line.split('\t').collect::<Vec<_>>();
        if fields[0] == "new_game" {
            if fields.len() != 2 || fields[1].is_empty() || fields[1].contains(['\r', '\n']) {
                return Err(format!(
                    "stdin line {} must be new_game<TAB>game_id",
                    line_number + 1
                ));
            }
            engine.new_game();
            writeln!(stdout, "new_game\t{}\tready", fields[1])
                .map_err(|error| format!("stdout: {error}"))?;
            stdout.flush().map_err(|error| format!("stdout: {error}"))?;
            continue;
        }
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
        if let Some(config) = &args.advisor_config {
            let mut budget = SearchBudget::with_time_limit(args.time_limit);
            if let Some(limit) = args.node_limit {
                budget = budget.with_node_limit(limit);
            }
            let analysis =
                engine.analyze_with_budget(&board, color, evaluator.as_ref(), config, &budget)?;
            let outcome = match analysis.outcome {
                SearchOutcome::Move(_) => "move",
                SearchOutcome::Pass => "pass",
                SearchOutcome::GameOver => "game_over",
            };
            let scores = analysis
                .scores
                .iter()
                .map(|score| {
                    serde_json::json!({
                        "move": move_name(score.position), "value": score.value,
                        "completed_depth": score.completed_depth, "exact": score.exact,
                    })
                })
                .collect::<Vec<_>>();
            let response = serde_json::json!({
                "schema_version": 1, "position_id": fields[0], "board": fields[1],
                "side": fields[2], "config_id": analysis.config_id, "outcome": outcome,
                "completed_depth": analysis.completed_depth, "exact": analysis.exact,
                "scores": scores,
            });
            writeln!(stdout, "{response}").map_err(|error| format!("stdout: {error}"))?;
            stdout.flush().map_err(|error| format!("stdout: {error}"))?;
            continue;
        }
        let decision_started = Instant::now();
        let match_config = match_config_for_board(&args, &board);
        let (move_name, search_result) = choose_move(
            &mut engine,
            evaluator.as_ref(),
            &board,
            color,
            &match_config,
            args.time_limit,
            args.node_limit,
        );
        let outcome = match search_result.outcome {
            SearchOutcome::Move(_) => "move",
            SearchOutcome::Pass => "pass",
            SearchOutcome::GameOver => "game_over",
        };
        eprintln!(
            "search_diagnostic_v1\tposition_id={}\telapsed_us={}\tnodes={}\texact={}\tscore={}\tcompleted_depth={}\toutcome={}\tcache_probes={}\tcache_hits={}\tcache_stores={}",
            fields[0],
            decision_started.elapsed().as_micros(),
            search_result.nodes_searched,
            search_result.exact,
            search_result.score.map_or_else(|| "none".to_string(), |score| score.to_string()),
            search_result.completed_depth,
            outcome,
            search_result.exact_cache.probes,
            search_result.exact_cache.hits,
            search_result.exact_cache.stores,
        );
        eprintln!(
            "exact_cache_policy_v1\tposition_id={}\texact_cache_scope={}\texact_cache_policy={}",
            fields[0],
            args.exact_cache_scope,
            if args.exact_cache_scope == "game" {
                "diagnostic-game-v1"
            } else {
                "exact-cache-cross-decision-suspended-v1"
            },
        );
        io::stderr()
            .flush()
            .map_err(|error| format!("stderr: {error}"))?;
        writeln!(stdout, "{}\t{}", fields[0], move_name)
            .map_err(|error| format!("stdout: {error}"))?;
        stdout.flush().map_err(|error| format!("stdout: {error}"))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(options: &[&str]) -> Result<CliArgs, String> {
        parse_args_from(options.iter().map(|option| option.to_string()))
    }

    fn board_with_stones(stones: usize) -> Board {
        let flat = format!("{}{}", "B".repeat(stones), ".".repeat(64 - stones));
        board_from_flat_string(&flat).unwrap()
    }

    #[test]
    fn exact_cache_game_is_explicit_diagnostic_opt_in() {
        assert_eq!(args(&[]).unwrap().exact_cache_scope, "turn");
        assert_eq!(
            args(&["--exact-cache-scope", "turn"])
                .unwrap()
                .exact_cache_scope,
            "turn"
        );
        assert_eq!(
            args(&["--exact-cache-scope", "game"])
                .unwrap()
                .exact_cache_scope,
            "game"
        );
        assert!(args(&["--exact-cache-scope", "persistent"]).is_err());
        assert!(args(&["--advisor-analysis", "--exact-cache-scope", "game"]).is_err());
        assert!(args(&["--advisor-analysis", "--exact-cache-scope", "turn"]).is_ok());
    }

    #[test]
    fn decision_move_match_uses_move_number_boundaries_and_exact_threshold() {
        let parsed = args(&[
            "--decision-move-phases",
            "--opening-depth",
            "2",
            "--midgame-depth",
            "5",
            "--exact-solver-empty-squares",
            "0",
        ])
        .unwrap();
        for stones in [4, 23] {
            let config = match_config_for_board(&parsed, &board_with_stones(stones));
            assert_eq!(config.depth_for_phase(stones as u32), 2);
            assert_eq!(config.exact_solver_empty_squares, 0);
        }
        for stones in [24, 63] {
            let config = match_config_for_board(&parsed, &board_with_stones(stones));
            assert_eq!(config.depth_for_phase(stones as u32), 5);
            assert_eq!(config.exact_solver_empty_squares, 0);
        }
        let threshold_16 = args(&[
            "--decision-move-phases",
            "--exact-solver-empty-squares",
            "16",
        ])
        .unwrap();
        assert_eq!(
            match_config_for_board(&threshold_16, &board_with_stones(48))
                .exact_solver_empty_squares,
            16
        );
    }

    #[test]
    fn decision_move_match_rejects_unavailable_settings() {
        for options in [
            vec!["--decision-move-phases", "--endgame-depth", "2"],
            vec![
                "--decision-move-phases",
                "--profile",
                "strong-engine-hcap-v1",
            ],
            vec!["--decision-move-phases", "--advisor-analysis"],
            vec!["--decision-move-phases", "--opening-depth", "13"],
            vec![
                "--decision-move-phases",
                "--exact-solver-empty-squares",
                "31",
            ],
        ] {
            assert!(args(&options).is_err(), "{options:?}");
        }
    }

    #[test]
    fn match_and_advisor_accept_identical_inclusive_limits() {
        for mode in ["--decision-move-phases", "--advisor-analysis"] {
            for (opening, midgame, exact, accepted) in [
                ("1", "1", "0", true),
                ("12", "16", "30", true),
                ("0", "1", "0", false),
                ("13", "1", "0", false),
                ("1", "0", "0", false),
                ("1", "17", "0", false),
                ("1", "1", "31", false),
            ] {
                let parsed = args(&[
                    mode,
                    "--opening-depth",
                    opening,
                    "--midgame-depth",
                    midgame,
                    "--exact-solver-empty-squares",
                    exact,
                ]);
                assert_eq!(
                    parsed.is_ok(),
                    accepted,
                    "{mode}: {opening}/{midgame}/{exact}"
                );
                if accepted {
                    let parsed = parsed.unwrap();
                    let config = parsed
                        .advisor_config
                        .or(parsed.decision_move_config)
                        .unwrap();
                    assert_eq!(config.opening_depth, opening.parse::<u8>().unwrap());
                    assert_eq!(config.midgame_depth, midgame.parse::<u8>().unwrap());
                    for stones in [23, 24, 33, 34] {
                        let search = config.search_config_for_stones(stones);
                        assert_eq!(
                            search.exact_solver_empty_squares,
                            exact.parse::<u32>().unwrap()
                        );
                        assert_eq!(
                            search.depth_for_phase(stones),
                            if stones <= 23 {
                                config.opening_depth
                            } else {
                                config.midgame_depth
                            }
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn ordinary_match_retains_existing_phase_policy() {
        let args = args(&[
            "--opening-depth",
            "2",
            "--midgame-depth",
            "5",
            "--endgame-depth",
            "7",
        ])
        .unwrap();
        assert!(args.decision_move_config.is_none());
        assert_eq!(
            match_config_for_board(&args, &board_with_stones(23)).depth_for_phase(23),
            5
        );
        assert_eq!(
            match_config_for_board(&args, &board_with_stones(45)).depth_for_phase(45),
            7
        );
    }
}
