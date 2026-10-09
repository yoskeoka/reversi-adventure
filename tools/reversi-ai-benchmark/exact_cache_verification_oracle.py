"""Bounded, checkpointed independent Oracle queries for the three-game sample."""

from pathlib import Path
import os
import re

import exact_threshold as et
import whole_game as wg

VERSION = "exact-cache-verification-v2"
TIMEOUT = 30
MAX_RSS = 1572864
SCORE_CONTRACT = "winner-empty-v1"


def profile():
    # Independent complete solves retain the historical receipt profile.
    # The measured CLI remains depth8; its heuristic settings are unrelated.
    return wg.oracle.profile_from_name("whole-game-depth-12-exact-20")


def query_identity(m, board, side):
    effective, _ = wg.oracle.effective_query(board, side)
    return {"board": board, "effective_side": effective,
            "oracle_binary_sha256": m["inputs"]["oracle"]["sha256"],
            "profile_digest": et.sha(wg.oracle.profile_metadata(profile())),
            "score_contract": SCORE_CONTRACT}


def _key(identity):
    return et.sha(identity)


def _terminal(board):
    return not wg.oracle.legal_moves(board, "B") and not wg.oracle.legal_moves(board, "W")


def _terminal_score(board, side):
    return wg.oracle.terminal_score(board, side)


def _selected(results):
    roots = []
    for result in results:
        if result["status"] != "completed" or result["unit"]["scope"] != "game":
            continue
        steps = [s for s in result["steps"] if s["search"]["exact"]
                 and not _terminal(s["board"]) and s["board"].count(".") <= 12]
        chosen = [steps[:1], [s for s in steps if s["board"].count(".") <= 8][:1], steps[-1:]]
        seen = set()
        for candidates in chosen:
            for step in candidates:
                key = step["board"], step["side"]
                if key in seen:
                    continue
                seen.add(key)
                roots.append({"source_digest": result["report_digest"], "unit_id": result["unit"]["id"],
                              "step": step})
    wg.require(len(roots) <= 9, "Oracle root cap exceeded")
    return roots


def freeze_stage(m, results, reusable_queries=()):
    reusable = {}
    for entry in reusable_queries:
        identity = entry["identity"]
        # The verified registry also contains unrelated depths and thresholds.
        # Only complete solves of the identical Oracle contract can be reused.
        if identity != query_identity(m, identity["board"], identity["effective_side"]):
            continue
        wg.require(entry.get("verified") is True and isinstance(entry.get("provenance"), dict)
                   and all(k in entry["provenance"] for k in ("receipt_digest", "query_index", "producer_revision")),
                   "Oracle reuse lacks verified producer provenance")
        verify_query(m, {"identity": identity, "child_query": entry.get("child_query", False)}, entry,
                     reused=True)
        key = _key(identity)
        wg.require(key not in reusable or reusable[key]["result"]["value"] == entry["result"]["value"],
                   "conflicting reusable Oracle values")
        reusable.setdefault(key, entry)
    roots, queries, used = _selected(results), {}, {}
    for root in roots:
        step = root["step"]
        root.update(root_query=None, child_query=None, terminal_score=None)
        positions = [("root_query", step["board"], step["side"], False)]
        if step["move"] != "pass":
            child = wg.oracle.apply_move(step["board"], step["side"], step["move"])
            if _terminal(child):
                root["terminal_score"] = _terminal_score(child, step["side"])
            else:
                positions.append(("child_query", child, wg.oracle.other(step["side"]), True))
        for field, board, side, is_child in positions:
            identity = query_identity(m, board, side)
            key = _key(identity)
            _, sign = wg.oracle.effective_query(board, side)
            root[field] = {"id": key, "sign": sign}
            if key in reusable:
                used[key] = reusable[key]
            else:
                queries.setdefault(key, {"id": key, "identity": identity, "child_query": is_child})
    wg.require(len(queries)+len(used) <= 18, "Oracle query cap exceeded")
    return wg.sealed({"version": VERSION, "score_contract": wg.SCORE_CONTRACT, "manifest_digest": m["report_digest"], "roots": roots,
                      "queries": list(queries.values()), "reused": used, "total": len(queries),
                      "timeout_seconds": TIMEOUT, "max_rss_kib": MAX_RSS})


