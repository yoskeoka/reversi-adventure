"""Disk-backed split exclusion and one-phase-at-a-time training rows."""
from __future__ import annotations

import collections
import json
import sqlite3
import tempfile
from pathlib import Path

import table32_inputs as inputs
import table32_model as model
import table32_store as st


def build(games, labels, specs, folder, *, early_limit, limits=None, target_phases=None,
          expected_prefixes=None, trusted_import_count=0, train_collision_priority=False,
          opening_coverage=False, fixed_rows=(), coverage_minima=None, reserved_keys=()):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    selected = tuple(range(60)) if target_phases is None else tuple(target_phases)
    st.require(bool(selected) and len(set(selected)) == len(selected)
               and all(type(p) is int and 0 <= p < 60 for p in selected),
               "invalid target phases")
    if expected_prefixes is None:
        expected_prefixes = sorted({spec["prefix_length"] for spec in specs})
    # Preserve legacy keys while reporting operator-selected and imported
    # prefixes, including those whose rows were all excluded.
    reported_prefixes = sorted(set(inputs.PREFIX_LENGTHS) | set(expected_prefixes)
                               | {spec["prefix_length"] for spec in specs})
    counts, prefix, raw_counts = collections.Counter(), collections.Counter(), collections.Counter()
    raw_prefix, side_counts = collections.Counter(), collections.Counter()
    run_games = collections.Counter()
    rejected_reserved, reached = collections.Counter(), collections.Counter()
    adopted_games = collections.defaultdict(set)
    reserved = set(reserved_keys)
    with tempfile.TemporaryDirectory(prefix="table32-split-") as temporary:
        db = sqlite3.connect(str(Path(temporary) / "rows.sqlite"))
        db.execute("PRAGMA cache_size=-8192")
        db.execute("CREATE TABLE rows (ordinal INTEGER PRIMARY KEY, id TEXT UNIQUE, key TEXT, split TEXT, phase INTEGER, value TEXT)")
        def add(row):
            if row["phase"] not in selected:
                return
            raw_counts[(row["split"], row["phase"])] += 1
            if row["prefix_length"] is not None:
                raw_prefix[(row["split"],row["prefix_length"])]+=1
            if row["canonical_key"] in reserved:
                rejected_reserved[(row["split"], row["phase"])] += 1
                return
            db.execute("INSERT INTO rows(id,key,split,phase,value) VALUES (?,?,?,?,?)",
                       (row["id"], row["canonical_key"], row["split"], row["phase"], st.blob(row).decode()))
        game_count = 0
        for game_count, game in enumerate(games, 1):
            st.require(game_count <= len(specs) and game["spec"] == specs[game_count-1],
                       "generation differs from frozen plan")
            if game_count <= trusted_import_count:
                spec = game["spec"]
                rows = [{"id": f"{spec['game_id']}-{cursor:03}", "game_id": spec["game_id"],
                         "split": spec["split"], "prefix_length": spec["prefix_length"],
                         "board": turn["board"], "side": turn["side"],
                         "phase": inputs.phase(turn["board"]),
                         "target": game["final_score_black"] * (1 if turn["side"] == "B" else -1),
                         "source_kind": "project-owned-s0-terminal", "score_contract": inputs.training.SCORE_CONTRACT,
                         "canonical_key": inputs.position_key(turn["board"], turn["side"])}
                        for cursor, turn in enumerate(game["decisions"])]
            else:
                rows = inputs.replay_game(game, limits=limits)
            if opening_coverage:
                # Only the selected opening belongs to this phase/split. Later
                # decisions remain exposures but cannot leak into another split.
                rows = rows[:1]
            if coverage_minima is not None:
                spec = game["spec"]
                run_games[(spec["split"], spec["prefix_length"])] += 1
                for phase in {row["phase"] for row in rows}:
                    reached[(spec["split"], phase)] += 1
            for row in rows:
                add(row)
        st.require(game_count == len(specs), "generation incomplete")
        label_count = 0
        for label_count, label in enumerate(labels, 1):
            st.require(label_count <= early_limit, "early label budget exceeded")
            add(inputs.early_row(label, limits=limits))
        fixed_count = 0
        for row in fixed_rows:
            fixed_count += 1
            add(row)
        db.execute("CREATE INDEX key_split ON rows(key,split)")
        db.execute("CREATE INDEX split_phase ON rows(split,phase)")
        db.execute("CREATE TABLE collisions AS SELECT key FROM rows GROUP BY key HAVING COUNT(DISTINCT split)>1")
        db.execute("CREATE TABLE train_priority (key TEXT PRIMARY KEY)")
        if train_collision_priority:
            # An initial position is necessarily shared by all games. Assign
            # shared positions to training only; never expose them to validation.
            db.execute("INSERT INTO train_priority SELECT DISTINCT rows.key FROM rows JOIN collisions c ON rows.key=c.key WHERE rows.split='train'")
        db.execute("CREATE INDEX collisions_key ON collisions(key)")
        db.execute("CREATE TABLE first_row(ordinal INTEGER PRIMARY KEY, key TEXT, split TEXT)")
        db.execute("INSERT INTO first_row SELECT MIN(ordinal),key,split FROM rows GROUP BY key,split")
        db.execute("CREATE INDEX first_key_split ON first_row(key,split)")
        unique = {(split, phase): count for split, phase, count in db.execute(
            "SELECT rows.split,rows.phase,COUNT(*) FROM rows JOIN first_row f USING (ordinal) "
            "GROUP BY rows.split,rows.phase")} if coverage_minima is not None else {}
        db.commit()
        paths = {}
        for split in ("train", "validation", "test"):
            for phase in range(60):
                path = folder / f"{split}-{phase:02d}.jsonl"
                with path.open("wb") as stream:
                    query = ("SELECT rows.value FROM rows JOIN first_row f ON rows.ordinal=f.ordinal "
                             "LEFT JOIN collisions c ON rows.key=c.key LEFT JOIN train_priority t ON rows.key=t.key "
                             "WHERE (c.key IS NULL OR (t.key IS NOT NULL AND rows.split='train')) "
                             "AND rows.split=? AND rows.phase=? ORDER BY rows.ordinal")
                    for (encoded,) in db.execute(query, (split, phase)):
                        row = json.loads(encoded)
                        row["features"] = model.features(row["board"], row["side"])
                        stream.write(st.blob(row))
                        counts[(split, phase)] += 1
                        if coverage_minima is not None and row["game_id"] is not None:
                            adopted_games[(split, phase)].add(row["game_id"])
                        side_counts[(split,row["side"])]+=1
                        if row["prefix_length"] is not None:
                            prefix[(split, row["prefix_length"])] += 1
                paths[path.name] = st.pin(path)["sha256"]
        with (folder / "excluded.jsonl").open("wb") as stream:
            query = ("SELECT rows.id,rows.key,rows.split,c.key IS NOT NULL FROM rows "
                     "JOIN first_row f ON rows.key=f.key AND rows.split=f.split "
                     "LEFT JOIN collisions c ON rows.key=c.key "
                     "LEFT JOIN train_priority t ON rows.key=t.key "
                     "WHERE (c.key IS NOT NULL AND NOT (t.key IS NOT NULL AND rows.split='train')) "
                     "OR rows.ordinal<>f.ordinal ORDER BY rows.ordinal")
            for identifier, key, split, collision in db.execute(query):
                stream.write(st.blob({"id": identifier, "key": key, "split": split,
                    "reason": "cross-split-canonical-collision" if collision else "within-split-canonical-duplicate"}))
        with (folder / "exposure-keys.jsonl").open("wb") as stream:
            for (key,) in db.execute("SELECT DISTINCT key FROM rows ORDER BY key"):
                stream.write(st.blob(key))
        db.close()
    for name in ("excluded.jsonl", "exposure-keys.jsonl"):
        paths[name] = st.pin(folder / name)["sha256"]
    missing = [p for p in selected if not counts[("train", p)] and not (opening_coverage and p == 0)]
    missing_validation = [p for p in selected if not counts[("validation", p)]]
    split_missing = [s for s in ("train", "validation", "test") if not any(counts[(s,p)] for p in range(60))]
    prefix_missing = [[s, length] for s in ("train", "validation", "test")
                      for length in expected_prefixes if not prefix[(s,length)]]
    status = ("training-phase-unavailable" if missing else
              "input-coverage-unavailable" if not opening_coverage and (split_missing or prefix_missing) else "ready")
    coverage = {}
    if coverage_minima is not None:
        shortages = [{"phase": p, "split": s, "minimum": coverage_minima[s],
                      "adopted": counts[(s, p)], "adopted_games": len(adopted_games[(s, p)])}
                     for p in selected if p >= 10 for s in coverage_minima
                     if len(adopted_games[(s, p)]) < coverage_minima[s]]
        status = ("training-phase-unavailable" if missing else
                  "input-coverage-unavailable" if shortages or prefix_missing else "ready")
        coverage = {"fixed_opening_labels": fixed_count,
                    "coverage_minima": coverage_minima, "coverage_shortages": shortages,
                    "games_per_prefix": {s: {str(p): run_games[(s, p)] for p in expected_prefixes}
                                         for s in coverage_minima},
                    "reached_games": {s: {str(p): reached[(s, p)] for p in selected} for s in coverage_minima},
                    "adopted_phase_games": {s: {str(p): len(adopted_games[(s, p)]) for p in selected}
                                            for s in coverage_minima},
                    "unique_phase_rows": {s: {str(p): unique.get((s, p), 0) for p in selected} for s in coverage_minima},
                    "reserved_phase_rows": {s: {str(p): rejected_reserved[(s, p)] for p in selected}
                                            for s in coverage_minima},
                    "test_unavailable": [p for p in selected if not counts[("test", p)]]}
    return {"outputs": paths, "games": game_count, "early_labels": label_count,
            "raw_phase_rows": {s: {str(p): raw_counts[(s,p)] for p in range(60)} for s in ("train", "validation", "test")},
            "phase_rows": {s: {str(p): counts[(s,p)] for p in range(60)} for s in ("train", "validation", "test")},
            "prefix_rows": {s: {str(p): prefix[(s,p)] for p in reported_prefixes} for s in ("train", "validation", "test")},
            "raw_prefix_rows": {s: {str(p):raw_prefix[(s,p)] for p in reported_prefixes} for s in ("train","validation","test")},
            "side_rows":{s:{side:side_counts[(s,side)] for side in ("B","W")} for s in ("train","validation","test")},
            "training_unavailable": missing, "validation_unavailable": missing_validation,
            **({"test_unavailable": [p for p in selected if not counts[("test", p)]],
                "fixed_zero_phases": [0] if 0 in selected else []} if opening_coverage else {}),
            "split_missing": split_missing, "prefix_missing": prefix_missing,
            **coverage, "status": status}


def phase_rows(folder, split, phase):
    # Deliberately load only one occupied-disc phase, never the full corpus.
    path = Path(folder) / f"{split}-{phase:02d}.jsonl"
    with path.open() as stream:
        return [json.loads(line) for line in stream]
