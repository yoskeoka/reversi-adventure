"""Frozen input policy for the 0058 table32 training experiment."""
from __future__ import annotations

import json
import os
from pathlib import Path

import table32_inputs as inputs
import table32_model as model
import table32_store as st
import training

SPLITS = tuple(inputs.SPLIT_COUNTS)
FIXED_SOURCE = "0058-fixed-opening-labels"


def add_arguments(parser):
    parser.add_argument("--data-0058", action="store_true", help="use the 0058 input policy")
    parser.add_argument("--fixed-opening-corpus", type=Path)
    parser.add_argument("--fixed-opening-labels", type=Path)
    parser.add_argument("--fixed-opening-limit-per-phase", type=int)
    parser.add_argument("--reserved-opening-keys", type=Path,
                        help="JSONL of canonical 0018 opening keys, when reserved")
    parser.add_argument("--exclude-exposure-keys", type=Path, action="append", default=[])
    for split in SPLITS:
        parser.add_argument(f"--minimum-{split}-rows", type=int,
                            help="minimum distinct games with a retained row per later phase (default: games per prefix)")


def settings(args, value):
    start, end, prefix = args.phase_start, args.phase_end, args.generation_prefix
    st.require(type(start) is int and type(end) is int and 0 <= start <= end <= 59,
               "0058 requires a valid phase-start and phase-end")
    st.require(not getattr(args, "opening_coverage", False) and
               getattr(args, "import_games_from", None) is None,
               "0058 uses fixed opening labels and fresh later games")
    early = start < 10
    st.require(((args.fixed_opening_corpus is not None and args.fixed_opening_labels is not None)
                if early else (args.fixed_opening_corpus is None and args.fixed_opening_labels is None)),
               "phases 0–9 require both fixed corpus and label roots")
    limit = args.fixed_opening_limit_per_phase
    st.require(limit is None or (early and type(limit) is int and limit > 0),
               "fixed opening limit requires selected early phases and a positive count")
    if end >= 10:
        st.require(type(prefix) is int and 10 <= prefix <= min(max(10, start), 58),
                   "0058 later phases require generation-prefix between 10 and first later phase")
        value["generation_prefix"] = prefix
        value["teacher_exact_solver_empty_squares"] = 20
    else:
        st.require(prefix is None, "early-only input has no generation prefix")
    minima = {}
    for split in SPLITS:
        explicit = getattr(args, f"minimum_{split}_rows")
        minima[split] = value[f"{split}_per_prefix"] if explicit is None else explicit
        st.require(type(minima[split]) is int and 1 <= minima[split] <= value[f"{split}_per_prefix"],
                   "0058 phase minima must be positive and fit the planned games")
    return {**value, "target_phases": list(range(start, end + 1)), "training_only": True,
            "data_0058": {"minimum_rows": minima, "fixed_limit_per_phase": limit}}


def _keys(path):
    keys = set()
    with Path(path).open() as stream:
        for line in stream:
            key = json.loads(line)
            st.require(isinstance(key, str) and key.count(":") == 1, "invalid position key")
            board, side = key.split(":")
            st.require(inputs.position_key(board, side) == key, "noncanonical position key")
            st.require(key not in keys, "duplicate position key")
            keys.add(key)
    return keys


def input_keys(args):
    reserved = args.reserved_opening_keys
    paths = ([reserved] if reserved is not None else []) + args.exclude_exposure_keys
    pins = [st.pin(path) for path in paths]
    groups = [_keys(pin["path"]) for pin in pins]
    for pin in pins:
        st.check_pin(pin)
    reservation = set()
    if reserved is not None:
        st.require(bool(groups[0]), "reserved opening keys are empty")
        reservation.update(groups[0])
        for key in groups[0]:
            board, side = key.split(":")
            other = inputs.rf.other(side)
            if bool(inputs.rf.legal_moves(board, side)) != bool(inputs.rf.legal_moves(board, other)):
                reservation.add(inputs.position_key(board, other))
    return pins, {"reserved_keys": sorted(reservation),
                  "excluded_keys": sorted(reservation.union(*groups))}


