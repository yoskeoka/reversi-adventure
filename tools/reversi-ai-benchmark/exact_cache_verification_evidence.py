"""Read-only verification of the frozen PR #251 producer and its receipts."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import whole_game as wg

PRODUCER = "42f6d575b7115b4ccd6aa2ab6d9d805adadc1b89"
MANIFEST_DIGEST = "7d3104d720fdbe605839af893a0ff4c47207e423d9b3eec633a6add1728de960"
SCORE_CONTRACT = "side-to-move-disc-difference-wipeout-64-v1"
ROOT = Path(__file__).resolve().parents[2]
FILES = ("tools/reversi-ai-oracle/oracle.py",
         "tools/reversi-ai-benchmark/prepare-whole-game-measurement.py",
         "tools/reversi-ai-benchmark/whole_game.py",
         "tools/reversi-ai-benchmark/exact_threshold.py")


def load(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    wg.require(raw == wg.canonical(value), f"historical noncanonical evidence: {path}")
    return value


def pin(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": wg.digest(path)}


@contextlib.contextmanager
def frozen_producer(manifest):
    """Load commit-pinned code, restoring the caller's modules afterwards."""
    names = ("oracle", "whole_game", "measurement_prepare", "exact_threshold")
    previous = {name: sys.modules.get(name) for name in names}
    search = list(sys.path)
    with tempfile.TemporaryDirectory(prefix="exact-cache-frozen-verifier-") as temporary:
        root = Path(temporary)
        try:
            for relative, recorded in zip(FILES, manifest["harness_files"], strict=True):
                wg.require(str(recorded["path"]).endswith("/"+relative), "historical harness registry mismatch")
                raw = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{PRODUCER}:{relative}"])
                wg.require(hashlib.sha256(raw).hexdigest() == recorded["sha256"], "frozen producer source digest mismatch")
                target = root/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            relative = "tools/reversi-ai-benchmark/whole-game-openings-v1.json"
            (root/relative).write_bytes(subprocess.check_output(["git", "-C", str(ROOT), "show", f"{PRODUCER}:{relative}"]))
            for name in names:
                sys.modules.pop(name, None)
            sys.path.insert(0, str(root/"tools/reversi-ai-benchmark"))
            spec = importlib.util.spec_from_file_location("exact_threshold", root/FILES[-1])
            module = importlib.util.module_from_spec(spec)
            sys.modules["exact_threshold"] = module
            spec.loader.exec_module(module)
            # Original resume provenance uses repository-relative git paths.
            # Keep its original registry while executing only extracted code.
            module.prep.ROOT = ROOT
            module.harness_paths = lambda: [Path(p["path"]) for p in manifest["harness_files"]]
            original_resume = module.resume_sources
            # resume_sources derives relative paths from prep.ROOT; historical
            # producer paths are a separate worktree of this same repository.
            def resume(m):
                old_root = module.prep.ROOT
                module.prep.ROOT = Path(m["harness_files"][0]["path"]).parents[2]
                try:
                    return original_resume(m)
                finally:
                    module.prep.ROOT = old_root
            module.resume_sources = resume
            yield module
        finally:
            sys.path[:] = search
            for name, old in previous.items():
                if old is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old


def query_record(receipt, index, receipt_pin):
    query = receipt["queries"][index]
    return {"identity": {"board": query["board"], "effective_side": query["effective_side"],
            "oracle_binary_sha256": receipt["oracle_binary"]["sha256"],
            "profile_digest": hashlib.sha256(wg.canonical(receipt["profile"])).hexdigest(),
            "score_contract": SCORE_CONTRACT}, "result": query["result"],
        "child_query": query["child_query"],
        "process_observation": receipt["process_observations"][index],
        "provenance": {"receipt_digest": receipt["report_digest"], "query_index": index,
            "producer_revision": PRODUCER, "receipt": receipt_pin,
            "receipt_status": receipt["status"], "receipt_failure": receipt["failure"]},
        "verified": True}


