#!/usr/bin/env python3
"""Versioned test-only CLI that emits the move telemetry required by 0019."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reinforcement

threshold = int(sys.argv[sys.argv.index("--exact-solver-empty-squares") + 1])
for line in sys.stdin:
    if line.startswith("new_game\t"):
        _, identifier = line.rstrip("\n").split("\t")
        print(f"new_game\t{identifier}\tready", flush=True)
        continue
    identifier, board, side = line.rstrip("\n").split("\t")
    legal = reinforcement.legal_moves(board, side)
    move = legal[0] if legal else "pass"
    empty = board.count(".")
    exact = bool(legal) and empty <= threshold
    depth = empty if exact else (12 if legal else 0)
    outcome = "move" if legal else "pass"
    print("search_diagnostic_v1"
          f"\tposition_id={identifier}\telapsed_us=1\tnodes=1\texact={str(exact).lower()}"
          f"\tscore=0\tcompleted_depth={depth}\toutcome={outcome}",
          file=sys.stderr, flush=True)
    print(f"{identifier}\t{move}", flush=True)
