"""Independent, bounded score-contract investigation; never invokes the Oracle.

Move generation uses masked directional bit shifts, independently of the CLI and
the coordinate-array Oracle adapter. Historical receipt validators stay intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path

FULL = (1 << 64) - 1
LEFT = 0xFEFEFEFEFEFEFEFE
RIGHT = 0x7F7F7F7F7F7F7F7F
CONTRACTS = ("project", "oracle")


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def bits(board, side):
    return tuple(sum(1 << i for i, cell in enumerate(board) if cell == color)
                 for color in (side, "W" if side == "B" else "B"))


def shift(value, direction):
    delta, mask = direction
    return ((value << delta) & FULL if delta > 0 else value >> -delta) & mask


DIRECTIONS = ((1, LEFT), (-1, RIGHT), (8, FULL), (-8, FULL),
              (9, LEFT), (7, RIGHT), (-7, LEFT), (-9, RIGHT))


def legal(own, opponent):
    result = 0
    empty = FULL ^ (own | opponent)
    for direction in DIRECTIONS:
        ray = shift(own, direction) & opponent
        for _ in range(5):
            ray |= shift(ray, direction) & opponent
        result |= shift(ray, direction) & empty
    return result


def play(own, opponent, move):
    flips = 0
    for direction in DIRECTIONS:
        ray, captured = shift(move, direction), 0
        while ray & opponent:
            captured |= ray
            ray = shift(ray, direction)
        if ray & own:
            flips |= captured
    if not flips or move & (own | opponent) or move.bit_count() != 1:
        raise ValueError("illegal move")
    return own | move | flips, opponent ^ flips


def terminal_score(own, opponent, contract):
    a, b = own.bit_count(), opponent.bit_count()
    difference = a - b
    if contract == "project":
        return 64 if b == 0 and a else -64 if a == 0 and b else difference
    if contract == "oracle":
        return difference + (64 - a - b) * ((difference > 0) - (difference < 0))
    raise ValueError("unknown score contract")


def move_name(move):
    index = move.bit_length() - 1
    return chr(97 + index % 8) + str(1 + index // 8)


def replay(board, side, pv):
    own, opponent = bits(board, side)
    for name in pv:
        moves = legal(own, opponent)
        if name == "pass":
            if moves or not legal(opponent, own):
                raise ValueError("illegal pass")
        else:
            move = 1 << ((int(name[1]) - 1) * 8 + ord(name[0]) - 97)
            if not move & moves:
                raise ValueError("illegal PV")
            own, opponent = play(own, opponent, move)
        own, opponent = opponent, own
        side = "W" if side == "B" else "B"
    if legal(own, opponent) or legal(opponent, own):
        raise ValueError("PV does not reach terminal")
    black, white = (own, opponent) if side == "B" else (opponent, own)
    return "".join("B" if black & (1 << i) else "W" if white & (1 << i) else "."
                   for i in range(64))


def solve(board, side, contract, seconds=30):
    """One alpha-beta solve, without production move generation, scoring or TT."""
    started = time.monotonic()
    deadline = started + seconds
    nodes = 0

    def visit(own, opponent, alpha, beta):
        nonlocal nodes
        nodes += 1
        if nodes % 256 == 0 and time.monotonic() >= deadline:
            raise TimeoutError("30 second investigation limit")
        moves = legal(own, opponent)
        if not moves:
            if not legal(opponent, own):
                return terminal_score(own, opponent, contract), []
            score, pv = visit(opponent, own, -beta, -alpha)
            return -score, ["pass"] + pv
        best, best_pv = -65, []
        ordered = []
        while moves:
            move = moves & -moves
            moves ^= move
            child_own, child_opponent = play(own, opponent, move)
            ordered.append((legal(child_opponent, child_own).bit_count(), move,
                            child_own, child_opponent))
        for _, move, child_own, child_opponent in sorted(ordered):
            score, pv = visit(child_opponent, child_own, -beta, -alpha)
            score = -score
            if score > best:
                best, best_pv = score, [move_name(move)] + pv
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        return best, best_pv

    result = {"board": board, "side": side, "contract": contract,
              "wall_limit_seconds": seconds, "rss_limit_kib": 1572864}
    try:
        score, pv = visit(*bits(board, side), -65, 65)
        leaf = replay(board, side, pv)
        scores = {name: terminal_score(*bits(leaf, side), name) for name in CONTRACTS}
        if scores[contract] != score:
            raise ValueError("PV terminal score differs from solved root")
        result.update(status="completed", score=score, pv=pv, terminal_board=leaf,
                      terminal_counts={cell: leaf.count(cell) for cell in "BW."},
                      terminal_scores_for_root_side=scores)
    except TimeoutError as error:
        result.update(status="incomplete", score=None, pv=None, failure=str(error))
    result.update(nodes=nodes, elapsed_seconds=time.monotonic() - started,
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True)
    parser.add_argument("--side", required=True, choices=("B", "W"))
    parser.add_argument("--contract", required=True, choices=CONTRACTS)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if len(args.board) != 64 or set(args.board) - set("BW.") or args.output.exists():
        parser.error("invalid board or output already exists")
    # RSS cannot exceed virtual address space; enforce a stricter address-space
    # cap and record Linux ru_maxrss. Each invocation is one bounded solve.
    cap = 1572864 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    result = solve(args.board, args.side, args.contract)
    result["reference_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result["report_digest"] = hashlib.sha256(canonical(result)).hexdigest()
    args.output.write_bytes(canonical(result))


if __name__ == "__main__":
    main()