def verify_counterexample(directory, fixture):
    expected = fixture["expected"]
    seen = []
    for recorded in fixture["evidence"]["receipts"]:
        path = directory/recorded["path"]
        result = load(path)
        wg.require(wg.digest(path) == recorded["file_sha256"]
                   and result["report_digest"] == recorded["report_digest"]
                   and result["status"] == recorded["status"], "counterexample receipt pin mismatch")
        if recorded["kind"] == "cli":
            step = result["steps"][fixture["evidence"]["step_index"]]
            saved = fixture["saved_turn_result"] if recorded["policy"] == "turn" else fixture["saved_failure"]
            wg.require(step["board"] == fixture["board"] and step["side"] == fixture["side"]
                       and step["move"] == saved["move"] and step["search"]["score"] == saved["root_score"]
                       and step["search"]["nodes"] == saved["nodes"] and step["search"]["exact"] is True,
                       "counterexample CLI mismatch")
        else:
            wg.require(result["job"]["source_digest"] == recorded["source_digest"], "counterexample source mismatch")
            root, child = result["queries"]
            move = "a4" if recorded["policy"] == "turn" else "a7"
            wg.require(root["board"] == fixture["board"] and root["effective_side"] == fixture["side"]
                       and root["result"]["value"] == expected["root_score"]
                       and root["result"]["move"] == expected["saved_oracle_root_move"]
                       and child["board"] == expected["children"][move]["board"]
                       and child["effective_side"] == expected["children"][move]["side"]
                       and child["result"]["value"] == expected["children"][move]["oracle_score"],
                       "counterexample Oracle root/child mismatch")
            seen.append({"receipt_digest": result["report_digest"], "status": result["status"],
                         "root_score": root["result"]["value"], "move": move,
                         "child_score_root_view": -child["result"]["value"], "failure": result["failure"]})
    return {"fixture": fixture["id"], "root_score": 4, "a4_score": 4, "a7_score": 2, "oracle_receipts": seen}


def verify_evidence(directory):
    directory = Path(directory).resolve(strict=True)
    manifest_path = directory/"manifest.json"
    manifest = load(manifest_path)
    wg.require(manifest["report_digest"] == MANIFEST_DIGEST and manifest["harness_revision"] == PRODUCER,
               "frozen historical manifest mismatch")
    receipts, queries, profiles = [], [], {}
    with frozen_producer(manifest) as producer:
        producer.verify_seal(manifest)
        wg.require(manifest["version"] == producer.VERSION and manifest["caps"] == producer.CAPS
                   and manifest["pilot_units"] == producer.units("pilot", manifest["roots"])
                   and manifest["pilot_total"] == 24 and manifest["cache_lifetime"] == "one-game"
                   and manifest["reset_protocol"] == "new_game-v1", "historical manifest contract mismatch")
        for recorded in manifest["inputs"].values():
            producer.prep.check_pin(recorded)
        source = producer.prep.load(Path(manifest["inputs"]["source_report"]["path"]))
        wg.require(manifest["roots"] == producer.freeze_roots(source)
                   and manifest["source_report_digest"] == source["report_digest"], "historical roots mismatch")
        producer.preflight(manifest, directory)
        counts = {"pilot": 24, "full": 32, "pilot-oracle": 112, "full-oracle": 584}
        for stage, count in counts.items():
            paths = sorted((directory/stage).glob("*.json"))
            wg.require(len(paths) == count, "historical receipt coverage mismatch")
            for path in paths:
                receipt = load(path)
                receipt_pin = pin(path)
                receipts.append({**receipt_pin, "report_digest": receipt["report_digest"],
                                 "status": receipt["status"], "failure": receipt["failure"]})
                if stage.endswith("-oracle"):
                    profile_digest = hashlib.sha256(wg.canonical(receipt["profile"])).hexdigest()
                    profiles[profile_digest] = receipt["profile"]
                    for index, query in enumerate(receipt["queries"]):
                        raw = query["result"]
                        if raw["exact"] is True and raw["completed_depth"] >= query["board"].count("."):
                            queries.append(query_record(receipt, index, receipt_pin))
    fixture = json.loads(Path(__file__).with_name("fixtures").joinpath("exact-cache-counterexample-v1.json").read_text())
    return {"producer_revision": PRODUCER, "source_revision": manifest["source_revision"],
            "directory": str(directory), "manifest": {**pin(manifest_path), "report_digest": MANIFEST_DIGEST},
            "input_pins": manifest["inputs"], "harness_files": manifest["harness_files"],
            "host": manifest["host"], "receipt_count": len(receipts), "counts": counts,
            "manifests": [pin(directory/name) for name in ("full-manifest.json", "pilot-oracle-manifest.json", "full-oracle-manifest.json", "assessment.json")],
            "receipts": receipts, "queries": queries,
            "profiles": [{"profile_digest": digest, "profile": profile}
                         for digest, profile in sorted(profiles.items())],
            "counterexample": verify_counterexample(directory, fixture)}


def reusable_queries(m, audit):
    """Only expose complete process-validated queries for the pinned binary."""
    profile = wg.oracle.profile_metadata(wg.oracle.profile_from_name("whole-game-depth-12-exact-20"))
    profile_digest = hashlib.sha256(wg.canonical(profile)).hexdigest()
    return [q for q in audit["queries"]
            if q["identity"]["oracle_binary_sha256"] == m["inputs"]["oracle"]["sha256"]
            and q["identity"]["profile_digest"] == profile_digest
            and q["identity"]["score_contract"] == SCORE_CONTRACT]
