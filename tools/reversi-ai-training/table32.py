"""Prepare/run/resume the isolated table32 cycle; real execution is human-operated."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import table32_extract as extraction
import table32_inputs as inputs
import table32_model as model
import table32_optimizer as optimizer
import table32_oracle_compat as oracle_compat
import table32_store as st
import training


def source_hashes():
    root = Path(__file__).resolve().parents[2]
    paths = list((root / "tools/reversi-ai-training").glob("*.py"))
    paths += list((root / "rust/reversi-ai").rglob("*.rs"))
    paths += [root / "rust/reversi-ai/data/table32-catalog.json", root / "Cargo.lock",
              root / "tools/reversi-ai-oracle/oracle.py"]
    return {str(p.relative_to(root)): training.sha256_file(p) for p in sorted(paths)}


def clean_commit():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                            capture_output=True, text=True, check=True)
    st.require(not result.stdout.strip(), "table32 prepare/run requires a clean producer checkout")
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def historical(source_manifest, comparison_root, evaluation_root, *, runtime_receipt,
               expected_oracle_identity=None, seed=inputs.SEED):
    """Use existing semantic verifiers; no trainer/CLI/Oracle is launched."""
    import optimizer_compare
    import optimizer_compare_evaluation
    import optimizer_compare_inputs
    before = [st.inventory(p) for p in (Path(source_manifest).parent, comparison_root, evaluation_root)]
    with oracle_compat.historical_replay(source_manifest, runtime_receipt,
                                         expected_identity=expected_oracle_identity) as oracle_identity:
        context = optimizer_compare_inputs.load_source(Path(source_manifest))
        report52 = optimizer_compare.verify(Path(comparison_root))
        report53 = optimizer_compare_evaluation.verify(Path(evaluation_root))
    st.require(report52["status"] == report53["status"] == "complete", "historical runs incomplete")
    games = training.read_jsonl(context["source_predecessors"]["self-play"] / "games.jsonl")
    exposures = set(context["exposure_keys"])
    for root in (comparison_root, evaluation_root):
        exposures.update(verified_match_exposure_keys(root))
        manifest = training.read_json(Path(root) / "manifest.json")
        for name, pairs in manifest.get("matches", {}).get("openings", {}).items():
            for pair in pairs:
                for opening in pair:
                    exposures.add(inputs.position_key(opening["board"], opening["side"]))
    snapshot = {"preflight_roots": inputs.preflight_roots(games,seed=seed),
                "validation": context["validation"], "held_out": context["held_out"],
                "corpus": context["corpus"], "golden": context["golden"],
                "excluded_keys": sorted(exposures)}
    after = [st.inventory(p) for p in (Path(source_manifest).parent, comparison_root, evaluation_root)]
    st.require(before == after, "historical verification changed an original")
    return {"inventories": before, "closure": context["pins"],
            "oracle_source_identity": oracle_identity,
            "source_manifest": st.pin(source_manifest),
            "comparison_report": st.pin(Path(comparison_root) / "report.json"),
            "evaluation_report": st.pin(Path(evaluation_root) / "report.json")}, snapshot


def verified_match_exposure_keys(root):
    """Collect exposure only after the owning historical verifier has replayed it."""
    keys=set()
    for name in ("games.jsonl","oracle-games.jsonl"):
        path=Path(root)/"matches"/name
        if not path.is_file():
            continue
        for game in training.read_jsonl(path):
            keys.add(inputs.position_key(game["start_board"],game["start_side"]))
            keys.update(inputs.position_key(row["board"],row["side"]) for row in game["decisions"])
            keys.update(inputs.position_key(game["terminal_board"],side) for side in ("B","W"))
    return keys


def settings(args):
    names = ("train_per_prefix", "validation_per_prefix", "test_per_prefix", "early_positions",
             "early_candidates_per_phase", "pool_sequences", "max_steps", "max_proposals",
             "decision_timeout_seconds", "time_limit_ms", "node_limit")
    value = {name: getattr(args, name) for name in names}
    st.require(all(type(v) is int and v > 0 for v in value.values()), "settings must be positive integers")
    st.require(value["early_positions"] >= 12 and value["time_limit_ms"] <= 300000
               and value["node_limit"] <= 10000000 and value["decision_timeout_seconds"] <= 310
               and value["decision_timeout_seconds"] * 1000 > value["time_limit_ms"],
               "invalid teacher resource limits (max300000ms/10000000nodes/310s)")
    return value


def prepare(args):
    root = args.run_root.resolve()
    checkout = Path(__file__).resolve().parents[2]
    st.require(args.run_root.is_absolute() and root != checkout and checkout not in root.parents,
               "run root must be an absolute checkout-external path")
    st.require(not root.exists(), "run root exists; resume it or choose a new root")
    config = settings(args)
    seed=training.require_int(args.seed,"seed",0,2**64-1)
    producer = clean_commit()
    baseline = st.pin(checkout / "models/trained/0019-20261020-02.json")
    st.require(baseline["sha256"] == st.BASELINE_SHA, "adopted S0 changed")
    originals, snapshot = historical(args.source_manifest, args.source_comparison_root,
                                      args.source_evaluation_root,
                                      runtime_receipt=args.oracle_runtime_receipt, seed=seed)
    oracle_identity = originals["oracle_source_identity"]
    runtime = oracle_identity["runtime"]
    specs = inputs.generation_plan(seed, config["train_per_prefix"],
                                   config["validation_per_prefix"], config["test_per_prefix"])
    limits = {**st.LIMITS, "games": len(specs), "early_labels": config["early_positions"],
              "training_steps_per_phase": config["max_steps"],
              "export_proposals_per_phase": config["max_proposals"],
              "wall_seconds": args.max_wall_seconds, "producer_rss_kib": args.producer_rss_kib,
              "child_rss_kib": args.child_rss_kib}
    st.require(all(type(v) is int and v > 0 for v in limits.values()), "invalid explicit resource budget")
    manifest = {"version": st.VERSION, "score_contract": training.SCORE_CONTRACT,
                "producer_commit": producer, "sources": source_hashes(), "seed": seed,
                "catalog_digest": model.CATALOG_DIGEST, "baseline": baseline,
                "candidate_executable": st.pin(args.candidate_executable),
                "oracle_runtime_receipt": st.pin(args.oracle_runtime_receipt),
                "oracle_runtime": runtime, "oracle_source_identity": oracle_identity,
                "oracle_profile": players.oracle.profile_metadata(players.full_solve_profile()),
                "historical": originals, "snapshot_digest": st.digest(snapshot),
                "settings": config, "limits": limits, "generation_plan": specs,
                "input_kind": "production", "acceptance_reservation": "not-yet-selected",
                "production_authorized": False}
    root.mkdir(parents=True, exist_ok=False)
    st.atomic(root / "snapshot.json", snapshot, once=True)
    st.atomic(root / "manifest.json", manifest, once=True)
    st.atomic(root / "prepare.receipt.json", st.seal({"manifest_digest": st.digest(manifest),
               "snapshot_digest": st.digest(snapshot)}), once=True)
    return manifest


def load(root, *, verify_originals=True):
    root = Path(root)
    manifest = st.read(root / "manifest.json")
    st.require(manifest["version"] == st.VERSION and manifest["score_contract"] == training.SCORE_CONTRACT
               and type(manifest["seed"]) is int and 0<=manifest["seed"]<2**64
               and manifest["catalog_digest"] == model.CATALOG_DIGEST
               and manifest["sources"] == source_hashes(), "table32 producer/feature/seed identity changed; use a new root")
    st.require(st.read(root / "prepare.receipt.json") == st.seal({"manifest_digest": st.digest(manifest),
               "snapshot_digest": manifest["snapshot_digest"]}), "prepare receipt differs")
    for name in ("baseline", "candidate_executable", "oracle_runtime_receipt"):
        st.check_pin(manifest[name])
    st.require(manifest["baseline"]["sha256"] == st.BASELINE_SHA, "baseline pin differs")
    source_manifest_path = manifest["historical"]["source_manifest"]["path"]
    oracle_identity = oracle_compat.verify_source_identity(
        source_manifest_path, manifest["oracle_runtime_receipt"]["path"])
    st.require(oracle_identity == manifest["oracle_source_identity"]
               and oracle_identity["runtime"] == manifest["oracle_runtime"],
               "table32 Oracle source/runtime identity differs")
    snapshot = st.read(root / "snapshot.json")
    st.require(st.digest(snapshot) == manifest["snapshot_digest"], "snapshot digest differs")
    if verify_originals:
        original = manifest["historical"]
        for value in original["inventories"]:
            st.require(st.inventory(value["path"]) == value, "historical original changed")
        for value in original["closure"]["files"]:
            if Path(value["path"]).resolve() == Path(oracle_identity["historical_binary"]["path"]).resolve():
                st.require(value == oracle_identity["historical_binary"],
                           "historical Oracle binary record differs")
            else:
                st.check_pin(value)
        pins, reconstructed = historical(original["source_manifest"]["path"],
                                         Path(original["inventories"][1]["path"]),
                                         Path(original["inventories"][2]["path"]),
                                         runtime_receipt=manifest["oracle_runtime_receipt"]["path"],
                                         expected_oracle_identity=oracle_identity,
                                         seed=manifest["seed"])
        st.require(pins == original and reconstructed == snapshot, "historical snapshot does not reconstruct")
    return manifest, snapshot


class MissingUnit(Exception):
    def __init__(self, phase, unit):
        self.phase, self.unit = phase, unit
        super().__init__(f"missing unit phase={phase} unit={unit}")


class Driver:
    """One event program used by execution and process-free semantic replay."""
    def __init__(self, root, manifest, *, execute=False, every=1, attempt=None, providers=None, resume_from=None):
        self.root, self.m = Path(root), manifest
        self.journal = st.Journal(root, manifest, every)
        self.existing = iter(self.journal.entries())
        self.execute, self.attempt, self.providers = execute, attempt, providers
        self.at_end = False
        self.resume_from = resume_from

    def unit(self, phase, name, produce, validate, n=1, total=1):
        self.journal.progress(phase, name, n-1, total,
                              "running" if n == 1 or self.journal.phase != phase else "saved")
        if self.attempt:
            st.atomic(self.attempt / "progress.json", {"phase": phase, "unit": name})
        try:
            entry = next(self.existing) if not self.at_end else None
        except StopIteration:
            self.at_end, entry = True, None
        if entry is not None:
            st.require(entry["phase"] == phase and entry["unit"] == name,
                       f"completed prefix differs at {phase}/{name}")
            validate(entry["value"])
            return entry["value"]
        if not self.execute:
            raise MissingUnit(phase, name)
        if self.resume_from is not None:
            st.require(st.PHASES.index(phase) >= st.PHASES.index(self.resume_from),
                       f"cannot skip missing {phase}/{name}; resume from {phase}")
            self.resume_from = None
        try:
            if self.attempt:
                import resource
                started=time.monotonic()
                own_before=resource.getrusage(resource.RUSAGE_SELF)
                child_before=resource.getrusage(resource.RUSAGE_CHILDREN)
            value = produce()
            validate(value)
            self.journal.save(phase, name, value, n, total)
            if self.attempt:
                own=resource.getrusage(resource.RUSAGE_SELF)
                children=resource.getrusage(resource.RUSAGE_CHILDREN)
                with (self.attempt/"unit-resources.jsonl").open("ab") as stream:
                    stream.write(st.blob({"phase":phase,"unit":name,"receipt_index":self.journal.cursor-1,
                        "wall_seconds":time.monotonic()-started,
                        "producer_cpu_seconds":own.ru_utime+own.ru_stime-own_before.ru_utime-own_before.ru_stime,
                        "reaped_children_cpu_seconds":children.ru_utime+children.ru_stime-child_before.ru_utime-child_before.ru_stime,
                        "producer_peak_rss_kib":own.ru_maxrss,
                        "child_peak_rss_kib":children.ru_maxrss,
                        "resource_note":"child CPU/peak includes reaped children; live process-group samples are in resources.json"}))
            return value
        except BaseException as error:
            error.phase, error.unit = phase, name
            raise

    def computed(self, phase, name, value, n=1, total=1):
        return self.unit(phase, name, lambda: value,
                         lambda saved: st.require(st.blob(saved) == st.blob(value), f"{phase}/{name} arithmetic differs"), n, total)

    def finish(self):
        if not self.at_end:
            try:
                next(self.existing)
                raise ValueError("unexpected completed units after final state")
            except StopIteration:
                pass


def _events(root, start, end, field=None):
    for index in range(start, end):
        value = st.read(Path(root) / "units" / f"{index:07d}.json")["value"]
        yield value if field is None else value[field]


def phase_metric(rows, weights):
    return optimizer.loss(rows, weights, integer=True)


def phase_precision_metrics(rows, floats, integers):
    """Measure parameter quantization, prediction clipping, and runtime rounding."""
    names = ("float_raw32", "export_raw32", "float_to_export_raw32",
             "float_clipped_disc", "export_clipped_disc", "runtime_disc",
             "export_to_runtime_disc")
    sums = {name: {"squared_error": 0.0, "absolute_error": 0.0} for name in names}
    clipped_float, clipped_export = 0, 0
    for row in rows:
        raw_float = sum(floats.get(i, 0) for i in row["features"])
        raw_export = sum(integers.get(i, 0) for i in row["features"])
        clipped_float += abs(raw_float) > optimizer.RAW_LIMIT
        clipped_export += abs(raw_export) > optimizer.RAW_LIMIT
        float_disc = max(-optimizer.RAW_LIMIT, min(optimizer.RAW_LIMIT, raw_float)) / 32
        export_disc = max(-optimizer.RAW_LIMIT, min(optimizer.RAW_LIMIT, raw_export)) / 32
        runtime = optimizer.runtime_score(raw_export)
        target = row["target"]
        errors = {"float_raw32": target * 32 - raw_float,
                  "export_raw32": target * 32 - raw_export,
                  "float_to_export_raw32": raw_float - raw_export,
                  "float_clipped_disc": target - float_disc,
                  "export_clipped_disc": target - export_disc,
                  "runtime_disc": target - runtime,
                  "export_to_runtime_disc": export_disc - runtime}
        for name, error in errors.items():
            sums[name]["squared_error"] += error * error
            sums[name]["absolute_error"] += abs(error)
    count = len(rows)
    for name, value in sums.items():
        value.update({"count": count, "units": "raw32" if name.endswith("raw32") else "disc",
                      "mse": value["squared_error"] / count if count else None,
                      "mae": value["absolute_error"] / count if count else None})
    return {"errors": sums,
            "prediction_clipping": {"rows": count,
                "float_count": clipped_float, "export_count": clipped_export,
                "float_rate": clipped_float / count if count else None,
                "export_rate": clipped_export / count if count else None}}


def opening_plan(seed, forbidden):
    import random
    rng = random.Random(inputs.seed_stream(seed, "independent-match"))
    result, seen = [], set(forbidden)
    for attempt in range(10000):
        spec = {"prefix_length": 12 + rng.randrange(19), "stream_seed": rng.getrandbits(256)}
        try:
            opening = inputs.random_prefix(spec)
        except training.TrainingError:
            continue
        key = inputs.position_key(opening["board"], opening["side"])
        if key in seen or not inputs.rf.legal_moves(opening["board"], opening["side"]):
            continue
        result.append({**opening, "canonical_key": key, "attempt": attempt})
        seen.add(key)
        if len(result) == 100:
            return result
    raise ValueError("independent match opening pool exhausted")


def match_game(index, opening, choose):
    board, side, decisions = opening["board"], opening["side"], []
    config = {**inputs.TEACHER_SETTINGS, "opening_depth": 12, "midgame_depth": 12,
              "endgame_depth": 12, "exact_solver_empty_squares": 16}
    while inputs.rf.legal_moves(board, side) or inputs.rf.legal_moves(board, inputs.rf.other(side)):
        st.require(len(decisions) < 120, "match decision cap exceeded")
        player = "candidate" if (side == "B") == (index % 2 == 0) else "baseline"
        identifier = f"match-{index:03d}-{len(decisions):03d}"
        decision = choose(player, identifier, board, side, config)
        decisions.append({"board": board, "side": side, "player": player, **decision})
        board, side = inputs.advance(board, side, decision["move"])
    score = training.terminal_score(board, "B") * (1 if index % 2 == 0 else -1)
    return {"index": index, "pair": index//2, "opening": opening, "decisions": decisions,
            "terminal_board": board, "score_candidate": score,
            "points": 1 if score > 0 else .5 if score == 0 else 0}


def learn_phases(driver, folder):
    """Replay/train every phase before export, retaining only one float phase.

    Final state files are materializations of the verified receipt chain, not
    independent authority.  Export wall slices charge only newly executed
    proposals; revalidating an existing prefix cannot consume that slice.
    """
    m, config = driver.m, driver.m["settings"]
    states = driver.root / "trained-phases"
    for phase in range(60):
        train = extraction.phase_rows(folder, "train", phase)
        validation = extraction.phase_rows(folder, "validation", phase)
        state = optimizer.initial_state(train, validation, phase=phase, max_steps=config["max_steps"])
        state = driver.computed("phase-training", f"p{phase:02}-initial", state)
        while not state["complete"]:
            following = optimizer.train_step(state, train, validation)
            updated = following["step"] > state["step"]
            name = f"p{phase:02}-s{following['step']:04}" if updated else f"p{phase:02}-validation-stop"
            state = driver.computed("phase-training", name, following,
                                    following["step"], config["max_steps"])
        path = states / f"p{phase:02}.json"
        if driver.execute:
            st.atomic(path, state, once=True)
        else:
            if not path.is_file():
                raise MissingUnit("phase-training", f"p{phase:02}-final-state")
            st.require(st.read(path) == state, f"final trained phase materialization differs: {phase}")
    del state, following, train, validation

    phase_weights, phase_diagnostics = {}, []
    for phase in range(60):
        train = extraction.phase_rows(folder, "train", phase)
        validation = extraction.phase_rows(folder, "validation", phase)
        state = st.read(states / f"p{phase:02}.json")
        exported = optimizer.initial_export(state, train, seed=inputs.seed_stream(m["seed"], "export", phase),
                                             max_proposals=config["max_proposals"])
        exported = driver.computed("export", f"p{phase:02}-initial", exported)
        slice_started = None
        while not exported["complete"]:
            proposal_started = time.monotonic() if driver.execute else None
            exported = driver.computed("export", f"p{phase:02}-t{exported['tries']+1:04}",
                       optimizer.export_step(exported, train), exported["tries"]+1, config["max_proposals"])
            if driver.execute and driver.at_end:
                if slice_started is None:
                    slice_started = proposal_started
                if time.monotonic()-slice_started >= 60 and not exported["complete"]:
                    return phase_weights, phase_diagnostics, phase
        weights = optimizer.exported_weights(exported)
        phase_weights[str(phase)] = weights
        floats = dict(zip(state["indices"], state["weights"]))
        occurrence, capped_occurrence = {}, {}
        for count, capped in zip(state["counts"], state["capped_counts"]):
            occurrence[str(count)] = occurrence.get(str(count), 0) + 1
            capped_occurrence[str(capped)] = capped_occurrence.get(str(capped), 0) + 1
        unobserved = model.PARAMETER_COUNT - len(state["indices"])
        occurrence["0"], capped_occurrence["0"] = unobserved, unobserved
        table_coverage = []
        for table, (offset, size) in enumerate(zip(model.OFFSETS, model.SIZES)):
            indices = [i for i in state["indices"] if offset <= i < offset + size]
            table_coverage.append({"table": table, "parameters": size,
                "observed": len(indices), "nonzero_float": sum(floats[i] != 0 for i in indices),
                "nonzero_export": sum(weights.get(i, 0) != 0 for i in indices)})
        phase_diagnostics.append({"phase": phase, "float_state_digest": optimizer.state_digest(state),
            "export_digest": optimizer.state_digest(exported),
            "counts": {str(i):n for i,n in zip(state["indices"], state["counts"])},
            "capped_counts": {str(i):n for i,n in zip(state["indices"], state["capped_counts"])},
            "count_contract": "source-feature-and-reversal-including-self-twice",
            "observed_parameters": len(state["indices"]), "unobserved_parameters": unobserved,
            "nonzero_float_parameters": sum(w != 0 for w in floats.values()),
            "nonzero_export_parameters": len(weights),
            "occurrence_histogram": occurrence, "capped_occurrence_histogram": capped_occurrence,
            "table_coverage": table_coverage,
            "float_train": optimizer.loss(train, floats), "integer_train": optimizer.loss(train, weights, integer=True),
            "float_validation": optimizer.loss(validation, floats),
            "integer_validation": optimizer.loss(validation, weights, integer=True),
            "train_precision": phase_precision_metrics(train, floats, weights),
            "validation_precision": phase_precision_metrics(validation, floats, weights),
            "validation_status": state["validation_status"]})
    return phase_weights, phase_diagnostics, None


def cycle(driver, snapshot, *, extend=False):
    m, root, config = driver.m, driver.root, driver.m["settings"]
    import table32_players as players
    candidate_pin = None
    def check(identifier, board, side, value, setting, kind="teacher"):
        effective = {**setting,"time_limit_ms":config["time_limit_ms"],"node_limit":config["node_limit"]}
        pins = ({"executable":m["candidate_executable"],
                 "artifact":candidate_pin if kind=="candidate" else m["baseline"]}
                if m["input_kind"]=="production" else None)
        return players.validate_raw_decision(identifier,board,side,value,effective,expected_pins=pins,
                    expected_evaluator="trained-table32" if kind=="candidate" else "trained")
    choose, solve = (driver.providers if driver.providers is not None else production_providers(driver))
    driver.computed("input-verification", "snapshot", {"snapshot_digest": m["snapshot_digest"],
                     "limits": m["limits"], "acceptance_reservation": "not-yet-selected"})
    pool = inputs.early_pool(m["seed"], max_sequences=config["pool_sequences"],
                             total_limit=config["early_positions"], candidate_limit=config["early_candidates_per_phase"])
    driver.computed("teacher-preflight", "early-pool", pool)
    roots = snapshot["preflight_roots"]
    decisions, queries, labels = [], [], []
    for index, position in enumerate(roots):
        identifier, board, side = position["id"], position["board"], position["side"]
        decision = driver.unit("teacher-preflight", identifier,
            lambda: choose("teacher", identifier, board, side, inputs.TEACHER_SETTINGS),
            lambda value: check(identifier, board, side, value, inputs.TEACHER_SETTINGS), index+1, 12)
        decisions.append(decision)
        for query in (inputs.oracle_query(position), inputs.oracle_query(position, child_move=decision["move"])):
            queries.append(driver.unit("teacher-preflight", query["id"], lambda: solve(query),
                lambda saved: players.verify_query(query, saved, m["oracle_runtime"], config["decision_timeout_seconds"]),
                len(queries)+1, 24))
    for position in pool["roots"][:2]:
        def create_label():
            return inputs.label_early(position, lambda i,b,s,c: choose("early", i,b,s,c))
        def validate_label(label):
            st.require(label["root"] == position, "early root changed")
            check(position["id"],position["board"],position["side"],label["decision"],inputs.EARLY_SETTINGS)
            inputs.early_row(label)
        labels.append(driver.unit("teacher-preflight", position["id"], create_label, validate_label))
    driver.computed("teacher-preflight", "complete", inputs.validate_preflight(roots, decisions, queries, labels))
    if hasattr(driver,"close_players"):
        driver.close_players()
    gen_start = driver.journal.cursor
    for index, spec in enumerate(m["generation_plan"]):
        def generate():
            return inputs.generate_game(spec, lambda i,b,s,c: choose("teacher",i,b,s,c))
        def validate_game(game):
            st.require(game["spec"] == spec, "game plan changed")
            inputs.replay_game(game)
            for turn, row in enumerate(game["decisions"]):
                check(f"{spec['game_id']}-{turn:03}",row["board"],row["side"],row,inputs.TEACHER_SETTINGS)
        driver.unit("generation", spec["game_id"], generate, validate_game,index+1,len(m["generation_plan"]))
    gen_end = driver.journal.cursor
    if hasattr(driver,"close_players"):
        driver.close_players()
    label_start = driver.journal.cursor
    for index, position in enumerate(pool["roots"][2:], 2):
        def create_label():
            return inputs.label_early(position, lambda i,b,s,c: choose("early", i,b,s,c))
        def validate_label(label):
            st.require(label["root"] == position, "early root changed")
            check(position["id"],position["board"],position["side"],label["decision"],inputs.EARLY_SETTINGS)
            inputs.early_row(label)
        driver.unit("early-labels", position["id"], create_label, validate_label,index+1,len(pool["roots"]))
    label_end = driver.journal.cursor
    if hasattr(driver,"close_players"):
        driver.close_players()
    def data_build(folder):
        import itertools
        return extraction.build(_events(root, gen_start, gen_end),
            itertools.chain(labels, _events(root, label_start, label_end)),
            m["generation_plan"], folder, early_limit=config["early_positions"])
    folder = root / "extracted"
    def validate_extraction(saved):
        with tempfile.TemporaryDirectory(prefix="table32-replay-") as temporary:
            st.require(data_build(temporary) == saved, "split extraction differs from legal replay")
        for name, sha in saved["outputs"].items():
            st.require(training.sha256_file(folder / name) == sha, f"extracted rows changed: {name}")
    extracted = driver.unit("extraction", "rows", lambda: data_build(folder), validate_extraction)
    if extracted["status"] != "ready":
        return final_report(m, driver, extracted["status"], {"coverage": extracted})
    phase_weights, phase_diagnostics, paused = learn_phases(driver, folder)
    if paused is not None:
        return final_report(m, driver, "export-paused", {"resume_phase": "export", "phase": paused})
    artifact = model.make_artifact(phase_weights, {"trainer_version":model.TRAINER,"seed":m["seed"],
        "input_manifest_digest": st.digest(m),"producer_commit":m["producer_commit"],
        "source_kind":"project-owned","optimizer":model.OPTIMIZER})
    driver.computed("export", "candidate-artifact", artifact)
    if driver.execute:
        st.atomic(root / "candidate-artifact.json", artifact, once=True)
    else:
        st.require(st.read(root / "candidate-artifact.json") == artifact,"candidate artifact changed")
    candidate_pin=st.pin(root/"candidate-artifact.json")
    def metrics(split):
        squared, count = 0, 0
        for phase in range(60):
            for row in extraction.phase_rows(folder,split,phase):
                squared += (model.predict(artifact,row["board"],row["side"])-row["target"])**2
                count += 1
        return {"rows":count,"squared_error":squared,"mse":squared/count if count else None}
    diagnostics = {"phases":phase_diagnostics,"test_once_after_candidate_freeze":metrics("test"),
        "coverage":extracted,"test_limitations":"small sample; phase coverage may be missing"}
    for name in ("validation","held_out"):
        rows = snapshot[name]
        squared = sum((model.predict(artifact,r["board"],r["side"])-r["target"])**2 for r in rows)
        diagnostics["exposed_reference_"+name] = {"rows":len(rows),"squared_error":squared,
                                                "mse":squared/len(rows) if rows else None}
    corpus_regret = {"baseline":0,"candidate":0}
    match_config = {**inputs.TEACHER_SETTINGS,"opening_depth":12,"midgame_depth":12,
                    "endgame_depth":12,"exact_solver_empty_squares":16}
    st.require(len(snapshot["corpus"])==len(snapshot["golden"]),"corpus/golden size differs")
    for index,(position,golden) in enumerate(zip(snapshot["corpus"],snapshot["golden"])):
        board,side=position["board"],position["side_to_move"]
        for kind in ("baseline","candidate"):
            identifier=f"corpus-{index:03d}-{kind}"
            decision=driver.unit("diagnostics",identifier,
                lambda:choose(kind,identifier,board,side,match_config),
                lambda value:check(identifier,board,side,value,match_config,kind),index+1,len(snapshot["corpus"]))
            analysis=golden["analysis"]
            values={row["move"]:row["value"] for row in analysis["evaluations"]}
            corpus_regret[kind]+=analysis["best_value"]-values[decision["move"]] if position["legal_moves"] else 0
    diagnostics["exposed_reference_corpus"]={kind:{"positions":len(snapshot["corpus"]),
        "sum_regret":value,"mean_regret":value/len(snapshot["corpus"]) if snapshot["corpus"] else None}
        for kind,value in corpus_regret.items()}
    driver.computed("diagnostics","metrics",diagnostics)
    forbidden = set(snapshot["excluded_keys"])
    with (folder / "exposure-keys.jsonl").open() as stream:
        forbidden.update(json.loads(line) for line in stream)
    forbidden.update(inputs.position_key(r["board"],r["side"]) for r in roots)
    forbidden.update(inputs.position_key(q["query"]["board"],q["query"]["side"]) for q in queries)
    forbidden.update(r["canonical_key"] for r in pool["candidates"])
    for index in range(gen_start,gen_end):
        game = st.read(root / "units" / f"{index:07d}.json")["value"]
        forbidden.update(inputs.position_key(t["board"],t["side"]) for t in game["opening"]["turns"]+game["decisions"])
        forbidden.update(inputs.position_key(game["terminal_board"],s) for s in ("B","W"))
    openings = driver.computed("match20","opening-plan",opening_plan(m["seed"],forbidden))
    points, results, overlaps = 0, [], set()
    exposure=set(forbidden)
    exposure.update(o["canonical_key"] for o in openings)
    for index in range(200 if extend else 20):
        if index == 20:
            st.require(points >= 10, "initial20 screen does not permit extension")
            driver.computed("explicit-match200","human-continue",{"stage20_points":points,"extend_to_200":True})
        phase = "match20" if index < 20 else "explicit-match200"
        opening = openings[index//2]
        def create_match():
            return match_game(index,opening,choose)
        def validate_match(saved):
            rows = iter(saved["decisions"])
            def replay_choose(player,i,b,s,c):
                row = next(rows)
                st.require(row["player"]==player and row["board"]==b and row["side"]==s,"match state differs")
                check(i,b,s,row,c,player)
                return {k:v for k,v in row.items() if k not in ("board","side","player")}
            st.require(match_game(index,opening,replay_choose)==saved,"match legal replay differs")
            st.require(next(rows,None) is None,"extra match decisions")
        game = driver.unit(phase,f"game-{index:03d}",create_match,validate_match,index+1,20 if index<20 else 200)
        points += game["points"]
        results.append({"index":index,"score":game["score_candidate"],"points":game["points"]})
        overlaps.update(inputs.position_key(r["board"],r["side"]) for r in game["decisions"]
                        if inputs.position_key(r["board"],r["side"]) in forbidden)
        exposure.update(inputs.position_key(r["board"],r["side"]) for r in game["decisions"])
        exposure.update(inputs.position_key(game["terminal_board"],s) for s in ("B","W"))
        if index == 19 and points < 10:
            break
    count = len(results)
    outcome = st.match_outcome(points,count)
    exposure_path=root/f"exposure-keys-{count}.jsonl"
    exposure_bytes=b"".join(st.blob(key) for key in sorted(exposure))
    if driver.execute:
        st.atomic_bytes(exposure_path,exposure_bytes,once=True)
    else:
        st.require(exposure_path.read_bytes()==exposure_bytes,"exposure keys do not reconstruct")
    return final_report(m,driver,outcome,{"matches":results,"points":points,"games":count,
        "candidate_digest":model.digest(artifact),"diagnostics_digest":st.digest(diagnostics),
        "incidental_overlap_keys":sorted(overlaps),"exposure_keys":{
            "path":exposure_path.name,"sha256":training.sha256_file(exposure_path),"count":len(exposure)}})


def final_report(manifest, driver, outcome, detail):
    return st.seal({"version":st.VERSION,"manifest_digest":st.digest(manifest),
        "status":"awaiting-human" if outcome in ("awaiting-explicit-continue","export-paused") else "complete",
        "outcome":outcome,"input_kind":manifest["input_kind"],"tooling_only":manifest["input_kind"]!="production",
        "cycle成立":outcome in ("awaiting-explicit-continue","promising-at-pilot-scale","not-improved-at-pilot-scale"),
        "adopted_model_replaced":False,"acceptance_0018":False,"oracle_match_games":0,
        "completed_prefix_digest":driver.journal.previous,**detail})


def production_providers(driver):
    # Lazy construction: saved-prefix replay and offline verify spawn nothing.
    import table32_players as players
    instances = {}
    def close():
        for player in instances.values():
            player.close()
        instances.clear()
    def choose(kind, identifier, board, side, config):
        st.require(driver.execute,"offline replay attempted to start a candidate")
        artifact = (driver.root / "candidate-artifact.json" if kind=="candidate"
                    else Path(driver.m["baseline"]["path"]))
        key = (kind,st.digest(config))
        if key not in instances:
            effective = {**config,"time_limit_ms":driver.m["settings"]["time_limit_ms"],
                         "node_limit":driver.m["settings"]["node_limit"]}
            instances[key] = players.Player(driver.m["candidate_executable"]["path"],artifact,effective,
                driver.m["settings"]["decision_timeout_seconds"],
                evaluator="trained-table32" if kind=="candidate" else "trained",
                log=driver.attempt / "decisions.jsonl",expected_pins={
                    "executable":driver.m["candidate_executable"],
                    "artifact":st.pin(artifact)})
        return instances[key].decision(identifier,board,side)
    def solve(query):
        st.require(driver.execute,"offline replay attempted to start Oracle")
        close()
        return players.query_oracle(query,driver.m["oracle_runtime"],
                   driver.m["settings"]["decision_timeout_seconds"],driver.attempt)
    driver.close_players = close
    return choose, solve


def run(args):
    import table32_process
    root = args.run_root.resolve()
    manifest,snapshot = load(root,verify_originals=False)
    st.require(clean_commit()==manifest["producer_commit"],"execution commit changed; use prepared producer")
    if args.extend_to_200:
        from table32_verify import verify
        st.require((root/"screening-report.json").is_file(),
                   "--extend-to-200 requires an existing completed20-game screen")
        verify(root)
        screening=st.read(root/"screening-report.json")
        st.require(screening.get("outcome")=="awaiting-explicit-continue" and screening.get("points",0)>=10
                   and not (root/"report.json").exists(),
                   "--extend-to-200 requires a completed20-game screen of at least10 points")
    for unit,total in (("planned-games",manifest["limits"]["games"]),
                       ("planned-early-labels",manifest["limits"]["early_labels"]),
                       ("planned-preflight-decisions",12),("planned-oracle-queries",24),
                       ("planned-training-steps",60*config_value(manifest,"max_steps")),
                       ("planned-export-proposals",60*config_value(manifest,"max_proposals")),
                       ("planned-matches",200 if args.extend_to_200 else 20)):
        print(f"table32 phase=input-verification unit={unit} completed=0 total={total} elapsed_seconds=0.000 status=planned",file=sys.stderr,flush=True)
    def worker(attempt):
        import contextlib
        with (attempt/"input-verification.stderr").open("w") as log:
            with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
                load(root)
        driver = Driver(root,manifest,execute=True,every=args.progress_every,attempt=attempt,
                        resume_from=args.resume_from)
        try:
            report = cycle(driver,snapshot,extend=args.extend_to_200)
            driver.finish()
            if report["outcome"]!="export-paused":
                target = "screening-report.json" if report["outcome"]=="awaiting-explicit-continue" else "report.json"
                st.atomic(root/target,report,once=True)
                if hasattr(driver,"close_players"):
                    driver.close_players()
                driver.journal.progress("offline-verification","report",0,1,"running")
                st.atomic(attempt/"progress.json",{"phase":"offline-verification","unit":"report"})
                from table32_verify import verify
                verified=verify(root)
                st.require(verified==report,"execution report differs from independent replay")
                name="screening-verification.receipt.json" if target=="screening-report.json" else "offline-verification.receipt.json"
                st.atomic(root/name,st.seal({"report_digest":st.digest(report),
                    "manifest_digest":st.digest(manifest),"prefix_digest":driver.journal.previous}),once=True)
                driver.journal.progress("offline-verification","report",1,1,"verified")
            st.atomic(root/"status.json",report)
        finally:
            if hasattr(driver,"close_players"):
                driver.close_players()
    table32_process.supervise(root,manifest,worker,progress_every=args.progress_every,
                               resume_from=args.resume_from,extend=args.extend_to_200)
    return st.read(root/"status.json")


def config_value(manifest,name):
    return manifest["settings"][name]


def main(argv):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="action",required=True)
    prep=commands.add_parser("prepare")
    for name in ("run-root","source-manifest","source-comparison-root","source-evaluation-root",
                 "candidate-executable","oracle-runtime-receipt"):
        prep.add_argument("--"+name,type=Path,required=True)
    defaults={"seed":inputs.SEED,"train-per-prefix":12,"validation-per-prefix":2,"test-per-prefix":2,
        "early-positions":256,"early-candidates-per-phase":32,"pool-sequences":10000,
        "max-steps":1000,"max-proposals":1000,"decision-timeout-seconds":310,
        "time-limit-ms":300000,"node-limit":10000000,"max-wall-seconds":259200,
        "producer-rss-kib":262144,"child-rss-kib":1572864}
    for name,value in defaults.items(): prep.add_argument("--"+name,type=int,default=value)
    for action in ("run","verify"):
        command=commands.add_parser(action)
        command.add_argument("--run-root",type=Path,required=True)
        command.add_argument("--progress-every",type=inputs.rf.positive_interval,default=1)
        if action=="run":
            command.add_argument("--resume-from",choices=st.PHASES)
            command.add_argument("--extend-to-200",action="store_true")
    args=parser.parse_args(argv)
    if args.action=="prepare": result=prepare(args)
    elif args.action=="run": result=run(args)
    else:
        from table32_verify import verify
        result=verify(args.run_root)
    print(f"table32 {args.action} root={args.run_root} digest={st.digest(result)} outcome={result.get('outcome','prepared')}")
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (training.TrainingError,ValueError,OSError,KeyError,TypeError) as error:
        print(f"table32 error: {error}",file=sys.stderr)
        raise SystemExit(2)
