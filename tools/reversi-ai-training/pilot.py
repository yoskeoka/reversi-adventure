#!/usr/bin/env python3
"""Prepare, run, or replay the bounded legal Black-start training pilot.

Real runs are human-operated. The execute command performs preparation, the
bounded run, and offline replay in one invocation. Verification only reads
saved evidence and never starts the candidate or an Oracle process.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import random
import sys
import time
from functools import lru_cache
from pathlib import Path

import reinforcement as rf
import training

ORACLE_PATH = Path(__file__).resolve().parents[1] / "reversi-ai-oracle" / "oracle.py"
SPEC = importlib.util.spec_from_file_location("pilot_oracle", ORACLE_PATH)
assert SPEC and SPEC.loader
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)

VERSION = "reversi-ai-training-method-pilot-v1"
BUNDLE_VERSION = "reversi-ai-training-method-pilot-v2"
DENOMINATORS = {"self_play_games": 64, "teacher_rows": 7680, "comparison_games": 200}
CAPS = {key: value // 10 for key, value in DENOMINATORS.items()}
UPDATE = {"name": "bounded_td_v1", "normalization_divisor": 64}
RULE = {"primary": "lower-held-out-mse", "validation_max_ratio": [11, 10],
        "corpus_regret_max_ratio": [11, 10], "minimum_match_points": 10}
OUTPUTS = ("games.jsonl", "teachers.jsonl", "candidate-artifact.json",
           "corpus-decisions.jsonl", "report.json")
SOURCE_PATHS = {"pilot.py": Path(__file__), "training.py": Path(training.__file__),
                "reinforcement.py": Path(rf.__file__), "oracle.py": ORACLE_PATH}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise training.TrainingError(message)


def sources() -> dict:
    return {name: training.sha256_file(path) for name, path in SOURCE_PATHS.items()}


def blob(value: object) -> bytes:
    return training.canonical_json(value) + b"\n"


def same(value: object, expected: object) -> bool:
    """Compare frozen JSON contracts without Python's bool/int/float coercion."""
    return training.canonical_json(value) == training.canonical_json(expected)


def lines(rows: list[dict]) -> bytes:
    return b"".join(blob(row) for row in rows)


def entry(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": training.sha256_file(path)}


@lru_cache(maxsize=4096)
def key(board: str, side: str) -> str:
    return training.canonical_position_key(board, side)


def reserved_keys(path: Path) -> set[str]:
    value = rf.require_keys(training.read_json(path), {"schema_version", "position_keys"}, "reserved openings")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1,
            "unsupported reserved opening schema")
    values = value["position_keys"]
    require(isinstance(values, list) and bool(values), "reserved opening keys must be nonempty")
    for position in values:
        require(isinstance(position, str) and len(position) == 66 and position[64] == ":"
                and position[65] in ("B", "W") and all(cell in "BW." for cell in position[:64]),
                "invalid reserved opening key")
        require(position == key(position[:64], position[65]), "reserved opening key is not canonical")
    require(len(set(values)) == len(values), "duplicate reserved opening key")
    return set(values)


def independent_rows(path: Path, split: str, provenance: dict | None = None) -> tuple[list[dict], dict]:
    raw = training.read_jsonl(path)
    require(bool(raw), f"empty {split} input")
    provenance = provenance or {name: raw[0].get(name) for name in ("source", "license", "source_digest")}
    require(set(provenance) == {"source", "license", "source_digest"}
            and all(isinstance(value, str) and value for value in provenance.values()),
            f"invalid {split} provenance")
    result, ids = [], set()
    for row in raw:
        require(type(row.get("schema_version")) is int and row.get("schema_version") == 2 and row.get("score_contract") == training.SCORE_CONTRACT
                and row.get("split") == split and isinstance(row.get("record_id"), str)
                and bool(row["record_id"]), f"invalid {split} record identity")
        require(row["record_id"] not in ids, f"duplicate {split} record id")
        ids.add(row["record_id"])
        require(all(row.get(name) == value for name, value in provenance.items()), f"{split} provenance mismatch")
        board, side, target = training.parse_position(row, f"{split} {row['record_id']}")
        result.append({"id": row["record_id"], "board": board, "side": side, "target": target})
    return result, provenance


def corpus_inputs(corpus_path: Path, golden_path: Path) -> tuple[list[dict], list[dict]]:
    records, golden = oracle.load_jsonl(corpus_path), oracle.load_jsonl(golden_path)
    require(all(type(row.get("schema_version")) is int and row["schema_version"] == 1 for row in records),
            "unsupported Oracle position schema")
    oracle.validate_corpus(records)
    oracle.verify_saved_golden(records, golden)
    require(bool(records), "empty Oracle corpus")
    require(len({key(row["board"], row["side_to_move"]) for row in records}) == len(records),
            "duplicate Oracle corpus position")
    require(len({training.digest(row["profile"]) for row in golden}) == 1, "mixed Oracle corpus profiles")
    return records, golden


