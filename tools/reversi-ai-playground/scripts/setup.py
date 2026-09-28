#!/usr/bin/env python3
"""Prepare and start the local playground without checkout-owned artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "tools" / "reversi-ai-playground"
ORACLE = ROOT / "tools" / "reversi-ai-oracle" / "oracle.py"
TRAINER = ROOT / "tools" / "reversi-ai-training" / "training.py"
FIXTURE = ROOT / "tools" / "reversi-ai-training" / "fixtures" / "tiny-manifest.json"


def setup_directory() -> Path:
    configured = os.environ.get("REVERSI_ADVENTURE_PLAYGROUND_SETUP_DIR")
    cache = os.environ.get("XDG_CACHE_HOME")
    if configured and not Path(configured).expanduser().is_absolute():
        raise ValueError("playground setup directory must be absolute")
    base = Path(configured) if configured else Path(cache) / "reversi-adventure" / "playground" if cache else Path.home() / ".cache" / "reversi-adventure" / "playground"
    path = base.expanduser().resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError(f"playground setup directory must be outside the checkout: {path}")
    return path


def checked_path(value: object, kind: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError(f"verified Oracle {kind} path is not absolute")
    path = Path(value).resolve(strict=True)
    if path == ROOT or ROOT in path.parents:
        raise ValueError(f"verified Oracle {kind} path is inside the checkout")
    if kind == "binary" and (not path.is_file() or not os.access(path, os.X_OK)):
        raise ValueError("verified Oracle binary is not executable")
    if kind == "dataDir" and not path.is_dir():
        raise ValueError("verified Oracle data directory is missing")
    return path


def oracle_paths() -> tuple[Path, Path]:
    result = subprocess.run([sys.executable, str(ORACLE), "setup-oracle", "--json"],
                            cwd=ROOT, text=True, capture_output=True, check=True)
    try:
        payload = json.loads(result.stdout)
        if payload["version"] != "7.8.1":
            raise ValueError("verified Oracle version changed")
        return checked_path(payload["binary"], "binary"), checked_path(payload["dataDir"], "dataDir")
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid Oracle setup result: {error}") from error


def install() -> None:
    directory = setup_directory()
    directory.mkdir(parents=True, exist_ok=True)
    binary, data_dir = oracle_paths()
    artifact = directory / "demo-trained-artifact.json"
    report = directory / "demo-trained-report.json"
    with tempfile.TemporaryDirectory(prefix=".training-", dir=directory) as temporary:
        temporary_dir = Path(temporary)
        candidate = temporary_dir / "artifact.json"
        candidate_report = temporary_dir / "report.json"
        subprocess.run([sys.executable, str(TRAINER), "train", "--manifest", str(FIXTURE),
                        "--artifact", str(candidate), "--report", str(candidate_report)],
                       cwd=ROOT, check=True)
        subprocess.run([sys.executable, str(TRAINER), "validate", "--artifact", str(candidate)],
                       cwd=ROOT, check=True)
        os.replace(candidate, artifact)
        os.replace(candidate_report, report)
    prepared = {"trained": {"artifact": str(artifact), "demo": True},
                "oracle": {"binary": str(binary), "dataDir": str(data_dir)}}
    config = directory / "prepared.json"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                     prefix=".prepared-", delete=False) as stream:
        temporary_config = Path(stream.name)
        json.dump(prepared, stream, sort_keys=True)
        stream.write("\n")
    os.replace(temporary_config, config)
    print(f"playground prepared: {config}")
    print("TrainedEvaluator uses the tiny fixture demo artifact; playing strength is unverified.")


def start() -> None:
    config = setup_directory() / "prepared.json"
    if not config.is_file() or not (PACKAGE / "node_modules").is_dir():
        raise ValueError("playground is not installed; run make playground-install first")
    env = dict(os.environ, PLAYGROUND_PREPARED_CONFIG=str(config))
    os.execvpe("pnpm", ["pnpm", "--dir", str(PACKAGE), "dev"], env)


def main() -> int:
    try:
        if sys.argv[1:] == ["install"]:
            install()
        elif sys.argv[1:] == ["start"]:
            start()
        else:
            raise ValueError("usage: setup.py install|start")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"playground setup: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