def prepare(root, args, config, baseline, candidate, candidate_commit, producer, seed, sources):
    pins, snapshot = input_keys(args)
    config = {**config, "data_0058": {**config["data_0058"], "reserved_keys": snapshot["reserved_keys"]}}
    fixed = None
    phases = [phase for phase in config["target_phases"] if phase < 10]
    if phases:
        import table32_corpus
        import table32_labels

        corpus = args.fixed_opening_corpus.resolve(strict=True)
        labels = args.fixed_opening_labels.resolve(strict=True)
        st.require(all(parent != root and parent not in root.parents and root not in parent.parents
                       for parent in (corpus, labels)), "training root overlaps fixed input")
        excluded = []
        if snapshot["reserved_keys"]:
            excluded = sorted(set(table32_corpus.find_position_ids(corpus, snapshot["reserved_keys"]).values()))
        fixed = {"corpus": str(corpus), "labels": str(labels), "phases": phases, "excluded_ids": excluded,
                 "identity": table32_labels.dataset_identity(corpus, labels, phases,
                     limit_per_phase=config["data_0058"]["fixed_limit_per_phase"], exclude_ids=excluded,
                     verify_scores=True)}
    prefix = config.get("generation_prefix")
    games = [] if prefix is None else inputs.generation_plan(
        seed, *(config[f"{split}_per_prefix"] for split in SPLITS), prefix_lengths=(prefix,))
    limits = {**st.LIMITS, "wall_seconds": args.max_wall_seconds,
              "producer_rss_kib": args.producer_rss_kib, "child_rss_kib": args.child_rss_kib,
              "training_steps_per_phase": config["max_steps"], "export_proposals_per_phase": config["max_proposals"]}
    st.require(all(type(value) is int and value > 0 for value in limits.values()),
               "invalid explicit resource budget")
    limits.update(games=len(games), early_labels=0, preflight_decisions=0, oracle_queries=0, matches=0)
    manifest = {"version": st.VERSION, "score_contract": training.SCORE_CONTRACT,
                "producer_commit": producer, "sources": sources, "seed": seed,
                "catalog_digest": model.CATALOG_DIGEST, "baseline": baseline,
                "candidate_executable": candidate, "candidate_source_commit": candidate_commit,
                "historical": {"policy": "0058-explicit-exposure-v1", "files": pins},
                "fixed_openings": fixed, "settings": config, "limits": limits,
                "generation_plan": games, "input_kind": "production",
                "snapshot_digest": st.digest(snapshot),
                "acceptance_reservation": "reserved" if snapshot["reserved_keys"] else "not-yet-selected",
                "production_authorized": False}
    root.mkdir(parents=True, exist_ok=False)
    st.atomic(root / "snapshot.json", snapshot, once=True)
    st.atomic(root / "manifest.json", manifest, once=True)
    st.atomic(root / "prepare.receipt.json", st.seal({"manifest_digest": st.digest(manifest),
              "snapshot_digest": manifest["snapshot_digest"]}), once=True)
    return manifest


def load(root, manifest):
    for name in ("baseline", "candidate_executable"):
        st.check_pin(manifest[name])
    st.require(os.access(manifest["candidate_executable"]["path"], os.X_OK),
               "candidate executable is not executable")
    st.require(manifest["baseline"]["sha256"] == st.BASELINE_SHA, "baseline pin differs")
    snapshot = st.read(root / "snapshot.json")
    st.require(st.digest(snapshot) == manifest["snapshot_digest"]
               and snapshot["reserved_keys"] == manifest["settings"]["data_0058"]["reserved_keys"],
               "snapshot digest or reservation differs")
    for pin in manifest["historical"]["files"]:
        st.check_pin(pin)
    fixed = manifest["fixed_openings"]
    if fixed is not None:
        import table32_labels

        identity = table32_labels.dataset_identity(fixed["corpus"], fixed["labels"], fixed["phases"],
                       limit_per_phase=manifest["settings"]["data_0058"]["fixed_limit_per_phase"],
                       exclude_ids=fixed["excluded_ids"])
        st.require(identity == fixed["identity"], "fixed label input changed; use a new root")
    return snapshot


def labeled_row(record):
    from table32_corpus import decode_position

    board, side = decode_position(record)
    st.require(inputs.phase(board) == record["phase"] and type(record["score"]) is int
               and -64 <= record["score"] <= 64, "invalid fixed opening record")
    return {"id": record["id"], "game_id": None, "split": "train", "prefix_length": None,
            "board": board, "side": side, "phase": record["phase"], "target": record["score"],
            "source_kind": FIXED_SOURCE, "score_contract": training.SCORE_CONTRACT,
            "canonical_key": inputs.position_key(board, side)}


def fixed_rows(manifest):
    fixed = manifest.get("fixed_openings")
    if fixed is None:
        return
    import table32_labels

    yield from map(labeled_row, table32_labels.iter_labeled(fixed["corpus"], fixed["labels"], fixed["phases"],
                       limit_per_phase=manifest["settings"]["data_0058"]["fixed_limit_per_phase"],
                       exclude_ids=fixed["excluded_ids"]))
