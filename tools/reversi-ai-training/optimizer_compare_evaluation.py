"""Evaluation-only reuse of a completed 0052 Adam candidate."""
from __future__ import annotations

import argparse
from pathlib import Path

import optimizer_compare as comparison
import optimizer_compare_matches as matches
import production_cycle as cycle
import reinforcement as rf
import training

VERSION = "optimizer-compare-evaluation-v1"
SOURCE_FILES = (
    "optimizer_compare_evaluation.py", "optimizer_compare.py", "optimizer_adam.py",
    "optimizer_compare_inputs.py", "optimizer_compare_matches.py", "training.py",
    "reinforcement.py", "production_cycle.py", "pilot.py",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise training.TrainingError(message)


def source_hashes() -> dict:
    folder = Path(__file__).resolve().parent
    return {name: training.sha256_file(folder / name) for name in SOURCE_FILES}


def source_inventory(root: Path) -> dict:
    """Digest every regular source-run file without following mutable links."""
    require(root.is_dir(), f"0052 source run root is missing: {root}")
    entries = []
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), f"0052 source run contains a symlink: {path}")
        if path.is_file():
            entries.append({"path": path.relative_to(root).as_posix(),
                            "sha256": training.sha256_file(path), "size": path.stat().st_size})
    require(entries, "0052 source run is empty")
    return {"file_count": len(entries), "tree_sha256": training.digest(entries)}


def _outside_checkout(path: Path) -> bool:
    checkout = Path(__file__).resolve().parents[2]
    return path != checkout and checkout not in path.parents


def _prior_openings(context: dict, source_manifest: dict) -> None:
    settings = source_manifest.get("matches", {})
    openings = settings.get("openings", {})
    context["evaluation_excluded_openings"] = [
        opening
        for name in ("comparison", "oracle-match")
        for pair in openings.get(name, [])
        for opening in pair
    ]


def _load_source(source_root: Path):
    before = source_inventory(source_root)
    for phase in comparison.PHASES:
        require((source_root / f"{phase}.receipt.json").is_file(),
                f"0052 source run is missing its {phase} receipt")
    require((source_root / "offline-verification.receipt.json").is_file(),
            "0052 source run is missing its offline verification receipt")
    source_manifest, context = comparison.load(source_root)
    report = comparison.verify(source_root)
    require(report.get("status") == "complete", "0052 source run has no completed report")
    require(training.read_json(source_root / "report.json") == report,
            "0052 source report differs from offline reconstruction")
    require(source_inventory(source_root) == before,
            "0052 verification would modify the source run; preserve it and repair verification separately")
    _prior_openings(context, source_manifest)
    return source_manifest, context, report


def _source_identity(root: Path, manifest: dict, report: dict) -> dict:
    candidate_path = root / "candidate-artifact.json"
    require(candidate_path.is_file(), "0052 source candidate artifact is missing")
    training.validate_artifact(training.read_json(candidate_path))
    selection_path = root / "selection.json"
    require(selection_path.is_file(), "0052 source selection is missing")
    inventory = source_inventory(root)
    return {
        "path": str(root.resolve()),
        **inventory,
        "manifest_sha256": training.sha256_file(root / "manifest.json"),
        "report_sha256": training.sha256_file(root / "report.json"),
        "candidate_artifact_sha256": training.sha256_file(candidate_path),
        "selection_sha256": training.sha256_file(selection_path),
    }


def _prepare_receipt(root: Path, manifest: dict) -> dict:
    return {
        "manifest_sha256": training.sha256_file(root / "manifest.json"),
        "source_run_tree_sha256": manifest["source_run"]["tree_sha256"],
        "candidate_artifact_sha256": training.sha256_file(root / "candidate-artifact.json"),
        "baseline_artifact": manifest["baseline_artifact"],
        "match_settings_digest": training.digest(manifest["matches"]),
    }


