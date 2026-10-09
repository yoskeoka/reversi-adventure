#!/usr/bin/env python3
"""Prepare and verify a fixed, human-operated six-game diagnostic."""
from __future__ import annotations

import argparse
import json
import hashlib
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import exact_threshold as et
import whole_game as wg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reversi-ai-training"))
import training
import exact_cache_verification_games as games
import exact_cache_verification_oracle as queries
import exact_cache_verification_evidence as evidence

prep = et.prep
VERSION = "exact-cache-verification-v2"
ROOT = prep.ROOT
SAMPLE = Path(__file__).with_name("exact-cache-verification-sample-v1.json")
FIXTURE = Path(__file__).with_name("fixtures") / "exact-cache-counterexample-v1.json"
REGRESSIONS = (
    "search::endgame::tests::retained_lower_bound_proves_selected_counterexample_child",
    "search::endgame::tests::counterexample_bounds_collisions_and_interrupted_reuse_preserve_proof",
    "search::endgame::tests::pvs_matches_reference_for_every_reachable_four_empty_position",
)
SETTINGS = {"opening_depth": 12, "midgame_depth": 8, "endgame_depth": 12,
            "exact_empty": 20, "timeout_seconds": 310, "max_rss_kib": 1572864,
            "node_limit": None, "oracle_timeout_seconds": 30,
            "cache_lifetime": "one-game", "reset_protocol": "new_game-v1"}
STARTED = time.monotonic()
LAST = ("inputs", "none", "fixture", 0, 1)

class Progress:
    def __init__(self, every=1):
        wg.require(type(every) is int and every > 0, "progress interval must be positive")
        self.every = every

    def emit(self, stage, condition, unit, done, total, status):
        global LAST
        LAST = stage, condition, unit, done, total
        if status in ("running", "saved", "skipped", "verified") and done % self.every and done != total:
            return
        print(f"progress exact-cache-verification stage={stage} condition={condition} unit={unit} "
              f"done={done} total={total} status={status} elapsed_s={time.monotonic()-STARTED:.3f}",
              file=sys.stderr, flush=True)

def seal(value):
    wg.require(value == wg.sealed(value), "verification digest mismatch")
    wg.require(value.get("score_contract") == wg.SCORE_CONTRACT, "verification score contract mismatch; old evidence requires --legacy-offline")

def sample():
    value = json.loads(SAMPLE.read_text())
    expected = {"version": "exact-cache-verification-sample-v1",
                "games": [{"opening_id": f"opening-{n}", "assignment": 0} for n in (1, 2, 4)],
                "selectors": ["first-exact-empty-le-12", "first-exact-empty-le-8", "last-nonterminal-exact-empty-le-12"]}
    wg.require(value == expected, "sample order/settings mismatch")
    return value

def harness_paths():
    return sorted(set([*prep.harness_paths(), Path(et.__file__).resolve(),
        *Path(__file__).parent.glob("exact_cache_verification*.py"), Path(training.__file__).resolve(), SAMPLE, FIXTURE]))

def source_paths():
    return sorted([ROOT/"Cargo.toml", ROOT/"Cargo.lock",
        *(ROOT/"rust/reversi-ai").rglob("*.rs"), *(ROOT/"rust/reversi-engine").rglob("*.rs"),
        *(ROOT/"rust").glob("*/Cargo.toml")])

def outputs(directory, units):
    return {"manifest": str(directory/"manifest.json"), "script": str(directory/"run-exact-cache-verification.sh"),
            "regression": str(directory/"regression.json"), "report": str(directory/"report.json"),
            "oracle_manifest": str(directory/"oracle-manifest.json"),
            "games": [str(directory/"games"/(u["id"]+".json")) for u in units],
            "oracle_directory": str(directory/"oracle")}

def immutable(path, value, verify_only=False):
    if path.exists():
        wg.require(prep.load(path) == value, f"saved evidence mismatch: {path}")
    else:
        wg.require(not verify_only, f"missing evidence: {path}")
        wg.atomic_write(path, value)

