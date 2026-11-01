"""Deterministic CPU arithmetic for the isolated 0054 table32 pilot.

Each call commits one complete full-batch step or integer-export proposal.  The
caller owns atomic persistence and resource supervision.  Missing parameters
are exactly zero; only a single phase's observed parameters are materialized.
The method follows pinned revision 67aa89f's equations, not CUDA execution or
its nondeterministic atomic reduction order.  All reductions here use row and
feature order.  There is no minibatch mean, warmup, best-weight restore, or
derivative suppression when a prediction has been clipped.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
import time

SCALE = 32
LIMIT = 4091
RAW_LIMIT = 64 * SCALE
MAX_STEPS = 1000
MAX_PROPOSALS = 1000


def state_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _rows(rows):
    result = []
    for row in rows:
        features = row["features"]
        target = row["target"]
        if (not isinstance(features, (list, tuple)) or not 1 <= len(features) <= 65
                or any(type(i) is not int or i < 0 for i in features)
                or type(target) not in (int, float) or not math.isfinite(target)
                or not -64 <= target <= 64):
            raise ValueError("invalid table32 optimizer row")
        result.append({"features": list(features), "target": target})
    return result


def _clip(value, limit=RAW_LIMIT):
    return max(-limit, min(limit, value))


def runtime_score(raw):
    """Round the summed raw32 value away from zero on a half, then clip."""
    if type(raw) is not int:
        raise ValueError("integer raw32 score required")
    return _clip((raw + 16) // 32 if raw >= 0 else -((-raw + 16) // 32), 64)


def loss(rows, weights, *, integer=False):
    """Return runtime-rounded integer or clipped continuous loss in disc units.

    The pinned source's adj_calculate_loss_round sums integer parameters, adds
    signed16, divides32 toward zero, clips64, then subtracts from score/32.
    Raw32 residuals are used by Adam, not by integer-export hill climbing.
    """
    squared = 0 if integer else 0.0
    absolute = 0 if integer else 0.0
    for row in rows:
        prediction = sum(weights.get(i, 0) for i in row["features"])
        prediction = runtime_score(prediction) if integer else _clip(prediction) / SCALE
        residual = row["target"] - prediction
        squared += residual * residual
        absolute += abs(residual)
    return {"count": len(rows), "squared_error": squared, "absolute_error": absolute,
            "mse": squared / len(rows) if rows else None,
            "mae": absolute / len(rows) if rows else None}


def initial_state(rows, validation_rows=(), *, phase, reverse_index=None, max_steps=MAX_STEPS):
    """Zero-initialize one phase.  A missing train phase is a hard stop."""
    rows, validation_rows = _rows(rows), _rows(validation_rows)
    if not rows:
        raise ValueError("training-phase-unavailable")
    if type(phase) is not int or not 0 <= phase < 60:
        raise ValueError("invalid phase")
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("max_steps must be a positive integer")
    if reverse_index is None:
        from table32_model import reverse_index
    counts = {}
    reverse = {}
    for row in rows:
        for index in row["features"]:
            other = reverse_index(index)
            if type(other) is not int or other < 0 or reverse_index(other) != index:
                raise ValueError("reversal must be a nonnegative involution")
            reverse[index], reverse[other] = other, index
            # Self-reversing indices deliberately receive both contributions.
            counts[index] = counts.get(index, 0) + 1
            counts[other] = counts.get(other, 0) + 1
    indices = sorted(counts)
    return {"schema": "table32-adam-state-v1", "phase": phase, "step": 0,
            "max_steps": max_steps, "alpha": 300.0, "best_validation_mse": None,
            "worse_count": 0, "lr_worse_count": 0, "complete": False,
            "stop_reason": None, "validation_status": "available" if validation_rows else "validation-unavailable",
            "train_sha256": state_digest(rows), "validation_sha256": state_digest(validation_rows),
            "indices": indices, "reverse": [reverse[i] for i in indices],
            "weights": [0.0] * len(indices), "m": [0.0] * len(indices),
            "v": [0.0] * len(indices), "counts": [counts[i] for i in indices],
            "capped_counts": [min(50, counts[i]) for i in indices],
            "train_loss": loss(rows, {}), "validation_loss": loss(validation_rows, {}),
            "predecessor_sha256": None}


def _check_training(state, rows, validation_rows):
    if (state.get("schema") != "table32-adam-state-v1"
            or state.get("train_sha256") != state_digest(rows)
            or state.get("validation_sha256") != state_digest(validation_rows)):
        raise ValueError("optimizer state/input identity mismatch")
    indices = state["indices"]
    if indices != sorted(set(indices)):
        raise ValueError("invalid optimizer parameter order")
    size = len(indices)
    if any(len(state[k]) != size for k in ("reverse", "weights", "m", "v", "counts", "capped_counts")):
        raise ValueError("invalid optimizer state shape")
    if (type(state["max_steps"]) is not int or state["max_steps"] < 1
            or not 0 <= state["step"] <= state["max_steps"]
            or not math.isfinite(state["alpha"]) or not 0 < state["alpha"] <= 300):
        raise ValueError("invalid optimizer step/alpha")
    positions = {index: n for n, index in enumerate(indices)}
    expected_counts = {index: 0 for index in indices}
    for row in rows:
        for index in row["features"]:
            if index not in positions:
                raise ValueError("missing observed parameter")
            other = state["reverse"][positions[index]]
            if other not in positions:
                raise ValueError("missing reversed parameter")
            expected_counts[index] += 1
            expected_counts[other] += 1
    for n, index in enumerate(indices):
        other = state["reverse"][n]
        if (other not in positions or state["reverse"][positions[other]] != index
                or state["counts"][n] != expected_counts[index]
                or state["capped_counts"][n] != min(50, expected_counts[index])
                or expected_counts[index] <= 0):
            raise ValueError("invalid reversal/count state")
        if (any(not math.isfinite(state[k][n]) for k in ("weights", "m", "v"))
                or abs(state["weights"][n]) > LIMIT or state["v"][n] < 0):
            raise ValueError("nonfinite/out-of-range optimizer state")
        if any(state[k][n] != state[k][positions[other]] for k in ("weights", "m", "v")):
            raise ValueError("optimizer reversal sharing mismatch")
    return positions


def train_step(state, rows, validation_rows=()):
    """Complete one validation check and at most one full-batch Adam step."""
    rows, validation_rows = _rows(rows), _rows(validation_rows)
    positions = _check_training(state, rows, validation_rows)
    if state["complete"]:
        return copy.deepcopy(state)
    result = copy.deepcopy(state)
    result["predecessor_sha256"] = state_digest(state)
    weights = dict(zip(state["indices"], state["weights"]))
    result["train_loss"] = loss(rows, weights)
    result["validation_loss"] = loss(validation_rows, weights)
    if validation_rows:
        mse = result["validation_loss"]["mse"]
        if state["best_validation_mse"] is None or mse <= state["best_validation_mse"]:
            result["best_validation_mse"] = mse
            result["worse_count"] = result["lr_worse_count"] = 0
        else:
            result["worse_count"] += 1
            result["lr_worse_count"] += 1
            if result["worse_count"] > 100:
                result["complete"], result["stop_reason"] = True, "validation-patience"
                return result
    residuals = [0.0] * len(positions)
    for row in rows:
        prediction = _clip(sum(weights.get(index, 0.0) for index in row["features"]))
        residual = row["target"] * SCALE - prediction
        for index in row["features"]:
            position = positions[index]
            residuals[position] += residual
            residuals[positions[state["reverse"][position]]] += residual
    step = state["step"] + 1
    correction = math.sqrt(1.0 - 0.999 ** step) / (1.0 - 0.9 ** step)
    for n, residual in enumerate(residuals):
        gradient = 2.0 * residual
        m = state["m"][n] + (1.0 - 0.9) * (gradient - state["m"][n])
        v = state["v"][n] + (1.0 - 0.999) * (gradient * gradient - state["v"][n])
        weight = state["weights"][n] + (state["alpha"] / state["capped_counts"][n]) * correction * m / (math.sqrt(v) + 1e-7)
        if not all(map(math.isfinite, (weight, m, v))):
            raise ValueError("nonfinite Adam transition")
        result["weights"][n], result["m"][n], result["v"][n] = _clip(weight, LIMIT), m, v
    result["step"] = step
    if result["lr_worse_count"] >= 10:
        result["alpha"] *= 0.7
        result["lr_worse_count"] = 0
    if step >= result["max_steps"]:
        result["complete"], result["stop_reason"] = True, "step-limit"
    return result


def train_phase(rows, validation_rows=(), *, phase, state=None, on_checkpoint=None,
                reverse_index=None, max_steps=MAX_STEPS):
    rows, validation_rows = _rows(rows), _rows(validation_rows)
    if state is None:
        state = initial_state(rows, validation_rows, phase=phase,
                              reverse_index=reverse_index, max_steps=max_steps)
    if state["phase"] != phase or state["max_steps"] != max_steps:
        raise ValueError("changed phase/step settings require a new root")
    while not state["complete"]:
        state = train_step(state, rows, validation_rows)
        if on_checkpoint:
            on_checkpoint(state)
    return state


def _float32(value):
    return struct.unpack("!f", struct.pack("!f", value))[0]


def round_candidates(value):
    """CUDA ceilf/floorf take f32, but initial round() takes the f64 weight."""
    if not math.isfinite(value) or not -LIMIT <= value <= LIMIT:
        raise ValueError("invalid floating export parameter")
    narrowed = _float32(value)
    lower, upper = math.floor(narrowed), math.ceil(narrowed)
    nearest = math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)
    return lower, upper, nearest == lower


def initial_export(training, rows, *, seed, parameter_count=None, max_proposals=MAX_PROPOSALS):
    rows = _rows(rows)
    if not training["complete"]:
        raise ValueError("cannot export unfinished Adam phase")
    if training["train_sha256"] != state_digest(rows):
        raise ValueError("export train identity mismatch")
    if type(seed) is not int or seed < 0:
        raise ValueError("invalid export seed")
    if parameter_count is None:
        from table32_model import PARAMETER_COUNT
        parameter_count = PARAMETER_COUNT
    if (type(parameter_count) is not int or parameter_count <= 0
            or max(training["indices"]) >= parameter_count
            or type(max_proposals) is not int or max_proposals < 1):
        raise ValueError("invalid export bounds")
    candidates = [round_candidates(w) for w in training["weights"]]
    result = {"schema": "table32-export-state-v1", "phase": training["phase"],
              "training_sha256": state_digest(training), "train_sha256": state_digest(rows),
              "indices": training["indices"][:], "reverse": training["reverse"][:],
              "lower": [c[0] for c in candidates], "upper": [c[1] for c in candidates],
              "round_down": [c[2] for c in candidates], "parameter_count": parameter_count,
              "rng": {"algorithm": "sha256-rejection-v1", "seed": seed, "cursor": 0},
              "tries": 0, "updates": 0, "improvements": 0, "max_proposals": max_proposals,
              "complete": False, "stop_reason": None, "last_proposal": None,
              "last_accepted": False, "predecessor_sha256": None}
    result["loss"] = loss(rows, exported_weights(result, require_complete=False), integer=True)
    return result


def exported_weights(state, *, require_complete=True):
    if require_complete and not state["complete"]:
        raise ValueError("integer export is unfinished")
    return {index: state["lower"][n] if state["round_down"][n] else state["upper"][n]
            for n, index in enumerate(state["indices"])
            if (state["lower"][n] if state["round_down"][n] else state["upper"][n]) != 0}


def _draw_parameter(rng, parameter_count):
    # Rejection rather than modulo bias; the full table, including all-zero
    # parameters, is sampled.  Every draw counts as a bounded proposal.
    limit = (1 << 256) - (1 << 256) % parameter_count
    attempt = 0
    while True:
        token = f"table32-export-v1:{rng['seed']}:{rng['cursor']}:{attempt}"
        number = int.from_bytes(hashlib.sha256(token.encode()).digest(), "big")
        if number < limit:
            return number % parameter_count
        attempt += 1


def export_step(state, rows):
    rows = _rows(rows)
    if state.get("schema") != "table32-export-state-v1" or state["train_sha256"] != state_digest(rows):
        raise ValueError("export state/input identity mismatch")
    if state["rng"]["cursor"] != state["tries"] or state["rng"]["algorithm"] != "sha256-rejection-v1":
        raise ValueError("export cursor mismatch")
    if state["complete"]:
        return copy.deepcopy(state)
    current_weights = exported_weights(state, require_complete=False)
    current_loss = loss(rows, current_weights, integer=True)
    if current_loss != state["loss"]:
        raise ValueError("export loss/state mismatch")
    result = copy.deepcopy(state)
    result["predecessor_sha256"] = state_digest(state)
    index = _draw_parameter(state["rng"], state["parameter_count"])
    result["last_proposal"], result["last_accepted"] = index, False
    positions = {i: n for n, i in enumerate(state["indices"])}
    if index in positions:
        position = positions[index]
        if state["lower"][position] != state["upper"][position]:
            other = state["reverse"][position]
            for changed in set((index, other)):
                n = positions[changed]
                result["round_down"][n] = not result["round_down"][n]
            candidate = loss(rows, exported_weights(result, require_complete=False), integer=True)
            if candidate["squared_error"] <= current_loss["squared_error"]:
                # Source round_n_updated includes ties; round_n_improve does
                # not. Only strict improvements feed the stopping ratio.
                result["updates"] += 1
                result["improvements"] += candidate["squared_error"] < current_loss["squared_error"]
                result["loss"], result["last_accepted"] = candidate, True
            else:
                result["round_down"] = state["round_down"][:]
    result["tries"] += 1
    result["rng"]["cursor"] += 1
    if result["tries"] >= result["max_proposals"]:
        result["complete"], result["stop_reason"] = True, "proposal-limit"
    elif result["tries"] >= 100 and result["improvements"] * 10000 <= result["tries"]:
        result["complete"], result["stop_reason"] = True, "improvement-rate"
    return result


def run_export(state, rows, *, on_checkpoint=None, wall_seconds=60):
    if not 0 < wall_seconds <= 60:
        raise ValueError("export wall slice must be in (0,60]")
    started = time.monotonic()
    while not state["complete"] and time.monotonic() - started < wall_seconds:
        state = export_step(state, rows)
        if on_checkpoint:
            on_checkpoint(state)
    # Wall exhaustion returns only the last completed atomic proposal.  The
    # caller persists it as incomplete; no candidate may be adopted from it.
    return state


def verify_training(state, rows, validation_rows=(), *, reverse_index=None):
    """Rebuild a saved transition prefix without invoking any process."""
    expected = initial_state(rows, validation_rows, phase=state["phase"],
                             reverse_index=reverse_index, max_steps=state["max_steps"])
    while expected["step"] < state["step"]:
        previous = expected["step"]
        expected = train_step(expected, rows, validation_rows)
        if expected["step"] == previous:
            raise ValueError("saved training prefix extends beyond valid stop")
    if state["complete"] and not expected["complete"]:
        expected = train_step(expected, rows, validation_rows)
    if expected != state:
        raise ValueError("Adam arithmetic replay mismatch")
    return state_digest(expected)


def verify_export(state, training, rows):
    expected = initial_export(training, rows, seed=state["rng"]["seed"],
                              parameter_count=state["parameter_count"], max_proposals=state["max_proposals"])
    for _ in range(state["tries"]):
        if expected["complete"]:
            raise ValueError("export prefix extends beyond valid stop")
        expected = export_step(expected, rows)
    if expected != state:
        raise ValueError("integer export arithmetic replay mismatch")
    return state_digest(expected)
