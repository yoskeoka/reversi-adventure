use std::io::Write;
use std::process::{Command, Stdio};

fn run_cli(input: &str) -> std::process::Output {
    run_cli_with_args(
        input,
        [
            "--evaluator",
            "novice",
            "--opening-depth",
            "1",
            "--midgame-depth",
            "1",
            "--endgame-depth",
            "1",
        ],
    )
}

fn run_cli_with_args<const N: usize>(input: &str, args: [&str; N]) -> std::process::Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_reversi-ai-cli"))
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("failed to start reversi-ai-cli");
    child
        .stdin
        .take()
        .expect("stdin was not piped")
        .write_all(input.as_bytes())
        .expect("failed to write CLI input");
    child.wait_with_output().expect("failed to read CLI output")
}

#[test]
fn cli_returns_legal_moves_and_forced_passes() {
    let initial = "...........................WB......BW...........................";
    let forced_pass = "WWW.....WWB.....WWBB....WWBBB...WB.BB...W...B...W...............";
    let output = run_cli(&format!(
        "initial\t{initial}\tB\nforced-pass\t{forced_pass}\tB\n"
    ));

    assert!(
        output.status.success(),
        "CLI failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let lines = String::from_utf8(output.stdout)
        .expect("CLI output was not UTF-8")
        .lines()
        .map(str::to_owned)
        .collect::<Vec<_>>();
    assert_eq!(lines.len(), 2);

    let initial_move = lines[0]
        .strip_prefix("initial\t")
        .expect("initial response ID mismatch");
    assert!(matches!(initial_move, "c4" | "d3" | "e6" | "f5"));
    assert_eq!(lines[1], "forced-pass\tpass");
}

#[test]
fn cli_reuses_player_without_crossing_side_to_move_cache_entries() {
    let initial = "...........................WB......BW...........................";
    let output = run_cli(&format!("black\t{initial}\tB\nwhite\t{initial}\tW\n"));

    assert!(
        output.status.success(),
        "CLI failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let lines = String::from_utf8(output.stdout)
        .expect("CLI output was not UTF-8")
        .lines()
        .map(str::to_owned)
        .collect::<Vec<_>>();
    assert_eq!(lines.len(), 2);
    assert!(matches!(
        lines[0].as_str(),
        "black\tc4" | "black\td3" | "black\te6" | "black\tf5"
    ));
    assert!(matches!(
        lines[1].as_str(),
        "white\tc5" | "white\td6" | "white\te3" | "white\tf4"
    ));
}

#[test]
fn cli_rejects_malformed_board_input() {
    let output =
        run_cli("bad\t...............................................................\tB\n");

    assert!(!output.status.success());
    assert!(
        String::from_utf8_lossy(&output.stdout).contains("board")
            || String::from_utf8_lossy(&output.stderr).contains("board")
    );
}

#[test]
fn cli_rejects_zero_search_depth() {
    let output = run_cli_with_args(
        "",
        [
            "--evaluator",
            "novice",
            "--opening-depth",
            "0",
            "--midgame-depth",
            "1",
            "--endgame-depth",
            "1",
        ],
    );

    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("positive"));
}

#[test]
fn cli_advisor_rejects_diagnostic_game_before_reading_input() {
    let output = run_cli_with_args("", ["--advisor-analysis", "--exact-cache-scope", "game"]);
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("advisor mode does not accept diagnostic")
    );
}

#[test]
fn cli_diagnostic_game_records_policy_reuses_proof_and_resets() {
    let board = "..WWWWWW.WWWWWWW.WWBWWBW.WBWBWBW.BBBWBWWBBBBWWWB.BBWBWWBBBBBBBWB";
    let input =
        format!("first\t{board}\tW\nrepeat\t{board}\tW\nnew_game\tsecond\nreset\t{board}\tW\n");
    let output = run_cli_with_args(&input, ["--exact-cache-scope", "game"]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        String::from_utf8(output.stdout)
            .unwrap()
            .lines()
            .collect::<Vec<_>>(),
        [
            "first\ta4",
            "repeat\ta4",
            "new_game\tsecond\tready",
            "reset\ta4"
        ]
    );
    let stderr = String::from_utf8(output.stderr).unwrap();
    let diagnostics: Vec<_> = stderr
        .lines()
        .filter(|line| line.starts_with("search_diagnostic_v1\t"))
        .collect();
    assert_eq!(diagnostics.len(), 3);
    let nodes: Vec<u64> = diagnostics
        .iter()
        .map(|line| {
            // Preserve the existing full-match parser's eleven tab-separated fields.
            assert_eq!(line.split('\t').count(), 11);
            assert!(line.contains("\texact=true\tscore=4\tcompleted_depth=7\toutcome=move\t"));
            line.split('\t')
                .find_map(|field| field.strip_prefix("nodes="))
                .unwrap()
                .parse()
                .unwrap()
        })
        .collect();
    assert!(nodes[1] < nodes[0]);
    assert_eq!(nodes[2], nodes[0]);
    let policies: Vec<_> = stderr
        .lines()
        .filter(|line| line.starts_with("exact_cache_policy_v1\t"))
        .collect();
    assert_eq!(policies.len(), 3);
    for (line, id) in policies.iter().zip(["first", "repeat", "reset"]) {
        assert_eq!(*line, format!("exact_cache_policy_v1\tposition_id={id}\texact_cache_scope=game\texact_cache_policy=diagnostic-game-v1"));
    }
}

