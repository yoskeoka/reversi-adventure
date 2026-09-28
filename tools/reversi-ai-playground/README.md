# Reversi AI playground

Local development UI for live Reversi games and a proving ground for match controls shared with the main game. The tool itself is not packaged in the Godot release build.

## Start

On Linux or WSL2, install Node.js 20.19+ or 22.12+, pnpm 10, Python 3, the Rust toolchain, CMake, and a C++ compiler. From the repository root, install dependencies and start the playground with:

```sh
make playground-install
make start-playground
```

`make playground` remains an alias for `make start-playground`. Install resolves pnpm dependencies in this package, downloads/builds and verifies the pinned external Egaroucid Oracle, and generates a TrainedEvaluator demo artifact from the checked-in tiny fixture. It saves the verified paths in `~/.cache/reversi-adventure/playground/prepared.json` (or under `XDG_CACHE_HOME`, if set). Oracle setup failures fail the install. The demo artifact is for trying the UI; its playing strength is unverified. Run install again to refresh the prepared paths and demo artifact. `REVERSI_ADVENTURE_PLAYGROUND_SETUP_DIR` selects a different absolute setup directory outside the checkout for both commands.

The direct package commands are available after install:

```sh
pnpm --dir tools/reversi-ai-playground test
pnpm --dir tools/reversi-ai-playground lint
pnpm --dir tools/reversi-ai-playground build
```

The manifest and pnpm lockfile belong in `tools/reversi-ai-playground`. Its `node_modules/` and build output are local ignored artifacts. Root-level npm manifests, pnpm lockfiles, and `node_modules/` are not inputs or committed artifacts for this tool.

`make start-playground` requires the install and builds `reversi-ai-cli` in release mode, computes its SHA-256 digest, starts the backend on `127.0.0.1:8787`, and serves the UI at `http://127.0.0.1:5173`. Stop with Ctrl-C.
`PLAYGROUND_PORT` and `PLAYGROUND_WEB_PORT` can select different local backend and UI ports when those defaults are occupied.

## Optional local players

Put a JSON file outside the checkout, for example `/tmp/reversi-playground.json`:

```json
{
  "trained": { "artifact": "/absolute/path/to/baseline-artifact.json" },
  "oracle": {
    "binary": "/absolute/path/to/egaroucid-console",
    "dataDir": "/absolute/path/to/egaroucid-data"
  }
}
```

Set `PLAYGROUND_CONFIG=/tmp/reversi-playground.json` before `make start-playground` to override either prepared entry. An override for one player leaves the other prepared entry in place. A missing, unreadable, or non-executable player path disables that player. An unreadable or malformed override file is reported and the prepared entries remain available. The oracle must be the external Egaroucid Console build with GTP support; its data and executable stay outside this checkout. The server verifies SHA-256 digests of the CLI, artifact, oracle binary, and oracle data tree at startup and again before each game, then shows the pinned identities under “実行情報”. The browser sends only player IDs and settings, never paths or commands.

Each searching seat sets opening depth for decision moves 1–20, midgame depth for moves 21–60, and exact solving start at 0–16 empty squares. Human seats can select an independent Advisor. Settings change at the next game. Random uses a 32-bit seed shown in the game snapshot; specifying it repeats the game. Reconnect within 30 seconds to resume the same game. After that, start a new game.

## Checks

```sh
pnpm --dir tools/reversi-ai-playground test
pnpm --dir tools/reversi-ai-playground lint
pnpm --dir tools/reversi-ai-playground build
```

The server, UI protocol, and tests belong to this package. No code from the external visualizer was copied.
