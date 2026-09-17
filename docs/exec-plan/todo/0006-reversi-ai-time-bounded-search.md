# Add time-bounded interruptible Reversi search

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Provide the shared search contract needed by the Godot game and a future
ai-arena adapter. Callers give a turn-time deadline and optional cancellation
token. With a legal move, search returns a legal fallback immediately and then
the best result from the last fully completed iterative-deepening iteration.
Node caps are secondary deterministic limits for tests, CI, and tuning runs.

## Existing references

- `rust/reversi-ai/src/search/negascout.rs:39-77` iterates fixed depths but
  lacks cancellation and preserves no completed-search metadata.
- `rust/reversi-ai/src/search/mod.rs:37-62` converts only fixed phase depths
  into `SearchResult`.
- `rust/reversi-ai/src/config.rs:9-31` provides depth-only configuration.
- `rust/reversi-godot/src/bridge.rs:164-206` synchronously calls `AiPlayer`.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- define deadline, optional node budget,
  caller-owned thread-safe cancellation token, `Move`/`Pass`/`GameOver`
  outcome, legal fallback, completed-depth/nodes/elapsed metadata, and
  interruption semantics.
- (MODIFY) `config.rs`, `search/mod.rs`, `search/negascout.rs`, `player.rs`,
  and GDExtension bridge -- accept budgets, poll cancellation, retain only
  wholly completed iterations, and expose project-owned metadata.
- (MODIFY) tests -- deterministic node-limit and cancellation fixtures.
- (DELETE) this plan after implementation verification and PR preparation.

## Execution steps

1. Create a monotonic-deadline primary budget with an optional node ceiling and
   a cloneable caller-owned `Arc<AtomicBool>` cancellation token. The caller may
   set it from another thread; search reads it only and owns no callback.
2. Return `Pass` or `GameOver` before choosing a `Position` when no legal move
   exists. Otherwise select a legal root fallback before deeper work.
3. After every completed depth, atomically replace the stable result with its
   move, PV, and score. If interrupted before depth 1 completes, return the
   legal fallback, an empty PV, no evaluated score, `completed_depth = 0`, and
   `exact = false`.
4. Poll deadline, node ceiling, and token during expansion. A partial iteration
   never becomes the completed PV.
5. Preserve node-budget determinism for corpus/GA runs while game integrations
   use a turn-time deadline. UI scheduling and ai-arena porting remain separate.

## Verification

- `cargo test -p reversi-ai` and `cargo build -p reversi-godot`
- Deadline, node, and token interruption each return the documented result.
- Pass, game-over, and pre-depth-one interruption never expose a fake move or
  sentinel score.
- Fixed-node runs reproduce depth, PV, and result metadata.

## Addresses

N/A