def verify_regression(m, result):
    seal(result)
    rows = result["fixtures"]
    failed = result.get("status", "completed") == "failed"
    wg.require(result["version"] == VERSION and result["manifest_digest"] == m["report_digest"]
               and [r["test"] for r in rows] == list(REGRESSIONS[:len(rows)])
               and 0 < len(rows) <= len(REGRESSIONS)
               and (failed or len(rows) == len(REGRESSIONS)), "regression identity mismatch")
    for index, row in enumerate(rows):
        wg.require(row["argv"] == ["cargo", "test", "-p", "reversi-ai", "--lib", row["test"], "--", "--exact", "--nocapture"]
                   and type(row["wall_ns"]) is int and row["wall_ns"] > 0, "regression execution failed")
        passed = row["returncode"] == 0 and f"test {row['test']} ... ok" in row["stdout"] and "1 passed; 0 failed;" in row["stdout"]
        wg.require((not passed if failed and index == len(rows)-1 else passed),
                   "regression must run exactly one passing test")
    if failed:
        wg.require(result["failure"] == "short regression failed: "+rows[-1]["test"], "regression failure evidence mismatch")
    else:
        wg.require(result["proved_root_score"] == result["proved_selected_child_score"] == 4,
                   "counterexample value mismatch")

def regression(m, directory, progress, verify_only=False):
    path = directory/"regression.json"
    if path.exists():
        result = prep.load(path)
        verify_regression(m, result)
        wg.require(result.get("status", "completed") == "completed", "saved regression failure; no retry")
        progress.emit("regression", "none", "fixture", len(REGRESSIONS), len(REGRESSIONS), "skipped")
        return result
    wg.require(not verify_only, "missing short regression")
    rows = []
    for index, test in enumerate(REGRESSIONS):
        progress.emit("regression", "none", "fixture", index, len(REGRESSIONS), "running")
        argv = ["cargo", "test", "-p", "reversi-ai", "--lib", test, "--", "--exact", "--nocapture"]
        started = time.monotonic_ns()
        raw = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, timeout=120)
        rows.append({"test": test, "argv": argv, "stdout": raw.stdout, "stderr": raw.stderr,
                     "returncode": raw.returncode, "wall_ns": time.monotonic_ns()-started})
        if raw.returncode != 0 or f"test {test} ... ok" not in raw.stdout or "1 passed; 0 failed;" not in raw.stdout:
            failure = wg.sealed({"version": VERSION, "score_contract": wg.SCORE_CONTRACT, "manifest_digest": m["report_digest"], "fixtures": rows,
                "status": "failed", "failure": "short regression failed: "+test})
            verify_regression(m, failure)
            wg.atomic_write(path, failure)
            progress.emit("regression", "none", "fixture", len(rows), len(REGRESSIONS), "failed")
            raise wg.BenchmarkError(failure["failure"])
    result = wg.sealed({"version": VERSION, "score_contract": wg.SCORE_CONTRACT, "manifest_digest": m["report_digest"],
        "status": "completed", "failure": None, "fixtures": rows, "proved_root_score": 4, "proved_selected_child_score": 4})
    verify_regression(m, result)
    wg.atomic_write(path, result)
    progress.emit("regression", "none", "fixture", len(rows), len(rows), "saved")
    return result

def script_bytes(directory):
    command = " ".join(shlex.quote(p) for p in ["rtk", "python3", str(Path(__file__).resolve()), "run", "--manifest", str(directory/"manifest.json")])
    return ("#!/usr/bin/env bash\nset -euo pipefail\n"+command+' "$@"\n').encode()

def oracle_files(directory):
    return sorted(p for p in (directory/"resources").rglob("*") if p.is_file())

