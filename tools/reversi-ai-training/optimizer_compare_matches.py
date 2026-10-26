"""Bounded, resumable diagnostic games for the frozen 0052 comparison.

Preparation and verification are offline. Only ``run`` starts players, and
the caller must pass the strict integer-validation gate before invoking it.
"""

from __future__ import annotations

from pathlib import Path

import pilot
import production_cycle as cycle
import reinforcement as rf
import training

VERSION = "optimizer-comparison-matches-v1"
CONFIG = {**cycle.MATCH_CONFIG, "time_limit_ms": 300000, "node_limit": 10000000}
COUNT = 20
FILES = {"binding.json", "games.jsonl", "corpus-decisions.jsonl", "oracle-games.jsonl", "report.json"}
MATCH_LED_VERSION = "optimizer-comparison-match-led-v1"
MATCH_LED_FIRST_COUNT = 20
MATCH_LED_TOTAL_COUNT = 200
MATCH_LED_ORACLE_COUNT = 20
MATCH_LED_FILES = {
    "binding.json", "games.jsonl", "corpus-decisions.jsonl", "oracle-games.jsonl",
    "stage-20.receipt.json", "stage-200.receipt.json", "oracle.receipt.json",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise training.TrainingError(message)


def _source(context: dict) -> dict:
    return context.get("source_context", context)


def _forbidden(context: dict) -> set[str]:
    source = _source(context)
    result = set(source.get("reserved", set())) | set(source.get("baseline_keys", set()))
    exposures = context.get("exposure_keys", {})
    if isinstance(exposures, dict):
        for values in exposures.values():
            result.update(values)
    else:
        result.update(exposures)
    for name in ("teachers", "validation", "held_out"):
        result.update(pilot.key(row["board"], row["side"]) for row in context.get(name, []))
    result.update(pilot.key(row["board"], row["side_to_move"])
                  for row in context.get("corpus", source.get("corpus", [])))
    for opening in context.get("evaluation_excluded_openings", []):
        if isinstance(opening, dict) and isinstance(opening.get("board"), str):
            result.add(pilot.key(opening["board"], opening["side"]))
    return result


def _openings(context: dict, seed: int) -> dict:
    forbidden = _forbidden(context)
    reserved = set(_source(context).get("reserved", set()))
    result = {}
    for name in ("comparison", "oracle-match"):
        roots = pilot.opening_pool(seed, 6, COUNT // 2, forbidden,
                                  f"{VERSION}-{name}", reserved=reserved)
        pairs = [[{**root, "rotation": 0}, cycle.transform_opening(root, 2)] for root in roots]
        forbidden.update(pilot.key(root["board"], root["side"]) for root in roots)
        result[name] = pairs
    return result


def _prepare(context: dict, seed: int, candidate_executable: Path,
             oracle_binary: Path, timeout: int, *, match_led: bool) -> dict:
    """Freeze executable identities, profiles and both disjoint opening sets."""
    training.require_int(seed, "comparison seed", 0, 2**64 - 1)
    training.require_int(timeout, "comparison timeout", 301, 3600)
    source_manifest = _source(context)["manifest"]
    oracle_entry = cycle.file_entry(oracle_binary)
    require(oracle_entry["sha256"] == source_manifest["oracle_binary"]["sha256"],
            "comparison Oracle differs from pinned 0019 binary")
    profile = pilot.oracle.profile_metadata(cycle.ORACLE_PROFILE)
    require(source_manifest["oracle_profile"] == profile,
            "comparison Oracle profile differs from pinned 0019 profile")
    require(source_manifest.get("oracle_version") == pilot.oracle.ORACLE_VERSION
            and source_manifest.get("oracle_source_sha256") == pilot.oracle.SOURCE_SHA256,
            "comparison Oracle source/version differs from pinned 0019 identity")
    pair_count = MATCH_LED_TOTAL_COUNT // 2 if match_led else COUNT // 2
    version = MATCH_LED_VERSION if match_led else VERSION
    forbidden = _forbidden(context)
    reserved = set(_source(context).get("reserved", set()))
    openings = {}
    for name, count in (("comparison", pair_count), ("oracle-match", MATCH_LED_ORACLE_COUNT // 2)):
        roots = pilot.opening_pool(seed, 6, count, forbidden, f"{version}-{name}", reserved=reserved)
        pairs = [[{**root, "rotation": 0}, cycle.transform_opening(root, 2)] for root in roots]
        forbidden.update(pilot.key(root["board"], root["side"]) for root in roots)
        openings[name] = pairs
    settings = {"version": version, "seed": seed, "decision_timeout_seconds": timeout,
            "candidate_executable": cycle.file_entry(candidate_executable),
            "oracle_binary": oracle_entry,
            "oracle_version": source_manifest["oracle_version"],
            "oracle_source_sha256": source_manifest["oracle_source_sha256"],
            "match_config": dict(CONFIG), "oracle_profile": profile,
            "oracle_profile_id": cycle.ORACLE_PROFILE.name,
            "oracle_exact_solver_empty_squares": pilot.oracle.profile_exact_threshold(cycle.ORACLE_PROFILE),
            "openings": openings,
            "requested_games": MATCH_LED_TOTAL_COUNT if match_led else COUNT}
    if match_led:
        settings["initial_games"] = MATCH_LED_FIRST_COUNT
        settings["oracle_requested_games"] = MATCH_LED_ORACLE_COUNT
    return settings


def prepare(context: dict, seed: int, candidate_executable: Path,
            oracle_binary: Path, timeout: int) -> dict:
    return _prepare(context, seed, candidate_executable, oracle_binary, timeout, match_led=False)


def prepare_match_led(context: dict, seed: int, candidate_executable: Path,
                      oracle_binary: Path, timeout: int) -> dict:
    """Freeze 100 baseline opening pairs and ten disjoint Oracle pairs."""
    return _prepare(context, seed, candidate_executable, oracle_binary, timeout, match_led=True)


def validate_settings(context: dict, settings: dict) -> None:
    prepare_fn = prepare_match_led if settings.get("version") == MATCH_LED_VERSION else prepare
    expected = prepare_fn(context, settings["seed"], Path(settings["candidate_executable"]["path"]),
                          Path(settings["oracle_binary"]["path"]), settings["decision_timeout_seconds"])
    require(pilot.same(settings, expected), "comparison settings or input identities differ from preparation")


def skipped(reason: str) -> dict:
    require(isinstance(reason, str) and bool(reason), "skipped comparison requires a reason")
    return {"comparison": {"status": "not-run", "reason": reason, "games": 0,
                           "wins": 0, "losses": 0, "draws": 0, "match_points": 0},
            "oracle": {"status": "not-run", "reason": reason, "games": 0,
                       "summary": {"candidate_win": 0, "oracle_win": 0, "draw": 0,
                                   "games": 0, "match_points": 0}},
            "corpus": {"status": "not-run", "reason": reason, "positions": 0}}


def _adopted_path(context: dict) -> Path:
    if "adopted_path" in context:
        return Path(context["adopted_path"])
    source = _source(context)
    manifest_path = source["manifest_path"]
    found = cycle.latest_success(manifest_path.parent, "candidate-update", training.sha256_file(manifest_path))
    require(found is not None, "comparison adopted candidate phase missing")
    return cycle.output(found[0], "candidate-artifact.json")


def _binding(context: dict, settings: dict, artifact_path: Path) -> dict:
    artifact = training.read_json(artifact_path)
    adopted_path = _adopted_path(context)
    adopted = training.read_json(adopted_path)
    training.validate_artifact(artifact)
    training.validate_artifact(adopted)
    require(adopted == context["adopted"], "comparison adopted artifact differs from frozen input")
    return {"version": VERSION, "settings_digest": training.digest(settings),
            "candidate_artifact": cycle.file_entry(artifact_path),
            "adopted_artifact": cycle.file_entry(adopted_path)}


def _load_rows(output: Path, name: str) -> list[dict]:
    path = output / name
    return training.read_jsonl(path) if path.exists() else []


def _write_rows(output: Path, name: str, rows: list[dict]) -> None:
    rf.atomic_write(output, name, pilot.lines(rows))


def _telemetry(telemetry: dict, board: str, side: str) -> None:
    require(isinstance(telemetry, dict)
            and type(telemetry.get("nodes")) is int and 0 <= telemetry["nodes"] <= CONFIG["node_limit"]
            and type(telemetry.get("elapsed_us")) is int
            and 0 <= telemetry["elapsed_us"] <= CONFIG["time_limit_ms"] * 1000
            and type(telemetry.get("completed_depth")) is int and telemetry["completed_depth"] >= 0
            and type(telemetry.get("exact")) is bool
            and telemetry.get("outcome") in ("move", "pass", "game_over"),
            "comparison candidate resource evidence is missing or exceeds limits")
    if rf.legal_moves(board, side) and board.count(".") <= CONFIG["exact_solver_empty_squares"]:
        require(telemetry["exact"], "comparison candidate omitted a required exact solve")


class _Player:
    def __init__(self, settings: dict, artifact: Path, reserved: set[str]):
        self.inner = rf.Candidate(Path(settings["candidate_executable"]["path"]), artifact,
                                  settings["match_config"], settings["decision_timeout_seconds"],
                                  capture_diagnostics=True)
        self.reserved, self.decisions = reserved, {}

    def new_game(self, identifier: str) -> None:
        self.decisions.clear()
        self.inner.new_game(identifier)

    def choose_with_diagnostic(self, identifier: str, board: str, side: str):
        require(pilot.key(board, side) not in self.reserved,
                "comparison visited a reserved 0018 position")
        move, telemetry = self.inner.choose_with_diagnostic(identifier, board, side)
        _telemetry(telemetry, board, side)
        self.decisions[identifier] = telemetry
        return move, telemetry

    def choose(self, identifier: str, board: str, side: str) -> str:
        return self.choose_with_diagnostic(identifier, board, side)[0]

    def close(self) -> None:
        self.inner.close()


def _verify_games(context: dict, settings: dict, games: list[dict], *, maximum: int = COUNT,
                  start_index: int = 0) -> None:
    require(start_index >= 0 and start_index + len(games) <= maximum,
            f"comparison completed prefix exceeds {maximum} games")
    reserved = set(_source(context).get("reserved", set()))
    for offset, game in enumerate(games):
        index = start_index + offset
        opening = settings["openings"]["comparison"][index // 2][index % 2]
        seats = {"B": "candidate", "W": "baseline"} if index % 2 == 0 else {"B": "baseline", "W": "candidate"}
        require(game.get("kind") == "optimizer-comparison" and game["pair"] == index // 2
                and game["member"] == index % 2 and game["players"] == seats
                and game["opening"] == opening["moves"] and game["rotation"] == opening["rotation"]
                and game["start_board"] == opening["board"] and game["start_side"] == opening["side"],
                "comparison completed game differs from frozen opening or seat")
        rf.replay(game)
        require(len(game["decisions"]) <= 120, "comparison game exceeds decision cap")
        for turn, decision in enumerate(game["decisions"]):
            require(decision["id"] == f"optimizer-comparison-p{index // 2}-m{index % 2}-t{turn}",
                    "comparison game decision identity mismatch")
            require(pilot.key(decision["board"], decision["side"]) not in reserved,
                    "comparison game visited a reserved 0018 position")
            if rf.legal_moves(decision["board"], decision["side"]):
                _telemetry(decision.get("search_telemetry"), decision["board"], decision["side"])


def _corpus_metrics(context: dict, decisions: list[dict], *, complete: bool) -> dict:
    records, goldens = context["corpus"], context["golden"]
    require(len(records) > 0 and len(records) == len(goldens), "comparison corpus is empty or unpaired")
    require(len(decisions) <= len(records) * 2
            and (not complete or len(decisions) == len(records) * 2), "incomplete comparison corpus decisions")
    sums = {"baseline": 0, "candidate": 0}
    reserved = set(_source(context).get("reserved", set()))
    for index, decision in enumerate(decisions):
        row, golden = records[index // 2], goldens[index // 2]
        player = "baseline" if index % 2 == 0 else "candidate"
        require(decision["position_id"] == row["position_id"] and decision["board"] == row["board"]
                and decision["side"] == row["side_to_move"] and decision["player"] == player,
                "comparison corpus decision identity mismatch")
        require(pilot.key(row["board"], row["side_to_move"]) not in reserved,
                "comparison corpus overlaps a reserved 0018 position")
        legal = row["legal_moves"]
        require(decision["move"] in legal if legal else decision["move"] == "pass",
                "comparison corpus decision is illegal")
        _telemetry(decision.get("search_telemetry"), row["board"], row["side_to_move"])
        analysis = golden["analysis"]
        values = {value["move"]: value["value"] for value in analysis["evaluations"]}
        sums[player] += analysis["best_value"] - values[decision["move"]] if legal else 0
    return {"status": "complete" if complete else "partial",
            **{player: {"positions": len(records), "sum_regret": value,
                        "mean_regret": value / len(records)} for player, value in sums.items()}}


def _verify_oracle(context: dict, settings: dict, games: list[dict], allowed: bool) -> dict:
    require(len(games) <= COUNT and (allowed or not games), "Oracle games violate comparison gate or cap")
    for index, game in enumerate(games):
        cycle.validate_oracle_game(settings, game, index)
        reserved = set(_source(context).get("reserved", set()))
        require(all(pilot.key(row["board"], row["side"]) not in reserved for row in game["decisions"]),
                "comparison Oracle game visited a reserved 0018 position")
    if not allowed:
        return skipped("B did not score strictly more than 10/20 against adopted A")["oracle"]
    summary = {name: sum(game["result"] == name for game in games)
               for name in ("candidate_win", "oracle_win", "draw")}
    summary.update(games=len(games), match_points=summary["candidate_win"] + summary["draw"] * .5)
    return {"status": "complete" if len(games) == COUNT else "partial", "games": len(games),
            "summary": summary}


def run(context: dict, settings: dict, artifact_path: Path, output: Path, progress=None) -> dict:
    """Play only unfinished games. Failed processes preserve the completed prefix."""
    validate_settings(context, settings)
    binding = _binding(context, settings, artifact_path)
    output.mkdir(parents=True, exist_ok=True)
    require(not ({path.name for path in output.iterdir()} - FILES), "unexpected comparison match output")
    if (output / "binding.json").exists():
        require(training.read_json(output / "binding.json") == binding,
                "comparison resume settings or artifacts changed")
    else:
        require(not list(output.iterdir()), "comparison output has data without its identity binding")
        rf.atomic_write(output, "binding.json", pilot.blob(binding))
    games = _load_rows(output, "games.jsonl")
    decisions = _load_rows(output, "corpus-decisions.jsonl")
    oracle_games = _load_rows(output, "oracle-games.jsonl")
    _verify_games(context, settings, games)
    _corpus_metrics(context, decisions, complete=False)
    require(not oracle_games or len(decisions) == len(context["corpus"]) * 2,
            "saved Oracle games precede completed corpus diagnostics")
    _verify_oracle(context, settings, oracle_games,
                   len(games) == COUNT and rf.match_summary(games)["match_points"] > 10)
    if (output / "report.json").exists():
        return verify(context, settings, artifact_path, output)
    emit = progress or (lambda phase, completed, total: None)
    emit("matches", len(games), COUNT)
    reserved = set(_source(context).get("reserved", set()))
    players = {}
    try:
        players["baseline"] = _Player(settings, _adopted_path(context), reserved)
        players["candidate"] = _Player(settings, artifact_path, reserved)
        remaining = [COUNT * 120 - sum(len(game["decisions"]) for game in games)]
        for index in range(len(games), COUNT):
            pair, member = divmod(index, 2)
            opening = settings["openings"]["comparison"][pair][member]
            seats = {"B": "candidate", "W": "baseline"} if member == 0 else {"B": "baseline", "W": "candidate"}
            game = rf.play("optimizer-comparison", pair, member, opening["board"], opening["side"],
                           opening["moves"], opening["rotation"], players, seats, remaining)
            for decision in game["decisions"]:
                if rf.legal_moves(decision["board"], decision["side"]):
                    decision["search_telemetry"] = players[seats[decision["side"]]].decisions[decision["id"]]
            game.pop("game_digest")
            game["game_digest"] = training.digest(game)
            games.append(game)
            _verify_games(context, settings, games)
            _write_rows(output, "games.jsonl", games)
            emit("matches", len(games), COUNT)
        emit("corpus", len(decisions), len(context["corpus"]) * 2)
        for index in range(len(decisions), len(context["corpus"]) * 2):
            row = context["corpus"][index // 2]
            name = "baseline" if index % 2 == 0 else "candidate"
            identifier = f"optimizer-corpus-{index // 2}-{name}"
            players[name].new_game(identifier)
            move, telemetry = players[name].choose_with_diagnostic(identifier, row["board"], row["side_to_move"])
            decisions.append({"position_id": row["position_id"], "board": row["board"],
                              "side": row["side_to_move"], "player": name, "move": move,
                              "search_telemetry": telemetry})
            _corpus_metrics(context, decisions, complete=False)
            _write_rows(output, "corpus-decisions.jsonl", decisions)
            emit("corpus", len(decisions), len(context["corpus"]) * 2)
        allowed = rf.match_summary(games)["match_points"] > 10
        emit("oracle-match", len(oracle_games), COUNT if allowed else 0)
        if allowed:
            def save_game(game):
                cycle.validate_oracle_game(settings, game, len(oracle_games))
                oracle_games.append(game)
                _write_rows(output, "oracle-games.jsonl", oracle_games)
                emit("oracle-match", len(oracle_games), COUNT)
            binary = Path(settings["oracle_binary"]["path"])
            pilot.oracle.run_profiled_match(binary, binary.parent, players["candidate"],
                settings["openings"]["oracle-match"], cycle.ORACLE_PROFILE, settings["match_config"],
                settings["decision_timeout_seconds"], 1, on_game=save_game, initial_games=oracle_games)
    finally:
        for player in players.values():
            player.close()
    for name, rows in (("games.jsonl", games), ("corpus-decisions.jsonl", decisions),
                       ("oracle-games.jsonl", oracle_games)):
        _write_rows(output, name, rows)
    report = _reconstruct(context, settings, games, decisions, oracle_games)
    rf.atomic_write(output, "report.json", pilot.blob(report))
    return verify(context, settings, artifact_path, output)


def _reconstruct(context: dict, settings: dict, games: list[dict], decisions: list[dict],
                 oracle_games: list[dict]) -> dict:
    _verify_games(context, settings, games)
    require(len(games) == COUNT, "comparison match is incomplete")
    comparison = {"status": "complete", **rf.match_summary(games)}
    corpus = _corpus_metrics(context, decisions, complete=True)
    oracle = _verify_oracle(context, settings, oracle_games, comparison["match_points"] > 10)
    require(oracle["status"] in ("complete", "not-run"), "comparison Oracle match is incomplete")
    report = {"comparison": comparison, "oracle": oracle, "corpus": corpus}
    report["report_digest"] = training.digest(report)
    return report


def verify(context: dict, settings: dict, artifact_path: Path, output: Path) -> dict:
    """Read/replay saved evidence only; never launch a candidate or Oracle."""
    validate_settings(context, settings)
    require(output.is_dir() and {path.name for path in output.iterdir()} == FILES,
            "comparison match outputs are missing or unexpected")
    require(training.read_json(output / "binding.json") == _binding(context, settings, artifact_path),
            "comparison artifact/settings binding changed")
    report = _reconstruct(context, settings, _load_rows(output, "games.jsonl"),
                          _load_rows(output, "corpus-decisions.jsonl"), _load_rows(output, "oracle-games.jsonl"))
    require(training.read_json(output / "report.json") == report, "comparison match report does not replay")
    return report


def _sealed_receipt(value: dict) -> dict:
    result = dict(value)
    result["digest"] = training.digest(result)
    return result


def _read_receipt(path: Path) -> dict:
    value = training.read_json(path)
    expected = dict(value)
    digest = expected.pop("digest", None)
    require(digest == training.digest(expected), f"changed match receipt {path}")
    return expected


def _write_once(output: Path, name: str, value: dict) -> None:
    path = output / name
    encoded = pilot.blob(value)
    if path.exists():
        require(path.read_bytes() == encoded, f"changed immutable match evidence {path}")
    else:
        rf.atomic_write(output, name, encoded)


def _match_led_stage_receipt(settings: dict, output: Path, games: list[dict], count: int) -> dict:
    stage_games = games[:count]
    summary = rf.match_summary(stage_games)
    value = {
        "version": MATCH_LED_VERSION,
        "stage": f"baseline-{count}",
        "settings_digest": training.digest(settings),
        "binding_sha256": training.sha256_file(output / "binding.json"),
        "game_digests": [game["game_digest"] for game in stage_games],
        "games_digest": training.digest(stage_games),
        "summary": summary,
    }
    if count == MATCH_LED_FIRST_COUNT:
        value["continuation_allowed"] = continuation_allowed(summary)
    else:
        stage20 = output / "stage-20.receipt.json"
        value["stage_20_receipt_sha256"] = training.sha256_file(stage20)
        value["outcome"] = "improved" if improved_after_200(summary) else "not-improved"
    return value


def continuation_allowed(summary: dict) -> bool:
    return summary["match_points"] >= 10


def improved_after_200(summary: dict) -> bool:
    return summary["match_points"] > 100


def _match_led_oracle_receipt(settings: dict, output: Path, games: list[dict]) -> dict:
    summary = _verify_oracle({}, settings, games, True)["summary"]
    return {
        "version": MATCH_LED_VERSION,
        "stage": "oracle-20",
        "settings_digest": training.digest(settings),
        "stage_200_receipt_sha256": training.sha256_file(output / "stage-200.receipt.json"),
        "game_digests": [game["game_digest"] for game in games],
        "games_digest": training.digest(games),
        "summary": summary,
    }


def _game_execution_identity(context: dict, settings: dict, artifact_path: Path) -> dict:
    return {
        "settings_digest": training.digest(settings),
        "decision_timeout_seconds": settings["decision_timeout_seconds"],
        "candidate_artifact_sha256": training.sha256_file(artifact_path),
        "baseline_artifact_sha256": cycle.file_entry(_adopted_path(context))["sha256"],
        "candidate_executable_sha256": settings["candidate_executable"]["sha256"],
        "baseline_executable_sha256": settings["candidate_executable"]["sha256"],
        "match_config": settings["match_config"],
    }


def _verify_match_led_games(context: dict, settings: dict, artifact_path: Path,
                            games: list[dict]) -> None:
    _verify_games(context, settings, games, maximum=MATCH_LED_TOTAL_COUNT)
    expected_identity = _game_execution_identity(context, settings, artifact_path)
    require(all(game.get("execution_identity") == expected_identity for game in games),
            "baseline game does not record the frozen timeout and participant identities")


def _match_led_summary(context: dict, settings: dict, games: list[dict], decisions: list[dict],
                       oracle_games: list[dict], stage20: dict | None,
                       stage200: dict | None) -> dict:
    summary = rf.match_summary(games)
    first = stage20["summary"] if stage20 else None
    full = stage200["summary"] if stage200 else None
    first_continues = bool(stage20 and stage20["continuation_allowed"])
    if len(games) < MATCH_LED_FIRST_COUNT:
        outcome, comparison_status = "pending-20", "partial"
    elif not first_continues:
        outcome, comparison_status = "not-improved", "complete"
    elif len(games) < MATCH_LED_TOTAL_COUNT:
        outcome, comparison_status = "pending-200", "partial"
    elif not improved_after_200(full):
        outcome, comparison_status = "not-improved", "complete"
    elif len(oracle_games) < MATCH_LED_ORACLE_COUNT:
        outcome, comparison_status = "pending-oracle", "complete"
    else:
        outcome, comparison_status = "improved", "complete"

    oracle_allowed = stage200 is not None and improved_after_200(full)
    oracle = _verify_oracle(context, settings, oracle_games, oracle_allowed)
    if oracle_allowed and not oracle_games:
        oracle = {**oracle, "status": "pending", "reason": "eligible Oracle diagnostic has not been run"}
    elif not oracle_allowed:
        if stage200 is not None:
            reason = "candidate scored 100/200 or less against baseline"
        elif stage20 is not None and not first_continues:
            reason = "20-game baseline match scored below the 10/20 continuation threshold"
        else:
            reason = "200-game baseline match is incomplete"
        oracle = {"status": "not-run", "reason": reason, "games": 0,
                  "summary": {"candidate_win": 0, "oracle_win": 0, "draw": 0,
                              "games": 0, "match_points": 0}}
    corpus_count = len(context.get("corpus", [])) * 2
    if not decisions:
        corpus = {"status": "not-run", "reason": "corpus diagnostics have not been run", "positions": 0}
    else:
        corpus = _corpus_metrics(context, decisions, complete=len(decisions) == corpus_count)
    complete = (outcome in ("improved", "not-improved") and corpus["status"] == "complete")
    return {
        "status": "complete" if complete else "pending",
        "outcome": outcome,
        "comparison": {"status": comparison_status, **summary},
        "stage_20": ({"status": "complete", "summary": first,
                      "continuation_allowed": first_continues} if first else {"status": "pending"}),
        "stage_200": ({"status": "complete", "summary": full,
                       "outcome": stage200["outcome"]} if full else {"status": "pending"}),
        "continuation": {
            "eligible": first_continues,
            "completed": stage200 is not None,
            "required_games": MATCH_LED_TOTAL_COUNT if first_continues else MATCH_LED_FIRST_COUNT,
        },
        "oracle": oracle,
        "corpus": corpus,
    }


def _expected_receipt(path: Path, expected: dict) -> dict | None:
    if not path.exists():
        return None
    actual = _read_receipt(path)
    require(actual == expected, f"match receipt does not replay: {path}")
    return actual


def verify_match_led(context: dict, settings: dict, artifact_path: Path, output: Path) -> dict:
    """Reconstruct staged match evidence without starting candidate or Oracle processes."""
    require(settings.get("version") == MATCH_LED_VERSION, "unsupported match-led settings")
    validate_settings(context, settings)
    if not output.exists():
        return _match_led_summary(context, settings, [], [], [], None, None)
    require(output.is_dir() and {path.name for path in output.iterdir()} <= MATCH_LED_FILES,
            "match-led outputs are unexpected")
    binding_path = output / "binding.json"
    games_path = output / "games.jsonl"
    decisions_path = output / "corpus-decisions.jsonl"
    oracle_path = output / "oracle-games.jsonl"
    require(binding_path.is_file(), "match-led binding is missing")
    require(training.read_json(binding_path) == _binding(context, settings, artifact_path),
            "match-led artifact/settings binding changed")
    games = _load_rows(output, "games.jsonl")
    decisions = _load_rows(output, "corpus-decisions.jsonl")
    oracle_games = _load_rows(output, "oracle-games.jsonl")
    _verify_match_led_games(context, settings, artifact_path, games)
    require(len(decisions) <= len(context.get("corpus", [])) * 2,
            "match-led corpus decision prefix exceeds its frozen positions")
    if decisions:
        _corpus_metrics(context, decisions, complete=False)
    if len(games) < MATCH_LED_FIRST_COUNT:
        require(not (output / "stage-20.receipt.json").exists(),
                "20-game receipt precedes a complete initial stage")
    else:
        require(len(games) >= MATCH_LED_FIRST_COUNT, "initial baseline match is incomplete")
        _expected_receipt(output / "stage-20.receipt.json",
                          _match_led_stage_receipt(settings, output, games, MATCH_LED_FIRST_COUNT))
        require((output / "stage-20.receipt.json").is_file(), "missing completed 20-game receipt")
    if len(games) < MATCH_LED_TOTAL_COUNT:
        require(not (output / "stage-200.receipt.json").exists(),
                "200-game receipt precedes a complete baseline match")
    else:
        _expected_receipt(output / "stage-200.receipt.json",
                          _match_led_stage_receipt(settings, output, games, MATCH_LED_TOTAL_COUNT))
        require((output / "stage-200.receipt.json").is_file(), "missing completed 200-game receipt")
    stage20 = _read_receipt(output / "stage-20.receipt.json") if (output / "stage-20.receipt.json").exists() else None
    stage200 = _read_receipt(output / "stage-200.receipt.json") if (output / "stage-200.receipt.json").exists() else None
    require(stage200 is None or (stage20 is not None and stage20["continuation_allowed"]),
            "200-game stage exists without an eligible 20-game receipt")
    oracle_allowed = stage200 is not None and improved_after_200(stage200["summary"])
    if oracle_games:
        require(len(decisions) == len(context.get("corpus", [])) * 2,
                "Oracle diagnostic preceded complete corpus diagnostics")
    oracle = _verify_oracle(context, settings, oracle_games, oracle_allowed)
    if len(oracle_games) == MATCH_LED_ORACLE_COUNT:
        expected = _match_led_oracle_receipt(settings, output, oracle_games)
        _expected_receipt(output / "oracle.receipt.json", expected)
        require((output / "oracle.receipt.json").is_file(), "missing completed Oracle receipt")
    else:
        require(not (output / "oracle.receipt.json").exists(),
                "Oracle receipt precedes a complete diagnostic")
    return _match_led_summary(context, settings, games, decisions, oracle_games, stage20, stage200)


def run_match_led(context: dict, settings: dict, artifact_path: Path, output: Path,
                  *, extend_to_200: bool = False, run_oracle: bool = False, progress=None) -> dict:
    """Run only explicitly selected match stages, preserving every completed game."""
    require(settings.get("version") == MATCH_LED_VERSION, "unsupported match-led settings")
    validate_settings(context, settings)
    output.mkdir(parents=True, exist_ok=True)
    require({path.name for path in output.iterdir()} <= MATCH_LED_FILES,
            "match-led output contains unexpected files")
    binding = _binding(context, settings, artifact_path)
    if (output / "binding.json").exists():
        require(training.read_json(output / "binding.json") == binding,
                "match-led resume settings or artifacts changed")
    else:
        require(not list(output.iterdir()), "match-led output has data without its identity binding")
        rf.atomic_write(output, "binding.json", pilot.blob(binding))

    games = _load_rows(output, "games.jsonl")
    decisions = _load_rows(output, "corpus-decisions.jsonl")
    oracle_games = _load_rows(output, "oracle-games.jsonl")
    _verify_match_led_games(context, settings, artifact_path, games)
    if decisions:
        _corpus_metrics(context, decisions, complete=False)
    require(not decisions or len(games) >= MATCH_LED_FIRST_COUNT,
            "corpus diagnostics precede the completed initial match")
    if oracle_games:
        require(len(decisions) == len(context.get("corpus", [])) * 2,
                "Oracle diagnostic preceded complete corpus diagnostics")
    oracle_allowed = len(games) == MATCH_LED_TOTAL_COUNT and rf.match_summary(games)["match_points"] > 100
    _verify_oracle(context, settings, oracle_games, oracle_allowed)

    stage20_path = output / "stage-20.receipt.json"
    stage200_path = output / "stage-200.receipt.json"
    had_stage20_receipt = stage20_path.is_file()
    had_stage200_receipt = stage200_path.is_file()
    if stage20_path.exists():
        expected = _match_led_stage_receipt(settings, output, games, MATCH_LED_FIRST_COUNT)
        _expected_receipt(stage20_path, expected)
    elif len(games) == MATCH_LED_FIRST_COUNT:
        _write_once(output, stage20_path.name,
                    _sealed_receipt(_match_led_stage_receipt(settings, output, games, MATCH_LED_FIRST_COUNT)))
    if stage200_path.exists():
        expected = _match_led_stage_receipt(settings, output, games, MATCH_LED_TOTAL_COUNT)
        _expected_receipt(stage200_path, expected)
    elif len(games) == MATCH_LED_TOTAL_COUNT:
        require(stage20_path.is_file(), "missing 20-game receipt before 200-game completion")
        _write_once(output, stage200_path.name,
                    _sealed_receipt(_match_led_stage_receipt(settings, output, games, MATCH_LED_TOTAL_COUNT)))

    if extend_to_200:
        require(had_stage20_receipt, "run and verify the initial 20-game stage before requesting extension")
        stage20 = _read_receipt(stage20_path)
        require(continuation_allowed(stage20["summary"]),
                "20-game result is below the 10-point continuation threshold")
        require(not (output / "report.json").exists(), "completed match-led evaluation cannot be extended")
    if run_oracle:
        require(had_stage200_receipt,
                "complete and verify 200 baseline games before requesting Oracle diagnostics")
        stage200 = _read_receipt(stage200_path)
        require(improved_after_200(stage200["summary"]),
                "Oracle diagnostics require more than 100 candidate points from 200 games")
        require(not (output / "report.json").exists(), "completed match-led evaluation cannot run Oracle again")

    emit = progress or (lambda phase, completed, total: None)
    needs_games = len(games) < MATCH_LED_FIRST_COUNT or (extend_to_200 and len(games) < MATCH_LED_TOTAL_COUNT)
    needs_corpus = (len(games) >= MATCH_LED_FIRST_COUNT
                    and len(decisions) < len(context.get("corpus", [])) * 2)
    needs_oracle = run_oracle and len(oracle_games) < MATCH_LED_ORACLE_COUNT
    if not (needs_games or needs_corpus or needs_oracle):
        return verify_match_led(context, settings, artifact_path, output)

    reserved = set(_source(context).get("reserved", set()))
    players = {}
    try:
        players["baseline"] = _Player(settings, _adopted_path(context), reserved)
        players["candidate"] = _Player(settings, artifact_path, reserved)
        remaining = [MATCH_LED_TOTAL_COUNT * 120 - sum(len(game["decisions"]) for game in games)]
        target = MATCH_LED_TOTAL_COUNT if extend_to_200 else MATCH_LED_FIRST_COUNT
        emit("baseline-match", len(games), target)
        for index in range(len(games), target):
            pair, member = divmod(index, 2)
            opening = settings["openings"]["comparison"][pair][member]
            seats = {"B": "candidate", "W": "baseline"} if member == 0 else {"B": "baseline", "W": "candidate"}
            game = rf.play("optimizer-comparison", pair, member, opening["board"], opening["side"],
                           opening["moves"], opening["rotation"], players, seats, remaining)
            for decision in game["decisions"]:
                if rf.legal_moves(decision["board"], decision["side"]):
                    decision["search_telemetry"] = players[seats[decision["side"]]].decisions[decision["id"]]
            game.pop("game_digest")
            game["execution_identity"] = _game_execution_identity(context, settings, artifact_path)
            game["game_digest"] = training.digest(game)
            games.append(game)
            _verify_games(context, settings, [game], maximum=MATCH_LED_TOTAL_COUNT, start_index=index)
            require(game.get("execution_identity") == _game_execution_identity(context, settings, artifact_path),
                    "baseline game does not record the frozen timeout and participant identities")
            _write_rows(output, "games.jsonl", games)
            emit("baseline-match", len(games), target)
            if len(games) == MATCH_LED_FIRST_COUNT:
                _write_once(output, "stage-20.receipt.json", _sealed_receipt(
                    _match_led_stage_receipt(settings, output, games, MATCH_LED_FIRST_COUNT)))
                if not continuation_allowed(_read_receipt(stage20_path)["summary"]):
                    break
        if len(games) == MATCH_LED_FIRST_COUNT and not stage20_path.exists():
            _write_once(output, "stage-20.receipt.json", _sealed_receipt(
                _match_led_stage_receipt(settings, output, games, MATCH_LED_FIRST_COUNT)))
        if len(games) == MATCH_LED_TOTAL_COUNT and not stage200_path.exists():
            _write_once(output, "stage-200.receipt.json", _sealed_receipt(
                _match_led_stage_receipt(settings, output, games, MATCH_LED_TOTAL_COUNT)))

        if len(games) >= MATCH_LED_FIRST_COUNT:
            emit("corpus", len(decisions), len(context.get("corpus", [])) * 2)
            for index in range(len(decisions), len(context.get("corpus", [])) * 2):
                row = context["corpus"][index // 2]
                name = "baseline" if index % 2 == 0 else "candidate"
                identifier = f"optimizer-corpus-{index // 2}-{name}"
                players[name].new_game(identifier)
                move, telemetry = players[name].choose_with_diagnostic(identifier, row["board"], row["side_to_move"])
                decisions.append({"position_id": row["position_id"], "board": row["board"],
                                  "side": row["side_to_move"], "player": name, "move": move,
                                  "search_telemetry": telemetry})
                _corpus_metrics(context, decisions, complete=False)
                _write_rows(output, "corpus-decisions.jsonl", decisions)
                emit("corpus", len(decisions), len(context.get("corpus", [])) * 2)

        if len(games) == MATCH_LED_TOTAL_COUNT:
            summary = rf.match_summary(games)
            if improved_after_200(summary) and run_oracle:
                emit("oracle-match", len(oracle_games), MATCH_LED_ORACLE_COUNT)
                binary = Path(settings["oracle_binary"]["path"])

                def save_game(game):
                    cycle.validate_oracle_game(settings, game, len(oracle_games))
                    oracle_games.append(game)
                    _write_rows(output, "oracle-games.jsonl", oracle_games)
                    emit("oracle-match", len(oracle_games), MATCH_LED_ORACLE_COUNT)

                pilot.oracle.run_profiled_match(binary, binary.parent, players["candidate"],
                    settings["openings"]["oracle-match"], cycle.ORACLE_PROFILE, settings["match_config"],
                    settings["decision_timeout_seconds"], 1, on_game=save_game, initial_games=oracle_games)
                if len(oracle_games) == MATCH_LED_ORACLE_COUNT:
                    _write_once(output, "oracle.receipt.json", _sealed_receipt(
                        _match_led_oracle_receipt(settings, output, oracle_games)))
        if len(oracle_games) == MATCH_LED_ORACLE_COUNT and not (output / "oracle.receipt.json").exists():
            _write_once(output, "oracle.receipt.json", _sealed_receipt(
                _match_led_oracle_receipt(settings, output, oracle_games)))
    finally:
        for player in players.values():
            player.close()
    return verify_match_led(context, settings, artifact_path, output)
