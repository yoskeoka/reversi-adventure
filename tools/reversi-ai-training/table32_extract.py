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
          expected_prefixes=None, trusted_import_count=0):
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
    raw_prefix,side_counts=collections.Counter(),collections.Counter()
    with tempfile.TemporaryDirectory(prefix="table32-split-") as temporary:
        db = sqlite3.connect(str(Path(temporary) / "rows.sqlite"))
        db.execute("PRAGMA cache_size=-8192")
        db.execute("CREATE TABLE rows (ordinal INTEGER PRIMARY KEY, id TEXT UNIQUE, key TEXT, split TEXT, value TEXT)")
        def add(row):
            if row["phase"] not in selected:
                return
            raw_counts[(row["split"], row["phase"])] += 1
            if row["prefix_length"] is not None:
                raw_prefix[(row["split"],row["prefix_length"])]+=1
            db.execute("INSERT INTO rows(id,key,split,value) VALUES (?,?,?,?)",
                       (row["id"], row["canonical_key"], row["split"], st.blob(row).decode()))
        game_count = 0
        for game_count, game in enumerate(games, 1):
            st.require(game_count <= len(specs) and game["spec"] == specs[game_count-1],
                       "generation differs from frozen plan")
            if game_count <= trusted_import_count:
                spec = game["spec"]
                rows = ({"id": f"{spec['game_id']}-{cursor:03}", "game_id": spec["game_id"],
                         "split": spec["split"], "prefix_length": spec["prefix_length"],
                         "board": turn["board"], "side": turn["side"],
                         "phase": inputs.phase(turn["board"]),
                         "target": game["final_score_black"] * (1 if turn["side"] == "B" else -1),
                         "source_kind": "project-owned-s0-terminal", "score_contract": inputs.training.SCORE_CONTRACT,
                         "canonical_key": inputs.position_key(turn["board"], turn["side"])}
                        for cursor, turn in enumerate(game["decisions"]))
            else:
                rows = inputs.replay_game(game, limits=limits)
            for row in rows:
                add(row)
        st.require(game_count == len(specs), "generation incomplete")
        label_count = 0
        for label_count, label in enumerate(labels, 1):
            st.require(label_count <= early_limit, "early label budget exceeded")
            add(inputs.early_row(label, limits=limits))
        db.execute("CREATE INDEX key_split ON rows(key,split)")
        db.execute("CREATE TABLE collisions AS SELECT key FROM rows GROUP BY key HAVING COUNT(DISTINCT split)>1")
        db.execute("CREATE INDEX collisions_key ON collisions(key)")
        db.execute("CREATE TABLE first_row AS SELECT key,split,MIN(ordinal) ordinal FROM rows GROUP BY key,split")
        db.execute("CREATE INDEX first_key_split ON first_row(key,split)")
        db.commit()
        paths = {}
        for split in ("train", "validation", "test"):
            for phase in range(60):
                path = folder / f"{split}-{phase:02d}.jsonl"
                with path.open("wb") as stream:
                    query = ("SELECT rows.value FROM rows JOIN first_row f ON rows.ordinal=f.ordinal "
                             "LEFT JOIN collisions c ON rows.key=c.key WHERE c.key IS NULL "
                             "AND rows.split=? ORDER BY rows.ordinal")
                    for (encoded,) in db.execute(query, (split,)):
                        row = json.loads(encoded)
                        if row["phase"] != phase:
                            continue
                        row["features"] = model.features(row["board"], row["side"])
                        stream.write(st.blob(row))
                        counts[(split, phase)] += 1
                        side_counts[(split,row["side"])]+=1
                        if row["prefix_length"] is not None:
                            prefix[(split, row["prefix_length"])] += 1
                paths[path.name] = st.pin(path)["sha256"]
        with (folder / "excluded.jsonl").open("wb") as stream:
            query = ("SELECT rows.id,rows.key,rows.split,c.key IS NOT NULL FROM rows "
                     "JOIN first_row f ON rows.key=f.key AND rows.split=f.split "
                     "LEFT JOIN collisions c ON rows.key=c.key "
                     "WHERE c.key IS NOT NULL OR rows.ordinal<>f.ordinal ORDER BY rows.ordinal")
            for identifier, key, split, collision in db.execute(query):
                stream.write(st.blob({"id": identifier, "key": key, "split": split,
                    "reason": "cross-split-canonical-collision" if collision else "within-split-canonical-duplicate"}))
        with (folder / "exposure-keys.jsonl").open("wb") as stream:
            for (key,) in db.execute("SELECT DISTINCT key FROM rows ORDER BY key"):
                stream.write(st.blob(key))
        db.close()
    for name in ("excluded.jsonl", "exposure-keys.jsonl"):
        paths[name] = st.pin(folder / name)["sha256"]
    missing = [p for p in selected if not counts[("train", p)]]
    missing_validation = [p for p in selected if not counts[("validation", p)]]
    split_missing = [s for s in ("train", "validation", "test") if not any(counts[(s,p)] for p in range(60))]
    prefix_missing = [[s, length] for s in ("train", "validation", "test")
                      for length in expected_prefixes if not prefix[(s,length)]]
    return {"outputs": paths, "games": game_count, "early_labels": label_count,
            "raw_phase_rows": {s: {str(p): raw_counts[(s,p)] for p in range(60)} for s in ("train", "validation", "test")},
            "phase_rows": {s: {str(p): counts[(s,p)] for p in range(60)} for s in ("train", "validation", "test")},
            "prefix_rows": {s: {str(p): prefix[(s,p)] for p in reported_prefixes} for s in ("train", "validation", "test")},
            "raw_prefix_rows": {s: {str(p):raw_prefix[(s,p)] for p in reported_prefixes} for s in ("train","validation","test")},
            "side_rows":{s:{side:side_counts[(s,side)] for side in ("B","W")} for s in ("train","validation","test")},
            "training_unavailable": missing, "validation_unavailable": missing_validation,
            "split_missing": split_missing, "prefix_missing": prefix_missing,
            "status": "training-phase-unavailable" if missing else
                      "input-coverage-unavailable" if split_missing or prefix_missing else "ready"}


def phase_rows(folder, split, phase):
    # Deliberately load only one occupied-disc phase, never the full corpus.
    path = Path(folder) / f"{split}-{phase:02d}.jsonl"
    with path.open() as stream:
        return [json.loads(line) for line in stream]
