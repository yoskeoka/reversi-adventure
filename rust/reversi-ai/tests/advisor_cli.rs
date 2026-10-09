use serde_json::Value;
use std::io::Write;
use std::process::{Command, Stdio};

const INITIAL: &str = "...........................WB......BW...........................";

#[test]
fn maximum_match_and_advisor_settings_remain_budget_bounded() {
    for mode in ["--decision-move-phases", "--advisor-analysis"] {
        let (ok, output) = invoke(&[
            mode,
            "--opening-depth",
            "12",
            "--midgame-depth",
            "16",
            "--exact-solver-empty-squares",
            "30",
            "--node-limit",
            "200",
        ]);
        assert!(ok, "{mode}");
        if mode == "--advisor-analysis" {
            let value: Value = serde_json::from_str(&output).unwrap();
            assert_eq!(value["exact"], false);
            let depth = value["completed_depth"].as_u64().unwrap();
            assert!((1..12).contains(&depth));
            assert_eq!(value["scores"].as_array().unwrap().len(), 4);
        } else {
            assert!(matches!(
                output.trim(),
                "p1\tc4" | "p1\td3" | "p1\te6" | "p1\tf5"
            ));
        }
    }
}

fn invoke(args: &[&str]) -> (bool, String) {
    let mut child = Command::new(env!("CARGO_BIN_EXE_reversi-ai-cli"))
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    writeln!(child.stdin.take().unwrap(), "p1\t{INITIAL}\tB").unwrap();
    let output = child.wait_with_output().unwrap();
    (
        output.status.success(),
        String::from_utf8(output.stdout).unwrap(),
    )
}

#[test]
fn advisor_cli_emits_complete_json_and_match_mode_stays_tab_delimited() {
    let (ok, output) = invoke(&[
        "--advisor-analysis",
        "--opening-depth",
        "2",
        "--midgame-depth",
        "3",
        "--exact-solver-empty-squares",
        "0",
    ]);
    assert!(ok);
    assert_eq!(output.lines().count(), 1);
    let value: Value = serde_json::from_str(&output).unwrap();
    assert_eq!(value["schema_version"], 2);
    assert_eq!(value["score_contract"], "winner-empty-v1");
    assert!(value["config_id"]
        .as_str()
        .unwrap()
        .starts_with("project-ai-advisor-v2:"));
    assert_eq!(value["position_id"], "p1");
    assert_eq!(value["board"], INITIAL);
    assert_eq!(value["side"], "B");
    assert_eq!(value["outcome"], "move");
    assert_eq!(value["completed_depth"], 2);
    let scores = value["scores"].as_array().unwrap();
    assert_eq!(scores.len(), 4);
    assert!(scores.iter().all(|score| score["completed_depth"] == 2));
    let (ok, output) = invoke(&[
        "--opening-depth",
        "1",
        "--midgame-depth",
        "1",
        "--endgame-depth",
        "1",
        "--exact-solver-empty-squares",
        "0",
    ]);
    assert!(ok);
    assert!(output.starts_with("p1\t"));
}

#[test]
fn advisor_cli_rejects_incomplete_initial_iteration_without_output() {
    let (ok, output) = invoke(&["--advisor-analysis", "--node-limit", "1"]);
    assert!(!ok);
    assert!(output.is_empty());
}

#[test]
fn printed_advisor_config_id_matches_analysis_and_validates_mode() {
    let settings = [
        "--advisor-analysis",
        "--opening-depth",
        "2",
        "--midgame-depth",
        "3",
        "--exact-solver-empty-squares",
        "0",
    ];
    let (ok, analysis) = invoke(&settings);
    assert!(ok);
    let analysis: Value = serde_json::from_str(&analysis).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_reversi-ai-cli"))
        .args(settings)
        .arg("--print-advisor-config-id")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8(output.stdout).unwrap(),
        format!("{}\n", analysis["config_id"].as_str().unwrap())
    );
    for invalid in [
        vec!["--print-advisor-config-id"],
        vec![
            "--advisor-analysis",
            "--print-advisor-config-id",
            "--opening-depth",
            "13",
        ],
        vec![
            "--advisor-analysis",
            "--print-advisor-config-id",
            "--evaluator",
            "trained",
            "--trained-artifact",
            "/nonexistent/reversi-ai-artifact.json",
        ],
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_reversi-ai-cli"))
            .args(invalid)
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
    }
}