def replay_opening(moves: list[str]) -> tuple[str, str]:
    require(isinstance(moves, list), "opening must be a move list")
    board, side = rf.INITIAL, "B"
    for move in moves:
        legal = rf.legal_moves(board, side)
        if not legal:
            side = rf.other(side)
            legal = rf.legal_moves(board, side)
        require(bool(legal) and move in legal, "illegal Black-start opening")
        board, side = rf.apply_move(board, side, move), rf.other(side)
    return board, side


def opening_pool(seed: int, plies: int, count: int, forbidden: set[str], domain: str,
                 reserved: set[str] | None = None) -> list[dict]:
    # Separate random collection streams; never invert the board's colors.
    domain_seed = int(training.digest({"version": VERSION, "seed": seed, "domain": domain})[:16], 16)
    rng, result, seen = random.Random(domain_seed), [], set(forbidden)
    for _ in range(10000):
        board, side, moves, crosses_reserved = rf.INITIAL, "B", [], False
        for _ in range(plies):
            legal = rf.legal_moves(board, side)
            if not legal:
                side = rf.other(side)
                legal = rf.legal_moves(board, side)
            require(bool(legal), "random opening ended before requested plies")
            move = legal[rng.randrange(len(legal))]
            moves.append(move)
            board, side = rf.apply_move(board, side, move), rf.other(side)
            crosses_reserved |= key(board, side) in (reserved or set())
        position = key(board, side)
        if position in seen or crosses_reserved:
            continue
        seen.add(position)
        result.append({"board": board, "side": side, "moves": moves})
        if len(result) == count:
            return result
    raise training.TrainingError("cannot collect complete disjoint opening set within attempt cap")


def config(depth: int, time_limit: int, node_limit: int) -> dict:
    return {"opening_depth": depth, "midgame_depth": depth, "endgame_depth": depth,
            "exact_solver_empty_squares": 16, "time_limit_ms": time_limit, "node_limit": node_limit}


class GuardedCandidate(rf.Candidate):
    """Refuse a reserved acceptance-suite root before sending a CLI request."""

    def __init__(self, executable: Path, artifact: Path, setting: dict, timeout: int, reserved: set[str]):
        self.reserved = reserved
        super().__init__(executable, artifact, setting, timeout)

    def choose(self, identifier: str, board: str, side: str) -> str:
        require(key(board, side) not in self.reserved, "pilot visited a reserved 0018 position")
        return super().choose(identifier, board, side)


def bundle_evidence(manifest: dict, parent: Path) -> dict | None:
    """Derive eligibility from saved producers again, never from caller context."""
    if manifest["schema_version"] == 1:
        return None
    import input_bundle
    inputs = manifest["inputs"]
    bundle_path = rf.checked_file(parent, inputs["input_bundle"], "input bundle")
    executable = rf.checked_file(parent, inputs["candidate_executable"], "candidate executable")
    receipt_path = rf.checked_file(parent, inputs["bundle_verification_receipt"], "bundle verification receipt")
    verified = input_bundle.verify_for_pilot(bundle_path, receipt_path, candidate_executable=executable)
    require(same(verified, manifest["bundle_verification"]), "pilot bundle verification differs from replay")
    for name in ("baseline_artifact", "baseline_manifest", "validation", "held_out", "corpus", "golden"):
        pinned = {field: inputs[name][field] for field in ("path", "sha256")}
        require(same(pinned, verified["inputs"][name]), f"pilot {name} differs from verified bundle")
        rf.checked_file(parent, pinned, name)
    require(same(manifest["acceptance_reservation"], verified["acceptance_reservation"]),
            "pilot acceptance reservation differs from bundle")
    require(manifest["input_kind"] == ("production" if verified["input_kind"] == "production" else "fixture"),
            "pilot input kind differs from verified bundle")
    require(type(verified["strength_inputs"]) is bool, "invalid bundle eligibility")
    return verified


def exposure_keys(manifest: dict, games: list[dict], decisions: list[dict]) -> dict:
    kinds = {"opening": {key(rf.INITIAL, "B")}, "decision": set(), "terminal": set()}
    for name in ("self_play_openings", "comparison_openings"):
        for opening in manifest[name]:
            for count in range(1, len(opening["moves"]) + 1):
                board, side = replay_opening(opening["moves"][:count])
                kinds["opening"].add(key(board, side))
    for game in games:
        kinds["decision"].update(key(row["board"], row["side"]) for row in game["decisions"])
        kinds["terminal"].update(key(game["terminal_board"], side) for side in ("B", "W"))
    kinds["decision"].update(key(row["board"], row["side"]) for row in decisions)
    return {name: sorted(values) for name, values in kinds.items()}


