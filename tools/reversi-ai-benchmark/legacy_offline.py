"""Explicit, read-only adapters for original score evidence.

Validators are loaded from their recorded Git revision, never re-labelled with
current source digests. This module cannot run an Oracle or a benchmark workload.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Latest unchanged schema1/schema2 whole-game verifier before score migration.
WHOLE_GAME_PRODUCER = "d6a858912078e5802d2f90bd6f3d4e54fcbb2dd6"


def reject_new_semantics(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("score_identity_raw", "search_semantics_version") or (
                key == "score_contract" and item != "side-to-move-disc-difference-wipeout-64-v1"
            ) or key == "score_scale" and item == "winner_empty_v1":
                raise ValueError("legacy evidence contains new score semantics")
            reject_new_semantics(item)
    elif isinstance(value, list):
        for item in value:
            reject_new_semantics(item)


def repository_relative(path):
    """Preserve a recorded pin while routing any historical worktree root."""
    parts = Path(path).parts
    for index, part in enumerate(parts):
        if part == "tools" and index + 1 < len(parts) and parts[index + 1] in (
            "reversi-ai-oracle", "reversi-ai-benchmark", "reversi-ai-training"):
            return Path(*parts[index:])
    raise ValueError("legacy producer path is outside the recorded tool registry")


def restore_pinned_entrypoint(script, extracted_path, recorded_path):
    extracted = shlex.quote(str(Path(extracted_path).resolve())).encode()
    recorded = shlex.quote(str(Path(recorded_path).resolve())).encode()
    if script.count(extracted) != 1:
        raise ValueError("legacy launch script entrypoint mismatch")
    return script.replace(extracted, recorded, 1)


class OfflineProcesses:
    """Only Git reads are permitted in the frozen offline validator."""
    def check_output(self, argv, **kwargs):
        if not isinstance(argv, list) or len(argv) < 5 or argv[:2] != ["git", "-C"] or argv[3] not in ("show", "rev-parse", "ls-tree"):
            raise ValueError("legacy offline validator cannot start a workload")
        return subprocess.check_output([*argv[:2], str(ROOT), *argv[3:]], **kwargs)

    def __getattr__(self, name):
        if name in ("Popen", "run", "call", "check_call"):
            def reject(*args, **kwargs):
                raise ValueError("legacy offline validator cannot start a workload")
            return reject
        return getattr(subprocess, name)


@contextlib.contextmanager
def frozen(revision, entrypoint):
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("legacy producer requires a full Git revision")
    names = ("oracle", "whole_game", "measurement_prepare", "exact_threshold",
             "exact_cache_verification", "exact_cache_verification_games",
             "exact_cache_verification_oracle", "exact_cache_verification_evidence", "compare", "training")
    previous = {name: sys.modules.get(name) for name in names}
    search = list(sys.path)
    with tempfile.TemporaryDirectory(prefix="winner-empty-legacy-") as temporary:
        root = Path(temporary)
        entries = subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", revision,
            "tools/reversi-ai-oracle", "tools/reversi-ai-benchmark", "tools/reversi-ai-training/training.py"], text=True).splitlines()
        try:
            for relative in entries:
                path = Path(relative)
                if entrypoint == "whole_game" and relative not in (
                    "tools/reversi-ai-benchmark/whole_game.py",
                    "tools/reversi-ai-oracle/oracle.py",
                    "tools/reversi-ai-benchmark/whole-game-openings-v1.json"):
                    continue
                if path.suffix not in (".py", ".json", ".jsonl") or "tests" in path.parts or path.name.startswith("test_"):
                    continue
                target = root/path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(["git", "-C", str(ROOT), "show", f"{revision}:{relative}"]))
            for name in names:
                sys.modules.pop(name, None)
            sys.path.insert(0, str(root/"tools/reversi-ai-benchmark"))
            spec = importlib.util.spec_from_file_location(entrypoint,
                root/("tools/reversi-ai-benchmark/prepare-whole-game-measurement.py" if entrypoint == "measurement_prepare" else f"tools/reversi-ai-benchmark/{entrypoint}.py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[entrypoint] = module
            spec.loader.exec_module(module)
            for name in names:
                loaded = sys.modules.get(name)
                if loaded is not None and hasattr(loaded, "subprocess"):
                    loaded.subprocess = OfflineProcesses()
            if hasattr(module, "prep"):
                module.prep.subprocess = OfflineProcesses()
            # Original validators may tolerate unknown fields. Reject new score
            # identities recursively before passing saved documents to them.
            for loaded in {id(m): m for m in [module, getattr(module, "prep", None),
                *[sys.modules.get(name) for name in names]] if m is not None}.values():
                for function_name in ("load", "read_canonical"):
                    original = getattr(loaded, function_name, None)
                    if original is None:
                        continue
                    def guarded(*args, _original=original, **kwargs):
                        value = _original(*args, **kwargs)
                        reject_new_semantics(value)
                        return value
                    setattr(loaded, function_name, guarded)
            yield module, root
        finally:
            sys.path[:] = search
            for name, old in previous.items():
                if old is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old


def whole_game_report(report, binary=None, artifact=None, *, evidence=None, oracle_binary=None):
    if not isinstance(report, dict) or evidence is not None and not isinstance(evidence, dict):
        raise ValueError("legacy report/evidence must be objects")
    reject_new_semantics(report)
    if evidence is not None:
        reject_new_semantics(evidence)
    if type(report.get("schema_version")) is not int or report.get("schema_version") not in (1, 2) or "score_contract" in report:
        raise ValueError("legacy whole-game adapter requires an original schema1/schema2 report")
    with frozen(WHOLE_GAME_PRODUCER, "whole_game") as (producer, _):
        producer.verify(report, binary, artifact)
        if evidence is not None:
            producer.verify_oracle_evidence(report, evidence, oracle_binary)


def assessment(path, command, every, entrypoint):
    if command not in ("verify", "verify-inputs"):
        raise ValueError("legacy offline adapter cannot execute measurements")
    path = Path(path)
    manifest = json.loads(path.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError("legacy manifest must be an object")
    reject_new_semantics(manifest)
    expected = {"exact_threshold": "exact-threshold-assessment-v1",
                "exact_cache_verification": "exact-cache-verification-v1"}[entrypoint]
    if manifest.get("version") != expected or "score_contract" in manifest:
        raise ValueError("legacy assessment adapter requires original version1 evidence")
    revision = manifest["harness_revision"]
    with frozen(revision, entrypoint) as (producer, extracted):
        prep = producer.prep
        expected_registry = [repository_relative(p) for p in producer.harness_paths()]
        recorded_registry = [repository_relative(item["path"]) for item in manifest["harness_files"]]
        if expected_registry != recorded_registry:
            raise ValueError("legacy frozen producer harness registry mismatch")
        relative_root = repository_relative(manifest["harness_files"][0]["path"])
        recorded_root = Path(manifest["harness_files"][0]["path"]).parents[len(relative_root.parts)-1]
        prep.ROOT = recorded_root
        prep.revision = lambda: revision
        pins = {item["path"]: item for item in manifest["harness_files"]}
        source_pins = {item["path"]: item for item in manifest.get("source_files", [])}
        original_pin = prep.check_pin
        def check_pin(item):
            if item["path"] in pins:
                relative = repository_relative(item["path"])
                raw = (extracted/relative).read_bytes()
                if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                    raise ValueError("legacy frozen producer digest mismatch")
                return Path(item["path"])
            if item["path"] in source_pins:
                relative = Path(item["path"]).relative_to(recorded_root)
                raw = subprocess.check_output(["git", "-C", str(ROOT), "show",
                    f"{manifest['source_revision']}:{relative}"])
                if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                    raise ValueError("legacy frozen source digest mismatch")
                return Path(item["path"])
            return original_pin(item)
        prep.check_pin = check_pin
        producer.harness_paths = lambda: [Path(item["path"]) for item in manifest["harness_files"]]
        producer.wg.OPENINGS = Path(manifest["inputs"]["openings"]["path"])
        if hasattr(producer, "ROOT"):
            producer.ROOT = recorded_root
        if entrypoint == "exact_cache_verification":
            recorded_entrypoints = [item["path"] for item in manifest["harness_files"]
                                    if Path(item["path"]).name == "exact_cache_verification.py"]
            if len(recorded_entrypoints) != 1:
                raise ValueError("legacy exact-cache entrypoint pin is missing or duplicated")
            original_script_bytes = producer.script_bytes
            def pinned_script_bytes(directory):
                return restore_pinned_entrypoint(
                    original_script_bytes(directory), producer.__file__, recorded_entrypoints[0])
            producer.script_bytes = pinned_script_bytes
        if "source_files" in manifest:
            entries = subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only",
                manifest["source_revision"], "Cargo.toml", "Cargo.lock", "rust"], text=True).splitlines()
            expected_sources = sorted(Path(name) for name in entries if name in ("Cargo.toml", "Cargo.lock") or (
                name.startswith(("rust/reversi-ai/", "rust/reversi-engine/")) and name.endswith(".rs")
            ) or len(Path(name).parts) == 3 and name.startswith("rust/") and name.endswith("/Cargo.toml"))
            recorded_sources = [Path(item["path"]).relative_to(recorded_root) for item in manifest["source_files"]]
            if recorded_sources != expected_sources:
                raise ValueError("legacy frozen source registry mismatch")
            producer.source_paths = lambda: [Path(item["path"]) for item in manifest["source_files"]]
        if hasattr(producer, "evidence"):
            producer.evidence.ROOT = ROOT
        producer.execute(path, command, every)


def whole_game_comparison(baseline, candidate):
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        raise ValueError("legacy comparison reports must be objects")
    reject_new_semantics(baseline)
    reject_new_semantics(candidate)
    with frozen(WHOLE_GAME_PRODUCER, "whole_game") as (producer, _):
        return producer.comparison(baseline, candidate)


def preparation(path, command, every):
    if command not in ("verify", "verify-inputs"):
        raise ValueError("legacy preparation adapter cannot execute measurements")
    path = Path(path)
    manifest = json.loads(path.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError("legacy manifest must be an object")
    reject_new_semantics(manifest)
    if type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != 1 or "score_contract" in manifest:
        raise ValueError("legacy preparation requires original schema1 manifest")
    revision = manifest["harness_revision"]
    with frozen(revision, "measurement_prepare") as (producer, extracted):
        expected_registry = [repository_relative(p) for p in producer.harness_paths()]
        if expected_registry != [repository_relative(item["path"]) for item in manifest["harness_files"]]:
            raise ValueError("legacy frozen producer harness registry mismatch")
        producer.ROOT = ROOT
        producer.revision = lambda: revision
        pins = {item["path"]: item for item in manifest["harness_files"]}
        original_pin = producer.check_pin
        def check_pin(item):
            if item["path"] in pins:
                raw = (extracted/repository_relative(item["path"])).read_bytes()
                if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                    raise ValueError("legacy frozen producer digest mismatch")
                return Path(item["path"])
            return original_pin(item)
        producer.check_pin = check_pin
        producer.harness_paths = lambda: [Path(item["path"]) for item in manifest["harness_files"]]
        producer.wg.OPENINGS = Path(manifest["inputs"]["openings"]["path"])
        if command == "verify-inputs":
            producer.verify_manifest(path)
        else:
            producer.execute(path, True, every)


def cost_comparison(report, records, baseline=None, candidate=None):
    if not isinstance(report, dict):
        raise ValueError("legacy comparison report must be an object")
    reject_new_semantics(report)
    if report.get("runner_version") != "reversi-ai-rust-cost-comparator-v1" or "score_contract" in report:
        raise ValueError("legacy cost comparator requires original version1 producer")
    with frozen(WHOLE_GAME_PRODUCER, "compare") as (producer, _):
        return producer.verify_report(report, records, baseline, candidate)
