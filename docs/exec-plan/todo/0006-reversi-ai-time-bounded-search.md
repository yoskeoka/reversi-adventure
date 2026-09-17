# Add time-bounded interruptible Reversi search

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Provide the shared search contract needed by the Godot game and a future
ai-arena adapter: callers give a turn-time budget or deadline, and search can
always return a legal fallback immediately plus the best result from the last
fully completed iterative-deepening iteration when interrupted. Node caps are
secondary deterministic limits for tests, CI, and tuning runs.

## Existing references

- `rust/reversi-ai/src/search/negascout.rs:39-77` iterates fixed depths but
  lacks cancellation and preserves no completed-search metadata.
- `rust/reversi-ai/src/search/mod.rs:37-62` converts only fixed phase depths
  into `SearchResult`.
- `rust/reversi-ai/src/config.rs:9-31` provides depth-only configuration.
- `rust/reversi-godot/src/bridge.rs:164-206` synchronously calls `AiPlayer`.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- define time/deadline and optional node
  budgets, legal fallback, completed-depth/nodes/elapsed metadata, and
  interruption semantics.
- (MODIFY) `config.rs`, `search/mod.rs`, `search/negascout.rs`, `player.rs`,
  and GDExtension bridge -- accept budgets, poll cancellation, retain only
  wholly completed iterations, and expose project-owned metadata.
- (MODIFY) tests -- deterministic node-limit and cancellation fixtures.
- (DELETE) this plan after implementation verification and PR preparation.

## Execution steps

1. Create a monotonic-deadline primary budget with an optional node ceiling.
2. Select a legal root fallback before deeper work. After every completed
   depth, atomically replace the stable result with its move, PV, and score.
3. Poll deadline/cancellation cooperatively during expansion; never publish a
   partial iteration as the completed PV.
4. Preserve node-budget determinism for corpus/GA runs while game integrations
   use a turn-time budget. UI scheduling and ai-arena porting remain separate.

## Verification

- `cargo test -p reversi-ai` and `cargo build -p reversi-godot`
- Deadline/node interruption returns a legal move and last completed result.
- Fixed-node runs reproduce depth, PV, and result metadata.

## Addresses

N/A
