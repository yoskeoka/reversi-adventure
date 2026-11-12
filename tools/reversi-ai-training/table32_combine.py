#!/usr/bin/env python3
"""Combine completed table32 runs and independently evaluate their candidate.

Production runs are explicitly human-operated. Verification only reads saved
evidence and replays recorded decisions; it never starts a player or trainer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import table32
import table32_inputs as inputs
import table32_model as model
import table32_store as st
import training


VERSION = "table32-combine-v1"


def source(root):
    """Trust a completed offline receipt, checking every file used here.

    This deliberately does not rerun historical searches, training or replay.
    The receipt is the boundary of trust, not an attestation by this producer.
    """
    root = Path(root).resolve(strict=True)
    manifest_path, artifact_path = root / "manifest.json", root / "candidate-artifact.json"
    manifest, artifact = st.read(manifest_path), st.read(artifact_path)
    report_path = root / "report.json"
    receipt_path = root / "offline-verification.receipt.json"
    if not report_path.exists():
        report_path = root / "screening-report.json"
        receipt_path = root / "screening-verification.receipt.json"
    report, receipt = st.read(report_path), st.read(receipt_path)
    st.require(manifest.get("version") == st.VERSION and
               manifest.get("score_contract") == training.SCORE_CONTRACT and
               manifest.get("catalog_digest") == model.CATALOG_DIGEST and
               manifest.get("input_kind") == "production", "unsupported source manifest")
    st.require(report == st.seal(report) and report.get("manifest_digest") == st.digest(manifest)
               and report.get("outcome") in ("training-complete", "not-improved-at-pilot-scale",
                   "awaiting-explicit-continue", "promising-at-pilot-scale")
               and report.get("status") in ("complete", "awaiting-human"), "source is not complete")
    st.require(receipt == st.seal({"report_digest": st.digest(report),
               "manifest_digest": st.digest(manifest),
               "prefix_digest": report["completed_prefix_digest"]}), "source verification receipt differs")
    if artifact.get("identity") == model.PARTIAL_IDENTITY:
        model.validate_partial_artifact(artifact)
    else:
        model.validate_artifact(artifact)
    provenance = artifact["provenance"]
    st.require(provenance.get("source_kind") == "project-owned"
               and provenance.get("input_manifest_digest") == st.digest(manifest)
               and provenance.get("seed") == manifest["seed"]
               and provenance.get("producer_commit") == manifest["producer_commit"]
               and report.get("candidate_digest") == model.digest(artifact), "source provenance differs")
    phases = sorted(int(p) for p in artifact["weights"])
    st.require(phases == manifest["settings"].get("target_phases", list(range(60))),
               "source phase selection differs")
    exposure = report["exposure_keys"]
    name = exposure["path"]
    st.require(isinstance(name, str) and Path(name).name == name, "invalid exposure path")
    exposure_path = root / name
    pin = st.pin(exposure_path)
    st.require(pin["sha256"] == exposure["sha256"], "source exposure digest differs")
    with exposure_path.open() as stream:
        keys = [json.loads(line) for line in stream]
    st.require(all(isinstance(k, str) for k in keys) and len(keys) == exposure["count"]
               and len(set(keys)) == len(keys), "invalid source exposure set")
    prepare = st.read(root / "prepare.receipt.json")
    st.require(prepare == st.seal({"manifest_digest": st.digest(manifest),
               "snapshot_digest": manifest["snapshot_digest"]}), "source prepare receipt differs")
    baseline = manifest["baseline"]
    st.require(baseline["sha256"] == st.BASELINE_SHA, "source baseline differs")
    return {"root": str(root), "files": [st.pin(p) for p in
            (manifest_path, artifact_path, report_path, receipt_path, root / "prepare.receipt.json", exposure_path)],
            "manifest_digest": st.digest(manifest), "artifact_digest": model.digest(artifact),
            "report_digest": st.digest(report), "outcome": report["outcome"],
            "phases": phases, "baseline": baseline, "producer_commit": manifest["producer_commit"],
            "settings": manifest["settings"], "generation_plan_digest": st.digest(manifest["generation_plan"]),
            "historical": manifest["historical"], "seed": manifest["seed"]}, artifact, set(keys)


def collect(roots):
    records, weights, exposure = [], {}, set()
    st.require(roots, "at least one source is required")
    for root in roots:
        record, artifact, keys = source(root)
        st.require(record["root"] not in [r["root"] for r in records], "duplicate source root")
        for phase, table in artifact["weights"].items():
            st.require(phase not in weights, f"duplicate phase {phase}; select nonoverlapping sources")
            weights[phase] = table
        records.append(record)
        exposure.update(keys)
    return records, weights, exposure


def candidate(manifest, weights):
    provenance = {"source_kind": "combined-project-owned", "combine_version": VERSION,
                  "input_manifest_digest": st.digest(manifest), "producer_commit": manifest["producer_commit"]}
    factory = model.make_artifact if len(weights) == 60 else model.make_partial_artifact
    return factory(weights, provenance)


def prepare(args):
    root = args.run_root.resolve()
    checkout = Path(__file__).resolve().parents[2]
    st.require(args.run_root.is_absolute() and root != checkout and checkout not in root.parents
               and not root.exists(), "choose a new absolute checkout-external run root")
    records, weights, exposure = collect(args.source_root)
    st.require(all(root != Path(r["root"]) and Path(r["root"]) not in root.parents
                   and root not in Path(r["root"]).parents for r in records), "source and output roots overlap")
    executable = st.pin(args.candidate_executable)
    st.require(os.access(executable["path"], os.X_OK), "candidate executable is not executable")
    commit = table32.clean_commit()
    table32.candidate_source_commit(args.candidate_source_commit)
    settings = {"time_limit_ms": args.time_limit_ms or None, "node_limit": args.node_limit or None,
                "decision_timeout_seconds": args.decision_timeout_seconds or None}
    st.require(all(type(v) is int and v >= 0 for v in (args.time_limit_ms, args.node_limit,
               args.decision_timeout_seconds)) and
               (not any(settings.values()) or (all(settings.values()) and
               args.decision_timeout_seconds * 1000 > args.time_limit_ms)), "invalid search resource settings")
    phases = sorted(map(int, weights))
    partial = len(phases) != 60
    if partial:
        settings["target_phases"] = phases
    limits = {**st.LIMITS, "wall_seconds": args.max_wall_seconds,
              "producer_rss_kib": args.producer_rss_kib, "child_rss_kib": args.child_rss_kib}
    st.require(all(type(v) is int and v > 0 for v in limits.values()), "invalid resource limits")
    baseline = records[0]["baseline"]
    st.check_pin(baseline)
    st.require(all(r["baseline"]["sha256"] == baseline["sha256"] for r in records), "incompatible baselines")
    manifest = {"version": VERSION, "producer_commit": commit, "sources": table32.source_hashes(),
                "source_runs": records, "seed": training.require_int(args.seed, "seed", 0, 2**64-1),
                "settings": settings, "limits": limits, "baseline": baseline,
                "candidate_executable": executable, "candidate_source_commit": args.candidate_source_commit,
                "input_kind": "production", "phases": phases,
                "coverage": "partial" if partial else "full", "exposure_digest": st.digest(sorted(exposure))}
    root.mkdir(parents=True, exist_ok=False)
    st.atomic(root / "manifest.json", manifest, once=True)
    st.atomic(root / "candidate-artifact.json", candidate(manifest, weights), once=True)
    st.atomic(root / "prepare.receipt.json", st.seal({"manifest_digest": st.digest(manifest),
              "candidate_digest": model.digest(st.read(root / "candidate-artifact.json"))}), once=True)
    return manifest


def load(root):
    root = Path(root)
    manifest = st.read(root / "manifest.json")
    st.require(manifest["version"] == VERSION and manifest["sources"] == table32.source_hashes(),
               "producer identity changed; use a new root")
    st.check_pin(manifest["baseline"])
    st.check_pin(manifest["candidate_executable"])
    records, weights, exposure = collect([r["root"] for r in manifest["source_runs"]])
    st.require(records == manifest["source_runs"] and st.digest(sorted(exposure)) == manifest["exposure_digest"],
               "source inputs changed; use a new root")
    artifact = candidate(manifest, weights)
    st.require(st.read(root / "candidate-artifact.json") == artifact, "combined candidate differs")
    st.require(st.read(root / "prepare.receipt.json") == st.seal({"manifest_digest": st.digest(manifest),
               "candidate_digest": model.digest(artifact)}), "combine prepare receipt differs")
    return manifest, artifact, exposure


def evaluate(driver, artifact, forbidden, *, extend=False):
    import table32_players as players

    m, root = driver.m, driver.root
    partial = m["coverage"] == "partial"
    phases = m["phases"]
    config = {**inputs.TEACHER_SETTINGS, "opening_depth": 4 if partial else 12,
              "midgame_depth": 4 if partial else 12, "endgame_depth": 4 if partial else 12,
              "exact_solver_empty_squares": 0 if partial else 16}
    low = max(8, min(phases) - 4) if partial else 12
    high = min(58, max(8, max(phases) - 4)) if partial else 30
    profile = {"name": "partial-depth4-v1" if partial else "full-depth12-v1",
               **{k: config[k] for k in ("opening_depth", "midgame_depth", "endgame_depth",
                                         "exact_solver_empty_squares")},
               "opening_prefix_min": low, "opening_prefix_max": high, "target_phases": phases,
               "fallback": "next-trained-phase-then-s0" if partial else "none"}
    driver.computed("input-verification", "sources", {"exposure_digest": m["exposure_digest"],
                    "candidate_digest": model.digest(artifact)})
    driver.computed("match20", "profile", profile)
    openings = driver.computed("match20", "opening-plan", table32.opening_plan(
        m["seed"], forbidden, prefix_min=low, prefix_max=high))
    choose, _ = driver.providers if driver.providers is not None else table32.production_providers(driver)
    candidate_pin = st.pin(root / "candidate-artifact.json")
    def validate_decision(identifier, board, side, value, player):
        effective = {**config, "time_limit_ms": m["settings"]["time_limit_ms"],
                     "node_limit": m["settings"]["node_limit"]}
        pins = None
        if m["input_kind"] == "production":
            pins = {"executable": m["candidate_executable"],
                    "artifact": candidate_pin if player == "candidate" else m["baseline"]}
            if player == "candidate" and partial:
                pins["fallback"] = m["baseline"]
        players.validate_raw_decision(identifier, board, side, value, effective, expected_pins=pins,
            expected_evaluator=("trained-table32-partial" if partial else "trained-table32")
            if player == "candidate" else "trained")
    results, points, overlaps = [], 0, set()
    exposure = set(forbidden)
    exposure.update(o["canonical_key"] for o in openings)
    for index in range(200 if extend else 20):
        if index == 20:
            st.require(points >= 10, "initial 20-game screen does not permit extension")
            driver.computed("explicit-match200", "human-continue", {"stage20_points": points,
                            "extend_to_200": True})
        phase = "match20" if index < 20 else "explicit-match200"
        opening = openings[index // 2]
        def validate_game(saved):
            rows = iter(saved["decisions"])
            def replay(player, identifier, board, side, _config):
                row = next(rows)
                st.require(row["player"] == player and row["board"] == board and row["side"] == side,
                           "match state differs")
                validate_decision(identifier, board, side, row, player)
                return {k: v for k, v in row.items() if k not in ("board", "side", "player")}
            st.require(table32.match_game(index, opening, replay, config) == saved, "match replay differs")
            st.require(next(rows, None) is None, "extra match decisions")
        game = driver.unit(phase, f"game-{index:03d}",
                           lambda: table32.match_game(index, opening, choose, config), validate_game,
                           index + 1, 20 if index < 20 else 200)
        points += game["points"]
        results.append({"index": index, "score": game["score_candidate"], "points": game["points"]})
        for row in game["decisions"]:
            key = inputs.position_key(row["board"], row["side"])
            if key in forbidden:
                overlaps.add(key)
            exposure.add(key)
        exposure.update(inputs.position_key(game["terminal_board"], side) for side in ("B", "W"))
        if index == 19 and points < 10:
            break
    count = len(results)
    outcome = st.match_outcome(points, count)
    path = root / f"exposure-keys-{count}.jsonl"
    data = b"".join(st.blob(key) for key in sorted(exposure))
    if driver.execute:
        st.atomic_bytes(path, data, once=True)
    else:
        st.require(path.read_bytes() == data, "combined exposure differs")
    return st.seal({"version": VERSION, "manifest_digest": st.digest(m),
        "status": "awaiting-human" if outcome == "awaiting-explicit-continue" else "complete",
        "outcome": outcome, "coverage": m["coverage"], "match_profile": profile,
        "points": points, "games": count, "matches": results, "candidate_digest": model.digest(artifact),
        "incidental_overlap_keys": sorted(overlaps), "exposure_keys": {"path": path.name,
            "sha256": training.sha256_file(path), "count": len(exposure)},
        "source_settings": [r["settings"] for r in m["source_runs"]],
        "completed_prefix_digest": driver.journal.previous, "full_pilot_equivalent": False,
        "adopted_model_replaced": False, "acceptance_0018": False})


def verify(root):
    from table32_verify import verify_attempts
    root = Path(root)
    manifest, artifact, exposure = load(root)
    verify_attempts(root, manifest)
    scan = st.Journal(root, manifest)
    extension = any(entry["phase"] == "explicit-match200" for entry in scan.entries())
    if extension:
        screening_driver = table32.Driver(root, manifest, execute=False)
        screening = evaluate(screening_driver, artifact, exposure)
        st.require(screening["outcome"] == "awaiting-explicit-continue"
                   and st.read(root / "screening-report.json") == screening,
                   "screening report differs from offline replay")
        st.require(st.read(root / "screening-verification.receipt.json") == st.seal({
            "report_digest": st.digest(screening), "manifest_digest": st.digest(manifest),
            "prefix_digest": screening["completed_prefix_digest"]}),
            "screening verification receipt differs")
    driver = table32.Driver(root, manifest, execute=False)
    try:
        report = evaluate(driver, artifact, exposure, extend=extension)
        driver.finish()
    except table32.MissingUnit as missing:
        st.require(not (root / "report.json").exists(), "incomplete run has final report")
        return {"status": "incomplete", "outcome": "saved-prefix-verified",
                "completed_units": driver.journal.cursor, "prefix_digest": driver.journal.previous,
                "resume_phase": missing.phase, "missing_unit": missing.unit}
    screening = report["outcome"] == "awaiting-explicit-continue"
    target = root / ("screening-report.json" if screening else "report.json")
    st.require(st.read(target) == report, "combined report differs from offline replay")
    receipt = root / ("screening-verification.receipt.json" if screening else "offline-verification.receipt.json")
    if receipt.exists():
        st.require(st.read(receipt) == st.seal({"report_digest": st.digest(report),
            "manifest_digest": st.digest(manifest), "prefix_digest": report["completed_prefix_digest"]}),
            "verification receipt differs")
    return report


def run(args):
    import table32_process
    root = args.run_root.resolve()
    manifest, artifact, exposure = load(root)
    st.require(table32.clean_commit() == manifest["producer_commit"], "execution commit changed; use new root")
    if args.extend_to_200:
        screen = st.read(root / "screening-report.json")
        receipt = st.read(root / "screening-verification.receipt.json")
        st.require(screen == st.seal(screen) and screen.get("outcome") == "awaiting-explicit-continue"
                   and screen["points"] >= 10 and receipt == st.seal({"report_digest": st.digest(screen),
                       "manifest_digest": st.digest(manifest), "prefix_digest": screen["completed_prefix_digest"]})
                   and not (root / "report.json").exists(), "extension requires verified 20-game screen")
        verified = verify(root)
        st.require(verified.get("outcome") in ("awaiting-explicit-continue", "saved-prefix-verified"),
                   "extension prefix differs")
    def worker(attempt):
        driver = table32.Driver(root, manifest, execute=True, every=args.progress_every, attempt=attempt,
                                resume_from=args.resume_from)
        try:
            report = evaluate(driver, artifact, exposure, extend=args.extend_to_200)
            driver.finish()
            screening = report["outcome"] == "awaiting-explicit-continue"
            target = "screening-report.json" if screening else "report.json"
            st.atomic(root / target, report, once=True)
            if hasattr(driver, "close_players"):
                driver.close_players()
            checked = verify(root)
            st.require(checked == report, "independent verification differs")
            name = "screening-verification.receipt.json" if screening else "offline-verification.receipt.json"
            st.atomic(root / name, st.seal({"report_digest": st.digest(report),
                "manifest_digest": st.digest(manifest), "prefix_digest": report["completed_prefix_digest"]}), once=True)
            st.atomic(root / "status.json", report)
        finally:
            if hasattr(driver, "close_players"):
                driver.close_players()
    table32_process.supervise(root, manifest, worker, progress_every=args.progress_every,
        resume_from=args.resume_from, extend=args.extend_to_200, attempt_wall_seconds=args.attempt_wall_seconds)
    return st.read(root / "status.json")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--run-root", type=Path, required=True)
    prep.add_argument("--source-root", type=Path, action="append", required=True)
    prep.add_argument("--candidate-executable", type=Path, required=True)
    prep.add_argument("--candidate-source-commit", required=True)
    for name, value in {"seed": inputs.SEED, "time-limit-ms": 0, "node-limit": 0,
                        "decision-timeout-seconds": 0, "max-wall-seconds": 259200,
                        "producer-rss-kib": 262144, "child-rss-kib": 1572864}.items():
        prep.add_argument("--" + name, type=int, default=value)
    for name in ("run", "resume", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--run-root", type=Path, required=True)
        if name != "verify":
            command.add_argument("--progress-every", type=inputs.rf.positive_interval, default=1)
            command.add_argument("--resume-from", choices=st.PHASES)
            command.add_argument("--extend-to-200", action="store_true")
            command.add_argument("--attempt-wall-seconds", type=int)
    args = parser.parse_args(argv)
    result = prepare(args) if args.action == "prepare" else verify(args.run_root) if args.action == "verify" else run(args)
    print(f"table32-combine {args.action} root={args.run_root} digest={st.digest(result)} "
          f"outcome={result.get('outcome', 'prepared')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (training.TrainingError, ValueError, OSError, KeyError, TypeError) as error:
        print(f"table32-combine error: {error}", file=sys.stderr)
        raise SystemExit(2)
