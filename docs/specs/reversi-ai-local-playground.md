# Local Reversi AI playground

This development-only tool runs from `tools/reversi-ai-playground` with `pnpm install` and `pnpm dev`. It binds HTTP and WebSocket to `127.0.0.1`. Startup builds the project CLI in release mode and fixes its SHA-256 digest for the lifetime of the server. The browser sends only stable player IDs, game settings, moves, and a reconnect token. Local configuration, never a WebSocket request, names the trained artifact and external oracle binary/data.

## Session and rules

The server owns a standard 8×8 Reversi position, turn, legal moves, pass, stone counts, and result. Each seat independently selects `human`, `strategic`, `novice`, `trained-baseline`, `random`, or `oracle`. `random` samples uniformly from legal moves using an optional fixed unsigned seed. Project AI seats have their own midgame search depth (1–12) and exact-solver start empty squares (0–16); opening and endgame depths equal the selected midgame depth. Settings freeze at game creation. The UI calls the latter control “完全読み開始空き数”. Trained and oracle seats are disabled unless their server configuration exists and passes startup verification. The trained artifact and each executable identity are shown in snapshots and session metadata.

`start` replaces any existing session and terminates its children. A successful start returns a token and complete snapshot. A WebSocket reconnect using that token within 30 seconds resumes the same session and receives the current snapshot. Disconnect preserves the session and children for 30 seconds; expiry closes them and invalidates the token. A new connection without a token can start a new session. Only one connected socket controls a session at a time.

## Wire contract

The server sends `catalog` on connection and `snapshot` on start, reconnect, and every state change. A snapshot contains session ID, revision, 64-cell row-major board (`B`, `W`, `.`), turn, legal coordinates (`a1`–`h8`), black/white seats and frozen settings, counts, last move, last pass, thinking flag, result, error, and identity metadata. Revision increases only on accepted moves and passes. `start` takes the two seat definitions and optional random seed. `move` takes session ID, revision, and coordinate; the server rejects stale, illegal, malformed, or non-human requests without modifying board or revision and sends an error snapshot. AI requests use a unique position ID derived from session/revision; a response can change state only when its ID and position still match. Malformed, late, illegal, or invalid pass responses stop that seat's child and produce an error snapshot without advancing revision.

An opponent move is broadcast immediately. A forced pass is explicit in the last-pass field and advances revision. Terminal snapshots contain the winner or draw. AI thinking is visible while a bounded query runs. Process failure and timeout report their cause; replacing/expiring a session ends its children. Rejected human requests are recoverable; process and AI errors stop automatic play until a new game.

## Process boundary

Each project AI seat owns a persistent `reversi-ai-cli` process with fixed server-generated arguments and a bounded response deadline. The server verifies the CLI digest before games and validates the artifact digest before trained games. It hashes the configured oracle executable and data tree at startup and before games. The external oracle runs only from a server-configured executable and data directory outside the checkout, with GTP `genmove` and `play` synchronization. Oracle is absent from Rust/GDExtension/release dependencies. No browser value is a command, executable path, artifact path, or argument fragment.

The UI shows seat names and settings, legal destinations, last move, turn, score, thinking, pass, result, and errors. One screen supports human vs human, human vs AI, and AI vs AI. The server is authoritative; visualizer board styling may inspire the display, but its replay validation does not determine live game legality.
