#!/usr/bin/env python3
"""Fixture candidate: return the first legal move for each protocol request."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reinforcement

for line in sys.stdin:
    identifier, board, side = line.rstrip("\n").split("\t")
    legal = reinforcement.legal_moves(board, side)
    print(f"{identifier}\t{legal[0] if legal else 'pass'}", flush=True)
