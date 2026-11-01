#!/usr/bin/env python3
"""Human entry point for long table32 tasks. No action runs implicitly.

Use prepare --help for frozen scale/resource parameters. run and resume use
the same manifest and completed prefix. Ctrl-C/SIGTERM preserves that prefix.
"""
from __future__ import annotations

import sys

import table32
import training


def main(argv):
    if argv and argv[0] == "resume":
        argv = ["run", *argv[1:]]
    return table32.main(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (training.TrainingError, ValueError, OSError, KeyError, TypeError) as error:
        print(f"table32 error: {error}", file=sys.stderr)
        raise SystemExit(2)