def verify_stage(m, stage, results=None, reusable_queries=()):
    wg.require(stage == wg.sealed(stage) and stage.get("version") == VERSION and stage.get("score_contract") == SCORE_CONTRACT
               and stage.get("manifest_digest") == m["report_digest"]
               and stage.get("timeout_seconds") == TIMEOUT and stage.get("max_rss_kib") == MAX_RSS
               and type(stage.get("total")) is int and stage.get("total") == len(stage["queries"]) <= 18
               and len(stage["roots"]) <= 9, "Oracle stage identity mismatch")
    ids = [q["id"] for q in stage["queries"]]
    wg.require(len(set(ids)) == len(ids) and not set(ids).intersection(stage["reused"]),
               "duplicate Oracle stage query")
    for query in stage["queries"]:
        identity = query["identity"]
        wg.require(query["id"] == _key(identity) and identity == query_identity(
            m, identity["board"], identity["effective_side"]) and type(query["child_query"]) is bool,
            "Oracle stage query identity mismatch")
    for key, entry in stage["reused"].items():
        wg.require(key == _key(entry["identity"]) and entry.get("verified") is True
                   and isinstance(entry.get("provenance"), dict)
                   and all(k in entry["provenance"] for k in ("receipt_digest", "query_index", "producer_revision")),
                   "Oracle reused stage provenance mismatch")
        verify_query(m, {"identity": entry["identity"], "child_query": entry.get("child_query", False)},
                     entry, reused=True)
    if results is not None:
        wg.require(stage == freeze_stage(m, results, reusable_queries), "Oracle extraction changed")


def _process(m, query, observation, timeout, historical=False):
    wg.require(isinstance(observation, dict), "Oracle process observation missing")
    argv = observation.get("argv")
    wg.require(isinstance(argv, list) and len(argv) >= 2 and argv[-2] == "-solve"
               and argv == wg.oracle.oracle_argv(Path(argv[0]) if historical else Path(m["inputs"]["oracle"]["path"]), profile(),
                   solve_path=Path(argv[-1]), child_query=query["child_query"]), "Oracle command mismatch")
    resources = observation.get("resources")
    wg.require(isinstance(resources, dict) and all(type(resources.get(k)) is int and resources[k] >= 0
               for k in ("user_cpu_ns", "system_cpu_ns"))
               and type(resources.get("peak_rss_kib")) is int and resources["peak_rss_kib"] > 0
               and type(observation.get("wall_ns")) is int and observation["wall_ns"] > 0
               and isinstance(observation.get("stdout"), str) and isinstance(observation.get("stderr"), str),
               "Oracle raw resource/output missing")
    sampled = observation.get("last_observation")
    if sampled is not None:
        wg.require(isinstance(sampled, dict) and all(type(sampled.get(k)) is int and sampled[k] >= 0
                   for k in ("user_cpu_ns", "system_cpu_ns"))
                   and type(sampled.get("peak_rss_kib")) is int and sampled["peak_rss_kib"] > 0,
                   "Oracle sampled resources invalid")
    if not historical or "exit_status" in observation or "returncode" in observation:
        wg.require(type(observation.get("exit_status")) is int and type(observation.get("returncode")) is int
                   and os.waitstatus_to_exitcode(observation["exit_status"]) == observation["returncode"],
                   "Oracle exit evidence invalid")
    return max(resources["peak_rss_kib"], sampled["peak_rss_kib"] if sampled else 0) > MAX_RSS


def verify_query(m, query, receipt, reused=False):
    if not reused:
        wg.require(receipt == wg.sealed(receipt) and receipt.get("version") == VERSION and receipt.get("score_contract") == SCORE_CONTRACT
                   and receipt.get("manifest_digest") == m["report_digest"] and receipt.get("query") == query,
                   "Oracle checkpoint identity mismatch")
    identity = query["identity"]
    wg.require(identity == query_identity(m, identity["board"], identity["effective_side"]),
               "Oracle query identity mismatch")
    timeout = 310 if reused else TIMEOUT
    observation, raw = receipt.get("process_observation"), receipt.get("result")
    failed = not reused and receipt.get("status") == "failed"
    wg.require(reused or receipt.get("status") in ("completed", "failed"), "Oracle status invalid")
    reason = receipt.get("failure")
    wg.require(reused or (isinstance(reason, str) and bool(reason) if failed else reason is None),
               "Oracle failure reason missing")
    if observation is None:
        wg.require(failed and raw is None and re.fullmatch(r"\[Errno -?\d+\] .+", reason, re.DOTALL),
                   "Oracle prelaunch failure lacks evidence")
        return
    cap = _process(m, query, observation, timeout, historical=reused)
    late = observation["wall_ns"] >= timeout*1_000_000_000
    nonzero = observation.get("returncode", 0) != 0
    if failed and raw is None:
        if reason == "Oracle decision timeout":
            wg.require(late, "Oracle timeout lacks deadline evidence")
        elif reason == "Oracle peak RSS cap exceeded":
            wg.require(cap, "Oracle RSS failure lacks exceeded cap")
        elif reason == "Oracle process failed":
            wg.require(nonzero, "Oracle process failure lacks nonzero exit")
        elif reason == observation.get("sampling_failure"):
            wg.require(not observation.get("exit_observation", {}).get("exiting", False),
                       "Oracle sampling failure contradicts exit")
        else:
            wg.require(not cap and not late and not nonzero, "Oracle failure contradicts process")
            try:
                parsed = wg.oracle.parse_solve_output(observation["stdout"], [identity["board"].count(".")], profile())
                move = parsed[0]["move"]
                expected = (f"Egaroucid returned an illegal continuation move for {identity['effective_side']}: {move!r}"
                            if move not in wg.oracle.legal_moves(identity["board"], identity["effective_side"]) else None)
            except wg.oracle.OracleError as exc:
                expected = str(exc)
            wg.require(expected is not None and reason == expected, "Oracle failure does not match raw output")
        return
    wg.require(not cap and not late and not nonzero and isinstance(raw, dict),
               "Oracle completed query exceeded caps or failed process")
    wg.require(type(raw.get("exact")) is bool
               and all(type(raw.get(key)) is int for key in ("completed_depth", "value", "nodes", "elapsed_ms", "nps")),
               "Oracle raw solve types invalid")
    wg.require(wg.oracle.parse_solve_output(observation["stdout"], [identity["board"].count(".")], profile()) == [raw]
               and raw["move"] in wg.oracle.legal_moves(identity["board"], identity["effective_side"]),
               "Oracle parsed output mismatch")
    complete = raw["exact"] is True and raw["completed_depth"] >= identity["board"].count(".")
    wg.require((failed and not complete and reason == "independent Oracle incomplete") or (not failed and complete),
               "Oracle completeness/failure mismatch")