def prepare(args) -> dict:
    source_root = args.source_run_root.resolve()
    evaluation_root = args.evaluation_root.resolve()
    require(args.source_run_root.is_absolute() and _outside_checkout(source_root),
            "0052 source run root must be absolute and outside the checkout")
    require(args.evaluation_root.is_absolute() and _outside_checkout(evaluation_root),
            "evaluation root must be absolute and outside the checkout")
    require(source_root != evaluation_root and source_root not in evaluation_root.parents
            and evaluation_root not in source_root.parents,
            "0052 source and evaluation roots must be separate")
    require(not evaluation_root.exists(), "evaluation root exists; choose a new empty root")

    before = source_inventory(source_root)
    source_manifest, context, report = _load_source(source_root)
    original_settings = source_manifest["matches"]
    oracle_path = Path(original_settings["oracle_binary"]["path"])
    candidate_entry = cycle.file_entry(args.candidate_executable)
    oracle_entry = cycle.file_entry(args.oracle_binary)
    require(candidate_entry == original_settings["candidate_executable"],
            "candidate executable differs from the identity pinned by the 0052 manifest")
    require(oracle_entry == original_settings["oracle_binary"],
            "Oracle binary differs from the identity pinned by the 0052 manifest")
    candidate_path = Path(original_settings["candidate_executable"]["path"])
    timeout = (original_settings["decision_timeout_seconds"] if args.decision_timeout_seconds is None
               else args.decision_timeout_seconds)
    seed = original_settings["seed"] if args.seed is None else args.seed
    setting = matches.prepare_match_led(context, seed, candidate_path, oracle_path, timeout)
    baseline_path = matches._adopted_path(context)
    baseline_entry = cycle.file_entry(baseline_path)
    candidate_source = source_root / "candidate-artifact.json"
    source_identity = _source_identity(source_root, source_manifest, report)
    manifest = comparison.seal({
        "schema_version": 1,
        "producer": VERSION,
        "source_run": source_identity,
        "baseline_artifact": baseline_entry,
        "matches": setting,
        "sources": source_hashes(),
        "execution_commit": cycle.source_commit(),
    })
    evaluation_root.mkdir(parents=True, exist_ok=False)
    comparison.write_once(evaluation_root, "manifest.json", manifest)
    comparison.write_once(evaluation_root, "candidate-artifact.json", training.read_json(candidate_source))
    require(training.sha256_file(evaluation_root / "candidate-artifact.json")
            == source_identity["candidate_artifact_sha256"],
            "candidate artifact could not be copied without changing its identity")
    comparison.write_once(evaluation_root, "prepare.receipt.json",
                          comparison.seal(_prepare_receipt(evaluation_root, manifest)))
    require(source_inventory(source_root) == before,
            "0052 source run changed during evaluation preparation")
    return manifest


def _unseal_manifest(path: Path) -> dict:
    manifest = comparison.unseal(path)
    require(manifest.get("schema_version") == 1 and manifest.get("producer") == VERSION,
            "unsupported evaluation manifest")
    return manifest


def _valid_failure(path: Path, manifest: dict) -> None:
    value = comparison.unseal(path)
    require(set(value) == {"error", "manifest_sha256"}
            and isinstance(value["error"], str) and value["manifest_sha256"] == training.sha256_file(
                path.parent / "manifest.json"),
            f"invalid evaluation failure evidence {path}")


def load(root: Path):
    manifest = _unseal_manifest(root / "manifest.json")
    allowed = {"manifest.json", "prepare.receipt.json", "candidate-artifact.json", "matches",
               "report.json", "offline-verification.receipt.json"}
    for path in root.iterdir():
        if path.name.startswith("failure-") and path.suffix == ".json":
            _valid_failure(path, manifest)
        else:
            require(path.name in allowed, f"unexpected evaluation output {path}")
    source_root = Path(manifest["source_run"]["path"])
    require(_outside_checkout(source_root) and source_root != root
            and source_root not in root.parents and root not in source_root.parents,
            "evaluation source root is invalid")
    require(source_inventory(source_root) == {
        "file_count": manifest["source_run"]["file_count"],
        "tree_sha256": manifest["source_run"]["tree_sha256"],
    }, "0052 source run changed after evaluation preparation")
    source_manifest, context, source_report = _load_source(source_root)
    source_identity = _source_identity(source_root, source_manifest, source_report)
    require(source_identity == manifest["source_run"], "0052 source run identity changed")
    require((root / "candidate-artifact.json").is_file()
            and training.sha256_file(root / "candidate-artifact.json")
            == manifest["source_run"]["candidate_artifact_sha256"]
            and (root / "candidate-artifact.json").read_bytes()
            == (source_root / "candidate-artifact.json").read_bytes(),
            "evaluation candidate artifact differs from the completed 0052 run")
    training.validate_artifact(training.read_json(root / "candidate-artifact.json"))
    require(cycle.file_entry(matches._adopted_path(context)) == manifest["baseline_artifact"],
            "adopted baseline artifact differs from the 0052 source identity")
    matches.validate_settings(context, manifest["matches"])
    require(manifest["sources"] == source_hashes(),
            "evaluation source changed; verify with the pinned implementation or prepare a new root")
    require(comparison.unseal(root / "prepare.receipt.json")
            == _prepare_receipt(root, manifest), "evaluation preparation receipt changed")
    return manifest, context, source_report


