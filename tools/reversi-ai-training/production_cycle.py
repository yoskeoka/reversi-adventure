"""Phase-receipted 0019 execution behind the existing pilot execute command."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pilot
import reinforcement as rf
import training

oracle_module = pilot.oracle

PHASES = ("input-verification", "self-play", "candidate-update", "baseline-match",
          "candidate-selection", "corpus-regret", "oracle-match", "offline-verification")
VERSION = "reversi-ai-0019-production-cycle-v2"
UPDATE_RULE = {"name": "bounded_td_v1", "normalization_divisor": 64}
SELF_PLAY_CONFIG = {"opening_depth": 8, "midgame_depth": 8, "endgame_depth": 8,
                    "exact_solver_empty_squares": 16}
MATCH_CONFIG = {"opening_depth": 12, "midgame_depth": 12, "endgame_depth": 12,
                "exact_solver_empty_squares": 16, "evaluator": "trained",
                "book": "off", "exact_cache_scope": "turn"}
ORACLE_PROFILE = oracle_module.ORACLE_0018_ACCEPTANCE_V1


def require(condition: bool, message: str) -> None:
    if not condition:
        raise training.TrainingError(message)


def blob(value: object) -> bytes:
    return training.canonical_json(value) + b"\n"


def file_entry(path: Path) -> dict:
    resolved = path.resolve()
    require(resolved.is_file(), f"required file does not exist: {resolved}")
    return {"path": str(resolved), "sha256": training.sha256_file(resolved)}


def source_commit() -> str:
    repository_root = Path(pilot.__file__).resolve().parents[2]
    result = subprocess.run(["git", "-C", str(repository_root), "rev-parse", "HEAD"],
                            check=True, capture_output=True, text=True)
    commit = result.stdout.strip()
    require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)),
            "could not identify the 0019 source commit")
    status = subprocess.run(["git", "-C", str(repository_root), "status", "--porcelain", "--untracked-files=normal"],
                            check=True, capture_output=True, text=True)
    require(not status.stdout.strip(), "0019 execution requires a clean source checkout")
    return commit


SETTING_KEYS = ("seed", "opening_plies", "requested_counts", "self_play_config",
                "match_config", "decision_timeout_seconds", "max_decisions", "openings")


def settings(manifest: dict) -> dict:
    return {key: copy.deepcopy(manifest[key]) for key in SETTING_KEYS}


def input_identities(manifest: dict) -> dict:
    return {key: manifest[key] for key in ("input_bundle", "bundle_verification_receipt",
            "candidate_executable", "oracle_binary", "inputs", "oracle_profile")}


def validate_provenance(value: dict, phase: str) -> None:
    require(value.get("phase") == phase and value.get("schema_version") == 1,
            "attempt provenance identity mismatch")
    require(isinstance(value.get("execution_commit"), str)
            and re.fullmatch(r"[0-9a-f]{40}", value["execution_commit"]),
            "invalid attempt execution commit")
    require(type(value.get("progress_every", 1)) is int and value.get("progress_every", 1) > 0,
            "invalid attempt progress interval")
    require(value.get("resume_from") is None or value.get("resume_from") in PHASES,
            "invalid attempt resume source")
    require(set(value.get("effective_settings", {})) == set(SETTING_KEYS)
            and isinstance(value.get("predecessors"), dict)
            and isinstance(value.get("input_identities"), dict), "incomplete attempt provenance")


def attempt_context(context: dict, attempt: Path, phase: str) -> dict:
    path = attempt / "provenance.json"
    if not path.exists():
        return {**context, "manifest": context.get("original_manifest", context["manifest"])}
    value = training.read_json(path)
    validate_provenance(value, phase)
    require(value["input_identities"] == input_identities(context["manifest"]),
            "attempt input identities differ")
    manifest = {**context["manifest"], **value["effective_settings"],
                "execution_commit": value["execution_commit"]}
    validate_settings_context({**context, "manifest": manifest})
    return {**context, "manifest": manifest}


def validate_settings_context(context: dict) -> None:
    manifest = context["manifest"]
    for key, minimum, maximum in (("seed", 0, 2**64 - 1), ("opening_plies", 4, 20),
                                  ("decision_timeout_seconds", 1, 3600)):
        training.require_int(manifest[key], key, minimum, maximum)
    counts = manifest["requested_counts"]
    require(set(counts) == {"self_play_games", "baseline_comparison_games", "oracle_match_games"},
            "invalid attempt requested count fields")
    for field, maximum in (("self_play_games", 64), ("baseline_comparison_games", 200),
                           ("oracle_match_games", 200)):
        training.require_int(counts[field], field, 2, maximum)
        require(counts[field] % 2 == 0, "attempt counts must contain complete pairs")
    config = manifest["self_play_config"]
    training.require_int(config["time_limit_ms"], "time limit", 1)
    training.require_int(config["node_limit"], "node limit", 1)
    require(manifest["decision_timeout_seconds"] * 1000 > config["time_limit_ms"],
            "decision timeout must exceed the candidate search limit")
    require(config == {**SELF_PLAY_CONFIG, "time_limit_ms": config["time_limit_ms"],
                       "node_limit": config["node_limit"]}
            and manifest["match_config"] == {**MATCH_CONFIG, "time_limit_ms": config["time_limit_ms"],
                                             "node_limit": config["node_limit"]},
            "attempt search configuration mismatch")
    args = SimpleNamespace(seed=manifest["seed"], opening_plies=manifest["opening_plies"],
        decision_timeout_seconds=manifest["decision_timeout_seconds"], **counts,
        time_limit_ms=config["time_limit_ms"], node_limit=config["node_limit"])
    expected = invocation_context(context, args, {})["manifest"]
    require(settings(manifest) == settings(expected), "attempt settings/openings do not reproduce")


def attempt_provenance(context: dict, phase: str, predecessors: dict[str, Path]) -> dict:
    manifest = context["manifest"]
    return {"schema_version": 1, "phase": phase,
            "resume_from": context.get("resume_from"),
            "execution_commit": context.get("execution_commit", manifest["execution_commit"]),
            "effective_settings": settings(manifest),
            "progress_every": context.get("progress_every", 1),
            "input_identities": input_identities(manifest),
            "predecessors": {name: training.read_json(path / "receipt.json")["receipt_digest"]
                             for name, path in predecessors.items()}}


def verify_failure(attempt: Path) -> dict:
    value = training.read_json(attempt / "failure.json")
    if "failure_digest" not in value:
        require(value.get("schema_version") == 1 and not (attempt / "provenance.json").exists(),
                "unsealed attempt failure")
        return value
    unsigned = dict(value)
    digest = unsigned.pop("failure_digest")
    require(digest == training.digest(unsigned), "failure record digest mismatch")
    actual = {path.name: training.sha256_file(path) for path in attempt.iterdir()
              if path.is_file() and path.name != "failure.json"}
    require(value.get("outputs") == actual, "failed attempt output digest mismatch")
    require(value.get("phase") == attempt.parent.name and value.get("attempt") == attempt.name
            and value.get("status") == "failed", "failure record identity mismatch")
    validate_provenance(training.read_json(attempt / "provenance.json"), attempt.parent.name)
    return value


def check_dependencies(context: dict, predecessors: dict[str, Path]) -> None:
    for phase, attempt in predecessors.items():
        path = attempt / "provenance.json"
        if path.exists():
            value = training.read_json(path)
            validate_provenance(value, phase)
            expected = {name: training.read_json(prior / "receipt.json")["receipt_digest"]
                        for name, prior in predecessors.items()
                        if PHASES.index(name) < PHASES.index(phase)}
            require(value["predecessors"] == expected, f"{phase} predecessor receipt chain mismatch")


def verify_failed_attempts(run_root: Path, context: dict) -> None:
    for phase in PHASES:
        for attempt in phase_dirs(run_root, phase):
            if (attempt / "failure.json").exists():
                value = verify_failure(attempt)
                if (attempt / "provenance.json").exists():
                    attempt_context(context, attempt, phase)
                    require(value.get("manifest_sha256") == training.sha256_file(context["manifest_path"]),
                            "failed attempt manifest identity differs")
                    provenance = training.read_json(attempt / "provenance.json")
                    required = set(PHASES[:PHASES.index(phase)])
                    require(set(provenance["predecessors"]) == required,
                            "failed attempt predecessor phases differ")
                    for prior, digest in provenance["predecessors"].items():
                        matches = [path for path in phase_dirs(run_root, prior)
                                   if (path / "receipt.json").exists()
                                   and training.read_json(path / "receipt.json").get("receipt_digest") == digest]
                        require(len(matches) == 1, "failed attempt predecessor receipt missing")
                        verify_receipt(matches[0], prior, value["manifest_sha256"])


def invocation_context(context: dict, args, predecessors: dict[str, Path]) -> dict:
    original = context["manifest"]
    manifest = copy.deepcopy(original)
    manifest["execution_commit"] = context.get("execution_commit", original["execution_commit"])
    manifest.update(seed=args.seed, opening_plies=args.opening_plies,
                    decision_timeout_seconds=args.decision_timeout_seconds)
    manifest["requested_counts"] = {"self_play_games": args.self_play_games,
        "baseline_comparison_games": args.baseline_comparison_games,
        "oracle_match_games": args.oracle_match_games}
    for key in ("self_play_config", "match_config"):
        manifest[key].update(time_limit_ms=args.time_limit_ms, node_limit=args.node_limit)
    affected = {"self-play": ("seed", "opening_plies", "self_play_config"),
                "baseline-match": ("match_config",), "oracle-match": ()}
    count_keys = {"self-play": "self_play_games", "baseline-match": "baseline_comparison_games",
                  "oracle-match": "oracle_match_games"}
    for phase, attempt in predecessors.items():
        if phase not in affected:
            continue
        previous = attempt_context(context, attempt, phase)["manifest"]
        keys = affected[phase]
        field = count_keys[phase]
        require(all(manifest[key] == previous[key] for key in keys)
                and manifest["requested_counts"][field] == previous["requested_counts"][field],
                f"changed settings require --resume-from {phase} or an earlier phase")
    forbidden = context["baseline_keys"] | context["reserved"] | context["corpus_keys"]
    forbidden |= {pilot.key(row["board"], row["side"]) for row in context["validation"] + context["held_out"]}
    for name in ("train", "validation", "held_out", "oracle_root", "oracle_child"):
        forbidden |= set(context["verified"]["exposure_keys"].get(name, []))
    for phase, field in count_keys.items():
        pairs = opening_pairs(manifest["seed"], manifest["opening_plies"],
                              manifest["requested_counts"][field] // 2, forbidden, "0019-" + phase)
        manifest["openings"][phase] = pairs
        forbidden |= opening_root_set(pairs)
    manifest["max_decisions"] = sum(manifest["requested_counts"].values()) * 120 + len(context["corpus"]) * 2
    return {**context, "manifest": manifest}


def rotate_coordinate(move: str, rotation: int) -> str:
    row, col = int(move[1]) - 1, ord(move[0]) - ord("a")
    if rotation >= 4:
        col = 7 - col
    for _ in range(rotation % 4):
        row, col = col, 7 - row
    return f"{chr(ord('a') + col)}{row + 1}"


def transform_board(board: str, rotation: int) -> str:
    transformed = ["."] * 64
    for index, cell in enumerate(board):
        row, col = divmod(index, 8)
        if rotation >= 4:
            col = 7 - col
        for _ in range(rotation % 4):
            row, col = col, 7 - row
        transformed[row * 8 + col] = cell
    return "".join(transformed)


def transform_opening(opening: dict, rotation: int) -> dict:
    moves = [rotate_coordinate(move, rotation) for move in opening["moves"]]
    reflected_start = transform_board(rf.INITIAL, rotation)
    color_swapped_initial = rf.INITIAL.translate(str.maketrans("BW", "WB"))
    require(reflected_start in (rf.INITIAL, color_swapped_initial),
            "D4 transform changed the Reversi starting position")
    # Odd quarter-turns and reflections exchange the starting colors. Express
    # that transformed game on the canonical initial board by swapping the
    # side to move, then replay the rotated coordinates.
    side = "W" if reflected_start == color_swapped_initial else "B"
    board = rf.INITIAL
    transformed_moves = []
    for move in moves:
        if move == "PS":
            require(not rf.legal_moves(board, side), "transformed opening has an illegal pass")
            side = rf.other(side)
            require(rf.legal_moves(board, side), "transformed opening has consecutive passes")
            transformed_moves.append(move)
            continue
        legal = rf.legal_moves(board, side)
        if not legal:
            side = rf.other(side)
            legal = rf.legal_moves(board, side)
        require(move in legal, "symmetry transform produced an illegal opening")
        board, side = rf.apply_move(board, side, move), rf.other(side)
        transformed_moves.append(move)
    return {"board": board, "side": side, "moves": transformed_moves, "rotation": rotation}


def opening_pairs(seed: int, plies: int, pair_count: int, forbidden: set[str], domain: str) -> list[list[dict]]:
    roots = pilot.opening_pool(seed, plies, pair_count, forbidden, domain)
    result = []
    for root in roots:
        result.append([{"board": root["board"], "side": root["side"], "moves": root["moves"], "rotation": 0},
                       transform_opening(root, 2)])
    return result


def initial_board() -> str:
    return rf.INITIAL


def opening_key(opening: dict) -> str:
    return pilot.key(opening["board"], opening["side"])


def opening_root_set(pairs: list[list[dict]]) -> set[str]:
    return {opening_key(opening) for pair in pairs for opening in pair}


def make_manifest(args, run_root: Path, execution_commit: str) -> dict:
    import input_bundle

    require(args.oracle_binary is not None, "0019 requires the pinned Egaroucid executable path")
    verified = input_bundle.verify_for_production_cycle(
        args.input_bundle, args.bundle_verification_receipt,
        candidate_executable=args.candidate_executable,
    )
    require(verified.get("strength_inputs") is True and verified.get("input_kind") == "production",
            "0019 requires a strength-eligible verified 0051 bundle")
    inputs = {name: {"path": item["path"], "sha256": item["sha256"]}
              for name, item in verified["inputs"].items()}
    input_paths = {name: Path(item["path"]) for name, item in inputs.items()}
    base_manifest = training.read_json(input_paths["baseline_manifest"])
    base_records = training.validate_records(
        training.validate_manifest(base_manifest, input_paths["baseline_manifest"].parent))
    baseline = training.read_json(input_paths["baseline_artifact"])
    training.validate_artifact(baseline)
    require(baseline["provenance"]["input_manifest_digest"] == training.digest(base_manifest),
            "0051 baseline does not match its frozen training manifest")
    validation, validation_provenance = pilot.independent_rows(input_paths["validation"], "validation")
    held_out, held_out_provenance = pilot.independent_rows(input_paths["held_out"], "held_out")
    corpus, golden = pilot.corpus_inputs(input_paths["corpus"], input_paths["golden"])
    reserved = set(verified["acceptance_reservation"]["keys"])
    corpus_keys = {pilot.key(row["board"], row["side_to_move"]) for row in corpus}
    corpus_keys |= set(verified["exposure_keys"].get("oracle_child", []))
    baseline_keys = {pilot.key(row["board"], row["side"]) for row in base_records
                     if row.get("split") == "train"}
    independent_keys = {pilot.key(row["board"], row["side"]) for row in validation + held_out}
    forbidden = baseline_keys | reserved | corpus_keys | independent_keys
    for name in ("train", "validation", "held_out", "oracle_root", "oracle_child"):
        forbidden |= set(verified["exposure_keys"].get(name, []))
    seed = int(args.seed)
    self_pairs = opening_pairs(seed, args.opening_plies, args.self_play_games // 2,
                               forbidden, "0019-self-play")
    forbidden |= opening_root_set(self_pairs)
    match_pairs = opening_pairs(seed, args.opening_plies, args.baseline_comparison_games // 2,
                                forbidden, "0019-baseline-match")
    forbidden |= opening_root_set(match_pairs)
    oracle_pairs = opening_pairs(seed, args.opening_plies, args.oracle_match_games // 2,
                                 forbidden, "0019-oracle-match")
    require(not (opening_root_set(self_pairs) & opening_root_set(match_pairs))
            and not (opening_root_set(self_pairs) & opening_root_set(oracle_pairs))
            and not (opening_root_set(match_pairs) & opening_root_set(oracle_pairs)),
            "0019 phase openings overlap")
    candidate = file_entry(args.candidate_executable)
    bundled_cli = verified["cli"].get("binary", {})
    require(candidate["sha256"] == bundled_cli.get("sha256", candidate["sha256"]),
            "candidate executable digest differs from verified bundle")
    oracle_binary = file_entry(args.oracle_binary)
    require(Path(oracle_binary["path"]).stat().st_mode & 0o111,
            "pinned Oracle binary is not executable")
    return {
        "schema_version": 2,
        "producer_version": VERSION,
        "score_contract": training.SCORE_CONTRACT,
        "execution_commit": execution_commit,
        "input_bundle": file_entry(args.input_bundle),
        "bundle_verification_receipt": file_entry(args.bundle_verification_receipt),
        "verified_bundle": verified,
        "inputs": inputs,
        "candidate_executable": candidate,
        "oracle_binary": oracle_binary,
        "oracle_profile": oracle_module.profile_metadata(ORACLE_PROFILE),
        "oracle_profile_id": ORACLE_PROFILE.name,
        "oracle_exact_solver_empty_squares": oracle_module.profile_exact_threshold(ORACLE_PROFILE),
        "corpus_profile": golden[0]["profile"],
        "oracle_version": oracle_module.ORACLE_VERSION,
        "oracle_source_sha256": oracle_module.SOURCE_SHA256,
        "seed": seed,
        "opening_plies": args.opening_plies,
        "requested_counts": {"self_play_games": args.self_play_games,
                             "baseline_comparison_games": args.baseline_comparison_games,
                             "oracle_match_games": args.oracle_match_games},
        "self_play_config": {**SELF_PLAY_CONFIG, "time_limit_ms": args.time_limit_ms,
                             "node_limit": args.node_limit},
        "match_config": {**MATCH_CONFIG, "time_limit_ms": args.time_limit_ms,
                         "node_limit": args.node_limit},
        "decision_timeout_seconds": args.decision_timeout_seconds,
        "max_decisions": args.self_play_games * 120 + args.baseline_comparison_games * 120
            + args.oracle_match_games * 120 + len(corpus) * 2,
        "pairing": "color-swap-d4-rotation-2-v1",
        "update_rule": UPDATE_RULE,
        "validation_provenance": validation_provenance,
        "held_out_provenance": held_out_provenance,
        "openings": {"self-play": self_pairs, "baseline-match": match_pairs,
                     "oracle-match": oracle_pairs},
    }


def checked_manifest(path: Path) -> dict:
    manifest = training.read_json(path)
    require(manifest.get("schema_version") == 2 and manifest.get("producer_version") == VERSION
            and manifest.get("score_contract") == training.SCORE_CONTRACT,
            "unsupported 0019 production manifest")
    execution_commit = manifest.get("execution_commit")
    require(isinstance(execution_commit, str) and re.fullmatch(r"[0-9a-f]{40}", execution_commit),
            "invalid 0019 execution commit")
    require(manifest.get("oracle_profile_id") == ORACLE_PROFILE.name
            and manifest.get("oracle_profile") == oracle_module.profile_metadata(ORACLE_PROFILE)
            and manifest.get("oracle_exact_solver_empty_squares")
                == oracle_module.profile_exact_threshold(ORACLE_PROFILE)
            and manifest.get("oracle_version") == oracle_module.ORACLE_VERSION
            and manifest.get("oracle_source_sha256") == oracle_module.SOURCE_SHA256,
            "0019 Oracle profile identity mismatch")
    requested = manifest.get("requested_counts", {})
    count_limits = {"self_play_games": 64, "baseline_comparison_games": 200,
                    "oracle_match_games": 200}
    for name, count in requested.items():
        training.require_int(count, name, 2, count_limits.get(name, 0))
        require(count % 2 == 0, f"{name} must contain complete color-swapped pairs")
    require(set(requested) == {"self_play_games", "baseline_comparison_games", "oracle_match_games"},
            "0019 requested count fields mismatch")
    require(requested["oracle_match_games"] > 0, "0019 Oracle match must contain at least one pair")
    require(manifest.get("inputs") and manifest.get("candidate_executable") and manifest.get("oracle_binary"),
            "0019 input identities are incomplete")
    for entry in [manifest["input_bundle"], manifest["bundle_verification_receipt"],
                  manifest["candidate_executable"], manifest["oracle_binary"], *manifest["inputs"].values()]:
        checked = training.sha256_file(Path(entry["path"]))
        require(checked == entry["sha256"], f"0019 frozen input digest changed: {entry['path']}")
    return manifest


def load_context(manifest_path: Path) -> dict:
    import input_bundle

    manifest = checked_manifest(manifest_path)
    verified = input_bundle.verify_for_production_cycle(
        Path(manifest["input_bundle"]["path"]),
        Path(manifest["bundle_verification_receipt"]["path"]),
        candidate_executable=Path(manifest["candidate_executable"]["path"]),
    )
    require(verified == manifest["verified_bundle"], "verified 0051 bundle evidence changed")
    paths = {name: Path(item["path"]) for name, item in manifest["inputs"].items()}
    base_manifest = training.read_json(paths["baseline_manifest"])
    baseline_records = training.validate_records(
        training.validate_manifest(base_manifest, paths["baseline_manifest"].parent))
    baseline = training.read_json(paths["baseline_artifact"])
    training.validate_artifact(baseline)
    require(baseline == training.artifact_from(base_manifest, baseline_records,
                                               training.digest(base_manifest)),
            "baseline artifact does not replay from frozen inputs")
    validation, _ = pilot.independent_rows(paths["validation"], "validation",
                                            manifest["validation_provenance"])
    held_out, _ = pilot.independent_rows(paths["held_out"], "held_out",
                                          manifest["held_out_provenance"])
    corpus, golden = pilot.corpus_inputs(paths["corpus"], paths["golden"])
    expected_decisions = sum(manifest["requested_counts"].values()) * 120 + len(corpus) * 2
    require(manifest["max_decisions"] == expected_decisions,
            "0019 maximum-decision resource cap mismatch")
    require(manifest["corpus_profile"] == golden[0]["profile"],
            "0019 corpus profile differs from the frozen bundle")
    baseline_keys = {pilot.key(row["board"], row["side"]) for row in baseline_records
                     if row.get("split") == "train"}
    reserved = set(verified["acceptance_reservation"]["keys"])
    corpus_keys = {pilot.key(row["board"], row["side_to_move"]) for row in corpus}
    corpus_keys |= set(verified["exposure_keys"].get("oracle_child", []))
    forbidden = baseline_keys | reserved | corpus_keys
    forbidden |= {pilot.key(row["board"], row["side"]) for row in validation + held_out}
    for name in ("train", "validation", "held_out", "oracle_root", "oracle_child"):
        forbidden |= set(verified["exposure_keys"].get(name, []))
    expected_openings = {}
    for name, domain, count_field in (
        ("self-play", "0019-self-play", "self_play_games"),
        ("baseline-match", "0019-baseline-match", "baseline_comparison_games"),
        ("oracle-match", "0019-oracle-match", "oracle_match_games"),
    ):
        expected_openings[name] = opening_pairs(manifest["seed"], manifest["opening_plies"],
            manifest["requested_counts"][count_field] // 2, forbidden, domain)
        require(manifest["openings"].get(name) == expected_openings[name],
                f"0019 frozen {name} openings do not reproduce")
        forbidden |= opening_root_set(expected_openings[name])
    return {"manifest": manifest, "original_manifest": copy.deepcopy(manifest),
            "verified": verified, "paths": paths,
            "baseline": baseline, "baseline_keys": baseline_keys, "validation": validation,
            "held_out": held_out, "reserved": reserved, "corpus": corpus,
            "golden": golden, "corpus_keys": corpus_keys,
            "manifest_path": manifest_path}


def phase_dirs(run_root: Path, phase: str) -> list[Path]:
    parent = run_root / "phases" / phase
    if not parent.is_dir():
        return []
    return sorted((path for path in parent.iterdir() if path.is_dir() and path.name.startswith("attempt-")),
                  key=lambda path: path.name)


def verify_receipt(attempt: Path, phase: str, manifest_digest: str) -> dict:
    receipt_path = attempt / "receipt.json"
    require(receipt_path.is_file(), f"missing {phase} receipt in {attempt.name}")
    receipt = training.read_json(receipt_path)
    expected = dict(receipt)
    actual_digest = expected.pop("receipt_digest", None)
    require(actual_digest == training.digest(expected), f"{phase} receipt digest mismatch")
    require(receipt.get("phase") == phase and receipt.get("status") == "complete"
            and receipt.get("manifest_sha256") == manifest_digest,
            f"{phase} receipt identity mismatch")
    require(receipt.get("schema_version") in (1, 2), "unsupported phase receipt")
    outputs = receipt.get("outputs")
    require(isinstance(outputs, dict) and outputs, f"{phase} receipt has no outputs")
    for name, digest in outputs.items():
        path = attempt / name
        require(path.is_file() and training.sha256_file(path) == digest,
                f"{phase} output digest mismatch: {name}")
    actual = {path.name for path in attempt.iterdir() if path.is_file() and path.name not in ("receipt.json",)}
    require(actual == set(outputs), f"{phase} attempt contains unreceipted outputs")
    require(receipt["schema_version"] != 2 or "provenance.json" in outputs,
            "missing attempt provenance")
    if "provenance.json" in outputs:
        validate_provenance(training.read_json(attempt / "provenance.json"), phase)
    return receipt


def latest_success(run_root: Path, phase: str, manifest_digest: str) -> tuple[Path, dict] | None:
    for attempt in reversed(phase_dirs(run_root, phase)):
        if not (attempt / "receipt.json").is_file():
            continue
        try:
            return attempt, verify_receipt(attempt, phase, manifest_digest)
        except training.TrainingError as error:
            raise training.TrainingError(f"invalid predecessor phase {phase}: {error}") from error
    return None


def require_predecessors(run_root: Path, target_phase: str, manifest_digest: str) -> dict[str, Path]:
    result = {}
    for phase in PHASES[:PHASES.index(target_phase)]:
        found = latest_success(run_root, phase, manifest_digest)
        require(found is not None, f"resume requires a verified predecessor phase: {phase}")
        result[phase] = found[0]
    return result


def write_attempt(run_root: Path, phase: str, manifest_digest: str, action, provenance=None) -> Path:
    parent = run_root / "phases" / phase
    parent.mkdir(parents=True, exist_ok=True)
    attempts = phase_dirs(run_root, phase)
    attempt = parent / f"attempt-{len(attempts) + 1:04d}"
    attempt.mkdir()
    try:
        if provenance is not None:
            validate_provenance(provenance, phase)
            rf.atomic_write(attempt, "provenance.json", blob(provenance))
        action(attempt)
        outputs = {path.name: training.sha256_file(path) for path in sorted(attempt.iterdir())
                   if path.is_file() and path.name != "receipt.json"}
        require(bool(outputs), f"{phase} produced no outputs")
        receipt = {"schema_version": 2 if provenance is not None else 1, "phase": phase, "status": "complete",
                   "attempt": attempt.name, "manifest_sha256": manifest_digest,
                   "outputs": outputs}
        receipt["receipt_digest"] = training.digest(receipt)
        rf.atomic_write(attempt, "receipt.json", blob(receipt))
        verify_receipt(attempt, phase, manifest_digest)
        return attempt
    except BaseException as error:
        failure = {"schema_version": 2 if provenance is not None else 1, "phase": phase, "attempt": attempt.name,
                   "status": "failed", "error": str(error)}
        if provenance is not None:
            failure["manifest_sha256"] = manifest_digest
            failure["outputs"] = {path.name: training.sha256_file(path) for path in attempt.iterdir()
                                  if path.is_file() and path.name != "failure.json"}
            failure["failure_digest"] = training.digest(failure)
        try:
            rf.atomic_write(attempt, "failure.json", blob(failure))
        except OSError:
            pass
        raise


def output(attempt: Path, name: str) -> Path:
    path = attempt / name
    require(path.is_file(), f"missing {name} from phase {attempt.parent.name}")
    return path


def all_game_records(context: dict, predecessors: dict[str, Path]) -> list[dict]:
    games = []
    for phase in ("self-play", "baseline-match"):
        if phase in predecessors:
            games.extend(training.read_jsonl(output(predecessors[phase], "games.jsonl")))
    return games


def played_keys(context: dict, games: list[dict]) -> set[str]:
    values = set()
    for game in games:
        values.add(pilot.key(game["start_board"], game["start_side"]))
        values.update(pilot.key(row["board"], row["side"]) for row in game["decisions"])
        values.update(pilot.key(game["terminal_board"], side) for side in ("B", "W"))
    return values


def tuning_rows(context: dict, games: list[dict]) -> list[dict]:
    unique, rows = set(), []
    forbidden = context["baseline_keys"] | context["reserved"] | context["corpus_keys"]
    for game in games:
        if game["kind"] != "0019-self-play":
            continue
        tuning = rf.replay(game)
        for decision, row in zip(game["decisions"], tuning):
            position = pilot.key(row["board"], row["side"])
            if position in forbidden or position in unique:
                continue
            unique.add(position)
            rows.append({"id": decision["id"], **row})
    require(rows, "0019 self-play produced no usable unique tuning rows")
    require(len(rows) <= 64 * 120, "0019 teacher row cap exceeded")
    return rows


def phase_input_verification(context: dict, attempt: Path) -> None:
    verified = context["verified"]
    evidence = {"schema_version": 1, "bundle_sha256": context["manifest"]["input_bundle"]["sha256"],
                "receipt_sha256": context["manifest"]["bundle_verification_receipt"]["sha256"],
                "strength_inputs": verified["strength_inputs"],
                "input_digests": {name: item["sha256"] for name, item in context["manifest"]["inputs"].items()},
                "candidate_sha256": context["manifest"]["candidate_executable"]["sha256"],
                "oracle_sha256": context["manifest"]["oracle_binary"]["sha256"],
                "execution_commit": context["manifest"]["execution_commit"]}
    rf.atomic_write(attempt, "evidence.json", blob(evidence))


def run_training_games(context: dict, kind: str, pairs: list[list[dict]],
                       output_path: Path, progress_every: int, *, initial_games=None,
                       pair_offset: int = 0, total_games: int | None = None,
                       progress=None) -> list[dict]:
    manifest = context["manifest"]
    artifact = context["baseline"]
    baseline_path = Path(context["paths"]["baseline_artifact"])
    players = {name: rf.Candidate(Path(manifest["candidate_executable"]["path"]),
                baseline_path, manifest["self_play_config"], manifest["decision_timeout_seconds"])
               for name in (("baseline-A", "baseline-B") if kind == "0019-self-play" else ("baseline",))}
    if kind == "0019-baseline-match":
        candidate_artifact = context["candidate_artifact_path"]
        players["candidate"] = rf.Candidate(Path(manifest["candidate_executable"]["path"]),
                candidate_artifact, manifest["match_config"], manifest["decision_timeout_seconds"])
    game_count = manifest["requested_counts"]["self_play_games" if kind == "0019-self-play"
                                                else "baseline_comparison_games"]
    remaining = [game_count * 120]
    progress = progress or rf.Progress(progress_every)
    results = list(initial_games or [])
    total_games = total_games or len(pairs) * 2
    failures = []
    try:
        for pair_index, pair in enumerate(pairs):
            absolute_pair = pair_offset + pair_index
            for member, opening in enumerate(pair):
                sides = (({"B": "baseline-A", "W": "baseline-B"} if member == 0 else
                          {"B": "baseline-B", "W": "baseline-A"}) if kind == "0019-self-play" else
                         ({"B": "candidate", "W": "baseline"} if member == 0 else
                          {"B": "baseline", "W": "candidate"}))
                started = time.monotonic()
                try:
                    game = rf.play(kind, absolute_pair, member, opening["board"], opening["side"],
                                   opening["moves"], opening["rotation"], players, sides, remaining)
                except BaseException as error:
                    failures.append({"kind": kind, "pair": absolute_pair, "member": member,
                                     "opening": opening["moves"], "start_board": opening["board"],
                                     "start_side": opening["side"], "failure": str(error)})
                    rf.atomic_write(output_path.parent, "failures.jsonl",
                                    b"".join(blob(item) for item in failures))
                    raise
                results.append(game)
                rf.atomic_write(output_path.parent, output_path.name,
                                b"".join(blob(item) for item in results))
                progress.game(kind, absolute_pair, member, len(results), total_games, started)
    finally:
        for player in players.values():
            player.close()
    rf.atomic_write(output_path.parent, "failures.jsonl", b"".join(blob(item) for item in failures))
    return results


def phase_self_play(context: dict, attempt: Path, progress_every: int) -> None:
    progress = rf.Progress(progress_every)
    games = run_training_games(context, "0019-self-play",
        context["manifest"]["openings"]["self-play"], attempt / "games.jsonl", progress_every,
        total_games=context["manifest"]["requested_counts"]["self_play_games"], progress=progress)
    require(len(games) == context["manifest"]["requested_counts"]["self_play_games"],
            "0019 self-play game count mismatch")
    rf.atomic_write(attempt, "games.jsonl", b"".join(blob(game) for game in games))
    rf.atomic_write(attempt, "actual-count.json", blob({"games": len(games)}))


def phase_candidate_update(context: dict, predecessors: dict[str, Path], attempt: Path) -> None:
    games = training.read_jsonl(output(predecessors["self-play"], "games.jsonl"))
    rows = tuning_rows(context, games)
    artifact = rf.updated_artifact(context["baseline"], rows, context["manifest"])
    training.validate_artifact(artifact)
    rf.atomic_write(attempt, "teacher-rows.jsonl", b"".join(blob(row) for row in rows))
    rf.atomic_write(attempt, "candidate-artifact.json", blob(artifact))


def phase_baseline_match(context: dict, predecessors: dict[str, Path], attempt: Path,
                         progress_every: int) -> None:
    update_attempt = predecessors["candidate-update"]
    context["candidate_artifact_path"] = output(update_attempt, "candidate-artifact.json")
    requested = context["manifest"]["requested_counts"]["baseline_comparison_games"]
    pairs = context["manifest"]["openings"]["baseline-match"]
    # Preserve the 0019 sequential gate: stop after 50 games when candidate
    # points do not exceed 25; otherwise complete the requested comparison.
    first_count = min(requested, 50)
    selected_pairs = pairs[:first_count // 2]
    progress = rf.Progress(progress_every)
    games = run_training_games(context, "0019-baseline-match", selected_pairs,
                               attempt / "games.jsonl", progress_every, total_games=requested,
                               progress=progress)
    rf.atomic_write(attempt, "checkpoint-after-initial-gate.jsonl",
                    b"".join(blob(game) for game in games))
    if requested > 50 and rf.match_summary(games)["match_points"] > 25:
        games = run_training_games(context, "0019-baseline-match", pairs[first_count // 2:],
                                   attempt / "games.jsonl", progress_every, initial_games=games,
                                   pair_offset=first_count // 2, total_games=requested, progress=progress)
    require(games and len(games) % 2 == 0, "0019 baseline match has an incomplete pair")
    rf.atomic_write(attempt, "games.jsonl", b"".join(blob(game) for game in games))
    rf.atomic_write(attempt, "actual-count.json", blob({"requested": requested, "actual": len(games)}))


def phase_candidate_selection(context: dict, predecessors: dict[str, Path], attempt: Path) -> None:
    games = training.read_jsonl(output(predecessors["baseline-match"], "games.jsonl"))
    summary = rf.match_summary(games)
    selected = "candidate" if summary["match_points"] > summary["games"] / 2 else "baseline"
    prior_games = all_game_records(context, predecessors)
    used = played_keys(context, prior_games) | context["baseline_keys"] | context["reserved"] | context["corpus_keys"]
    validation = [row for row in context["validation"]
                  if pilot.key(row["board"], row["side"]) not in used]
    require(validation, "0019 validation split is empty after exposure exclusion")
    candidate_path = output(predecessors["candidate-update"], "candidate-artifact.json")
    candidate = training.read_json(candidate_path)
    comparison = {"baseline": rf.mse(context["baseline"], validation),
                  "candidate": rf.mse(candidate, validation)}
    value = {"schema_version": 1, "selected": selected, "match": summary,
             "required_match_points": summary["games"] / 2,
             "early_stop": summary["games"] < context["manifest"]["requested_counts"]["baseline_comparison_games"],
             "validation_metrics": comparison,
             "validation_position_keys": sorted(pilot.key(row["board"], row["side"]) for row in validation),
             "candidate_artifact_sha256": training.sha256_file(candidate_path),
             "baseline_artifact_sha256": context["manifest"]["inputs"]["baseline_artifact"]["sha256"]}
    rf.atomic_write(attempt, "selection.json", blob(value))


def phase_corpus_regret(context: dict, predecessors: dict[str, Path], attempt: Path,
                        progress_every: int) -> None:
    games = all_game_records(context, predecessors)
    played = played_keys(context, games)
    base_ctx = {"baseline_keys": context["baseline_keys"], "reserved": context["reserved"],
                "corpus_keys": context["corpus_keys"], "corpus": context["corpus"],
                "golden": context["golden"]}
    records, _, _ = pilot.independent_corpus(base_ctx, played)
    candidate_path = output(predecessors["candidate-update"], "candidate-artifact.json")
    manifest = context["manifest"]
    players = {
        "baseline": rf.Candidate(Path(manifest["candidate_executable"]["path"]),
            Path(context["paths"]["baseline_artifact"]), manifest["match_config"],
            manifest["decision_timeout_seconds"]),
        "candidate": rf.Candidate(Path(manifest["candidate_executable"]["path"]), candidate_path,
            manifest["match_config"], manifest["decision_timeout_seconds"]),
    }
    decisions = []
    progress = rf.Progress(progress_every)
    try:
        total = len(records) * 2
        for index, row in enumerate(records):
            for name in ("baseline", "candidate"):
                started = time.monotonic()
                identifier = f"0019-corpus-{index}-{name}"
                players[name].new_game(identifier)
                move = players[name].choose(identifier, row["board"], row["side_to_move"])
                decisions.append({"position_id": row["position_id"], "board": row["board"],
                                  "side": row["side_to_move"], "player": name, "move": move})
                rf.atomic_write(attempt, "decisions.jsonl", b"".join(blob(item) for item in decisions))
                progress.game("corpus-regret", index, 0 if name == "baseline" else 1,
                              len(decisions), total, started)
    finally:
        for player in players.values():
            player.close()
    report = pilot.corpus_metrics(base_ctx, decisions, played)
    rf.atomic_write(attempt, "report.json", blob(report))


def game_origin(context: dict, source: Path, game: dict) -> dict:
    path = source / "provenance.json"
    provenance = (training.read_json(path) if path.exists() else
                  {"schema_version": 1, "phase": "oracle-match", "resume_from": None,
                   "execution_commit": context.get("original_manifest", context["manifest"])["execution_commit"],
                   "effective_settings": settings(context.get("original_manifest", context["manifest"])),
                   "input_identities": input_identities(context["manifest"]), "predecessors": {}})
    validate_provenance(provenance, "oracle-match")
    return {"game": game["game"], "game_digest": game["game_digest"],
            "source_attempt": source.name, "provenance": provenance,
            "provenance_digest": training.digest(provenance)}


def verify_game_origin(context: dict, attempt: Path, game: dict, origin: dict) -> dict:
    require(origin.get("game") == game["game"] and origin.get("game_digest") == game["game_digest"],
            "Oracle game provenance identity mismatch")
    source_name = origin.get("source_attempt", "")
    require(bool(re.fullmatch(r"attempt-[0-9]{4,}", source_name)), "invalid Oracle source attempt")
    source = attempt.parent / source_name
    require(source.name <= attempt.name, "Oracle provenance points to a later attempt")
    expected = game_origin(context, source, game)
    require(origin == expected, "Oracle game provenance mismatch")
    source_lines = output(source, "games.jsonl").read_text(encoding="utf-8").splitlines()
    require(len(source_lines) >= game["game"]
            and json.loads(source_lines[game["game"] - 1]) == game,
            "Oracle source game differs")
    value = origin["provenance"]
    current_path = attempt / "provenance.json"
    if current_path.exists():
        current_update = training.read_json(current_path)["predecessors"].get("candidate-update")
        source_update = value["predecessors"].get("candidate-update")
        if (source / "provenance.json").exists():
            require(current_update == source_update, "Oracle game candidate predecessor differs")
        else:
            original_update = attempt.parents[2] / "phases" / "candidate-update" / "attempt-0001" / "receipt.json"
            require(original_update.is_file()
                    and current_update == training.read_json(original_update)["receipt_digest"],
                    "legacy Oracle game candidate predecessor differs")
    validate_settings_context({**context, "manifest": {**context["manifest"], **value["effective_settings"]}})
    require(value["input_identities"] == input_identities(context["manifest"]),
            "Oracle source input identities differ")
    return {**context["manifest"], **value["effective_settings"],
            "execution_commit": value["execution_commit"]}


def oracle_prefix(context: dict, predecessors: dict[str, Path], attempt: Path) -> tuple[list, list]:
    previous = [path for path in phase_dirs(attempt.parents[2], "oracle-match") if path < attempt]
    if not previous or not (previous[-1] / "failure.json").exists():
        return [], []
    source = previous[-1]
    verify_failure(source)
    if not (source / "games.jsonl").exists():
        return [], []
    prior_context = attempt_context(context, source, "oracle-match")
    prior_manifest = prior_context["manifest"]
    # A changed candidate artifact invalidates the old match, even when the executable is unchanged.
    provenance_path = source / "provenance.json"
    if provenance_path.exists():
        prior_update = training.read_json(provenance_path)["predecessors"].get("candidate-update")
        if prior_update != training.read_json(predecessors["candidate-update"] / "receipt.json")["receipt_digest"]:
            return [], []
    elif predecessors["candidate-update"].name != "attempt-0001":
        return [], []
    games, origins = [], []
    origin_path = source / "game-provenance.jsonl"
    old_origins = training.read_jsonl(origin_path) if origin_path.exists() else None
    # Parse line by line so a broken tail never discards a validated completed prefix.
    for index, line in enumerate((source / "games.jsonl").read_text(encoding="utf-8").splitlines()):
        try:
            if index >= context["manifest"]["requested_counts"]["oracle_match_games"]:
                break
            game = json.loads(line)
            origin = old_origins[index] if old_origins is not None else game_origin(context, source, game)
            origin_manifest = verify_game_origin(context, source, game, origin)
            validate_oracle_game(origin_manifest, game, index)
            require(context["manifest"]["match_config"] == origin_manifest["match_config"],
                    "Oracle retry candidate configuration differs")
            require(context["manifest"]["openings"]["oracle-match"][index // 2][index % 2]
                    == origin_manifest["openings"]["oracle-match"][index // 2][index % 2],
                    "Oracle retry opening differs")
            require(prior_manifest["oracle_profile"] == context["manifest"]["oracle_profile"],
                    "Oracle retry profile differs")
        except (training.TrainingError, ValueError, KeyError, IndexError, TypeError):
            break
        games.append(game)
        origins.append(origin)
    return games, origins


def phase_oracle_match(context: dict, predecessors: dict[str, Path], attempt: Path,
                       progress_every: int) -> None:
    manifest = context["manifest"]
    candidate_artifact = output(predecessors["candidate-update"], "candidate-artifact.json")
    completed, origins = oracle_prefix(context, predecessors, attempt)
    candidate = rf.Candidate(Path(manifest["candidate_executable"]["path"]), candidate_artifact,
        manifest["match_config"], manifest["decision_timeout_seconds"], capture_diagnostics=True)
    try:
        pairs = [(pair[0], pair[1]) for pair in manifest["openings"]["oracle-match"]]
        rf.atomic_write(attempt, "games.jsonl", b"".join(blob(item) for item in completed))
        rf.atomic_write(attempt, "game-provenance.jsonl", b"".join(blob(item) for item in origins))
        def save_game(game):
            completed.append(game)
            origins.append(game_origin(context, attempt, game))
            rf.atomic_write(attempt, "games.jsonl", b"".join(blob(item) for item in completed))
            rf.atomic_write(attempt, "game-provenance.jsonl", b"".join(blob(item) for item in origins))
        report = oracle_module.run_profiled_match(
            Path(manifest["oracle_binary"]["path"]),
            Path(manifest["oracle_binary"]["path"]).parent,
            candidate, pairs, ORACLE_PROFILE, manifest["match_config"],
            manifest["decision_timeout_seconds"], progress_every, on_game=save_game, initial_games=completed,
        )
    finally:
        candidate.close()
    rf.atomic_write(attempt, "match.json", blob(report))


def validate_oracle_game(manifest: dict, game: dict, index: int) -> None:
    opening = manifest["openings"]["oracle-match"][index // 2][index % 2]
    require(game["game"] == index + 1 and game["pair"] == index // 2
            and game["member"] == index % 2 and game["rotation"] == opening["rotation"]
            and game["opening"] == opening["moves"] and game["start_board"] == opening["board"]
            and game["start_side"] == opening["side"]
            and game["candidate_side"] == ("B" if index % 2 == 0 else "W"),
            "0019 Oracle match pair differs from frozen opening")
    expected = dict(game)
    digest = expected.pop("game_digest")
    require(digest == hashlib.sha256(json.dumps(expected, sort_keys=True,
            separators=(",", ":")).encode("ascii")).hexdigest(),
            "0019 Oracle match game digest mismatch")
    board, side = game["start_board"], game["start_side"]
    for decision in game["decisions"]:
        root_empty = board.count(".")
        root_occupied = board.count("B") + board.count("W")
        require(decision["board"] == board and decision["side"] == side,
                "0019 Oracle match decision state mismatch")
        require(decision.get("actor") == ("candidate" if side == game["candidate_side"] else "oracle"),
                "0019 Oracle match actor does not match the frozen seat")
        legal = oracle_module.legal_moves(board, side)
        if legal:
            require(decision["move"] in legal, "0019 Oracle match contains an illegal move")
            board = oracle_module.apply_move(board, side, decision["move"])
        else:
            require(decision["move"] == "pass" and oracle_module.legal_moves(board, oracle_module.other(side)),
                    "0019 Oracle match pass is invalid")
        require(type(decision["completed_depth"]) is int and type(decision["exact"]) is bool,
                "0019 Oracle telemetry is incomplete")
        if decision["actor"] == "candidate":
            telemetry = decision.get("search_telemetry", {})
            configured = decision["configured_search"]
            depth_name = "opening_depth" if root_occupied < 24 else (
                "endgame_depth" if root_empty <= manifest["match_config"][
                    "exact_solver_empty_squares"] else "midgame_depth")
            require(configured == manifest["match_config"]
                    and decision["configured_depth"] == manifest["match_config"][depth_name]
                    and decision["exact_solver_empty_squares"]
                        == manifest["match_config"]["exact_solver_empty_squares"],
                    "0019 candidate Oracle-match profile mismatch")
            require(type(telemetry.get("nodes")) is int and type(telemetry.get("elapsed_us")) is int
                    and telemetry.get("outcome") in ("move", "pass", "game_over")
                    and telemetry["nodes"] <= configured["node_limit"]
                    and telemetry["elapsed_us"] <= configured["time_limit_ms"] * 1000,
                    "0019 candidate exceeded or omitted its search resource evidence")
        else:
            expected_depth = oracle_module.profile_depth_at(
                ORACLE_PROFILE, root_occupied) if legal else 0
            oracle_search = {**manifest["oracle_profile"]["oracle"],
                             "profile": manifest["oracle_profile_id"],
                             "exact_solver_empty_squares": manifest[
                                 "oracle_exact_solver_empty_squares"]}
            require(decision["configured_search"] == oracle_search
                    and decision["configured_depth"] == expected_depth
                    and decision["exact_solver_empty_squares"]
                        == manifest["oracle_exact_solver_empty_squares"],
                    "0019 Oracle search profile mismatch")
        if decision["move"] != "pass" and root_empty <= decision["exact_solver_empty_squares"]:
            require(decision["exact"], "0019 Oracle match omitted a required exact solve")
        side = oracle_module.other(side)
    require(board == game["terminal_board"] and not oracle_module.legal_moves(board, side)
            and not oracle_module.legal_moves(board, oracle_module.other(side)),
            "0019 Oracle game does not reach its recorded terminal board")
    candidate_score = oracle_module.terminal_score(board, game["candidate_side"])
    oracle_score = oracle_module.terminal_score(board, game["oracle_side"])
    expected_result = "draw" if candidate_score == oracle_score else (
        "candidate_win" if candidate_score > oracle_score else "oracle_win")
    require(game["candidate_score"] == candidate_score and game["oracle_score"] == oracle_score
            and game["result"] == expected_result,
            "0019 Oracle match score does not replay")
    expected_record = "".join(opening["moves"] + [
        "PS" if decision["move"] == "pass" else decision["move"]
        for decision in game["decisions"]])
    require(game["game_record"] == expected_record
            and game["moves"] == len(opening["moves"]) + sum(
                decision["move"] != "pass" for decision in game["decisions"])
            and game["black"] == board.count("B") and game["white"] == board.count("W"),
            "0019 Oracle match record or terminal counts do not replay")


def semantic_phase_check(context: dict, phase: str, attempt: Path,
                         predecessors: dict[str, Path]) -> None:
    context = attempt_context(context, attempt, phase)
    manifest = context["manifest"]
    if phase == "input-verification":
        evidence = training.read_json(output(attempt, "evidence.json"))
        expected = {"schema_version": 1, "bundle_sha256": manifest["input_bundle"]["sha256"],
                    "receipt_sha256": manifest["bundle_verification_receipt"]["sha256"],
                    "strength_inputs": True,
                    "input_digests": {name: item["sha256"] for name, item in manifest["inputs"].items()},
                    "candidate_sha256": manifest["candidate_executable"]["sha256"],
                    "oracle_sha256": manifest["oracle_binary"]["sha256"],
                    "execution_commit": manifest["execution_commit"]}
        require(evidence == expected, "0019 input verification evidence mismatch")
    elif phase == "self-play":
        games = training.read_jsonl(output(attempt, "games.jsonl"))
        require(len(games) == manifest["requested_counts"]["self_play_games"],
                "0019 self-play receipt count mismatch")
        expected_pairs = manifest["openings"]["self-play"]
        for index, game in enumerate(games):
            rf.replay(game)
            opening = expected_pairs[index // 2][index % 2]
            require(game["kind"] == "0019-self-play" and game["pair"] == index // 2
                    and game["member"] == index % 2 and game["opening"] == opening["moves"]
                    and game["start_board"] == opening["board"] and game["start_side"] == opening["side"]
                    and game["rotation"] == opening["rotation"]
                    and game["players"] == ({"B": "baseline-A", "W": "baseline-B"} if index % 2 == 0
                                             else {"B": "baseline-B", "W": "baseline-A"}),
                    "0019 self-play pair does not match frozen opening")
    elif phase == "candidate-update":
        games = training.read_jsonl(output(predecessors["self-play"], "games.jsonl"))
        rows = tuning_rows(context, games)
        require(training.read_jsonl(output(attempt, "teacher-rows.jsonl")) == rows,
                "0019 teacher rows do not replay")
        expected = rf.updated_artifact(context["baseline"], rows, manifest)
        actual = training.read_json(output(attempt, "candidate-artifact.json"))
        require(actual == expected, "0019 candidate artifact does not replay")
    elif phase == "baseline-match":
        games = training.read_jsonl(output(attempt, "games.jsonl"))
        actual = training.read_json(output(attempt, "actual-count.json"))
        require(len(games) == actual["actual"] and len(games) % 2 == 0,
                "0019 baseline match is incomplete")
        requested = manifest["requested_counts"]["baseline_comparison_games"]
        require(actual["requested"] == requested and actual["actual"] <= requested,
                "0019 baseline match count metadata mismatch")
        summary = rf.match_summary(games)
        require(actual["actual"] == requested or
                (requested > 50 and actual["actual"] == 50 and summary["match_points"] <= 25),
                "0019 baseline match stopped before its declared gate")
        expected_pairs = manifest["openings"]["baseline-match"]
        for index, game in enumerate(games):
            rf.replay(game)
            opening = expected_pairs[index // 2][index % 2]
            expected_players = ({"B": "candidate", "W": "baseline"} if index % 2 == 0
                                else {"B": "baseline", "W": "candidate"})
            require(game["kind"] == "0019-baseline-match" and game["pair"] == index // 2
                    and game["member"] == index % 2 and game["opening"] == opening["moves"]
                    and game["start_board"] == opening["board"] and game["start_side"] == opening["side"]
                    and game["rotation"] == opening["rotation"] and game["players"] == expected_players,
                    "0019 baseline comparison pair does not match frozen opening")
        checkpoint = training.read_jsonl(output(attempt, "checkpoint-after-initial-gate.jsonl"))
        require(checkpoint == games[:min(len(games), 50)],
                "0019 baseline match initial checkpoint differs from final replay")
    elif phase == "candidate-selection":
        games = training.read_jsonl(output(predecessors["baseline-match"], "games.jsonl"))
        expected_summary = rf.match_summary(games)
        expected = "candidate" if expected_summary["match_points"] > expected_summary["games"] / 2 else "baseline"
        actual = training.read_json(output(attempt, "selection.json"))
        require(actual["match"] == expected_summary and actual["selected"] == expected,
                "0019 selection does not replay from baseline match")
        used = played_keys(context, all_game_records(context, predecessors))
        used |= context["baseline_keys"] | context["reserved"] | context["corpus_keys"]
        validation = [row for row in context["validation"]
                      if pilot.key(row["board"], row["side"]) not in used]
        expected_metrics = {"baseline": rf.mse(context["baseline"], validation),
                            "candidate": rf.mse(training.read_json(
                                output(predecessors["candidate-update"], "candidate-artifact.json")), validation)}
        require(validation and actual["validation_metrics"] == expected_metrics,
                "0019 validation metrics do not replay on the disjoint split")
    elif phase == "corpus-regret":
        games = all_game_records(context, predecessors)
        played = played_keys(context, games)
        base_ctx = {"baseline_keys": context["baseline_keys"], "reserved": context["reserved"],
                    "corpus_keys": context["corpus_keys"], "corpus": context["corpus"],
                    "golden": context["golden"]}
        records, _, _ = pilot.independent_corpus(base_ctx, played)
        decisions = training.read_jsonl(output(attempt, "decisions.jsonl"))
        require(len(decisions) == len(records) * 2, "0019 corpus decisions are incomplete")
        for row, decision in zip([item for record in records for item in (record, record)], decisions):
            legal = row["legal_moves"]
            require(decision["move"] in legal if legal else decision["move"] == "pass",
                    "0019 corpus decision is illegal")
        require(training.read_json(output(attempt, "report.json"))
                == pilot.corpus_metrics(base_ctx, decisions, played),
                "0019 corpus-regret report does not replay")
    elif phase == "oracle-match":
        report = training.read_json(output(attempt, "match.json"))
        saved_games = training.read_jsonl(output(attempt, "games.jsonl"))
        expected_games = manifest["requested_counts"]["oracle_match_games"]
        require(report["games"] == expected_games and len(report["results"]) == expected_games
                and saved_games == report["results"],
                "0019 Oracle match game count mismatch")
        expected_summary = {name: 0 for name in ("candidate_win", "oracle_win", "draw")}
        origins_path = attempt / "game-provenance.jsonl"
        origins = training.read_jsonl(origins_path) if origins_path.exists() else None
        require((origins is not None or not (attempt / "provenance.json").exists())
                and (origins is None or len(origins) == expected_games), "Oracle game provenance count mismatch")
        for index, game in enumerate(report["results"]):
            game_manifest = manifest
            if origins is not None:
                origin = origins[index]
                game_manifest = verify_game_origin(context, attempt, game, origin)
            require(game_manifest["match_config"] == manifest["match_config"],
                    "Oracle game origin candidate configuration differs")
            require(game_manifest["openings"]["oracle-match"][index // 2][index % 2]
                    == manifest["openings"]["oracle-match"][index // 2][index % 2],
                    "Oracle game origin opening differs from attempt")
            validate_oracle_game(game_manifest, game, index)
            expected_summary[game["result"]] += 1
        expected_summary["games"] = expected_games
        expected_summary["match_points"] = expected_summary["candidate_win"] + expected_summary["draw"] * 0.5
        require(report["summary"] == expected_summary
                and report["profile"] == manifest["oracle_profile"],
                "0019 Oracle match summary or profile does not replay")
    elif phase == "offline-verification":
        report = training.read_json(output(attempt, "report.json"))
        require(report["schema_version"] == 2 and report["run_status"] == "complete"
                and report.get("execution_commit") == context.get("original_manifest", manifest)["execution_commit"],
                "0019 final report is incomplete")
        expected = build_final_report(context, predecessors, report["manifest_sha256"])
        require(report == expected, "0019 final report does not reconstruct from verified phase outputs")


def run_phase(context: dict, run_root: Path, manifest_digest: str, phase: str,
              predecessors: dict[str, Path], progress_every: int) -> Path:
    progress = rf.Progress(progress_every)
    started = progress.stage_start(phase)

    def action(attempt: Path) -> None:
        if phase == "input-verification":
            phase_input_verification(context, attempt)
        elif phase == "self-play":
            phase_self_play(context, attempt, progress_every)
        elif phase == "candidate-update":
            phase_candidate_update(context, predecessors, attempt)
        elif phase == "baseline-match":
            phase_baseline_match(context, predecessors, attempt, progress_every)
        elif phase == "candidate-selection":
            phase_candidate_selection(context, predecessors, attempt)
        elif phase == "corpus-regret":
            phase_corpus_regret(context, predecessors, attempt, progress_every)
        elif phase == "oracle-match":
            phase_oracle_match(context, predecessors, attempt, progress_every)
        else:
            all_predecessors = {}
            for prior in PHASES[:-1]:
                found = latest_success(run_root, prior, manifest_digest)
                require(found is not None, f"offline verification requires completed phase {prior}")
                verify_receipt(found[0], prior, manifest_digest)
                all_predecessors[prior] = found[0]
            check_dependencies(context, all_predecessors)
            verify_failed_attempts(run_root, context)
            for prior in PHASES[:-1]:
                semantic_phase_check(context, prior, all_predecessors[prior], all_predecessors)
            report = build_final_report(context, all_predecessors, manifest_digest)
            rf.atomic_write(attempt, "report.json", blob(report))
        semantic_phase_check(context, phase, attempt, predecessors)

    attempt = write_attempt(run_root, phase, manifest_digest, action,
                            attempt_provenance(context, phase, predecessors))
    progress.stage_done(phase, started)
    return attempt


def build_final_report(context: dict, predecessors: dict[str, Path], manifest_digest: str) -> dict:
    manifest = copy.deepcopy(context["manifest"])
    for phase, field in (("self-play", "self_play_games"), ("baseline-match", "baseline_comparison_games"),
                         ("oracle-match", "oracle_match_games")):
        phase_manifest = attempt_context(context, predecessors[phase], phase)["manifest"]
        manifest["requested_counts"][field] = phase_manifest["requested_counts"][field]
        manifest["openings"][phase] = phase_manifest["openings"][phase]
        if phase == "oracle-match":
            manifest["match_config"] = phase_manifest["match_config"]
    manifest["max_decisions"] = sum(manifest["requested_counts"].values()) * 120 + len(context["corpus"]) * 2
    manifest["execution_commit"] = context.get("original_manifest", manifest)["execution_commit"]
    selection = training.read_json(output(predecessors["candidate-selection"], "selection.json"))
    regret = training.read_json(output(predecessors["corpus-regret"], "report.json"))
    oracle_report = training.read_json(output(predecessors["oracle-match"], "match.json"))
    selfplay = training.read_jsonl(output(predecessors["self-play"], "games.jsonl"))
    comparison = training.read_jsonl(output(predecessors["baseline-match"], "games.jsonl"))
    oracle_games = oracle_report["results"]
    corpus_decisions = training.read_jsonl(output(predecessors["corpus-regret"], "decisions.jsonl"))
    decision_count = sum(len(game["decisions"]) for game in selfplay + comparison + oracle_games) \
        + len(corpus_decisions)
    require(decision_count <= manifest["max_decisions"], "0019 run exceeded its frozen decision cap")
    exposures = {"opening": set(), "decision": set(), "terminal": set(),
                 "validation": set(selection["validation_position_keys"]), "corpus": set()}
    for phase in ("self-play", "baseline-match", "oracle-match"):
        for pair in manifest["openings"][phase]:
            for opening in pair:
                exposures["opening"].add(pilot.key(opening["board"], opening["side"]))
    for game in selfplay + comparison:
        exposures["decision"].update(pilot.key(row["board"], row["side"]) for row in game["decisions"])
        exposures["terminal"].update(pilot.key(game["terminal_board"], side) for side in ("B", "W"))
    for game in oracle_games:
        exposures["opening"].add(pilot.key(game["start_board"], game["start_side"]))
        exposures["decision"].update(pilot.key(row["board"], row["side"]) for row in game["decisions"])
        exposures["terminal"].update(pilot.key(game["terminal_board"], side) for side in ("B", "W"))
    exposures["corpus"].update(pilot.key(row["board"], row["side"]) for row in corpus_decisions)
    candidate_path = output(predecessors["candidate-update"], "candidate-artifact.json")
    selected_digest = candidate_path if selection["selected"] == "candidate" else context["paths"]["baseline_artifact"]
    return {
        "schema_version": 2, "run_status": "complete", "producer_version": VERSION,
        "manifest_sha256": manifest_digest, "score_contract": training.SCORE_CONTRACT,
        "execution_commit": manifest["execution_commit"],
        "input_bundle_sha256": manifest["input_bundle"]["sha256"],
        "bundle_verification_receipt_sha256": manifest["bundle_verification_receipt"]["sha256"],
        "candidate_executable_sha256": manifest["candidate_executable"]["sha256"],
        "baseline_artifact_sha256": manifest["inputs"]["baseline_artifact"]["sha256"],
        "candidate_artifact_sha256": training.sha256_file(candidate_path),
        "selected_artifact_sha256": training.sha256_file(selected_digest),
        "selected_artifact": selection["selected"],
        "selected_artifact_relative_path": (str(output(predecessors["candidate-update"],
            "candidate-artifact.json").relative_to(context["manifest_path"].parent))
            if selection["selected"] == "candidate" else "input:baseline_artifact"),
        "requested_counts": manifest["requested_counts"],
        "actual_counts": {"self_play_games": len(selfplay), "baseline_comparison_games": len(comparison),
                          "oracle_match_games": oracle_report["games"]},
        "decision_count": decision_count,
        "max_decisions": manifest["max_decisions"],
        "self_play": {"games": len(selfplay), "teacher_rows": len(training.read_jsonl(
            output(predecessors["candidate-update"], "teacher-rows.jsonl")))},
        "baseline_comparison": selection["match"], "candidate_selection": selection,
        "validation_metrics": selection["validation_metrics"], "corpus_regret": regret,
        "oracle_match": {"profile": oracle_report["profile"], "summary": oracle_report["summary"],
                         "oracle_exact_solver_empty_squares": manifest[
                             "oracle_exact_solver_empty_squares"],
                         "candidate_config": manifest["match_config"]},
        "exposure_keys": {name: sorted(values) for name, values in exposures.items()},
        "phase_receipts": {phase: verify_receipt(predecessors[phase], phase, manifest_digest)["receipt_digest"]
                           for phase in PHASES[:-1]},
        "phase_provenance": {phase: (training.read_json(path / "provenance.json")
                              if (path / "provenance.json").exists() else
                              {"legacy_manifest_sha256": manifest_digest,
                               "execution_commit": context.get("original_manifest", manifest)["execution_commit"],
                               "effective_settings": settings(context.get("original_manifest", manifest))})
                             for phase, path in predecessors.items() if phase != "offline-verification"},
        "failed_attempts": {str(path.relative_to(context["manifest_path"].parent)):
                            {"failure_sha256": training.sha256_file(path / "failure.json"),
                             "provenance": training.read_json(path / "provenance.json")
                                if (path / "provenance.json").exists() else
                                {"legacy_manifest_sha256": manifest_digest}}
                            for phase in PHASES for path in phase_dirs(context["manifest_path"].parent, phase)
                            if (path / "failure.json").exists()},
        "oracle_game_provenance": (training.read_jsonl(predecessors["oracle-match"] / "game-provenance.jsonl")
                                   if (predecessors["oracle-match"] / "game-provenance.jsonl").exists() else []),
    }


def runtime_representatives(opening: dict) -> list[dict]:
    """Replay the opening, keeping only positions with a legal move."""
    board, side = opening["board"], opening["side"]
    candidates = []
    last_legal = None
    for target in (board.count("B") + board.count("W"), 30, 48):
        while True:
            legal = rf.legal_moves(board, side)
            if not legal:
                side = rf.other(side)
                legal = rf.legal_moves(board, side)
                if not legal:
                    break
            occupied = board.count("B") + board.count("W")
            last_legal = {"board": board, "side": side, "actual_occupied_count": occupied}
            if occupied >= target:
                break
            board, side = rf.apply_move(board, side, legal[0]), rf.other(side)
        require(last_legal is not None,
                "runtime estimate could not select a legal representative position")
        candidates.append({**last_legal, "requested_occupied_count": target})
    return candidates


def runtime_estimate(context: dict) -> dict:
    """Measure three bounded Oracle roots, then project the requested match."""
    candidates = runtime_representatives(context["manifest"]["openings"]["oracle-match"][0][0])
    samples, project_samples = [], []
    binary = Path(context["manifest"]["oracle_binary"]["path"])
    project = rf.Candidate(Path(context["manifest"]["candidate_executable"]["path"]),
        Path(context["paths"]["baseline_artifact"]), context["manifest"]["match_config"],
        context["manifest"]["decision_timeout_seconds"], capture_diagnostics=True)
    try:
        for index, item in enumerate(candidates):
            started = time.monotonic()
            oracle_module.run_solve([(item["board"], item["side"])], binary, binary.parent,
                                    ORACLE_PROFILE, context["manifest"]["decision_timeout_seconds"],
                                    child_query=False)
            samples.append(time.monotonic() - started)
            project.new_game(f"0019-runtime-estimate-{index}")
            project_started = time.monotonic()
            project.choose_with_diagnostic(f"0019-runtime-estimate-{index}", item["board"], item["side"])
            project_samples.append(time.monotonic() - project_started)
    finally:
        project.close()
    average = sum(samples) / len(samples)
    project_average = sum(project_samples) / len(project_samples)
    requested = context["manifest"]["requested_counts"]
    core_scales = (991.8 * requested["baseline_comparison_games"] / 20,
                   991.8 * requested["self_play_games"] / 6)
    core_low, core_high = min(core_scales), max(core_scales)
    oracle_seconds = (average + project_average) * 29 * requested["oracle_match_games"]
    measurements = [{"phase": phase,
                     "requested_occupied_count": item["requested_occupied_count"],
                     "actual_occupied_count": item["actual_occupied_count"],
                     "oracle_seconds": round(oracle_seconds, 3),
                     "candidate_seconds": round(candidate_seconds, 3)}
                    for phase, item, oracle_seconds, candidate_seconds in zip(
                        ("opening", "midgame", "endgame"), candidates, samples, project_samples)]
    return {"core_seconds": [round(core_low, 1), round(core_high, 1)],
            "representative_searches": measurements,
            "estimated_oracle_decisions_per_game": 29,
            "oracle_match_seconds": round(oracle_seconds, 1),
            "combined_seconds": [round(core_low + oracle_seconds, 1), round(core_high + oracle_seconds, 1)]}


def execute(args) -> dict:
    require(args.oracle_binary is not None, "0019 requires the pinned Egaroucid executable path")
    execution_commit = source_commit()
    require(isinstance(execution_commit, str) and re.fullmatch(r"[0-9a-f]{40}", execution_commit),
            "invalid 0019 execution commit")
    training.require_int(args.seed, "seed", 0, 2**64 - 1)
    training.require_int(args.opening_plies, "opening plies", 4, 20)
    training.require_int(args.time_limit_ms, "time limit", 1)
    training.require_int(args.node_limit, "node limit", 1)
    training.require_int(args.decision_timeout_seconds, "decision timeout", 1, 3600)
    require(args.decision_timeout_seconds * 1000 > args.time_limit_ms,
            "decision timeout must exceed the candidate search limit")
    training.require_int(args.progress_every, "progress interval", 1)
    count_limits = {"self_play_games": 64, "baseline_comparison_games": 200,
                    "oracle_match_games": 200}
    for name, maximum in count_limits.items():
        value = training.require_int(getattr(args, name), name, 2, maximum)
        require(value % 2 == 0, f"{name} must contain complete color-swapped pairs")
    require(args.oracle_match_games > 0, "0019 Oracle match must contain at least one color-swapped pair")
    run_root = args.run_root.resolve()
    repository_root = Path(pilot.__file__).resolve().parents[2]
    require(args.run_root.is_absolute() and run_root != repository_root
            and repository_root not in run_root.parents,
            "0019 run root must be absolute and outside the source checkout")
    manifest_path = run_root / "manifest.json"
    if args.resume_from:
        require(run_root.is_dir() and manifest_path.is_file(), "resume requires an existing 0019 run root")
        manifest = checked_manifest(manifest_path)
        require(manifest["input_bundle"] == file_entry(args.input_bundle)
                and manifest["bundle_verification_receipt"] == file_entry(args.bundle_verification_receipt)
                and manifest["candidate_executable"] == file_entry(args.candidate_executable)
                and manifest["oracle_binary"] == file_entry(args.oracle_binary),
                "resume input identities differ from the frozen 0019 manifest")
        require(not (run_root / "report.json").exists(),
                "0019 run is already complete and cannot be resumed")
    else:
        require(not run_root.exists(), "0019 run root already exists; resume it or choose a fresh path")
        run_root.mkdir(parents=True, exist_ok=False)
        try:
            manifest = make_manifest(args, run_root, execution_commit)
            rf.atomic_write(run_root, "manifest.json", blob(manifest))
        except BaseException:
            try:
                run_root.rmdir()
            except OSError:
                pass
            raise
    manifest = checked_manifest(manifest_path)
    context = load_context(manifest_path)
    context["original_manifest"] = copy.deepcopy(manifest)
    context["execution_commit"] = execution_commit
    context["resume_from"] = args.resume_from
    context["progress_every"] = args.progress_every
    manifest_digest = training.sha256_file(manifest_path)
    start = args.resume_from or PHASES[0]
    require(start in PHASES, "invalid --resume-from phase")
    if args.resume_from:
        predecessors = require_predecessors(run_root, start, manifest_digest)
        check_dependencies(context, predecessors)
        verify_failed_attempts(run_root, context)
        for phase, attempt in predecessors.items():
            semantic_phase_check(context, phase, attempt, predecessors)
    else:
        predecessors = {}
    context = invocation_context(context, args, predecessors)
    # Print the bounded representative-search estimate before expensive phases.
    if not args.resume_from:
        estimate = runtime_estimate(context)
        print("0019 runtime estimate " + json.dumps(estimate, sort_keys=True), file=sys.stderr, flush=True)
    for phase in PHASES[PHASES.index(start):]:
        if phase == "candidate-update":
            predecessors.update({"self-play": latest_success(run_root, "self-play", manifest_digest)[0]})
        elif phase == "baseline-match":
            predecessors.update({"candidate-update": latest_success(run_root, "candidate-update", manifest_digest)[0]})
        elif phase == "candidate-selection":
            predecessors.update({"baseline-match": latest_success(run_root, "baseline-match", manifest_digest)[0]})
        elif phase == "corpus-regret":
            predecessors.update({"candidate-selection": latest_success(run_root, "candidate-selection", manifest_digest)[0]})
        elif phase == "oracle-match":
            predecessors.update({"corpus-regret": latest_success(run_root, "corpus-regret", manifest_digest)[0]})
        elif phase == "offline-verification":
            predecessors = {name: latest_success(run_root, name, manifest_digest)[0]
                            for name in PHASES[:-1]}
        attempt = run_phase(context, run_root, manifest_digest, phase, predecessors, args.progress_every)
        predecessors[phase] = attempt
        if phase == "offline-verification":
            report = training.read_json(output(attempt, "report.json"))
            semantic_phase_check(context, phase, attempt, predecessors)
            rf.atomic_write(run_root, "report.json", blob(report))
    report_path = run_root / "report.json"
    require(report_path.is_file(), "0019 report was not published")
    report = training.read_json(report_path)
    print(f"0019 verified report={report_path} digest={training.digest(report)}")
    return report
