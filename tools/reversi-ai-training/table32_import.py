"""Read completed games from a saved table32 run without changing its files.

Saved receipts are trusted as completed records.  This module checks the
compatibility and split boundaries needed by a new experiment; it does not
replay historic searches or rebuild their reports.
"""
from pathlib import Path

import reinforcement as rf
import table32_inputs as inputs
import table32_store as st
import training


def _game_rows(game):
    spec = game.get("spec")
    st.require(isinstance(spec, dict) and spec.get("split") in ("train", "validation", "test")
               and isinstance(spec.get("game_id"), str), "import game split/spec invalid")
    decisions = game.get("decisions")
    st.require(isinstance(decisions, list) and decisions, "import game has no completed decisions")
    terminal = game.get("terminal_board")
    side = game.get("terminal_side")
    st.require(isinstance(terminal, str) and len(terminal) == 64 and set(terminal) <= {"B", "W", "."}
               and side in ("B", "W")
               and not rf.legal_moves(terminal, side)
               and not rf.legal_moves(terminal, rf.other(side))
               and game.get("final_score_black") == training.terminal_score(terminal, "B"),
               "import game is not completed")
    for decision in decisions:
        st.require(isinstance(decision, dict), "import decision invalid")
        yield inputs.position_key(decision.get("board"), decision.get("side"))


def validate_splits(games):
    """Reject duplicate game ids and cross-split board/side exposure."""
    names, positions = set(), {}
    for game in games:
        spec = game["spec"]
        name, split = spec["game_id"], spec["split"]
        st.require(name not in names, "duplicate imported game id")
        names.add(name)
        for key in _game_rows(game):
            prior = positions.setdefault(key, split)
            st.require(prior == split, "import cross-split position collision")


def _compatible_teacher(saved, requested, target_phases):
    if not isinstance(saved, dict) or not isinstance(requested, dict):
        return False
    if saved == requested:
        return True
    threshold = "exact_solver_empty_squares"
    if ({k: v for k, v in saved.items() if k != threshold} !=
            {k: v for k, v in requested.items() if k != threshold}):
        return False
    if not target_phases or not all(type(p) is int and 0 <= p < 60 for p in target_phases):
        return False
    saved_exact, requested_exact = saved.get(threshold), requested.get(threshold)
    # Each phase p has 60-p empty squares. Every imported target position
    # must fall into the exact-search region under both policies.
    largest_empty = 60 - min(target_phases)
    return (saved_exact == 25 and type(saved_exact) is int
            and requested_exact == 20 and type(requested_exact) is int
            and saved_exact >= largest_empty and requested_exact >= largest_empty)


def completed_games(source_root, *, teacher_settings, baseline, other_games=(),
                    target_phases=None):
    """Return trusted complete records and source metadata; never write source.

    `baseline` is the saved manifest identity dict. The source teacher must use
    the same saved baseline digest and compatible search settings. The old
    exact25 setting is compatible with exact20 for phases 40 and later only.
    `other_games` lets the caller enforce split separation against its own data.
    """
    root = Path(source_root).resolve(strict=True)
    manifest = st.read(root / "manifest.json")
    st.require(manifest.get("version") == st.VERSION
               and manifest.get("score_contract") == training.SCORE_CONTRACT,
               "unsupported import manifest")
    source_baseline = manifest.get("baseline", {})
    st.require(isinstance(source_baseline, dict) and isinstance(baseline, dict)
               and source_baseline.get("sha256") is not None
               and source_baseline.get("sha256") == baseline.get("sha256"),
               "import baseline differs")
    units = sorted((root / "units").glob("*.json"))
    games, receipts = [], []
    for index, path in enumerate(units):
        st.require(path.name == f"{index:07d}.json", "import units are not contiguous")
        entry = st.read(path)
        st.require(entry.get("index") == index, "import unit index differs")
        if entry.get("phase") != "generation":
            continue
        game = entry.get("value")
        st.require(isinstance(game, dict) and game.get("schema_version") == 1
                   and game.get("version") == inputs.VERSION
                   and game.get("score_contract") == training.SCORE_CONTRACT
                   and game.get("source_kind") == "project-owned-s0-continuation"
                   and _compatible_teacher(game.get("teacher_settings"), teacher_settings,
                                           target_phases),
                   "import game settings or format differ")
        st.require(entry.get("unit") == game.get("spec", {}).get("game_id"),
                   "import game unit differs")
        # The saved game is the completed unit; temporary move checkpoints and
        # raw logs never enter this list.
        list(_game_rows(game))
        games.append(game)
        receipts.append({"index": index, "unit": entry["unit"], "digest": entry.get("digest")})
    st.require(games, "source has no completed generation games")
    validate_splits([*games, *other_games])
    return {"source_root": str(root), "source_manifest_digest": st.digest(manifest),
            "receipts": receipts, "games": games}
