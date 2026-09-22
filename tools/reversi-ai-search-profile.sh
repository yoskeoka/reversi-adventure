#!/usr/bin/env sh
set -eu

exec cargo +1.98.1 run --release -p reversi-ai --bin reversi-ai-search-profile -- "$@"
