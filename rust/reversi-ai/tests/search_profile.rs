use std::fs;
use std::process::Command;

use serde_json::Value;

const INITIAL: &str = "...........................WB......BW...........................";
const FORCED_PASS: &str = "WWW.....WWB.....WWBB....WWBBB...WB.BB...W...B...W...............";
const GAME_OVER: &str = "WWWWWWWBWWWWWWWBWWWWWWWBWWWWWBWBWWWBWWBBWWBWWWBBWBWWWWWWBBBBBBBW";
const SIXTEEN_EMPTY: &str = "..B.W.....BBW.WB.B.WWWBW.WWWBBWWB.WBBWWWWWWWWBW.WWBWBBB.BBBBBBB.";

fn run_profile(corpus: &std::path::Path) -> Vec<Value> {
    let output = Command::new(env!("CARGO_BIN_EXE_reversi-ai-search-profile"))
        .args([
            "--corpus",
            corpus.to_str().expect("temporary path was UTF-8"),
            "--node-limit",
            "10000",
        ])
        .output()
        .expect("failed to start reversi-ai-search-profile");
    assert!(
        output.status.success(),
        "profiler failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout)
        .expect("profiler output was not UTF-8")
        .lines()
        .map(|line| serde_json::from_str(line).expect("profiler emitted JSON"))
        .collect()
}

fn run_profile_with_args(corpus: &std::path::Path, args: &[&str]) -> Vec<Value> {
    let output = Command::new(env!("CARGO_BIN_EXE_reversi-ai-search-profile"))
        .args([
            "--corpus",
            corpus.to_str().expect("temporary path was UTF-8"),
        ])
        .args(args)
        .output()
        .expect("failed to start reversi-ai-search-profile");
    assert!(
        output.status.success(),
        "profiler failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout)
        .expect("profiler output was not UTF-8")
        .lines()
        .map(|line| serde_json::from_str(line).expect("profiler emitted JSON"))
        .collect()
}

fn deterministic_projection(mut record: Value) -> Value {
    record
        .as_object_mut()
        .expect("profiler record was an object")
        .remove("elapsed_ns");
    record
}

#[test]
fn search_profile_encodes_terminal_outcomes_and_repeats_fixed_node_projection() {
    let path = std::env::temp_dir().join(format!(
        "reversi-ai-search-profile-{}-{}.jsonl",
        std::process::id(),
        std::thread::current().name().unwrap_or("test")
    ));
    let corpus = format!(
        "{{\"position_id\":\"initial\",\"board\":\"{INITIAL}\",\"side_to_move\":\"B\"}}\n{{\"position_id\":\"pass\",\"board\":\"{FORCED_PASS}\",\"side_to_move\":\"B\"}}\n{{\"position_id\":\"game-over\",\"board\":\"{GAME_OVER}\",\"side_to_move\":\"B\"}}\n"
    );
    fs::write(&path, corpus).expect("failed to write temporary corpus");

    let first = run_profile(&path);
    let second = run_profile(&path);
    fs::remove_file(&path).expect("failed to remove temporary corpus");

    assert_eq!(first.len(), 3);
    assert_eq!(
        first[0]["outcome"]["kind"], "move",
        "initial position should encode a move"
    );
    assert!(first[0]["pv"].as_array().is_some_and(|pv| !pv.is_empty()));
    assert_eq!(first[1]["outcome"]["kind"], "pass");
    assert_eq!(first[2]["outcome"]["kind"], "game_over");
    assert_eq!(
        first
            .into_iter()
            .map(deterministic_projection)
            .collect::<Vec<_>>(),
        second
            .into_iter()
            .map(deterministic_projection)
            .collect::<Vec<_>>()
    );
}

#[test]
fn search_profile_requires_exactly_one_budget_mode() {
    for arguments in [
        vec!["--corpus", "-"],
        vec!["--corpus", "-", "--node-limit", "1", "--time-limit-ms", "1"],
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_reversi-ai-search-profile"))
            .args(arguments)
            .output()
            .expect("failed to start reversi-ai-search-profile");
        assert!(!output.status.success());
        assert!(
            String::from_utf8_lossy(&output.stderr).contains("exactly one")
                || String::from_utf8_lossy(&output.stderr).contains("mutually exclusive")
        );
    }
}

#[test]
fn search_profile_reports_time_mode_completion_metadata() {
    let path = std::env::temp_dir().join(format!(
        "reversi-ai-search-profile-time-{}-{}.jsonl",
        std::process::id(),
        std::thread::current().name().unwrap_or("test")
    ));
    let corpus = format!(
        "{{\"position_id\":\"initial\",\"board\":\"{INITIAL}\",\"side_to_move\":\"B\"}}\n{{\"position_id\":\"exact\",\"board\":\"{SIXTEEN_EMPTY}\",\"side_to_move\":\"B\"}}\n"
    );
    fs::write(&path, corpus).expect("failed to write temporary corpus");

    let records = run_profile_with_args(
        &path,
        &[
            "--time-limit-ms",
            "60000",
            "--opening-depth",
            "1",
            "--midgame-depth",
            "1",
            "--endgame-depth",
            "1",
        ],
    );
    fs::remove_file(&path).expect("failed to remove temporary corpus");

    assert_eq!(records.len(), 2);
    assert_eq!(records[0]["time_limit_ms"], 60000);
    assert_eq!(records[0]["timing_success"], true);
    assert_eq!(records[0]["timing_failure_reason"], Value::Null);
    assert_eq!(records[0]["exact"], false);
    assert_eq!(records[0]["exact_pvs"]["null_window_calls"], 0);
    assert_eq!(records[1]["timing_success"], true);
    assert_eq!(records[1]["timing_failure_reason"], Value::Null);
    assert_eq!(records[1]["completed_depth"], 16);
    assert_eq!(records[1]["exact"], true);
    assert!(
        records[1]["exact_pvs"]["null_window_calls"]
            .as_u64()
            .unwrap()
            > 0
    );
    assert!(records[1]["exact_pvs"]["full_researches"].as_u64().unwrap() > 0);
    assert!(records
        .iter()
        .all(|record| record.get("node_limit").is_none()));
}

#[test]
fn search_profile_reports_incomplete_time_mode_samples() {
    let path = std::env::temp_dir().join(format!(
        "reversi-ai-search-profile-timeout-{}-{}.jsonl",
        std::process::id(),
        std::thread::current().name().unwrap_or("test")
    ));
    let corpus = format!(
        "{{\"position_id\":\"exact\",\"board\":\"{SIXTEEN_EMPTY}\",\"side_to_move\":\"B\"}}\n"
    );
    fs::write(&path, corpus).expect("failed to write temporary corpus");

    let records = run_profile_with_args(&path, &["--time-limit-ms", "1"]);
    fs::remove_file(&path).expect("failed to remove temporary corpus");

    assert_eq!(records.len(), 1);
    assert_eq!(records[0]["timing_success"], false);
    assert_eq!(records[0]["timing_failure_reason"], "incomplete_depth");
}

#[test]
fn search_profile_treats_a_full_board_as_exact_at_zero_threshold() {
    let path = std::env::temp_dir().join(format!(
        "reversi-ai-search-profile-terminal-{}-{}.jsonl",
        std::process::id(),
        std::thread::current().name().unwrap_or("test")
    ));
    let corpus = format!(
        "{{\"position_id\":\"game-over\",\"board\":\"{GAME_OVER}\",\"side_to_move\":\"B\"}}\n"
    );
    fs::write(&path, corpus).expect("failed to write temporary corpus");

    let records = run_profile_with_args(
        &path,
        &["--time-limit-ms", "1", "--exact-solver-empty-squares", "0"],
    );
    fs::remove_file(&path).expect("failed to remove temporary corpus");

    assert_eq!(records.len(), 1);
    assert_eq!(records[0]["timing_success"], true);
    assert_eq!(records[0]["timing_failure_reason"], Value::Null);
    assert_eq!(records[0]["completed_depth"], 0);
    assert_eq!(records[0]["exact"], true);
}