def report(manifest: dict, source_report: dict, match_report: dict) -> dict:
    selection = source_report["selection"]
    source = manifest["source_run"]
    stage20 = match_report["stage_20"]
    stage200 = match_report["stage_200"]
    return {
        "producer": VERSION,
        "status": match_report["status"],
        "source_run": {
            "tree_sha256": source["tree_sha256"],
            "manifest_sha256": source["manifest_sha256"],
            "report_sha256": source["report_sha256"],
            "candidate_artifact_sha256": source["candidate_artifact_sha256"],
        },
        "candidate_artifact_sha256": training.sha256_file(
            Path(source["path"]) / "candidate-artifact.json"),
        "baseline_artifact": manifest["baseline_artifact"],
        "candidate_executable": manifest["matches"]["candidate_executable"],
        "oracle_binary": manifest["matches"]["oracle_binary"],
        "oracle_source_sha256": manifest["matches"]["oracle_source_sha256"],
        "oracle_profile": manifest["matches"]["oracle_profile"],
        "decision_timeout_seconds": manifest["matches"]["decision_timeout_seconds"],
        "match_config": manifest["matches"]["match_config"],
        "reference_metrics": {
            "validation": {
                "baseline_mse": selection["control"]["validation_mse"],
                "candidate_mse": selection["candidate"]["validation_mse"],
                "candidate_improved": selection["validation_improved"],
            },
            "held_out": selection["held_out"],
            "corpus": match_report["corpus"],
        },
        "baseline_match": {
            "stage_20": stage20,
            "stage_200": stage200,
            "comparison": match_report["comparison"],
            "continuation": match_report["continuation"],
        },
        "oracle": match_report["oracle"],
        "outcome": match_report["outcome"],
        "adopted_model_replaced": False,
        "acceptance_0018": False,
    }


def _terminal(value: dict) -> bool:
    return value["status"] == "complete" and value["outcome"] in ("improved", "not-improved")


def verify(root: Path) -> dict:
    """Offline verifier: replay source and match evidence without external players."""
    manifest, context, source_report = load(root)
    match_report = matches.verify_match_led(context, manifest["matches"],
                                             root / "candidate-artifact.json", root / "matches")
    expected = report(manifest, source_report, match_report)
    report_path = root / "report.json"
    receipt_path = root / "offline-verification.receipt.json"
    if _terminal(expected):
        require(report_path.is_file() and report_path.read_bytes() == comparison.blob(expected),
                "evaluation report does not replay")
        value = comparison.unseal(receipt_path)
        require(value == {"report_sha256": training.sha256_file(report_path)},
                "evaluation offline receipt does not replay")
    else:
        require(not report_path.exists() and not receipt_path.exists(),
                "pending evaluation has a final report or completion receipt")
    return expected


def run(args) -> dict:
    root = args.evaluation_root.resolve()
    manifest, context, source_report = load(root)
    require(manifest["execution_commit"] == cycle.source_commit(),
            "evaluation execution commit changed; use the prepared checkout")
    require(not (root / "report.json").exists(), "evaluation is complete; use verify")
    try:
        match_report = matches.run_match_led(
            context, manifest["matches"], root / "candidate-artifact.json", root / "matches",
            extend_to_200=args.extend_to_200, run_oracle=args.run_oracle,
            progress=lambda phase, completed, total: (
                print(f"optimizer-compare-evaluate phase={phase} games={completed}/{total}", flush=True)
                if completed in (0, total) or completed % args.progress_every == 0 else None))
        result = report(manifest, source_report, match_report)
        if _terminal(result):
            comparison.write_once(root, "report.json", result)
            comparison.write_once(root, "offline-verification.receipt.json",
                                  comparison.seal({"report_sha256": training.sha256_file(root / "report.json")}))
            print(f"optimizer-compare evaluate verified report={root / 'report.json'} "
                  f"digest={training.digest(result)}")
        else:
            initial = result["baseline_match"]["stage_20"].get("summary", {})
            final = result["baseline_match"]["stage_200"].get("summary", {})
            print(f"optimizer-compare evaluate pending outcome={result['outcome']} "
                  f"points20={initial.get('match_points', 'not-complete')} "
                  f"points200={final.get('match_points', 'not-complete')} root={root}")
        return result
    except BaseException as error:
        count = len(list(root.glob("failure-*.json")))
        comparison.write_once(root, f"failure-{count:04}.json", comparison.seal({
            "error": str(error), "manifest_sha256": training.sha256_file(root / "manifest.json")
        }))
        raise


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--source-run-root", type=Path, required=True)
    prep.add_argument("--evaluation-root", type=Path, required=True)
    prep.add_argument("--candidate-executable", type=Path, required=True)
    prep.add_argument("--oracle-binary", type=Path, required=True)
    prep.add_argument("--decision-timeout-seconds", type=int)
    prep.add_argument("--seed", type=int)
    run_command = commands.add_parser("run")
    run_command.add_argument("--evaluation-root", type=Path, required=True)
    run_command.add_argument("--extend-to-200", action="store_true")
    run_command.add_argument("--run-oracle", action="store_true")
    run_command.add_argument("--progress-every", type=rf.positive_interval, default=10)
    verify_command = commands.add_parser("verify")
    verify_command.add_argument("--evaluation-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "prepare":
        value = prepare(args)
        print(f"optimizer-compare evaluate prepared root={args.evaluation_root} "
              f"digest={training.digest(value)}")
    elif args.action == "run":
        run(args)
    else:
        result = verify(args.evaluation_root.resolve())
        print(f"optimizer-compare evaluate offline verified outcome={result['outcome']} "
              f"digest={training.digest(result)}")
    return 0