def load_manifest(path: Path) -> dict:
    manifest = training.read_json(path)
    extra = {"bundle_verification", "acceptance_reservation"} if manifest.get("schema_version") == 2 else set()
    rf.require_keys(manifest, {"schema_version", "producer_version", "score_contract", "sources", "inputs",
                    "input_kind", "seed", "opening_plies", "denominators", "cap_rule", "caps", "actual_openings",
                    "self_play_search", "comparison_search", "decision_timeout_seconds", "max_decisions",
                    "exact_cache_policy", "reset_protocol", "teacher", "update_rule", "update_count",
                    "improvement_rule", "self_play_openings", "comparison_openings", "oracle_profile",
                    "oracle_version", "oracle_source_sha256"} | extra, "pilot manifest")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] in (1, 2)
            and manifest["producer_version"] == (VERSION if manifest["schema_version"] == 1 else BUNDLE_VERSION)
            and manifest["score_contract"] == training.SCORE_CONTRACT, "unsupported pilot manifest")
    require(manifest["sources"] == sources(), "pilot producer source digest mismatch")
    require(same(manifest["denominators"], DENOMINATORS) and manifest["cap_rule"] == "floor-divide-by-ten"
            and same(manifest["caps"], CAPS) and same(manifest["actual_openings"], {"self_play_games": 6, "comparison_pairs": 10}),
            "pilot denominators or caps mismatch")
    require(manifest["input_kind"] in ("fixture", "production"), "invalid input kind")
    training.require_int(manifest["seed"], "seed", 0, 2**64 - 1)
    training.require_int(manifest["opening_plies"], "opening plies", 4, 20)
    require(same(manifest["update_rule"], UPDATE) and type(manifest["update_count"]) is int
            and manifest["update_count"] == 1 and same(manifest["improvement_rule"], RULE),
            "pilot update or improvement rule mismatch")
    require(manifest["teacher"] == "completed-project-ai-terminal-winner-empty-for-side"
            and manifest["exact_cache_policy"] == "turn" and manifest["reset_protocol"] == rf.RESET_PROTOCOL,
            "pilot teacher or cache/reset contract mismatch")
    for name, depth in (("self_play_search", 8), ("comparison_search", 12)):
        setting = rf.require_keys(manifest[name], set(config(depth, 1, 1)), name)
        training.require_int(setting["time_limit_ms"], "time limit", 1)
        training.require_int(setting["node_limit"], "node limit", 1)
        require(same(setting, config(depth, setting["time_limit_ms"], setting["node_limit"])), "pilot search profile mismatch")
    require(manifest["self_play_search"]["time_limit_ms"] == manifest["comparison_search"]["time_limit_ms"]
            and manifest["self_play_search"]["node_limit"] == manifest["comparison_search"]["node_limit"],
            "pilot resource limits differ")
    timeout = training.require_int(manifest["decision_timeout_seconds"], "decision timeout", 1, 3600)
    require(timeout * 1000 > manifest["comparison_search"]["time_limit_ms"], "timeout must exceed search time limit")
    require(type(manifest["max_decisions"]) is int and manifest["max_decisions"] == 26 * 120,
            "pilot decision cap mismatch")
    reservation_input = "reserved_openings" if manifest["schema_version"] == 1 else "input_bundle"
    receipt_inputs = {"bundle_verification_receipt"} if manifest["schema_version"] == 2 else set()
    inputs = rf.require_keys(manifest["inputs"], {"baseline_artifact", "baseline_manifest", "candidate_executable",
                    "validation", "held_out", reservation_input, "corpus", "golden"} | receipt_inputs, "pilot inputs")
    paths = {}
    for name, item in inputs.items():
        if name in ("validation", "held_out"):
            rf.require_keys(item, {"path", "sha256", "provenance"}, name)
        else:
            rf.require_keys(item, {"path", "sha256"}, name)
        paths[name] = rf.checked_file(path.parent, {field: item[field] for field in ("path", "sha256")}, name)
    verified = bundle_evidence(manifest, path.parent)
    base_manifest = training.read_json(paths["baseline_manifest"])
    loaded = training.validate_manifest(base_manifest, paths["baseline_manifest"].parent)
    base_records = training.validate_records(loaded)
    baseline = training.read_json(paths["baseline_artifact"])
    training.validate_artifact(baseline)
    require(baseline["provenance"]["input_manifest_digest"] == training.digest(base_manifest),
            "baseline trainer manifest identity mismatch")
    require(same(baseline, training.artifact_from(base_manifest, base_records, training.digest(base_manifest))),
            "baseline artifact does not reproduce from its trainer inputs")
    baseline_keys = {key(row["board"], row["side"]) for row in base_records if row["split"] == "train"}
    validation, _ = independent_rows(paths["validation"], "validation", inputs["validation"]["provenance"])
    held_out, _ = independent_rows(paths["held_out"], "held_out", inputs["held_out"]["provenance"])
    reserved = (reserved_keys(paths["reserved_openings"]) if verified is None
                else set(verified["acceptance_reservation"]["keys"]))
    records, golden = corpus_inputs(paths["corpus"], paths["golden"])
    require(same(manifest["oracle_profile"], golden[0]["profile"]) and manifest["oracle_version"] == oracle.ORACLE_VERSION
            and manifest["oracle_source_sha256"] == oracle.SOURCE_SHA256, "pilot Oracle identity mismatch")
    corpus_keys = {key(row["board"], row["side_to_move"]) for row in records}
    if verified is not None:
        corpus_keys |= set(verified["exposure_keys"]["oracle_child"])
    forbidden = baseline_keys | reserved | corpus_keys | {key(row["board"], row["side"]) for row in validation + held_out}
    expected_self = opening_pool(manifest["seed"], manifest["opening_plies"], 6, forbidden, "self-play", reserved)
    expected_match = opening_pool(manifest["seed"], manifest["opening_plies"], 10,
            forbidden | {key(row["board"], row["side"]) for row in expected_self}, "comparison", reserved)
    require(same(manifest["self_play_openings"], expected_self) and same(manifest["comparison_openings"], expected_match),
            "frozen legal opening set mismatch")
    # Eligibility is recomputed from producer evidence; labels cannot grant it.
    return {"manifest": manifest, "paths": paths, "baseline": baseline, "baseline_keys": baseline_keys,
            "validation": validation, "held_out": held_out, "reserved": reserved, "corpus": records,
            "golden": golden, "corpus_keys": corpus_keys, "manifest_parent": path.parent,
            "tooling_only": verified is None or not verified["strength_inputs"]}