#[test]
fn default_and_explicit_turn_repeated_exact_requests_match() {
    let board = "..WWWWWW.WWWWWWW.WWBWWBW.WBWBWBW.BBBWBWWBBBBWWWB.BBWBWWBBBBBBBWB";
    let input = format!("position\t{board}\tW\nposition\t{board}\tW\n");
    for args in [vec![], vec!["--exact-cache-scope", "turn"]] {
        let mut child = Command::new(env!("CARGO_BIN_EXE_reversi-ai-cli"))
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(input.as_bytes())
            .unwrap();
        let output = child.wait_with_output().unwrap();
        assert!(output.status.success());
        let stdout = String::from_utf8(output.stdout).unwrap();
        let lines: Vec<_> = stdout.lines().collect();
        assert_eq!(lines, ["position\ta4", "position\ta4"]);
        let stderr = String::from_utf8(output.stderr).unwrap();
        let diagnostics: Vec<Vec<_>> = stderr
            .lines()
            .filter(|line| line.starts_with("search_diagnostic_v1\t"))
            .map(|line| {
                line.split('\t')
                    .filter(|field| !field.starts_with("elapsed_us="))
                    .collect()
            })
            .collect();
        assert_eq!(diagnostics.len(), 2);
        assert_eq!(diagnostics[0], diagnostics[1]);
        assert_eq!(diagnostics[0].len(), 10);
        let policies: Vec<_> = stderr
            .lines()
            .filter(|line| line.starts_with("exact_cache_policy_v1\t"))
            .collect();
        assert_eq!(policies.len(), 2);
        assert!(policies.iter().all(|line| *line == "exact_cache_policy_v1\tposition_id=position\texact_cache_scope=turn\texact_cache_policy=exact-cache-cross-decision-suspended-v1"));
    }
}

#[test]
fn cli_rejects_invalid_trained_mode_configuration() {
    let missing_artifact = run_cli_with_args("", ["--evaluator", "trained"]);
    assert!(!missing_artifact.status.success());
    assert!(String::from_utf8_lossy(&missing_artifact.stderr).contains("--trained-artifact"));

    let misplaced_artifact = run_cli_with_args(
        "",
        [
            "--evaluator",
            "novice",
            "--trained-artifact",
            "/missing/artifact.json",
        ],
    );
    assert!(!misplaced_artifact.status.success());
    assert!(String::from_utf8_lossy(&misplaced_artifact.stderr)
        .contains("requires --evaluator trained"));

    let profile_conflict = run_cli_with_args(
        "",
        [
            "--evaluator",
            "novice",
            "--profile",
            "strong-engine-hcap-v1",
            "--midgame-depth",
            "1",
        ],
    );
    assert!(!profile_conflict.status.success());
    assert!(String::from_utf8_lossy(&profile_conflict.stderr).contains("conflicts"));
}

#[test]
fn new_game_repeat_games_match_fresh_search_diagnostics() {
    let initial = "...........................WB......BW...........................";
    let input = format!(
        "new_game\tfirst\nposition\t{initial}\tB\nnew_game\tsecond\nposition\t{initial}\tB\n"
    );
    let mut child = Command::new(env!("CARGO_BIN_EXE_reversi-ai-cli"))
        .args([
            "--opening-depth",
            "4",
            "--midgame-depth",
            "4",
            "--endgame-depth",
            "4",
            "--node-limit",
            "1000000",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(input.as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8(output.stdout).unwrap();
    let lines: Vec<_> = stdout.lines().collect();
    assert_eq!(lines[0], "new_game\tfirst\tready");
    assert_eq!(lines[2], "new_game\tsecond\tready");
    assert_eq!(lines[1], lines[3]);
    let diagnostics = String::from_utf8(output.stderr).unwrap();
    let stable: Vec<Vec<_>> = diagnostics
        .lines()
        .filter(|line| line.starts_with("search_diagnostic_v1\t"))
        .map(|line| {
            line.split('\t')
                .filter(|field| !field.starts_with("elapsed_us="))
                .collect()
        })
        .collect();
    assert_eq!(stable.len(), 2);
    assert_eq!(stable[0], stable[1]);
}

#[test]
fn cli_rejects_empty_and_malformed_game_reset_ids() {
    for request in [
        "new_game\t\n",
        "new_game\tgame\textra\n",
        "new_game\tgame\rid\n",
    ] {
        assert!(!run_cli(request).status.success());
    }
}

#[test]
fn new_game_ack_flushes_without_waiting_for_next_input() {
    use std::io::{BufRead, BufReader};
    let mut child = Command::new(env!("CARGO_BIN_EXE_reversi-ai-cli"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut stdin = child.stdin.take().unwrap();
    stdin.write_all(b"new_game\tinteractive\n").unwrap();
    stdin.flush().unwrap();
    let mut stdout = BufReader::new(child.stdout.take().unwrap());
    let mut line = String::new();
    stdout.read_line(&mut line).unwrap();
    assert_eq!(line, "new_game\tinteractive\tready\n");
    drop(stdin);
    assert!(child.wait().unwrap().success());
}
