"""Read-only reconstruction and pinning of the completed 0019 comparison inputs."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pilot
import production_cycle as cycle
import reinforcement as rf
import training

BASELINE_SHA256 = "23ed5f73d939300cd04b0842ce24e840f8c829e3ee942244a7de56a293dc6875"
SOURCE_MANIFEST_SHA256 = "efc0c268435d6f16944449696ac34f1943e06e0d1e6e13be4ed2de8592412e40"
SOURCE_REPORT_SHA256 = "5954f980d7e019b3b73fc2c379f6de18f619935b476210401a31dffa86b0bbdb"
ADOPTED_SHA256 = "13e8bdf59553746ba32ce47b53a09c011eb79223cabf4ddefb224b2640d283de"
ADOPTED_WEIGHT_DIGEST = "1c8ffd775feabbc663e4e6f9aef7972738bc5719342f834671fdd99e3827d009"


def require(condition: bool, message: str) -> None:
    cycle.require(condition, message)


def _keys(rows: list[dict]) -> set[str]:
    return {pilot.key(row["board"], row["side"]) for row in rows}


def _audit(raw: list[dict], admitted: list[dict]) -> dict:
    admitted_ids = Counter(row["id"] for row in admitted)
    excluded = []
    for row in raw:
        if admitted_ids[row["id"]]:
            admitted_ids[row["id"]] -= 1
        else:
            excluded.append(row)
    return {"source_rows": len(raw), "admitted_rows": len(admitted),
            "source_keys": sorted(_keys(raw)), "admitted_keys": sorted(_keys(admitted)),
            "excluded_keys": sorted(_keys(excluded)),
            "excluded_ids": [row["id"] for row in excluded]}


def _collect_pins(source_manifest: Path, fixture: bool) -> dict:
    """Pin source attempts and recursively referenced JSON input manifests."""
    files: dict[str, dict] = {}

    def add(path: Path, expected: str | None = None) -> None:
        path = path.resolve()
        name = str(path)
        if name in files:
            require(expected is None or files[name]["sha256"] == expected,
                    "conflicting comparison input pins")
            return
        entry = cycle.file_entry(path)
        require(expected is None or entry["sha256"] == expected,
                f"comparison input digest changed: {path}")
        files[name] = entry
        if path.suffix == ".json":
            walk(training.read_json(path), path.parent)

    def walk(value: object, parent: Path) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                # Oracle runtime resources retain a logical resources/... name
                # and a separately validated absolute on-disk resolved_path.
                target = Path(value.get("resolved_path", value["path"]))
                add(target if target.is_absolute() else parent / target, value["sha256"])
            for item in value.values():
                walk(item, parent)
        elif isinstance(value, list):
            for item in value:
                walk(item, parent)

    add(source_manifest)
    add(source_manifest.parent / "report.json")
    for path in sorted((source_manifest.parent / "phases").rglob("*")):
        if path.is_file():
            add(path)
    return {"schema_version": 1, "fixture": fixture,
            "source_manifest": cycle.file_entry(source_manifest),
            "files": [files[name] for name in sorted(files)]}


def load_source(source_manifest: Path, *, fixture: bool = False) -> dict:
    """Replay completed source evidence without learning or starting any processes.

    ``fixture`` bypasses only the adopted production identities/counts. The full
    0019 verifier remains mandatory, including for fixtures.
    """
    require(type(fixture) is bool, "comparison fixture eligibility must be boolean")
    source_manifest = source_manifest.resolve()
    context = cycle.load_context(source_manifest)
    manifest = context["manifest"]
    root = source_manifest.parent
    digest = training.sha256_file(source_manifest)
    predecessors = {}
    for phase in cycle.PHASES:
        found = cycle.latest_success(root, phase, digest)
        require(found is not None, f"comparison requires completed source phase {phase}")
        predecessors[phase] = found[0]
    cycle.check_dependencies(context, predecessors)
    cycle.verify_failed_attempts(root, context)
    for phase in cycle.PHASES:
        cycle.semantic_phase_check(context, phase, predecessors[phase], predecessors)
    report = training.read_json(root / "report.json")
    require(report == cycle.build_final_report(context, predecessors, digest)
            and report == training.read_json(predecessors["offline-verification"] / "report.json"),
            "comparison source report does not reconstruct")
    require(report["selected_artifact"] == "candidate", "comparison source did not adopt candidate")
    games = training.read_jsonl(predecessors["self-play"] / "games.jsonl")
    teachers = cycle.tuning_rows(context, games)
    adopted_path = predecessors["candidate-update"] / "candidate-artifact.json"
    adopted = training.read_json(adopted_path)
    control = rf.updated_artifact(context["baseline"], teachers, manifest)
    require(control["weights"] == adopted["weights"]
            and control["weight_digest"] == adopted["weight_digest"],
            "comparison control A does not reproduce adopted weights")
    prior_games = cycle.all_game_records(context, predecessors)
    used = cycle.played_keys(context, prior_games)
    used |= context["baseline_keys"] | context["reserved"] | context["corpus_keys"]
    validation = [row for row in context["validation"] if pilot.key(row["board"], row["side"]) not in used]
    selection = training.read_json(predecessors["candidate-selection"] / "selection.json")
    require(sorted(_keys(validation)) == selection["validation_position_keys"],
            "comparison validation differs from original 0019 split")
    exposure_keys = set().union(*(set(values) for values in report["exposure_keys"].values()))
    forbidden = used | exposure_keys | _keys(teachers) | _keys(validation)
    held_out, seen = [], set(forbidden)
    for row in context["held_out"]:
        key = pilot.key(row["board"], row["side"])
        if key not in seen:
            held_out.append(row)
            seen.add(key)
    require(teachers and validation and held_out, "comparison requires nonempty independent splits")
    require(not (_keys(teachers) & _keys(validation))
            and not (_keys(teachers) & _keys(held_out))
            and not (_keys(validation) & _keys(held_out)), "comparison split collision")
    if not fixture:
        require(digest == SOURCE_MANIFEST_SHA256
                and training.sha256_file(root / "report.json") == SOURCE_REPORT_SHA256
                and manifest["inputs"]["baseline_artifact"]["sha256"] == BASELINE_SHA256
                and training.sha256_file(adopted_path) == ADOPTED_SHA256
                and adopted["weight_digest"] == ADOPTED_WEIGHT_DIGEST,
                "comparison requires pinned adopted 0019 production identities")
        require(len(games) == 64 and len(teachers) == 3364 and len(validation) == 13401
                and len(context["corpus"]) == 12, "comparison source production counts differ")
    # Retain original decision IDs and add the explicit game/source/view identity.
    teachers = [{**row, "source": "project-owned-self-play-0019",
                 "game_id": row["id"].rsplit("-t", 1)[0],
                 "score_view": "side-to-move-winner-empty-v1"} for row in teachers]
    return {"baseline": context["baseline"], "adopted": adopted,
            "teachers": teachers, "validation": validation, "held_out": held_out,
            "corpus": context["corpus"], "golden": context["golden"],
            "source_context": context, "source_report": report,
            "source_predecessors": predecessors,
            "adopted_path": adopted_path,
            "pins": _collect_pins(source_manifest, fixture),
            "exposure_keys": sorted(exposure_keys | used | _keys(teachers)
                                    | _keys(validation) | _keys(held_out)),
            "split_audit": {"validation": _audit(context["validation"], validation),
                            "held_out": _audit(context["held_out"], held_out)}}


def pin_inputs(source_manifest: Path, *, fixture: bool = False) -> dict:
    return load_source(source_manifest, fixture=fixture)["pins"]


def load_pinned(pins: dict, *, fixture: bool = False) -> dict:
    require(set(pins) == {"schema_version", "fixture", "source_manifest", "files"}
            and type(pins["schema_version"]) is int and pins["schema_version"] == 1
            and type(pins["fixture"]) is bool and pins["fixture"] is fixture,
            "invalid comparison input pins or fixture eligibility")
    for entry in pins["files"]:
        require(cycle.file_entry(Path(entry["path"])) == entry, "comparison pinned input changed")
    source = Path(pins["source_manifest"]["path"])
    require(cycle.file_entry(source) == pins["source_manifest"], "comparison source manifest changed")
    context = load_source(source, fixture=fixture)
    require(context["pins"] == pins, "comparison input file inventory changed")
    return context
