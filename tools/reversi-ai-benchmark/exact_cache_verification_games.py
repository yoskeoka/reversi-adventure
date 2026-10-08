"""Six serial game units and offline evidence checks for plan 0045."""

from __future__ import annotations

import re

import exact_threshold as et

wg = et.wg
VERSION = "exact-cache-verification-v1"
GAME_IDENTITIES = [{"opening_id": f"opening-{i}", "assignment": 0} for i in (1, 2, 4)]
POLICIES = {"turn": "exact-cache-cross-decision-suspended-v1", "game": "diagnostic-game-v1"}


def units(sample):
    wg.require(sample.get("games") == GAME_IDENTITIES, "ordered three-game sample identity mismatch")
    openings = {row["id"]: row for row in wg.opening_rows()}
    starts = [{**openings[row["opening_id"]], **row,
               "opening": openings[row["opening_id"]]["moves"]} for row in sample["games"]]
    return [{"id": f"games-{scope}-{row['opening_id']}-seat0", "stage": "full",
             "threshold": 20, "depth": 8, "scope": scope, "start": row}
            for scope in ("turn", "game") for row in starts]


def require_unit(unit):
    wg.require(unit in units({"games": GAME_IDENTITIES}), "unknown or changed game unit")


def policy_errors(unit, result):
    errors = []
    observations = [(step["id"], step["search"]) for step in result["steps"]]
    attempt = result["failed_attempt"]
    if attempt and attempt.get("observed_search") is not None:
        observations.append((attempt["id"], attempt["observed_search"]))
    for identifier, search in observations:
        expected = {"scope": unit["scope"], "policy": POLICIES[unit["scope"]],
                    "raw": f"exact_cache_policy_v1\tposition_id={identifier}"
                           f"\texact_cache_scope={unit['scope']}\texact_cache_policy={POLICIES[unit['scope']]}"}
        if search.get("exact_cache_policy") != expected:
            errors.append(identifier)
    return errors


def measure_unit(manifest, unit):
    require_unit(unit)
    result = et.measure_unit(manifest, unit, include_cache_policy=True)
    result["version"] = VERSION
    errors = policy_errors(unit, result)
    result["policy_failures"] = errors
    if errors and result["status"] == "completed":
        result.update(status="failed", failure="CLI cache policy missing or mismatched")
    result = wg.sealed(result)
    verify_unit(manifest, unit, result)
    return result


def raw_usage(raw, message):
    wg.require(isinstance(raw, dict) and all(type(raw.get(k)) is int and raw[k] >= 0
        for k in ("user_cpu_ns", "system_cpu_ns", "peak_rss_kib"))
        and raw["peak_rss_kib"] > 0, message)


def verify_unit(manifest, unit, result):
    require_unit(unit)
    et.verify_seal(result)
    wg.require(result.get("version") == VERSION, "game unit version mismatch")
    legacy_view = wg.sealed({**result, "version": et.VERSION})
    et.verify_unit(manifest, unit, legacy_view)
    wg.require(type(result.get("ended_at_ns")) is int and result["started_at_ns"] > 0
               and result["ended_at_ns"] >= result["started_at_ns"]
               and re.fullmatch(r"[0-9a-f]{32}", result["session_id"]) is not None,
               "game lifecycle invalid")
    errors = policy_errors(unit, result)
    wg.require(result.get("policy_failures") == errors, "cache policy failures mismatch")
    wg.require(not errors or result["status"] == "failed", "completed game cache policy mismatch")
    if result["failure"] == "CLI cache policy missing or mismatched":
        wg.require(bool(errors), "cache policy failure evidence missing")
    for label, event in result["reset_events"].items():
        wg.require(label in ("B", "W") and event["game_id"] == unit["id"]
                   and event["acknowledged"] is True and event["protocol"] == "new_game-v1"
                   and type(event.get("elapsed_ns")) is int and event["elapsed_ns"] >= 0,
                   "game reset evidence invalid")
    for label, usage in result["seat_processes"].items():
        raw_usage(usage, "game process raw resources missing")
        wg.require(type(usage.get("started_at_ns")) is int and type(usage.get("ended_at_ns")) is int
                   and result["started_at_ns"] <= usage["started_at_ns"] <= usage["ended_at_ns"]
                   <= result["ended_at_ns"], "seat lifecycle invalid")
        for step in result["steps"]:
            if step["seat"] == label:
                wg.require(all(step["cpu_after"][key] <= usage[key]
                    for key in ("user_cpu_ns", "system_cpu_ns")), "decision cumulative CPU exceeds process total")
    for step in result["steps"]:
        for key in ("cpu_before", "cpu_after"):
            raw_usage(step[key], "game decision raw resources missing")
        if "peak_observation" in step:
            raw_usage(step["peak_observation"], "game polling resources missing")
        wg.require(step["decision_elapsed_ns"] <= et.CAPS["timeout_seconds"] * 1_000_000_000,
                   "game decision timeout exceeded")
    attempt = result["failed_attempt"]
    if attempt:
        raw_usage(attempt.get("before_usage"), "failure attempt raw resources missing")
        for key in ("after_usage", "last_resource_observation", "peak_observation"):
            if attempt.get(key) is not None:
                raw_usage(attempt[key], "failure attempt raw resources invalid")


