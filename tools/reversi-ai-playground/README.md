# Reversi AI playground

Local development UI for live Reversi games. It is not part of the Godot game or release build.

## Start

Install Node.js 20.19+ or 22.12+, pnpm 10, and the Rust toolchain. From the repository root, install dependencies and start the playground with:

```sh
make playground-install
make playground
```

The direct package commands are also available:

```sh
cd tools/reversi-ai-playground
pnpm install
pnpm dev
```

The manifest and pnpm lockfile belong in `tools/reversi-ai-playground`. Its `node_modules/` and build output are local ignored artifacts. Root-level npm manifests, pnpm lockfiles, and `node_modules/` are not inputs or committed artifacts for this tool.

`pnpm dev` builds `reversi-ai-cli` in release mode, computes its SHA-256 digest, starts the backend on `127.0.0.1:8787`, and serves the UI at `http://127.0.0.1:5173`. Stop with Ctrl-C. No external oracle is required for human, random, strategic, or novice games.

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

Set `PLAYGROUND_CONFIG=/tmp/reversi-playground.json` before `pnpm dev`. Both optional entries are independent. A missing, unreadable, or non-executable optional input disables only that player. The oracle must be the external Egaroucid Console build with GTP support; its data and executable stay outside this checkout. Its local GTP profile uses one thread, no book, hash 16, and level 10. The server verifies SHA-256 digests of the CLI, artifact, oracle binary, and oracle data tree at startup and again before each game, then shows the pinned identities under “実行情報”. The browser sends only player IDs and settings, never paths or commands.

Each AI seat sets midgame depth 1–12 and exact solving start at 0–16 empty squares. The same depth is applied in all three game phases. Settings change at the next game. Random uses a 32-bit seed shown in the game snapshot; specifying it repeats the game. Reconnect within 30 seconds to resume the same game. After that, start a new game.

## Checks

```sh
pnpm test
pnpm lint
pnpm build
```

The server, UI protocol, and tests belong to this package. No code from the external visualizer was copied.
