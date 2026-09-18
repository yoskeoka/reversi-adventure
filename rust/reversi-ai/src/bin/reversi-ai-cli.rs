use std::io::{self, BufRead, Write};

use reversi_ai::config::AiConfig;
use reversi_ai::eval::novice::NoviceEvaluator;
use reversi_ai::eval::strategic::StrategicEvaluator;
use reversi_ai::eval::BoardEvaluator;
use reversi_ai::player::AiPlayer;
use reversi_engine::board::Board;
use reversi_engine::moves;
use reversi_engine::types::{Color, Position};

fn usage() -> &'static str {
    "usage: reversi-ai-cli [--evaluator strategic|novice] [--opening-depth N] \
--midgame-depth N --endgame-depth N\n\nstdin/stdout protocol: position_id<TAB>64-char-board<TAB>B|W -> position_id<TAB>move|pass"
}

fn parse_u8(value: &str, option: &str) -> Result<u8, String> {
    let parsed = value
        .parse::<u8>()
        .map_err(|_| format!("{option} expects a positive unsigned 8-bit integer"))?;
    if parsed == 0 {
        return Err(format!("{option} expects a positive unsigned 8-bit integer"));
    }
    Ok(parsed)
}

fn parse_args() -> Result<(String, AiConfig), String> {
    let mut evaluator = String::from("strategic");
    let mut opening_depth = 3;
    let mut midgame_depth = 4;
    let mut endgame_depth = 6;
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
            "--opening-depth" => opening_depth = parse_u8(&value()?, "--opening-depth")?,
            "--midgame-depth" => midgame_depth = parse_u8(&value()?, "--midgame-depth")?,
            "--endgame-depth" => endgame_depth = parse_u8(&value()?, "--endgame-depth")?,
            _ => return Err(format!("unknown option {option}\n{}", usage())),
        }
    }

    if !matches!(evaluator.as_str(), "strategic" | "novice") {
        return Err(format!("unknown evaluator {evaluator:?}"));
    }
    Ok((
        evaluator,
        AiConfig::new(opening_depth, midgame_depth, endgame_depth),
    ))
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

fn choose_move(player: &mut AiPlayer, board: &Board, color: Color) -> String {
    if !moves::has_legal_move(board, color) {
        return "pass".to_string();
    }

    move_name(player.think(board, color).best_move)
}

fn main() -> Result<(), String> {
    let (evaluator_name, config) = parse_args()?;
    let evaluator: Box<dyn BoardEvaluator> = match evaluator_name.as_str() {
        "strategic" => Box::new(StrategicEvaluator::new()),
        "novice" => Box::new(NoviceEvaluator::new()),
        _ => unreachable!("evaluator was checked while parsing arguments"),
    };
    let mut player = AiPlayer::new(evaluator, config);
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
        let move_name = choose_move(&mut player, &board, color);
        writeln!(stdout, "{}\t{}", fields[0], move_name)
            .map_err(|error| format!("stdout: {error}"))?;
        stdout.flush().map_err(|error| format!("stdout: {error}"))?;
    }
    Ok(())
}