def build_cli(revision):
    argv = ["cargo", "build", "--locked", "--release", "-p", "reversi-ai", "--bin", "reversi-ai-cli"]
    started = time.monotonic_ns()
    raw = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=True)
    metadata = json.loads(subprocess.check_output(["cargo", "metadata", "--no-deps", "--format-version", "1"], cwd=ROOT, text=True))
    return {"source_revision": revision, "argv": argv, "returncode": raw.returncode,
            "stdout": raw.stdout, "stderr": raw.stderr, "wall_ns": time.monotonic_ns()-started,
            "binary": prep.pin(Path(metadata["target_directory"])/"release"/"reversi-ai-cli")}

def prepare(args):
    progress = Progress()
    progress.emit("inputs", "none", "fixture", 0, 1, "running")
    directory = args.output_dir.resolve()
    wg.require(sys.platform == "linux" and directory.is_absolute() and not directory.exists(),
               "preparation requires Linux and a new output directory")
    revision = prep.revision()
    wg.require(args.source_revision == revision, "source revision must match clean checkout")
    changed = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=normal"], text=True)
    wg.require(not changed.strip(), "commit source and harness before freezing")
    inputs = {name: prep.pin(path) for name, path in (
        ("cli", args.cli_binary), ("oracle", args.oracle_binary), ("artifact", args.artifact),
        ("openings", wg.OPENINGS), ("sample", SAMPLE), ("fixture", FIXTURE))}
    for name in ("cli", "oracle"):
        wg.require(os.access(inputs[name]["path"], os.X_OK), "binary is not executable")
    build = build_cli(revision)
    wg.require(build["binary"]["sha256"] == inputs["cli"]["sha256"], "CLI binary differs from clean repaired-source release build")
    training.validate_artifact(json.loads(Path(inputs["artifact"]["path"]).read_text()))
    oracle_cwd = (args.oracle_cwd or args.oracle_binary.parent).resolve(strict=True)
    wg.require(bool(oracle_files(oracle_cwd)), "Oracle evaluation resources missing")
    audit = evidence.verify_evidence(args.evidence_dir.resolve())
    units = games.units(sample())
    prep.probe_reset(Path(inputs["cli"]["path"]), Path(inputs["artifact"]["path"]), 10)
    manifest = wg.sealed({"version": VERSION, "score_contract": wg.SCORE_CONTRACT, "source_revision": revision, "harness_revision": revision,
        "build": build, "source_files": [prep.pin(p) for p in source_paths()],
        "harness_files": [prep.pin(p) for p in harness_paths()], "inputs": inputs,
        "host": prep.host(), "settings": SETTINGS, "games_total": 3, "conditions_total": 2,
        "units": units, "sample": sample(), "output_directory": str(directory),
        "outputs": outputs(directory, units), "evidence_directory": str(args.evidence_dir.resolve()),
        "historical_audit": audit, "oracle_cwd": str(oracle_cwd),
        "oracle_resources": [prep.pin(p) for p in oracle_files(oracle_cwd)],
        "policies": {"turn": "exact-cache-cross-decision-suspended-v1", "game": "diagnostic-game-v1"}})
    directory.mkdir(parents=True)
    wg.atomic_write(directory/"manifest.json", manifest)
    script = directory/"run-exact-cache-verification.sh"
    prep.atomic(script, script_bytes(directory))
    script.chmod(0o755)
    regression(manifest, directory, progress)
    verify_manifest(directory/"manifest.json")
    progress.emit("inputs", "none", "fixture", 1, 1, "verified")
    print("rtk bash "+shlex.quote(str(script)))
    return directory/"manifest.json"

