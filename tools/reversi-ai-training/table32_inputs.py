"""Deterministic, project-owned inputs for the bounded table32 pilot.

No process is launched here. The operator supplies frozen teacher/Oracle
adapters; saved games and labels can be replayed entirely offline.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Callable, Iterable

import reinforcement as rf
import training

VERSION = "reversi-ai-table32-inputs-v1"
SEED = 2026110102
PREFIX_LENGTHS = (12, 18, 21, 24, 30, 40, 50, 58)
SPLIT_COUNTS = {"train": 12, "validation": 2, "test": 2}
TEACHER_SETTINGS = {"opening_depth": 11, "midgame_depth": 11,
                    "endgame_depth": 11, "exact_solver_empty_squares": 25,
                    "time_limit_ms": 300000, "node_limit": 10000000,
                    "book": "off", "cache_scope": "turn"}
EARLY_SETTINGS = {**TEACHER_SETTINGS, "opening_depth": 17,
                  "midgame_depth": 17, "endgame_depth": 17}
FULL_SOLVE_SETTINGS = {"version": "7.8.1", "book": "off", "threads": 1,
                       "hash": 25, "mpc": False, "profile": "table32-full-solve-v1"}
Choose = Callable[[str, str, str, dict], dict]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise training.TrainingError(message)


def seed_stream(seed: int, purpose: str, length: int = 0,
                split: str = "", game: int = 0) -> int:
    require(type(seed) is int and 0 <= seed < 2**64, "invalid master seed")
    return int(training.digest({"version": VERSION, "master": seed,
                               "purpose": purpose, "length": length,
                               "split": split, "game": game}), 16)


def position_key(board: str, side: str) -> str:
    require(isinstance(board, str) and len(board) == 64 and set(board) <= {"B", "W", "."}
            and side in ("B", "W"), "invalid board/side")
    return training.canonical_position_key(board, side)


def phase(board: str) -> int:
    occupied = 64 - board.count(".")
    require(4 <= occupied <= 64, "invalid occupied count")
    return min(59, occupied - 4)


def generation_plan(seed: int = SEED, train_per_prefix: int = 12,
                    validation_per_prefix: int = 2, test_per_prefix: int = 2) -> list[dict]:
    counts = {"train": train_per_prefix, "validation": validation_per_prefix, "test": test_per_prefix}
    require(all(type(value) is int and value > 0 for value in counts.values()),
            "split counts must be positive integers")
    return [{"game_id": f"p{length:02}-{split}-{ordinal:02}", "split": split,
             "prefix_length": length, "ordinal": ordinal, "seed": seed,
             "stream_seed": seed_stream(seed, "generation", length, split, ordinal)}
            for length in PREFIX_LENGTHS for split, count in counts.items()
            for ordinal in range(count)]


def advance(board: str, side: str, move: str) -> tuple[str, str]:
    legal = sorted(rf.legal_moves(board, side))
    if move == "pass":
        require(not legal and bool(rf.legal_moves(board, rf.other(side))), "illegal pass")
    else:
        require(move in legal, "illegal recorded move")
        board = rf.apply_move(board, side, move)
    return board, rf.other(side)


def random_prefix(spec: dict, *, allow_terminal: bool = False) -> dict:
    require(type(spec.get("prefix_length")) is int and 0 <= spec["prefix_length"] <= 58,
            "invalid prefix length")
    board, side, turns, placements = rf.INITIAL, "B", [], 0
    rng = random.Random(spec["stream_seed"])
    while placements < spec["prefix_length"]:
        legal = sorted(rf.legal_moves(board, side))
        if legal:
            move = legal[rng.randrange(len(legal))]
            placements += 1
        else:
            if not rf.legal_moves(board, rf.other(side)):
                require(allow_terminal, "random prefix reached terminal before requested placements")
                break
            move = "pass"
        turns.append({"board": board, "side": side, "move": move, "kind": "random-prefix"})
        board, side = advance(board, side, move)
    return {"board": board, "side": side, "turns": turns}


def validate_decision(board: str, side: str, result: dict, settings: dict) -> dict:
    require(isinstance(result, dict), "teacher-policy-infeasible: missing decision")
    for name in ("score", "completed_depth", "nodes", "elapsed_ms"):
        require(type(result.get(name)) is int, f"teacher-policy-infeasible: invalid {name}")
    require(type(result.get("exact")) is bool and -64 <= result["score"] <= 64,
            "teacher-policy-infeasible: invalid score/exactness")
    require(0 <= result["nodes"] <= settings["node_limit"]
            and 0 <= result["elapsed_ms"] <= settings["time_limit_ms"],
            "teacher-policy-infeasible: resource ceiling exceeded")
    if result.get("forced_pass") is True:
        require(not rf.legal_moves(board, side) and bool(rf.legal_moves(board, rf.other(side)))
                and result.get("move") == "pass" and result["score"] == 0
                and result["completed_depth"] == 0 and result["exact"] is False
                and result["nodes"] == result["elapsed_ms"] == 0,
                "teacher-policy-infeasible: invalid forced pass")
        return dict(result)
    empties = board.count(".")
    if empties <= settings["exact_solver_empty_squares"]:
        require(result["exact"] and result["completed_depth"] >= empties,
                "teacher-policy-infeasible: incomplete exact search")
    else:
        require(result["completed_depth"] >= settings["opening_depth"],
                "teacher-policy-infeasible: incomplete requested depth")
    advance(board, side, result.get("move"))
    return dict(result)


def generate_game(spec: dict, choose: Choose) -> dict:
    opening = random_prefix(spec)
    board, side, decisions = opening["board"], opening["side"], []
    while rf.legal_moves(board, side) or rf.legal_moves(board, rf.other(side)):
        require(len(decisions) < 120, "generation decision ceiling exceeded")
        result = validate_decision(board, side,
                                   choose(f"{spec['game_id']}-{len(decisions):03}", board, side,
                                          dict(TEACHER_SETTINGS)), TEACHER_SETTINGS)
        decisions.append({"board": board, "side": side, **result})
        board, side = advance(board, side, result["move"])
    game = {"schema_version": 1, "version": VERSION,
            "score_contract": training.SCORE_CONTRACT, "spec": dict(spec),
            "opening": opening, "decisions": decisions, "terminal_board": board,
            "terminal_side": side, "final_score_black": training.terminal_score(board, "B"),
            "teacher_settings": dict(TEACHER_SETTINGS), "source_kind": "project-owned-s0-continuation"}
    game["game_digest"] = training.digest(game)
    return game


def replay_game(game: dict) -> list[dict]:
    require(game.get("version") == VERSION and game.get("schema_version") == 1
            and game.get("score_contract") == training.SCORE_CONTRACT
            and game.get("source_kind") == "project-owned-s0-continuation"
            and game.get("teacher_settings") == TEACHER_SETTINGS,
            "unsupported table32 game provenance")
    unsigned = {k: v for k, v in game.items() if k != "game_digest"}
    require(game.get("game_digest") == training.digest(unsigned), "table32 game digest mismatch")
    spec = game["spec"]
    require(game["opening"] == random_prefix(spec), "random prefix reconstruction mismatch")
    board, side = game["opening"]["board"], game["opening"]["side"]
    rows = []
    require(isinstance(game["decisions"], list) and len(game["decisions"]) <= 120,
            "generation decision ceiling exceeded")
    for cursor, decision in enumerate(game["decisions"]):
        require(decision.get("board") == board and decision.get("side") == side,
                "generation decision state mismatch")
        validate_decision(board, side, decision, TEACHER_SETTINGS)
        rows.append({"id": f"{spec['game_id']}-{cursor:03}", "game_id": spec["game_id"],
                     "split": spec["split"], "prefix_length": spec["prefix_length"],
                     "board": board, "side": side, "phase": phase(board),
                     "target": game["final_score_black"] * (1 if side == "B" else -1),
                     "source_kind": "project-owned-s0-terminal", "score_contract": training.SCORE_CONTRACT,
                     "canonical_key": position_key(board, side)})
        board, side = advance(board, side, decision["move"])
    require(not rf.legal_moves(board, side) and not rf.legal_moves(board, rf.other(side))
            and board == game["terminal_board"] and side == game["terminal_side"]
            and type(game["final_score_black"]) is int
            and game["final_score_black"] == training.terminal_score(board, "B"),
            "generation terminal score/replay mismatch")
    return rows


def early_pool(seed: int = SEED, *, max_sequences: int = 10000,
               total_limit: int = 256, candidate_limit: int = 32) -> dict:
    require(type(max_sequences) is int and max_sequences >= 1
            and type(total_limit) is int and total_limit >= 12
            and type(candidate_limit) is int and candidate_limit >= 1, "early pool ceiling invalid")
    pools: dict[int, dict[str, dict]] = {length: {} for length in range(12)}
    sequences, exclusions = [], Counter()
    for sequence in range(max_sequences):
        spec = {"prefix_length": 11, "stream_seed": seed_stream(seed, "early-pool", 11, "train", sequence)}
        prefix = random_prefix(spec, allow_terminal=True)
        turns = prefix["turns"]
        sequences.append({"sequence": sequence, "moves": [turn["move"] for turn in turns]})
        board, side, moves, length = rf.INITIAL, "B", [], 0
        for cursor in range(len(turns) + 1):
            legal = rf.legal_moves(board, side)
            if not legal:
                exclusions["forced-pass" if rf.legal_moves(board, rf.other(side)) else "terminal"] += 1
                if cursor < len(turns):
                    move = turns[cursor]["move"]
                    board, side = advance(board, side, move)
                    moves.append(move)
                continue
            key = position_key(board, side)
            pool = pools[length]
            if key in pool:
                exclusions["duplicate"] += 1
            elif len(pool) >= candidate_limit:
                exclusions["phase-candidate-cap"] += 1
            else:
                pool[key] = {"id": f"early-{length:02}-{len(pool):02}", "board": board,
                             "side": side, "placements": length, "phase": phase(board),
                             "canonical_key": key, "prefix": list(moves), "sequence": sequence}
            if cursor < len(turns):
                move = turns[cursor]["move"]
                board, side = advance(board, side, move)
                moves.append(move)
                length += move != "pass"
    require(all(pools.values()), "early pool missing placement length")
    first = [next(iter(pools[length].values())) for length in range(12)]
    first_ids = {root["id"] for root in first}
    rest = [root for pool in pools.values() for root in pool.values() if root["id"] not in first_ids]
    rest.sort(key=lambda root: (training.digest({"seed": seed, "domain": "early-rank",
                                                "key": root["canonical_key"]}), root["id"]))
    selected = first + rest[:total_limit - len(first)]
    selected_ids = {root["id"] for root in selected}
    return {"seed": seed, "roots": selected, "sequences": sequences,
            "candidates": [dict(root, selection="selected" if root["id"] in selected_ids
                                  else "total-root-cap") for pool in pools.values() for root in pool.values()],
            "exclusions": dict(sorted(exclusions.items())),
            "limits": {"sequences": max_sequences, "total": total_limit, "per_phase": candidate_limit}}


def label_early(root: dict, choose: Choose) -> dict:
    require(0 <= root["placements"] <= 11 and phase(root["board"]) == root["phase"]
            and root["canonical_key"] == position_key(root["board"], root["side"]), "invalid early root")
    result = validate_decision(root["board"], root["side"],
                               choose(root["id"], root["board"], root["side"], dict(EARLY_SETTINGS)), EARLY_SETTINGS)
    require(result.get("forced_pass") is not True, "forced pass is not an early search label")
    return {"root": root, "decision": result, "settings": dict(EARLY_SETTINGS),
            "source_kind": "project-owned-s0-depth17", "score_contract": training.SCORE_CONTRACT}


def early_row(label: dict) -> dict:
    require(label.get("settings") == EARLY_SETTINGS
            and label.get("source_kind") == "project-owned-s0-depth17"
            and label.get("score_contract") == training.SCORE_CONTRACT,
            "invalid early teacher provenance")
    root = label["root"]
    validate_decision(root["board"], root["side"], label["decision"], EARLY_SETTINGS)
    require(label["decision"].get("forced_pass") is not True, "forced pass is not an early search label")
    board, side = rf.INITIAL, "B"
    for move in root["prefix"]:
        board, side = advance(board, side, move)
    require((board, side) == (root["board"], root["side"])
            and 64 - board.count(".") - 4 == root["placements"], "invalid early prefix replay")
    return {"id": root["id"], "game_id": None, "split": "train", "prefix_length": None,
            "board": board, "side": side, "phase": phase(board), "target": label["decision"]["score"],
            "source_kind": label["source_kind"], "score_contract": training.SCORE_CONTRACT,
            "canonical_key": position_key(board, side)}


def extract(games: list[dict], labels: list[dict], *, seed: int = SEED,
            require_complete: bool = True, planned_specs: list[dict] | None = None,
            early_limit: int = 256) -> dict:
    expected = generation_plan(seed) if planned_specs is None else planned_specs
    require(type(early_limit) is int and early_limit >= 12
            and bool(expected) and len(games) <= len(expected)
            and len(labels) <= early_limit, "input unit ceiling exceeded")
    specs = [game["spec"] for game in games]
    require(specs == expected[:len(specs)] and (not require_complete or len(specs) == len(expected)),
            "generation plan is not the fixed contiguous prefix")
    raw = [row for game in games for row in replay_game(game)] + [early_row(label) for label in labels]
    require(len(raw) <= len(expected) * 120 + early_limit and len({row["id"] for row in raw}) == len(raw),
            "teacher row ceiling or duplicate IDs")
    key_splits: dict[str, set[str]] = defaultdict(set)
    for row in raw:
        key_splits[row["canonical_key"]].add(row["split"])
    exclusions, rows, seen = [], [], set()
    for row in raw:
        reason = "cross-split-canonical-collision" if len(key_splits[row["canonical_key"]]) > 1 else None
        if not reason and (row["split"], row["canonical_key"]) in seen:
            reason = "within-split-canonical-duplicate"
        if reason:
            exclusions.append({"id": row["id"], "key": row["canonical_key"], "split": row["split"], "reason": reason})
        else:
            seen.add((row["split"], row["canonical_key"]))
            rows.append(row)
    counts = {split: dict(sorted(Counter(str(row["phase"]) for row in rows if row["split"] == split).items(), key=lambda x: int(x[0])))
              for split in SPLIT_COUNTS}
    prefix_counts = {split: dict(Counter(str(row["prefix_length"]) for row in rows
                                        if row["split"] == split and row["prefix_length"] is not None))
                     for split in SPLIT_COUNTS}
    missing_train = [phase for phase in range(60) if not counts["train"].get(str(phase))]
    missing_validation = [phase for phase in range(60) if not counts["validation"].get(str(phase))]
    if require_complete:
        require(all(counts[split] for split in SPLIT_COUNTS), "empty split after deduplication")
        require(all(set(prefix_counts[split]) == {str(length) for length in PREFIX_LENGTHS} for split in SPLIT_COUNTS),
                "missing prefix layer after deduplication")
        require(not missing_train, "training-phase-unavailable: " + ",".join(map(str, missing_train)))
    return {"rows": rows, "exclusions": exclusions,
            "coverage": {"raw_rows": len(raw), "accepted_rows": len(rows), "phase_rows": counts,
                         "prefix_rows": prefix_counts, "training_unavailable": missing_train,
                         "validation_unavailable": missing_validation},
            "exposure_keys": sorted({row["canonical_key"] for row in raw})}


def historical_states(game: dict) -> list[dict]:
    """Replay saved project-owned logs from initial Black, preserving real turns."""
    require(game.get("score_contract") == training.SCORE_CONTRACT, "historical score contract mismatch")
    board, side, states = rf.INITIAL, "B", []
    if "turns" in game:
        turns = game["turns"]
    else:
        require(isinstance(game.get("opening"), list), "historical opening missing")
        for move in game["opening"]:
            if not rf.legal_moves(board, side):
                require(bool(rf.legal_moves(board, rf.other(side))), "historical terminal opening")
                states.append({"board": board, "side": side})
                board, side = advance(board, side, "pass")
            states.append({"board": board, "side": side})
            board, side = advance(board, side, move)
        require((board, side) == (game.get("start_board"), game.get("start_side")), "historical opening mismatch")
        turns = game["decisions"]
    require(isinstance(turns, list) and len(turns) <= 120, "historical turn ceiling")
    for turn in turns:
        require(turn.get("side") == side and turn.get("board", board) == board, "historical turn mismatch")
        states.append({"board": board, "side": side})
        board, side = advance(board, side, turn["move"])
    require(game.get("terminal_board") == board and not rf.legal_moves(board, side)
            and not rf.legal_moves(board, rf.other(side)), "historical nonterminal/mismatched game")
    return states


def preflight_roots(games: Iterable[dict], seed: int = SEED) -> list[dict]:
    candidates: dict[int, dict[str, dict]] = {empty: {} for empty in (20, 22, 24, 25)}
    for game_id, game in enumerate(games):
        turns = game.get("turns", game.get("decisions"))
        require(isinstance(turns, list), "saved historical decisions missing")
        offset = 0 if "turns" in game else len(game.get("opening", []))
        for cursor, state in enumerate(turns, start=offset):
            require(isinstance(state.get("board"), str) and state.get("side") in ("B", "W"),
                    "saved historical position missing")
            state = {"board": state["board"], "side": state["side"]}
            empty = state["board"].count(".")
            if empty in candidates and rf.legal_moves(state["board"], state["side"]):
                key = position_key(state["board"], state["side"])
                candidates[empty].setdefault(key, {"id": f"preflight-e{empty}-g{game_id}-t{cursor}",
                                                     **state, "empty": empty, "canonical_key": key,
                                                     "source_game": game_id, "source_turn": cursor})
    result = []
    for empty, roots in candidates.items():
        ordered = sorted(roots.values(), key=lambda root: (training.digest({"seed": seed,
                         "domain": "preflight-root", "key": root["canonical_key"]}), root["id"]))
        require(len(ordered) >= 3, f"teacher-policy-infeasible: missing saved roots at empty {empty}")
        result.extend(ordered[:3])
    return result


def oracle_query(root: dict, *, child_move: str | None = None) -> dict:
    board, side = root["board"], root["side"]
    if child_move is not None:
        board, side = advance(board, side, child_move)
    return {"id": root["id"] + ("-child" if child_move is not None else "-root"),
            "board": board, "side": side, "depth": board.count("."),
            "settings": dict(FULL_SOLVE_SETTINGS), "score_contract": training.SCORE_CONTRACT}


def validate_preflight(roots: list[dict], decisions: list[dict], queries: list[dict],
                       labels: list[dict]) -> dict:
    require(len(roots) == len(decisions) == 12 and len(queries) == 24
            and Counter(root["empty"] for root in roots) == {20: 3, 22: 3, 24: 3, 25: 3},
            "teacher-policy-infeasible: incomplete exact preflight")
    require(len(labels) == 2, "teacher-policy-infeasible: missing first two early labels")
    for label in labels:
        early_row(label)
    for cursor, (root, decision) in enumerate(zip(roots, decisions)):
        validate_decision(root["board"], root["side"], decision, TEACHER_SETTINGS)
        for offset, query in enumerate((oracle_query(root), oracle_query(root, child_move=decision["move"]))):
            saved = queries[cursor * 2 + offset]
            require(saved.get("query") == query and isinstance(saved.get("result"), dict),
                    "teacher-policy-infeasible: full-solve query identity mismatch")
            result = saved["result"]
            terminal = not rf.legal_moves(query["board"], query["side"]) and not rf.legal_moves(query["board"], rf.other(query["side"]))
            require(type(result.get("score")) is int and result.get("exact") is True
                    and type(result.get("completed_depth")) is int and result["completed_depth"] >= query["depth"]
                    and result["score"] == (decision["score"] if offset == 0 else -decision["score"]),
                    "teacher-policy-infeasible: root/selected-child exact disagreement")
            if terminal:
                require(result["score"] == training.terminal_score(query["board"], query["side"]),
                        "teacher-policy-infeasible: terminal score mismatch")
    return {"status": "feasible", "roots": 12, "oracle_queries": 24, "early_labels": 2,
            "side_counts": dict(sorted(Counter(root["side"] for root in roots).items())),
            "root_keys": [root["canonical_key"] for root in roots],
            "query_keys": [position_key(query["query"]["board"], query["query"]["side"]) for query in queries]}
