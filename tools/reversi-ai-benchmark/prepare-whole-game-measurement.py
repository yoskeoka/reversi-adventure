#!/usr/bin/env python3
"""Freeze whole-game inputs and generate a human-operated resumable launch script."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from pathlib import Path

import whole_game as wg

ROOT = Path(__file__).resolve().parents[2]
STARTED = time.monotonic()
CURRENT = {"condition": "none", "done": 0, "total": 6}


def progress(stage: str, condition: str = "none", done: int = 0, total: int = 0,
             status: str = "verified") -> None:
    CURRENT.update(condition=condition, done=done, total=total)
    print(f"progress whole-game stage={stage} condition={condition} conditions={done}/{total} "
          f"games=0/8 status={status} elapsed_s={time.monotonic() - STARTED:.3f}",
          file=sys.stderr, flush=True)


def host() -> dict:
    return {"host": platform.node(), "os": platform.platform(), "machine": platform.machine()}


def revision() -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                   text=True).strip()


def harness_paths() -> list[Path]:
    return [*sorted((ROOT / "tools/reversi-ai-oracle").glob("*.py")), Path(__file__).resolve(), Path(wg.__file__).resolve()]


def probe_reset(binary: Path, artifact: Path, timeout: float) -> None:
    seat = wg.Seat("cli", binary, artifact, 8, min(timeout, 10), "prepare-probe")
    try:
        seat.new_game("prepare-reset-probe")
        seat.close()
    finally:
        seat.abort()


def pin(path: Path) -> dict:
    path = path.resolve(strict=True)
    wg.require(path.is_file(), f"not a regular input file: {path}")
    return {"path": str(path), "sha256": wg.digest(path)}


def check_pin(item: dict) -> Path:
    path = Path(item["path"])
    wg.require(path.is_absolute() and path.is_file() and wg.digest(path) == item["sha256"],
               f"input digest mismatch: {path}")
    return path


def load(path: Path) -> dict:
    raw = path.read_bytes()
    result = json.loads(raw)
    wg.require(raw == wg.canonical(result), f"noncanonical JSON: {path}")
    return result


def signed(value: dict) -> dict:
    return {**value, "manifest_digest": hashlib.sha256(wg.canonical(value)).hexdigest()}


def atomic(path: Path, value: bytes) -> None:
    # Exclusive creation protects existing evidence; the enclosing driver lock serializes writers.
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def legacy_registry(directory: Path, binaries: dict, artifact: dict, oracle: dict) -> list[dict]:
    entries = []
    for depth in (12, 8):
        reports = {}
        for name, binary in (("oracle", oracle), ("legacy", binaries["legacy"]),
                             ("turn", binaries["candidate"]), ("game", binaries["candidate"]),
                             ("persistent", binaries["candidate"])):
            path = directory / f"{name}-{depth}.json"
            report = load(path)
            wg.require(report.get("schema_version") == 1, "legacy registry requires version-1 reports")
            wg.verify(report, check_pin(binary), None if name == "oracle" else check_pin(artifact))
            wg.require(report["settings"]["midgame_depth"] == depth, "legacy depth mismatch")
            expected_kind = {"oracle": "oracle", "legacy": "cli-legacy", "persistent": "cli-persistent"}.get(name, "cli")
            wg.require(report["kind"] == expected_kind and report["settings"]["exact_cache_scope"] ==
                       ("turn" if name == "turn" else "game"), "legacy condition identity mismatch")
            reports[name] = report
            entries.append({"id": f"legacy-{name}-{depth}", "type": "report", "name": name,
                            "depth": depth, "file": pin(path), "binary": binary,
                            "artifact": None if name == "oracle" else artifact,
                            "cache_lifetime": "legacy-cross-game" if name == "persistent" else "legacy-one-game"})
        comparison = directory / f"comparison-{depth}.json"
        wg.require(load(comparison) == wg.comparison(reports["turn"], reports["game"]),
                   "legacy comparison mismatch")
        entries.append({"id": f"legacy-comparison-{depth}", "type": "comparison", "depth": depth,
                        "file": pin(comparison)})
        evidence = directory / f"exact-check-{depth}.json"
        wg.verify_oracle_evidence(reports["game"], load(evidence), check_pin(oracle))
        entries.append({"id": f"legacy-exact-check-{depth}", "type": "oracle", "depth": depth,
                        "file": pin(evidence)})
    return entries


def verify_legacy(manifest: dict) -> None:
    entries = manifest["legacy"]
    if not entries:
        return
    wg.require(len(entries) == 14 and len({e["id"] for e in entries}) == 14, "legacy registry incomplete")
    for item in entries:
        check_pin(item["file"])
    directory = Path(entries[0]["file"]["path"]).parent
    regenerated = legacy_registry(directory, manifest["legacy_binaries"],
                                  manifest["inputs"]["artifact"], manifest["inputs"]["oracle"])
    wg.require(entries == regenerated, "legacy registry identity mismatch")


def verify_manifest(path: Path) -> dict:
    manifest = load(path)
    wg.require(manifest == signed({k: v for k, v in manifest.items() if k != "manifest_digest"}),
               "manifest digest mismatch")
    wg.require(manifest["schema_version"] == 1 and manifest["host"] == host(), "manifest host mismatch")
    wg.require(manifest["harness_revision"] == revision(), "harness revision mismatch")
    wg.require([item["path"] for item in manifest["harness_files"]] ==
               [str(path.resolve()) for path in harness_paths()], "harness file registry mismatch")
    for item in [*manifest["inputs"].values(), *manifest["harness_files"],
                 *manifest["legacy_binaries"].values()]:
        check_pin(item)
    wg.require(Path(manifest["inputs"]["openings"]["path"]) == wg.OPENINGS.resolve(),
               "runner opening path mismatch")
    assignments = [{"opening_id": row["id"], "assignment": assignment}
                   for row in wg.opening_rows() for assignment in (0, 1)]
    wg.require(manifest["assignments"] == assignments and manifest["cache_lifetime"] == "one-game"
               and manifest["reset_protocol"] == "new_game-v1",
               "assignment or cache lifetime mismatch")
    expected_conditions = conditions(manifest["output_directory"])
    wg.require(manifest["conditions"] == expected_conditions, "condition order or identity mismatch")
    wg.require(manifest["settings"]["opening_depth"] == 12 and manifest["settings"]["endgame_depth"] == 12
               and manifest["settings"]["exact_empty"] == 16
               and manifest["settings"]["timeout_seconds"] > 1
               and manifest["settings"]["max_rss_kib"] > 0
               and manifest["settings"]["max_decisions"] >= 120, "resource or search settings mismatch")
    verify_legacy(manifest)
    progress("inputs", total=len(manifest["conditions"]))
    return manifest


def conditions(directory: str) -> list[dict]:
    return [{"id": f"{name}-{depth}", "kind": kind, "midgame_depth": depth,
             "cache_scope": scope, "process_lifetime": "segments-per-seat" if kind == "cli-persistent" else "one-game-per-seat",
             "output": str(Path(directory) / f"{name}-{depth}.json"),
             "checkpoint_directory": str(Path(directory) / f"{name}-{depth}.checkpoints")}
            for depth in (12, 8)
            for name, kind, scope in (("turn", "cli", "turn"), ("game", "cli", "game"),
                                      ("persistent", "cli-persistent", "game"))]


def prepare(args: argparse.Namespace) -> Path:
    progress("prepare", status="measuring", total=6)
    wg.require(sys.platform == "linux", "CPU/RSS measurement requires Linux")
    wg.require(args.output_dir.is_absolute() and not args.output_dir.exists(), "output directory must be new and absolute")
    wg.require(len(args.source_revision) == 40 and all(c in "0123456789abcdef" for c in args.source_revision),
               "source revision must be a full commit hash")
    wg.require(args.harness_revision == revision(), "harness revision differs from checkout")
    subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", args.source_revision + "^{commit}"], check=True)
    wg.require(args.timeout_seconds > 1 and args.max_rss_kib > 0, "invalid resource caps")
    inputs = {"cli": pin(args.cli_binary), "oracle": pin(args.oracle_binary),
              "artifact": pin(args.artifact), "openings": pin(wg.OPENINGS)}
    for key in ("cli", "oracle"):
        wg.require(os.access(inputs[key]["path"], os.X_OK), f"{key} binary is not executable")
    legacy_binaries = {}
    legacy = []
    if args.legacy_dir:
        wg.require(args.legacy_binary and args.legacy_candidate_binary, "legacy registration needs both pinned binaries")
        legacy_binaries = {"legacy": pin(args.legacy_binary), "candidate": pin(args.legacy_candidate_binary)}
        legacy = legacy_registry(args.legacy_dir.resolve(), legacy_binaries, inputs["artifact"], inputs["oracle"])
    probe_reset(Path(inputs["cli"]["path"]), Path(inputs["artifact"]["path"]), args.timeout_seconds)
    harness_files = [pin(path) for path in harness_paths()]
    manifest = signed({"schema_version": 1, "source_revision": args.source_revision,
                       "harness_revision": args.harness_revision, "harness_files": harness_files,
                       "host": host(), "inputs": inputs, "legacy": legacy, "legacy_binaries": legacy_binaries,
                       "output_directory": str(args.output_dir), "cache_lifetime": "one-game", "reset_protocol": "new_game-v1",
                       "oracle_cwd": str((args.oracle_cwd or args.oracle_binary.parent).resolve(strict=True)),
                       "settings": {"opening_depth": 12, "endgame_depth": 12, "exact_empty": 16,
                                    "timeout_seconds": args.timeout_seconds, "max_rss_kib": args.max_rss_kib,
                                    "max_decisions": 120},
                       "assignments": [{"opening_id": row["id"], "assignment": assignment}
                                       for row in wg.opening_rows() for assignment in (0, 1)],
                       "conditions": conditions(str(args.output_dir))})
    args.output_dir.mkdir(parents=True)
    path = args.output_dir / "manifest.json"
    atomic(path, wg.canonical(manifest))
    script = args.output_dir / "run-whole-game.sh"
    command = " ".join(shlex.quote(part) for part in
                       ["rtk", "python3", str(Path(__file__).resolve()), "run", "--manifest", str(path)])
    atomic(script, ("#!/usr/bin/env bash\nset -euo pipefail\n" + command + "\n").encode())
    script.chmod(0o755)
    verify_manifest(path)
    progress("prepare", total=6, status="verified")
    print(f"rtk bash {shlex.quote(str(script))}")
    return path


def evidence(path: Path, compute, verify_only: bool) -> None:
    if path.exists():
        wg.require(load(path) == compute(), f"existing evidence mismatch: {path}")
    else:
        wg.require(not verify_only, f"missing evidence: {path}")
        atomic(path, wg.canonical(compute()))


def args_for_condition(manifest: dict, condition: dict, progress_every: int) -> argparse.Namespace:
    return argparse.Namespace(**manifest["settings"], **{k: condition[k] for k in ("kind", "midgame_depth", "cache_scope")},
                              binary=Path(manifest["inputs"]["cli"]["path"]),
                              artifact=Path(manifest["inputs"]["artifact"]["path"]), output=Path(condition["output"]),
                              oracle_cwd=Path(manifest["oracle_cwd"]), source_revision=manifest["source_revision"],
                              progress_every=progress_every)


def verify_condition(manifest: dict, condition: dict, report: dict, progress_every: int) -> None:
    args = args_for_condition(manifest, condition, progress_every)
    wg.verify(report, args.binary, args.artifact)
    wg.require(report.get("manifest_digest") == manifest["manifest_digest"]
               and report.get("condition_id") == condition["id"]
               and report.get("identity") == wg.measurement_identity(args), "complete report manifest identity mismatch")


def execute(path: Path, verify_only: bool, progress_every: int) -> None:
    manifest = verify_manifest(path)
    directory = Path(manifest["output_directory"])
    with (directory / "measurement.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise wg.BenchmarkError("another measurement driver is running") from exc
        total = len(manifest["conditions"])
        # Validate every existing completed artifact before starting any seat process.
        existing = {}
        for condition in manifest["conditions"]:
            output = Path(condition["output"])
            if output.exists():
                report = load(output)
                verify_condition(manifest, condition, report, progress_every)
                existing[condition["id"]] = report
        for depth in (12, 8):
            comparison_path = directory / f"comparison-{depth}.json"
            oracle_path = directory / f"exact-check-{depth}.json"
            if comparison_path.exists():
                wg.require(f"turn-{depth}" in existing and f"game-{depth}" in existing,
                           "comparison has missing completed inputs")
                wg.require(load(comparison_path) == wg.comparison(existing[f"turn-{depth}"], existing[f"game-{depth}"]),
                           "existing comparison mismatch")
            if oracle_path.exists():
                wg.require(f"game-{depth}" in existing, "oracle evidence has missing completed input")
                wg.verify_oracle_evidence(existing[f"game-{depth}"], load(oracle_path),
                                         Path(manifest["inputs"]["oracle"]["path"]))
        for item in manifest["legacy"]:
            progress("verify", item["id"], total=total, status="skipped")
        reports = {}
        for done, condition in enumerate(manifest["conditions"]):
            CURRENT.update(condition=condition["id"], done=done, total=total)
            output = Path(condition["output"])
            args = args_for_condition(manifest, condition, progress_every)
            if verify_only:
                report = load(output)
                verify_condition(manifest, condition, report, progress_every)
            else:
                report = wg.measure_resumable(args, manifest["manifest_digest"], condition["id"],
                                              Path(condition["checkpoint_directory"]), done, total)
            reports[condition["id"]] = report
            progress("verify", condition["id"], done + 1, total)
        for depth in (12, 8):
            turn, game = reports[f"turn-{depth}"], reports[f"game-{depth}"]
            progress("compare", f"comparison-{depth}", total, total)
            evidence(directory / f"comparison-{depth}.json", lambda: wg.comparison(turn, game), verify_only)
            oracle_path = directory / f"exact-check-{depth}.json"
            progress("oracle", f"exact-check-{depth}", total, total)
            if oracle_path.exists():
                wg.verify_oracle_evidence(game, load(oracle_path), Path(manifest["inputs"]["oracle"]["path"]))
            else:
                wg.require(not verify_only, f"missing oracle evidence: {oracle_path}")
                result = wg.oracle_evidence(game, Path(manifest["inputs"]["oracle"]["path"]),
                                            Path(manifest["oracle_cwd"]), manifest["settings"]["timeout_seconds"],
                                            progress_enabled=False)
                wg.verify_oracle_evidence(game, result, Path(manifest["inputs"]["oracle"]["path"]))
                atomic(oracle_path, wg.canonical(result))


def main(argv: list[str] | None = None) -> int:
    actual = sys.argv[1:] if argv is None else argv
    if actual and actual[0] == "exact-threshold":
        import exact_threshold
        return exact_threshold.main(actual[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    for name in ("cli-binary", "oracle-binary", "artifact", "output-dir"):
        prep.add_argument("--" + name, type=Path, required=True)
    for name in ("oracle-cwd", "legacy-dir", "legacy-binary", "legacy-candidate-binary"):
        prep.add_argument("--" + name, type=Path)
    prep.add_argument("--source-revision", required=True)
    prep.add_argument("--harness-revision", required=True)
    prep.add_argument("--timeout-seconds", type=float, default=310)
    prep.add_argument("--max-rss-kib", type=int, required=True)
    for name in ("run", "verify", "verify-inputs"):
        operation = sub.add_parser(name)
        operation.add_argument("--manifest", type=Path, required=True)
        operation.add_argument("--progress-every", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "verify-inputs":
            verify_manifest(args.manifest)
        else:
            wg.require(args.progress_every > 0, "progress interval must be positive")
            execute(args.manifest, args.command == "verify", args.progress_every)
    except (wg.BenchmarkError, wg.oracle.OracleError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        progress("verify", CURRENT["condition"], CURRENT["done"], CURRENT["total"], status="failed")
        print(f"whole-game preparation error: {exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        progress("measure", CURRENT["condition"], CURRENT["done"], CURRENT["total"], status="interrupted")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