def semantic_pair(turn, game):
    return et.semantic_pair(turn, game)


def game_totals(result):
    exact = [step for step in result["steps"] if step["search"]["exact"]]
    heuristic = [step for step in result["steps"] if not step["search"]["exact"]]
    return {"wall_ns": result["wall_ns"], **result["resources"],
            "exact_decision_ns": sum(s["decision_elapsed_ns"] for s in exact),
            "heuristic_decision_ns": sum(s["decision_elapsed_ns"] for s in heuristic),
            "exact_search_us": sum(s["search"]["elapsed_us"] for s in exact),
            "exact_cpu_ns": sum(s["decision_cpu_ns"] for s in exact),
            "heuristic_cpu_ns": sum(s["decision_cpu_ns"] for s in heuristic),
            "exact_nodes": sum(s["search"]["nodes"] for s in exact),
            "heuristic_nodes": sum(s["search"]["nodes"] for s in heuristic),
            "exact_cache_probes": sum(s["search"]["cache_probes"] for s in exact),
            "exact_cache_hits": sum(s["search"]["cache_hits"] for s in exact),
            "exact_cache_stores": sum(s["search"]["cache_stores"] for s in exact)}


def summary(results):
    expected = units({"games": GAME_IDENTITIES})
    ids = [r["unit"]["id"] for r in results]
    expected_ids = [u["id"] for u in expected]
    wg.require(len(set(ids)) == len(ids) and ids == [i for i in expected_ids if i in ids],
               "duplicate, unknown or unordered game results")
    for result in results:
        require_unit(result["unit"])
    by_id = {r["unit"]["id"]: r for r in results}
    conditions, comparisons = [], []
    for scope in ("turn", "game"):
        rows = [by_id[u["id"]] for u in expected if u["scope"] == scope and u["id"] in by_id]
        complete = len(rows) == 3 and all(r["status"] == "completed" for r in rows)
        condition = {"scope": scope, "games_total": 3, "saved": len(rows),
                     "completed": sum(r["status"] == "completed" for r in rows),
                     "status": "completed" if complete else "failed",
                     "units": [{"id": r["unit"]["id"], "status": r["status"],
                                "failure": r["failure"], "report_digest": r["report_digest"]} for r in rows]}
        if complete:
            totals = [game_totals(r) for r in rows]
            condition["averages"] = {key: sum(row[key] for row in totals)/3 for key in totals[0]}
        else:
            condition["failure"] = "three successful games required; no partial averages"
        conditions.append(condition)
    for i in range(3):
        turn, game = by_id.get(expected[i]["id"]), by_id.get(expected[i+3]["id"])
        failure = "both successful game units required"
        if turn and game and turn["status"] == game["status"] == "completed":
            try:
                semantic_pair(turn, game)
                failure = None
            except wg.BenchmarkError as exc:
                failure = str(exc)
        comparisons.append({"opening_id": GAME_IDENTITIES[i]["opening_id"],
                            "status": "failed" if failure else "matched", "failure": failure})
    matched = all(c["status"] == "completed" for c in conditions) and all(
        c["status"] == "matched" for c in comparisons)
    if any(c["failure"] not in (None, "both successful game units required") for c in comparisons):
        for condition in conditions:
            condition.pop("averages", None)
            condition["status"] = "failed"
            condition["failure"] = "semantic mismatch; no averages"
    return {"version": VERSION, "games_total": 3, "conditions": conditions,
            "comparisons": comparisons, "games_matched": matched, "adoption": False,
            "limitations": "Three selected openings, assignment 0 only, one repetition; human adoption decision and independent Oracle evidence required."}
