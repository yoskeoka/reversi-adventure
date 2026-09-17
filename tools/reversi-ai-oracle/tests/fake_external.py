#!/usr/bin/env python3
import sys


def main() -> int:
    if "--candidate" in sys.argv:
        candidate_moves = ["d3"]
        for index, line in enumerate(sys.stdin):
            position_id, _, _ = line.rstrip("\n").split("\t")
            print(f"{position_id}\t{candidate_moves[index]}", flush=True)
        return 0

    if "--partial-candidate" in sys.argv:
        sys.stdin.readline()
        sys.stdout.write("partial")
        sys.stdout.flush()
        sys.stdin.readline()
        return 0

    problem = sys.argv[sys.argv.index("-solve") + 1]
    print("| Level | Depth | Move | Score | Time | Nodes | NPS |")
    solve_moves = ["c3", "c3", "d6", "d6"]
    with open(problem, encoding="ascii") as stream:
        for index, _ in enumerate(stream):
            print(
                f"| 8 | 8@100% | {solve_moves[index]} | +1 | "
                "000:00:00.001 | 10 | 10000 |"
            )
    print("total 10 nodes in 0.001s NPS 10000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
