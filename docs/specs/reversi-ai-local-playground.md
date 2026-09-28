# Local Reversi AI playground

This development-only tool is owned by `tools/reversi-ai-playground`; its only committed Node manifest and pnpm lockfile are `tools/reversi-ai-playground/package.json` and `tools/reversi-ai-playground/pnpm-lock.yaml`. From the repository root, `make playground-install` resolves dependencies and `make playground` starts the tool, with both commands running pnpm in that package directory. The package's `node_modules/` and build output are local ignored artifacts. Root-level npm manifests, pnpm lockfiles, and `node_modules/` are not inputs or output contracts for the tool.

The tool binds HTTP and WebSocket to `127.0.0.1`. Startup builds the project CLI in release mode and fixes its SHA-256 digest for the lifetime of the server. The browser sends only stable player IDs, game settings, moves, and a reconnect token. Local configuration, never a WebSocket request, names the trained artifact and external oracle binary/data.

## Session and rules

The server owns a standard 8×8 Reversi position, turn, legal moves, pass, stone counts, and result. Each seat independently selects `human`, `strategic`, `novice`, `trained-baseline`, `random`, or `oracle`. `random` samples uniformly from legal moves using an optional fixed unsigned seed. Project AI seats have their own midgame search depth (1–12) and exact-solver start empty squares (0–16); opening and endgame depths equal the selected midgame depth. Settings freeze at game creation. The UI calls the latter control “完全読み開始空き数”. Trained and oracle seats are disabled unless their server configuration exists and passes startup verification. The trained artifact and each executable identity are shown in snapshots and session metadata.

`start` replaces any existing session and terminates its children. A successful start returns a token and complete snapshot. A WebSocket reconnect using that token within 30 seconds resumes the same session and receives the current snapshot. Disconnect preserves the session and children for 30 seconds; expiry closes them and invalidates the token. A new connection without a token can start a new session. Only one connected socket controls a session at a time.

## Wire contract

The server sends `catalog` on connection and `snapshot` on start, reconnect, and every state change. A snapshot contains session ID, revision, 64-cell row-major board (`B`, `W`, `.`), turn, legal coordinates (`a1`–`h8`), black/white seats and frozen settings, counts, last move, last pass, thinking flag, result, error, and identity metadata. Revision increases only on accepted moves and passes. `start` takes the two seat definitions and optional random seed. `move` takes session ID, revision, and coordinate; the server rejects stale, illegal, malformed, or non-human requests without modifying board or revision and sends an error snapshot. AI requests use a unique position ID derived from session/revision; a response can change state only when its ID and position still match. Malformed, late, illegal, or invalid pass responses stop that seat's child and produce an error snapshot without advancing revision.

An opponent move is broadcast immediately. A forced pass is explicit in the last-pass field and advances revision. Terminal snapshots contain the winner or draw. AI thinking is visible while a bounded query runs. Process failure and timeout report their cause; replacing/expiring a session ends its children. Rejected human requests are recoverable; process and AI errors stop automatic play until a new game.

## Process boundary

### Advisor analysis producers

An explicit project-AI CLI analysis mode and an independent external Oracle
analysis command accept a position ID, the 64-character board and side `B` or
`W`. Each successful request emits exactly one newline-delimited JSON object:
`{schema_version:1, position_id, board, side, config_id, outcome,
completed_depth, exact, scores:[{move, value, completed_depth, exact}]}`.
`outcome` is `move`, `pass`, or `game_over`. Scores cover each legal coordinate
exactly once for `move`, and are empty otherwise. Values are finite and from
the current side's perspective. Nonterminal candidates share the root's
completed depth; immediately terminal candidates may carry their own proven
depth and `exact=true`. Root `exact` is true only when every candidate is exact.
No partial set is a successful response. Consumers validate the schema,
position, board, side, config identity, legal-move set, uniqueness, and depth
consistency before display; a stale response never changes the board.

Oracle advisor analysis uses the pinned external `-solve` child-position batch.
Its separately validated configuration specifies opening and midgame depths,
exact threshold, generated depth range, and fingerprint without changing the
named match/corpus profiles. The range uses moves 1–20 and 21–60; at an exact
threshold `E` from 1–16 it searches at least all `61-m` remaining empties from
move `m=61-E`, while `E=0` adds no exact range. The command fails unless every
legal candidate reaches the required depth. Advisor values are local to their
producer and search regime; the UI must not compare different scales.

Each project AI seat owns a persistent `reversi-ai-cli` process with fixed server-generated arguments and a bounded response deadline. The server verifies the CLI digest before games and validates the artifact digest before trained games. It hashes the configured oracle executable and data tree at startup and before games. The external oracle runs only from a server-configured executable and data directory outside the checkout, with GTP `genmove` and `play` synchronization. Oracle is absent from Rust/GDExtension/release dependencies. No browser value is a command, executable path, artifact path, or argument fragment.

The UI shows seat names and settings, legal destinations, last move, turn, score, thinking, pass, result, and errors. One screen supports human vs human, human vs AI, and AI vs AI. The server is authoritative; visualizer board styling may inspire the display, but its replay validation does not determine live game legality.