def verify_manifest(path):
    m = prep.load(path)
    seal(m)
    wg.require(m["version"] == VERSION and re.fullmatch(r"[0-9a-f]{40}", m["source_revision"]) is not None
               and re.fullmatch(r"[0-9a-f]{40}", m["harness_revision"]) is not None
               and m["host"] == prep.host() and m["settings"] == SETTINGS,
               "manifest version/source/host/settings mismatch")
    for kind in ("source", "harness"):
        for item in m[kind+"_files"]:
            relative = Path(item["path"]).relative_to(ROOT)
            raw = subprocess.check_output(["git", "-C", str(ROOT), "show", f'{m[kind+"_revision"]}:{relative}'])
            wg.require(hashlib.sha256(raw).hexdigest() == item["sha256"], "recorded revision/file mismatch")
    build = m["build"]
    wg.require(build["source_revision"] == m["source_revision"] and build["argv"] == ["cargo", "build", "--locked", "--release", "-p", "reversi-ai", "--bin", "reversi-ai-cli"]
               and build["returncode"] == 0 and type(build["wall_ns"]) is int and build["wall_ns"] > 0
               and build["binary"]["sha256"] == m["inputs"]["cli"]["sha256"], "release build provenance mismatch")
    prep.check_pin(build["binary"])
    wg.require(m["games_total"] == 3 and m["conditions_total"] == 2
               and m["sample"] == sample() and m["units"] == games.units(sample())
               and m["policies"] == {"turn": "exact-cache-cross-decision-suspended-v1", "game": "diagnostic-game-v1"},
               "condition/sample identity mismatch")
    wg.require([p["path"] for p in m["harness_files"]] == [str(p.resolve()) for p in harness_paths()]
               and [p["path"] for p in m["source_files"]] == [str(p.resolve()) for p in source_paths()],
               "source/harness registry mismatch")
    wg.require([p["path"] for p in m["oracle_resources"]] == [str(p.resolve()) for p in oracle_files(Path(m["oracle_cwd"]))], "Oracle resource registry mismatch")
    for pin in [*m["inputs"].values(), *m["harness_files"], *m["source_files"], *m["oracle_resources"]]:
        prep.check_pin(pin)
    wg.require(m["outputs"] == outputs(Path(m["output_directory"]), m["units"])
               and str(path.resolve()) == m["outputs"]["manifest"], "output identity mismatch")
    wg.require(Path(m["outputs"]["script"]).read_bytes() == script_bytes(Path(m["output_directory"])), "launch script identity mismatch")
    wg.require(m["historical_audit"] == evidence.verify_evidence(Path(m["evidence_directory"])),
               "historical evidence changed")
    return m

def saved_games(m, directory):
    folder = directory/"games"
    found = {}
    if folder.exists():
        by_id = {u["id"]: u for u in m["units"]}
        for path in folder.iterdir():
            if path.name.startswith(".unfinished-"):
                continue
            wg.require(path.suffix == ".json" and path.stem in by_id, "unknown game checkpoint")
            result = prep.load(path)
            games.verify_unit(m, by_id[path.stem], result)
            found[path.stem] = result
    return found

def report(m, results, oracle, regression_result):
    base = games.summary(results)
    if not oracle["completed"]:
        for condition in base["conditions"]:
            condition.pop("averages", None)
            condition.update(status="failed", failure="independent Oracle evidence failed; no averages")
    return wg.sealed({"version": VERSION, "score_contract": wg.SCORE_CONTRACT, "manifest_digest": m["report_digest"],
        "game_digests": [r["report_digest"] for r in results],
        "regression_digest": regression_result["report_digest"], "games": base, "oracle": oracle,
        "production_adoption": False,
        "remaining_blockers": ["human-run acceptance and 0040 decision", "unresolved sixteen-empty score contract"],
        "interpretation": "Three biased samples, one repetition. Independent Oracle covers selected roots only; no significance or general correctness claim."})