def measure_query(m, query):
    observations, raw, failure = [], None, None
    identity = query["identity"]
    try:
        raw = wg.oracle.run_solve([(identity["board"], identity["effective_side"])],
            Path(m["inputs"]["oracle"]["path"]), Path(m["oracle_cwd"]), profile(), TIMEOUT,
            child_query=query["child_query"],
            runner=lambda argv, **kw: et.measured_oracle(argv, observations=observations, **kw))[0]
        wg.require(raw["exact"] and raw["completed_depth"] >= identity["board"].count("."),
                   "independent Oracle incomplete")
    except (wg.BenchmarkError, wg.oracle.OracleError, OSError, ValueError) as exc:
        failure = str(exc)
    return wg.sealed({"version": VERSION, "score_contract": wg.SCORE_CONTRACT, "manifest_digest": m["report_digest"], "query": query,
                      "status": "failed" if failure else "completed", "failure": failure,
                      "result": raw, "process_observation": observations[0] if observations else None})


def assess(stage, receipts):
    values, failures = {}, []
    for key, entry in stage["reused"].items():
        values[key] = entry["result"]["value"]
    for receipt in receipts:
        key = receipt["query"]["id"]
        if receipt["status"] == "failed":
            failures.append({"query_id": key, "failure": receipt["failure"]})
        else:
            values[key] = receipt["result"]["value"]
    roots = []
    for root in stage["roots"]:
        root_ref, child_ref = root["root_query"], root["child_query"]
        root_value = root_ref["sign"]*values[root_ref["id"]] if root_ref["id"] in values else None
        selected = (root["terminal_score"] if root["terminal_score"] is not None else
                    -child_ref["sign"]*values[child_ref["id"]] if child_ref and child_ref["id"] in values else
                    root_value if child_ref is None else None)
        matches = root_value is not None and selected is not None and root_value == selected == root["step"]["search"]["score"]
        roots.append({"unit_id": root["unit_id"], "step_id": root["step"]["id"],
                      "root_score": root_value, "selected_score": selected, "matches": matches})
        if root_value is not None and selected is not None and not matches:
            failures.append({"step_id": root["step"]["id"], "failure": "independent Oracle score/continuation mismatch"})
    return {"receipts": receipts, "roots": roots, "failures": failures,
            "completed": not failures and all(r["matches"] for r in roots)}


def preflight_stage(m, stage, directory):
    """Validate every saved query without requiring unfinished queries to exist."""
    verify_stage(m, stage)
    directory = Path(directory)
    known = {q["id"]: q for q in stage["queries"]}
    receipts = {}
    if not directory.exists():
        return receipts
    for path in directory.iterdir():
        if path.name.startswith(".unfinished-"):
            continue
        wg.require(path.suffix == ".json" and path.stem in known, "unknown Oracle query checkpoint")
        receipt = wg.read_canonical(path)
        verify_query(m, known[path.stem], receipt)
        receipts[path.stem] = receipt
    return receipts


def run_stage(m, stage, directory, progress, verify_only=False):
    receipts = preflight_stage(m, stage, directory)
    directory = Path(directory)
    if not verify_only:
        directory.mkdir(parents=True, exist_ok=True)
    if stage["total"] == 0:
        progress.emit("oracle", "game", "position", 0, 0, "verified")
    for index, query in enumerate(stage["queries"]):
        def emit(status, done):
            progress.emit("oracle", "game", "position", done, stage["total"], status)
        if query["id"] in receipts:
            emit("skipped", index+1)
            continue
        wg.require(not verify_only, "missing Oracle query checkpoint")
        emit("running", index)
        try:
            receipt = measure_query(m, query)
        except KeyboardInterrupt:
            emit("interrupted", index)
            raise
        verify_query(m, query, receipt)
        wg.atomic_write(directory / f"{query['id']}.json", receipt)
        receipts[query["id"]] = receipt
        emit("failed" if receipt["status"] == "failed" else "saved", index+1)
    return assess(stage, [receipts[q["id"]] for q in stage["queries"]])
