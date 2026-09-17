#!/usr/bin/env python3
import sys


def main() -> int:
    if "--candidate" in sys.argv:
        for line in sys.stdin:
            position_id, _, _ = line.rstrip("\n").split("\t")
            print(f"{position_id}\td3", flush=True)
        return 0

    if "--partial-candidate" in sys.argv:
        sys.stdin.readline()
        sys.stdout.write("partial")
        sys.stdout.flush()
        sys.stdin.readline()
        return 0

    problem = sys.argv[sys.argv.index("-solve") + 1]
    print("| Level | Depth | Move | Score | Time | Nodes | NPS |")
    with open(problem, encoding="ascii") as stream:
        for _ in stream:
            print("| 8 | 8@100% | a1 | +1 | 000:00:00.001 | 10 | 10000 |")
    print("total 10 nodes in 0.001s NPS 10000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
