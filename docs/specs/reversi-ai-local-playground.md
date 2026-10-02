# Local Reversi AI playground

## Purpose and ownership

The playground is the low-cost Web feedback surface for the main game's pure Reversi experience. Its scope includes AI-versus-AI matches and analysis, human play against computer opponents, and local problems such as Reversi puzzles. Reversi interactions and their UX are refined here before being brought into Godot; the playground is not a separate game design or a release target.

Project AI search, analysis, and the meaning of their settings are reusable across the playground and the main game. Both frontends call AI with an explicit position, side to move, and configuration, then consume a validated result under the same contract. A new AI capability must live in the shared Rust AI rather than in playground-only AI behavior. Godot adopts new ways of using that AI when the corresponding main-game experience is developed; its current defaults need not change with a playground iteration.

The Web and Godot frontends each own their Reversi game flow and position controls, including human moves, legal destinations, passes, and results. They must follow the same Reversi rules, but they may implement those controls separately. Confirm each new human-facing Reversi interaction in the Web UI, then carry the validated UX into Godot during main-game development.

This development-only tool is owned by `tools/reversi-ai-playground`; its only committed Node manifest and pnpm lockfile are `tools/reversi-ai-playground/package.json` and `tools/reversi-ai-playground/pnpm-lock.yaml`. From the repository root, `make playground-install` installs package dependencies, prepares the pinned external Oracle, generates a demo trained artifact from the checked-in tiny fixture, and saves verified absolute paths in a configuration file outside the checkout. It fails if Oracle setup or verification fails. `make start-playground` launches the local server with that prepared configuration and reports a missing install; `make playground` is a compatible alias. `PLAYGROUND_CONFIG` can supply optional per-item overrides for a real trained artifact or Oracle paths, and an invalid parsed override disables only its player. An unreadable or malformed override file is reported and leaves the prepared players available. The demo artifact remains explicitly labelled as untrained for strength claims. Both commands run pnpm in the package directory. The package's `node_modules/` and build output are local ignored artifacts. Root-level npm manifests, pnpm lockfiles, and `node_modules/` are not inputs or output contracts for the tool.

The tool binds HTTP and WebSocket to `127.0.0.1`. Startup builds the project CLI in release mode and fixes its SHA-256 digest for the lifetime of the server. The browser sends only stable player IDs, game settings, moves, and a reconnect token. Local configuration, never a WebSocket request, names the trained artifact and external oracle binary/data.

## Session and rules

The server owns a standard 8×8 Reversi position, turn, legal moves, pass, stone counts, and result. Each seat independently selects `human`, `strategic`, `novice`, `trained-baseline`, `random`, or `oracle`. `random` samples uniformly from legal moves using an optional fixed unsigned seed. Each searching player configures opening depth for decision moves 1–20, midgame depth for moves 21–60, and exact-solver start empty squares (0–30); the next decision number is the board's occupied count minus three, including after passes. Opening depth accepts integers 1–12 and midgame depth accepts integers 1–16 for both players and Advisors. A legacy single `depth` setting accepts 1–12 and maps to equal opening and midgame depths. Out-of-range settings are rejected without rounding. Catalog limits are `openingDepth: [1,12]`, `midgameDepth: [1,16]`, and `exact: [0,30]`. Defaults and phase boundaries stay unchanged. These limits permit configuration; depth 16 or 30-empty exact search completion, speed, and strength are not guaranteed. Existing search budgets and process timeouts still apply, and interrupted searches are never reported as completed exact solves. This decision-move phase policy is a reusable AI configuration for match play and analysis, including future main-game integration; the Playground UI does not offer endgame depth. Existing main-game defaults remain as specified in the AI contract until that integration is selected. Oracle uses the same move-number phases and begins full depth at move `61-E` for exact threshold `E>0`; `E=0` never switches to exact. Human seats independently select no Advisor or an available Strategic, Novice, Trained, or Oracle Advisor with their own opening depth, midgame depth, and exact threshold. Random has no search controls and cannot advise. All seat and Advisor settings freeze at game creation. The UI calls the exact control “完全読み開始空き数”. Trained and oracle choices are disabled unless their server configuration exists and passes startup verification. The trained artifact and each executable identity are shown in snapshots and session metadata.