def execute(path, command, every):
    progress = Progress(every)
    progress.emit("inputs", "none", "fixture", 0, 1, "running")
    m = verify_manifest(path)
    progress.emit("inputs", "none", "fixture", 1, 1, "verified")
    if command == "verify-inputs":
        return
    directory = Path(m["output_directory"])
    verify_only = command == "verify"
    with wg.exclusive_lock(directory):
        known = {"manifest.json", "run-exact-cache-verification.sh", "regression.json", "report.json", "oracle-manifest.json", "games", "oracle", ".lock"}
        wg.require(all(p.name in known or p.name.startswith(".unfinished-") for p in directory.iterdir()), "unknown output identity")
        found = saved_games(m, directory)
        reg = None
        if (directory/"regression.json").exists():
            reg = prep.load(directory/"regression.json")
            verify_regression(m, reg)
            wg.require(reg.get("status", "completed") == "completed", "saved regression failure; no retry")
        results = [found[u["id"]] for u in m["units"] if u["id"] in found]
        reusable = evidence.reusable_queries(m, m["historical_audit"])
        stage_path = directory/"oracle-manifest.json"
        if stage_path.exists() or (directory/"report.json").exists():
            wg.require(len(results) == len(m["units"]), "derived evidence has missing games")
            stage = queries.freeze_stage(m, results, reusable)
            immutable(stage_path, stage, True)
            queries.preflight_stage(m, stage, directory/"oracle")
            if (directory/"report.json").exists():
                oracle = queries.run_stage(m, stage, directory/"oracle", progress, True)
                wg.require(reg is not None, "derived report lacks regression")
                immutable(directory/"report.json", report(m, results, oracle, reg), True)
        wg.require(not (directory/"oracle").exists() or stage_path.exists(), "Oracle checkpoints lack stage manifest")
        reg = regression(m, directory, progress, verify_only)
        # Never launch a process before all saved checkpoints and derived evidence verify.
        for scope in ("turn", "game"):
            rows = [u for u in m["units"] if u["scope"] == scope]
            for index, unit in enumerate(rows):
                if unit["id"] in found:
                    progress.emit("games", scope, "game", index+1, 3, "skipped")
                    continue
                wg.require(not verify_only, "missing game checkpoint")
                progress.emit("games", scope, "game", index, 3, "running")
                result = games.measure_unit(m, unit)
                games.verify_unit(m, unit, result)
                wg.atomic_write(directory/"games"/(unit["id"]+".json"), result)
                found[unit["id"]] = result
                progress.emit("games", scope, "game", index+1, 3, "failed" if result["status"] == "failed" else "saved")
        results = [found[u["id"]] for u in m["units"]]
        stage = queries.freeze_stage(m, results, reusable)
        immutable(stage_path, stage, verify_only)
        oracle = queries.run_stage(m, stage, directory/"oracle", progress, verify_only)
        value = report(m, results, oracle, reg)
        immutable(directory/"report.json", value, verify_only)
        progress.emit("verify", "none", "game", 6, 6, "verified")

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    for name in ("cli-binary", "oracle-binary", "artifact", "evidence-dir", "output-dir"):
        p.add_argument("--"+name, required=True, type=Path)
    p.add_argument("--oracle-cwd", type=Path)
    p.add_argument("--source-revision", required=True)
    for name in ("run", "verify", "verify-inputs"):
        p = sub.add_parser(name)
        if name in ("verify", "verify-inputs"):
            p.add_argument("--legacy-offline", action="store_true")
        p.add_argument("--manifest", required=True, type=Path)
        p.add_argument("--progress-every", type=int, default=1)
    args = parser.parse_args(argv)
    previous = signal.getsignal(signal.SIGTERM)
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    try:
        if args.command == "prepare":
            prepare(args)
        else:
            if getattr(args, "legacy_offline", False):
                from legacy_offline import assessment
                assessment(args.manifest, args.command, args.progress_every, Path(__file__).stem)
            else:
                execute(args.manifest, args.command, args.progress_every)
    except KeyboardInterrupt:
        Progress().emit(*LAST, "interrupted")
        return 130
    except (wg.BenchmarkError, wg.oracle.OracleError, OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError) as exc:
        Progress().emit(*LAST, "failed")
        print(f"exact-cache verification error: {exc}", file=sys.stderr, flush=True)
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
