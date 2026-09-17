use std::io::Write;
use std::process::{Command, Stdio};

fn run_cli(input: &str) -> std::process::Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_reversi-ai-cli"))
        .args([
            "--evaluator",
            "novice",
            "--opening-depth",
            "1",
            "--midgame-depth",
            "1",
            "--endgame-depth",
            "1",
        ])
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
fn cli_rejects_malformed_board_input() {
    let output =
        run_cli("bad\t...............................................................\tB\n");

    assert!(!output.status.success());
    assert!(
        String::from_utf8_lossy(&output.stdout).contains("board")
            || String::from_utf8_lossy(&output.stderr).contains("board")
    );
}