`start` replaces any existing session and terminates its children. A successful start returns a token and complete snapshot. A WebSocket reconnect using that token within 30 seconds resumes the same session and receives the current snapshot. Disconnect preserves the session and children for 30 seconds; expiry closes them and invalidates the token. A new connection without a token can start a new session. Only one connected socket controls a session at a time.

## Wire contract

The server sends `catalog` on connection and `snapshot` on start, reconnect, and every state change. A snapshot contains session ID, revision, 64-cell row-major board (`B`, `W`, `.`), turn, legal coordinates (`a1`–`h8`), black/white seats and frozen settings, counts, last move, last pass, thinking flag, result, error, identity metadata, Advisor pending/result/error state, and `thinkingTimeMs: { B: number, W: number }`. Revision increases only on accepted moves and passes. `start` takes the two seat definitions and optional random seed. `move` takes session ID, revision, and coordinate; the server rejects stale, illegal, malformed, or non-human requests without modifying board or revision and sends an error snapshot. AI requests use a unique position ID derived from session/revision; a response can change state only when its ID and position still match. Malformed, late, illegal, or invalid pass responses stop that seat's child and produce an error snapshot without advancing revision.

Thinking times are finite nonnegative milliseconds, initialized to zero per new game. The server uses a monotonic clock immediately before each AI move query until it completes, accumulating once for the requested color, including communication and response waiting and failed or timed-out queries. Random uses the same boundary. Process startup, Oracle synchronization of an opponent move, Human waiting, Advisor analysis, rendering, and forced passes without a query are excluded. The next snapshot publishes completed-query totals; live updates during thinking are optional. Totals survive game over, errors, and reconnect, and reset on a new game. A closed old session cannot change a new session through delayed completion. The UI displays black and white 総思考時間 in seconds with one decimal digit (for example `12.3 秒`), including zero for Human and both totals after game over.

At the start of each Human turn with an Advisor, the server automatically requests all legal-move scores from a separate analysis process; this never plays a move. Each project Advisor owns a dedicated persistent CLI child with frozen configuration. Its configuration identity is obtained without blocking Human moves or other sessions. Oracle analysis uses an external adapter independent of match GTP processes and rechecks the executable digest before adapter launch. A Human can move while analysis runs. A move, pass, replacement, or expiry cancels pending work, including adapter subprocesses, and clears its result; stale completions cannot change the new position. The server accepts a completed result only for the same session, revision, board, side, configuration, and exact legal-move set. A reconnect receives current pending or completed Advisor state. Failure clears pending, reports an Advisor error, and leaves the game playable.

Until all scores arrive, legal destinations remain `●` and “Advisor 思考中…” appears beside the current Human name. The UI replaces all legal `●` together with the selected Advisor's signed, rounded scores. Finite values round to the nearest integer with half values away from zero; rounded zero, including negative zero, displays as `+0`. No partial result appears. Scores from different Advisors or heuristic and exact analysis have no shared scale.

The 8×8 board keeps a square outline and equal cell dimensions at a given viewport size. Its width and height do not change as turns advance or legal destinations switch between dots, Advisor scores, pieces, and empty cells. The board may resize when the viewport changes.

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
threshold `E` from 1–30 it searches at least all `61-m` remaining empties from
move `m=61-E`, while `E=0` adds no exact range. The command fails unless every
legal candidate reaches the required depth. Advisor values are local to their
producer and search regime; the UI must not compare different scales.

Each project AI seat owns a persistent `reversi-ai-cli` process with fixed server-generated arguments and a bounded response deadline. The server verifies the CLI digest before games and validates the artifact digest before trained games. It hashes the configured oracle executable and data tree at startup and before games. The external oracle runs only from a server-configured executable and data directory outside the checkout, with GTP `genmove` and `play` synchronization. Oracle is absent from Rust/GDExtension/release dependencies. No browser value is a command, executable path, artifact path, or argument fragment.

The UI shows seat names and settings, legal destinations, last move, turn, score, thinking, pass, result, and errors. One screen supports human vs human, human vs AI, and AI vs AI. The server is authoritative; visualizer board styling may inspire the display, but its replay validation does not determine live game legality.