def prepare(args: argparse.Namespace) -> None:
    require(not args.manifest.exists(), "frozen pilot manifest already exists")
    training.require_int(args.seed, "seed", 0, 2**64 - 1)
    training.require_int(args.opening_plies, "opening plies", 4, 20)
    bundle_path = getattr(args, "input_bundle", None)
    verified = None
    if bundle_path is not None:
        require(getattr(args, "bundle_verification_receipt", None) is not None,
                "input bundle requires a completed bundle verification receipt")
        import input_bundle
        verified = input_bundle.verify_for_pilot(bundle_path, args.bundle_verification_receipt,
                                                  candidate_executable=args.candidate_executable)
        for name in ("baseline_artifact", "baseline_manifest", "corpus", "golden"):
            setattr(args, name, Path(verified["inputs"][name]["path"]))
        args.validation_input = Path(verified["inputs"]["validation"]["path"])
        args.held_out_input = Path(verified["inputs"]["held_out"]["path"])
        args.input_kind = "production" if verified["input_kind"] == "production" else "fixture"
    else:
        require(all(getattr(args, name, None) is not None for name in (
            "baseline_artifact", "baseline_manifest", "validation_input", "held_out_input",
            "reserved_openings", "corpus", "golden")), "legacy prepare requires all input paths")
    inputs = {name: entry(getattr(args, name)) for name in ("baseline_artifact", "baseline_manifest",
            "candidate_executable", "corpus", "golden")}
    inputs["reserved_openings" if verified is None else "input_bundle"] = entry(
        args.reserved_openings if verified is None else bundle_path)
    if verified is not None:
        inputs["bundle_verification_receipt"] = entry(args.bundle_verification_receipt)
    validation, vp = independent_rows(args.validation_input, "validation")
    held_out, hp = independent_rows(args.held_out_input, "held_out")
    inputs["validation"] = {**entry(args.validation_input), "provenance": vp}
    inputs["held_out"] = {**entry(args.held_out_input), "provenance": hp}
    base_manifest = training.read_json(args.baseline_manifest)
    base_records = training.validate_records(training.validate_manifest(base_manifest, args.baseline_manifest.parent))
    reserved = (reserved_keys(args.reserved_openings) if verified is None
                else set(verified["acceptance_reservation"]["keys"]))
    corpus, golden = corpus_inputs(args.corpus, args.golden)
    forbidden = reserved | {key(row["board"], row["side_to_move"]) for row in corpus}
    if verified is not None:
        forbidden |= set(verified["exposure_keys"]["oracle_child"])
    forbidden |= {key(row["board"], row["side"]) for row in base_records if row["split"] == "train"}
    forbidden |= {key(row["board"], row["side"]) for row in validation + held_out}
    own = opening_pool(args.seed, args.opening_plies, 6, forbidden, "self-play", reserved)
    matches = opening_pool(args.seed, args.opening_plies, 10,
                          forbidden | {key(row["board"], row["side"]) for row in own}, "comparison", reserved)
    manifest = {"schema_version": 1, "producer_version": VERSION, "score_contract": training.SCORE_CONTRACT,
        "sources": sources(), "inputs": inputs, "input_kind": args.input_kind,
        "seed": args.seed, "opening_plies": args.opening_plies, "denominators": DENOMINATORS,
        "cap_rule": "floor-divide-by-ten", "caps": CAPS, "actual_openings": {"self_play_games": 6, "comparison_pairs": 10},
        "self_play_search": config(8, args.time_limit_ms, args.node_limit),
        "comparison_search": config(12, args.time_limit_ms, args.node_limit),
        "decision_timeout_seconds": args.decision_timeout_seconds, "max_decisions": 26 * 120,
        "exact_cache_policy": "turn", "reset_protocol": rf.RESET_PROTOCOL,
        "teacher": "completed-project-ai-terminal-winner-empty-for-side", "update_rule": UPDATE, "update_count": 1,
        "improvement_rule": RULE, "self_play_openings": own, "comparison_openings": matches,
        "oracle_profile": golden[0]["profile"], "oracle_version": oracle.ORACLE_VERSION,
        "oracle_source_sha256": oracle.SOURCE_SHA256}
    if verified is not None:
        manifest.update(schema_version=2, producer_version=BUNDLE_VERSION, bundle_verification=verified,
                        acceptance_reservation=verified["acceptance_reservation"])
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_bytes(blob(manifest))
    try:
        load_manifest(args.manifest)
        # One reset is a bounded protocol/artifact acceptance probe, not a game.
        player = rf.Candidate(args.candidate_executable.resolve(), args.baseline_artifact.resolve(),
                              manifest["comparison_search"], manifest["decision_timeout_seconds"])
        try:
            player.new_game("pilot-prepare-artifact-probe")
        finally:
            player.close()
    except BaseException:
        args.manifest.unlink()
        raise


def checked_games(context: dict, games: list[dict], *, complete: bool = True) -> tuple[list[dict], set[str], list[str]]:
    manifest = context["manifest"]
    require(len(games) <= 26 and (not complete or len(games) == 26), "incomplete or excessive pilot game set")
    teachers, played, excluded, seen = [], set(), [], set()
    forbidden = context["baseline_keys"] | context["reserved"] | context["corpus_keys"]
    forbidden |= {key(row["board"], row["side"]) for row in manifest["comparison_openings"]}
    for index, game in enumerate(games):
        self_play = index < 6
        kind, pair, member = ("self-play", index, 0) if self_play else ("candidate-match", (index - 6) // 2, (index - 6) % 2)
        opening = manifest["self_play_openings" if self_play else "comparison_openings"][pair]
        players = {"B": "baseline", "W": "baseline"} if self_play else (
                {"B": "candidate", "W": "baseline"} if member == 0 else {"B": "baseline", "W": "candidate"})
        require(isinstance(game, dict), "pilot game must be an object")
        rf.require_keys(game, {"schema_version", "score_contract", "kind", "pair", "member", "players", "opening",
            "rotation", "cache_lifetime", "reset_protocol", "reset_events", "start_board", "start_side", "decisions",
            "terminal_board", "disc_counts", "final_score_black", "failure", "game_digest"}, "pilot game")
        require(game["kind"] == kind and type(game["pair"]) is int and game["pair"] == pair
                and type(game["member"]) is int and game["member"] == member and game["players"] == players
                and type(game["rotation"]) is int and game["rotation"] == 0 and game["failure"] is None,
                "pilot pair or player identity mismatch")
        require(type(game["final_score_black"]) is int and isinstance(game["disc_counts"], dict)
                and all(type(count) is int for count in game["disc_counts"].values()), "pilot terminal score type mismatch")
        require(game["opening"] == opening["moves"] and replay_opening(game["opening"]) == (game["start_board"], game["start_side"])
                and (game["start_board"], game["start_side"]) == (opening["board"], opening["side"]), "pilot legal start mismatch")
        require(isinstance(game["decisions"], list) and len(game["decisions"]) <= 120, "pilot game turn cap exceeded")
        for turn, decision in enumerate(game["decisions"]):
            rf.require_keys(decision, {"id", "board", "side", "move"}, "pilot decision")
            require(decision["id"] == f"{kind}-p{pair}-m{member}-t{turn}", "pilot decision identity mismatch")
            require(key(decision["board"], decision["side"]) not in context["reserved"],
                    "pilot visited a reserved 0018 position")
        tuning = rf.replay(game)
        for side in ("B", "W"):
            terminal_key = key(game["terminal_board"], side)
            require(terminal_key not in context["reserved"], "pilot terminal board is a reserved 0018 position")
            played.add(terminal_key)
        for turn, row in enumerate(tuning):
            position = key(row["board"], row["side"])
            played.add(position)
            if not self_play:
                continue
            identifier = game["decisions"][turn]["id"]
            if position in forbidden or position in seen:
                excluded.append(identifier)
                continue
            seen.add(position)
            teachers.append({"id": identifier, **row})
    require(len(teachers) <= CAPS["teacher_rows"], "pilot teacher row cap exceeded after deduplication")
    require(bool(teachers) or not complete, "pilot has no usable teacher rows")
    require(sum(len(game["decisions"]) for game in games) <= manifest["max_decisions"], "pilot decision cap exceeded")
    # Reserve the initial state and opening roots as well as every played decision.
    played.add(key(rf.INITIAL, "B"))
    for name in ("self_play_openings", "comparison_openings"):
        for opening in manifest[name]:
            for count in range(1, len(opening["moves"]) + 1):
                board, side = replay_opening(opening["moves"][:count])
                played.add(key(board, side))
    return teachers, played, excluded


def metric_rows(context: dict, played: set[str]) -> tuple[dict, dict]:
    forbidden = played | context["baseline_keys"] | context["reserved"] | context["corpus_keys"]
    selected, excluded = {}, {}
    seen = set(forbidden)
    for split in ("validation", "held_out"):
        selected[split], excluded[split] = [], []
        for row in context[split]:
            position = key(row["board"], row["side"])
            if position in seen:
                excluded[split].append(row["id"])
            else:
                seen.add(position)
                selected[split].append(row)
        require(bool(selected[split]), f"empty independent {split} metric after exclusions")
    return selected, excluded


def independent_corpus(context: dict, played: set[str]) -> tuple[list[dict], list[dict], list[str]]:
    forbidden = context["baseline_keys"] | context["reserved"] | played
    records, golden, excluded = [], [], []
    for row, saved in zip(context["corpus"], context["golden"]):
        if key(row["board"], row["side_to_move"]) in forbidden:
            excluded.append(row["position_id"])
        else:
            records.append(row)
            golden.append(saved)
    require(any(row["legal_moves"] for row in records), "empty independent decision-bearing corpus after exclusions")
    return records, golden, excluded


def corpus_metrics(context: dict, decisions: list[dict], played: set[str]) -> dict:
    records, saved, excluded = independent_corpus(context, played)
    require(len(decisions) == len(records) * 2, "incomplete corpus decisions")
    sums = {"baseline": 0, "candidate": 0}
    for index, decision in enumerate(decisions):
        row = records[index // 2]
        player = "baseline" if index % 2 == 0 else "candidate"
        rf.require_keys(decision, {"position_id", "board", "side", "player", "move"}, "corpus decision")
        require(decision["position_id"] == row["position_id"] and decision["board"] == row["board"]
                and decision["side"] == row["side_to_move"] and decision["player"] == player,
                "corpus decision identity mismatch")
        legal = row["legal_moves"]
        require(decision["move"] in legal if legal else decision["move"] == "pass", "illegal corpus decision")
        golden = saved[index // 2]["analysis"]
        values = {item["move"]: item["value"] for item in golden["evaluations"]}
        regret = golden["best_value"] - values[decision["move"]] if legal else 0
        sums[player] += regret
    count = len(records)
    return {**{player: {"positions": count, "sum_regret": total, "mean_regret": total / count} for player, total in sums.items()},
            "excluded_ids": excluded}


def reconstruct(context: dict, games: list[dict], decisions: list[dict]) -> dict[str, bytes]:
    manifest, baseline = context["manifest"], context["baseline"]
    verified = bundle_evidence(manifest, context.get("manifest_parent", Path(".")))
    strength_inputs = verified is not None and verified["strength_inputs"]
    teachers, played, excluded_teachers = checked_games(context, games)
    candidate = rf.updated_artifact(baseline, teachers, manifest)
    training.validate_artifact(candidate)
    rows, excluded = metric_rows(context, played)
    metrics = {split: {"baseline": rf.mse(baseline, records), "candidate": rf.mse(candidate, records),
                       "excluded_ids": excluded[split], "position_keys": sorted(key(row["board"], row["side"]) for row in records)}
               for split, records in rows.items()}
    regret, match = corpus_metrics(context, decisions, played), rf.match_summary(games[6:])
    # Integer comparisons preserve the predeclared 10% rule exactly.
    validation = metrics["validation"]
    held_out = metrics["held_out"]
    checks = {"held_out_improved": held_out["candidate"]["sum_squared_error"] < held_out["baseline"]["sum_squared_error"],
        "validation_not_materially_worse": validation["candidate"]["sum_squared_error"] * 10 <= validation["baseline"]["sum_squared_error"] * 11,
        "corpus_not_materially_worse": regret["candidate"]["sum_regret"] * 10 <= regret["baseline"]["sum_regret"] * 11,
        "match_points_sufficient": match["match_points"] >= 10,
        "strength_inputs": strength_inputs}
    blobs = {"games.jsonl": lines(games), "teachers.jsonl": lines(teachers),
             "candidate-artifact.json": blob(candidate), "corpus-decisions.jsonl": lines(decisions)}
    report = {"schema_version": 1, "producer_version": VERSION, "score_contract": training.SCORE_CONTRACT,
        "manifest_digest": training.digest(manifest), "input_digests": {name: item["sha256"] for name, item in manifest["inputs"].items()},
        "baseline_artifact_digest": baseline["artifact_digest"], "candidate_artifact_digest": candidate["artifact_digest"],
        "denominators": DENOMINATORS, "cap_rule": manifest["cap_rule"], "caps": CAPS,
        "actual_counts": {"self_play_games": 6, "teacher_rows": len(teachers), "comparison_games": 20,
                          "comparison_pairs": 10, "corpus_positions": regret["baseline"]["positions"],
                          "decisions": sum(len(game["decisions"]) for game in games)},
        "teacher_excluded_ids": excluded_teachers, "independent_metrics": metrics, "corpus_regret": regret,
        "match": match, "improvement_checks": checks, "tooling_only": not strength_inputs,
        "improvement_observed": all(checks.values()), "production_authorized": False,
        "game_digests": [game["game_digest"] for game in games],
        "outputs": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(blobs.items())}}
    if verified is not None:
        report.update(schema_version=2, producer_version=BUNDLE_VERSION, bundle_verification=verified,
                      acceptance_reservation=manifest["acceptance_reservation"],
                      exposure_keys=exposure_keys(manifest, games, decisions))
    report["report_digest"] = training.digest(report)
    blobs["report.json"] = blob(report)
    return blobs


def run(manifest_path: Path, output: Path, progress_every: int = 1) -> None:
    progress = rf.Progress(progress_every)
    stage = progress.stage_start("pilot-loading")
    context = load_manifest(manifest_path)
    require(not output.exists() or not any(output.iterdir()), "pilot output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    manifest = context["manifest"]
    progress.stage_done("pilot-loading", stage)
    games, decisions, remaining = [], [], [manifest["max_decisions"]]
    paths = context["paths"]
    stage = progress.stage_start("pilot-self-play")
    player = GuardedCandidate(paths["candidate_executable"], paths["baseline_artifact"], manifest["self_play_search"],
                              manifest["decision_timeout_seconds"], context["reserved"])
    try:
        for index, opening in enumerate(manifest["self_play_openings"]):
            started = time.monotonic()
            game = rf.play("self-play", index, 0, opening["board"], opening["side"], opening["moves"], 0,
                           {"baseline": player}, {"B": "baseline", "W": "baseline"}, remaining)
            games.append(game)
            rf.atomic_write(output, "games.jsonl", lines(games))
            progress.game("self-play", index, 0, index + 1, 6, started)
    finally:
        player.close()
    progress.stage_done("pilot-self-play", stage)
    stage = progress.stage_start("pilot-teacher-extraction")
    teachers, _, _ = checked_games(context, games, complete=False)
    require(bool(teachers), "pilot has no usable teacher rows")
    rf.atomic_write(output, "teachers.jsonl", lines(teachers))
    progress.stage_done("pilot-teacher-extraction", stage)
    stage = progress.stage_start("pilot-update")
    candidate = rf.updated_artifact(context["baseline"], teachers, manifest)
    training.validate_artifact(candidate)
    artifact_path = output / "candidate-artifact.json"
    rf.atomic_write(output, artifact_path.name, blob(candidate))
    progress.stage_done("pilot-update", stage)
    players = {}
    try:
        for name, artifact in (("baseline", paths["baseline_artifact"]), ("candidate", artifact_path)):
            players[name] = GuardedCandidate(paths["candidate_executable"], artifact, manifest["comparison_search"],
                                            manifest["decision_timeout_seconds"], context["reserved"])
        stage = progress.stage_start("pilot-comparison")
        for pair, opening in enumerate(manifest["comparison_openings"]):
            for member in (0, 1):
                started = time.monotonic()
                seats = {"B": "candidate", "W": "baseline"} if member == 0 else {"B": "baseline", "W": "candidate"}
                game = rf.play("candidate-match", pair, member, opening["board"], opening["side"], opening["moves"], 0,
                               players, seats, remaining)
                games.append(game)
                rf.atomic_write(output, "games.jsonl", lines(games))
                progress.game("candidate-match", pair, member, len(games) - 6, 20, started)
        progress.stage_done("pilot-comparison", stage)
        stage = progress.stage_start("pilot-corpus")
        _, played, _ = checked_games(context, games)
        records, _, _ = independent_corpus(context, played)
        total = len(records) * 2
        for index, row in enumerate(records):
            for member, name in enumerate(("baseline", "candidate")):
                started = time.monotonic()
                identifier = f"pilot-corpus-{index}-{name}"
                players[name].new_game(identifier)
                move = players[name].choose(identifier, row["board"], row["side_to_move"])
                decisions.append({"position_id": row["position_id"], "board": row["board"], "side": row["side_to_move"],
                                  "player": name, "move": move})
                rf.atomic_write(output, "corpus-decisions.jsonl", lines(decisions))
                progress.game("corpus", index, member, len(decisions), total, started)
        corpus_metrics(context, decisions, played)
        progress.stage_done("pilot-corpus", stage)
    finally:
        for player in players.values():
            player.close()
    stage = progress.stage_start("pilot-independent-metrics")
    blobs = reconstruct(context, games, decisions)
    progress.stage_done("pilot-independent-metrics", stage)
    stage = progress.stage_start("pilot-publication")
    for name in OUTPUTS:  # The report is deliberately published last.
        rf.atomic_write(output, name, blobs[name])
    progress.stage_done("pilot-publication", stage)


def verify(manifest_path: Path, output: Path, progress_every: int = 1) -> dict:
    progress = rf.Progress(progress_every)
    stage = progress.stage_start("pilot-offline-verification")
    context = load_manifest(manifest_path)
    require(output.is_dir() and {path.name for path in output.iterdir()} == set(OUTPUTS), "missing or extra pilot outputs")
    games = training.read_jsonl(output / "games.jsonl")
    decisions = training.read_jsonl(output / "corpus-decisions.jsonl")
    expected = reconstruct(context, games, decisions)
    for name, data in expected.items():
        require((output / name).read_bytes() == data, f"pilot {name} differs from replay")
    progress.stage_done("pilot-offline-verification", stage)
    return training.read_json(output / "report.json")


def execute(args: argparse.Namespace) -> dict:
    if args.oracle_match_games > 0:
        import production_cycle
        return production_cycle.execute(args)
    require(args.self_play_games == 6 and args.baseline_comparison_games == 20
            and args.resume_from is None,
            "the bounded pilot execute path requires 6/20/0 counts and no phase resume")
    run_root = args.run_root.resolve()
    repository_root = Path(__file__).resolve().parents[2]
    require(args.run_root.is_absolute(), "pilot run root must be an absolute path")
    require(repository_root not in run_root.parents and run_root != repository_root,
            "pilot run root must be outside the source checkout")
    require(not run_root.exists(), "pilot run root already exists; use a fresh path")
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise training.TrainingError("pilot run root already exists; use a fresh path") from error

    manifest_path = run_root / "manifest.json"
    output_dir = run_root / "output"
    prepare_args = argparse.Namespace(
        manifest=manifest_path,
        input_bundle=args.input_bundle,
        bundle_verification_receipt=args.bundle_verification_receipt,
        candidate_executable=args.candidate_executable,
        seed=args.seed,
        opening_plies=args.opening_plies,
        time_limit_ms=args.time_limit_ms,
        node_limit=args.node_limit,
        decision_timeout_seconds=args.decision_timeout_seconds,
    )

    progress = rf.Progress(args.progress_every)
    stage = progress.stage_start("pilot-prepare")
    try:
        prepare(prepare_args)
    except BaseException:
        # prepare removes a manifest that fails its final identity/reset probe.
        # Remove only the new, still-empty run root so the user can correct the
        # inputs without leaving a misleading run behind.
        try:
            run_root.rmdir()
        except OSError:
            pass
        raise
    progress.stage_done("pilot-prepare", stage)

    run(manifest_path, output_dir, args.progress_every)
    report = verify(manifest_path, output_dir, args.progress_every)
    print(f"pilot verified report={output_dir / 'report.json'} digest={report['report_digest']}")
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    for name in ("manifest", "baseline-artifact", "baseline-manifest", "candidate-executable", "validation-input",
                 "held-out-input", "reserved-openings", "corpus", "golden", "input-bundle", "bundle-verification-receipt"):
        prep.add_argument("--" + name, type=Path, required=name in ("manifest", "candidate-executable"))
    prep.add_argument("--input-kind", choices=("fixture", "production"), default="production")
    prep.add_argument("--seed", type=int, default=20261014)
    prep.add_argument("--opening-plies", type=int, default=6)
    prep.add_argument("--time-limit-ms", type=int, default=300000)
    prep.add_argument("--node-limit", type=int, default=10000000)
    prep.add_argument("--decision-timeout-seconds", type=int, default=310)
    for name in ("run", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--progress-every", type=rf.positive_interval, default=1)
    execute_command = commands.add_parser("execute")
    execute_command.add_argument("--run-root", type=Path, required=True)
    execute_command.add_argument("--input-bundle", type=Path, required=True)
    execute_command.add_argument("--bundle-verification-receipt", type=Path, required=True)
    execute_command.add_argument("--candidate-executable", type=Path, required=True)
    execute_command.add_argument("--oracle-binary", type=Path)
    execute_command.add_argument("--self-play-games", type=int, required=True)
    execute_command.add_argument("--baseline-comparison-games", type=int, required=True)
    execute_command.add_argument("--oracle-match-games", type=int, required=True)
    execute_command.add_argument("--resume-from", choices=("input-verification", "self-play", "candidate-update",
        "baseline-match", "candidate-selection", "corpus-regret", "oracle-match", "offline-verification"))
    execute_command.add_argument("--seed", type=int, default=20261014)
    execute_command.add_argument("--opening-plies", type=int, default=6)
    execute_command.add_argument("--time-limit-ms", type=int, default=300000)
    execute_command.add_argument("--node-limit", type=int, default=10000000)
    execute_command.add_argument("--decision-timeout-seconds", type=int, default=310)
    execute_command.add_argument("--progress-every", type=rf.positive_interval, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "run":
            run(args.manifest, args.output_dir, args.progress_every)
        elif args.command == "verify":
            verify(args.manifest, args.output_dir, args.progress_every)
        else:
            execute(args)
    except (training.TrainingError, oracle.OracleError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"pilot error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
