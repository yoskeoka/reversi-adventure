# 002: Reversi AI Engine

## Objective

Implement the Reversi AI engine as a separate `reversi-ai` crate, per the design in `docs/design-decisions/2026-03-02-reversi-ai-design.md`. The AI must:

- Search for the best move using Negascout with iterative deepening
- Support pluggable evaluation strategies (strategic, novice)
- Produce move explanations with principal variation (読み筋) and factor breakdown
- Be configurable in difficulty via per-phase search depth
- Integrate with the GDExtension bridge for GDScript access

Linked to project requirements: リバーシAI（着手理由説明付き）の実装 (Phase 2).

## Spec Changes

Create `docs/specs/reversi-ai.md` covering:

- BoardEvaluator trait and EvalResult/EvalFactors types
- SearchEngine API (Negascout, iterative deepening, transposition table)
- Move ordering strategy
- AiPlayer facade API
- MoveExplanation and ExplainTag types
- AiConfig (per-phase depth settings)
- GDExtension bridge additions (set_ai, ai_think, ai_explain_move)

Update `docs/specs/reversi-engine.md`:

- Add reference to reversi-ai crate dependency

## Code Changes

### New crate: `rust/reversi-ai/`

```
rust/reversi-ai/
  Cargo.toml          # depends on reversi-engine
  src/
    lib.rs            # public API re-exports
    eval/
      mod.rs          # BoardEvaluator trait, EvalResult, EvalFactors
      strategic.rs    # StrategicEvaluator
      novice.rs       # NoviceEvaluator
    search/
      mod.rs          # SearchEngine, SearchResult
      negascout.rs    # Negascout + iterative deepening
      tt.rs           # TranspositionTable
      ordering.rs     # move ordering heuristics
    explain.rs        # MoveExplanation, ExplainTag, explanation generation
    player.rs         # AiPlayer facade
    config.rs         # AiConfig, difficulty presets
```

### Modified files

- `Cargo.toml` (workspace root) — add `rust/reversi-ai` to members
- `rust/reversi-godot/Cargo.toml` — add `reversi-ai` dependency
- `rust/reversi-godot/src/bridge.rs` — add AI methods (set_ai, ai_think, ai_explain_move)
- `.github/workflows/ci.yml` — add `cargo test -p reversi-ai`
- `CLAUDE.md` / `AGENTS.md` — update Tech Stack to list 3 workspace members

## Sub-tasks

### Layer 1: Foundation (parallel)

- [ ] [parallel] Create `rust/reversi-ai/` crate scaffolding (Cargo.toml, lib.rs, module structure)
- [ ] [parallel] Create spec: `docs/specs/reversi-ai.md`
- [ ] [parallel] Update workspace Cargo.toml to add reversi-ai member

### Layer 2: Evaluation (parallel, depends on: scaffolding)

- [ ] [parallel] [depends on: scaffolding] Implement `eval/mod.rs` — BoardEvaluator trait, EvalResult, EvalFactors
- [ ] [parallel] [depends on: scaffolding] Implement `config.rs` — AiConfig, phase detection, difficulty presets

### Layer 3: Evaluators (parallel, depends on: eval trait)

- [ ] [parallel] [depends on: eval trait] Implement `eval/strategic.rs` — StrategicEvaluator (corner control, stability, mobility, edge control, parity, piece count)
- [ ] [parallel] [depends on: eval trait] Implement `eval/novice.rs` — NoviceEvaluator (piece count heavy, edge grabbing, no mobility, randomness)

### Layer 4: Search (depends on: eval trait, config)

- [ ] [depends on: eval trait, config] Implement `search/tt.rs` — TranspositionTable (hash, store, probe, bound types)
- [ ] [depends on: tt] Implement `search/ordering.rs` — move ordering (TT move, corners, opponent mobility, positional value)
- [ ] [depends on: ordering] Implement `search/negascout.rs` — Negascout with iterative deepening, PV extraction
- [ ] [depends on: negascout] Implement `search/mod.rs` — SearchEngine facade wrapping Negascout + TT + ordering

### Layer 5: Explanation and Player (depends on: search, evaluators)

- [ ] [depends on: search, evaluators] Implement `explain.rs` — MoveExplanation, ExplainTag, factor-diff explanation generation
- [ ] [depends on: explain, search] Implement `player.rs` — AiPlayer facade (think, explain)

### Layer 6: Unit tests (depends on: player)

- [ ] [depends on: evaluators] Unit tests for StrategicEvaluator and NoviceEvaluator (known positions, expected factor signs)
- [ ] [depends on: search] Unit tests for Negascout (depth control, PV extraction, TT hits)
- [ ] [depends on: player] Integration tests for AiPlayer (known positions with expected best moves)
- [ ] [depends on: player] Self-play test: StrategicEvaluator vs NoviceEvaluator (strategic should win consistently)

### Layer 7: Bridge integration (depends on: player)

- [ ] [depends on: player] Update `rust/reversi-godot/Cargo.toml` — add reversi-ai dependency
- [ ] [depends on: bridge Cargo.toml] Update `rust/reversi-godot/src/bridge.rs` — add set_ai, ai_think, ai_explain_move methods
- [ ] [depends on: bridge] Update `.github/workflows/ci.yml` — add `cargo test -p reversi-ai`

### Layer 8: Finalize (depends on: all)

- [ ] [depends on: all] Update spec to match final implementation
- [ ] [depends on: all] Update CLAUDE.md / AGENTS.md — Tech Stack with 3 workspace members
- [ ] [depends on: all] Verify spec-code parity

## Design Decisions

All architectural decisions were made during the brainstorming phase and documented in `docs/design-decisions/2026-03-02-reversi-ai-design.md`:

- Negascout over MCTS (Othello branching factor ~10, score-maximization)
- Pluggable BoardEvaluator trait for varied opponent personalities
- Hand-tuned evaluation first (trained evaluator deferred)
- Board copy per search node (16 bytes, negligible)
- Separate reversi-ai crate
- Explanation via PV + factor breakdown at leaf position

No new ADR entries needed — append a brief Phase 2 note to existing adr.md when implementation is complete.

## Verification

- `cargo test -p reversi-ai` passes all unit tests
- `cargo test -p reversi-engine` still passes (no regressions)
- `cargo clippy --workspace -- -D warnings` is clean
- `cargo build -p reversi-godot` builds with AI bridge methods
- Self-play: StrategicEvaluator beats NoviceEvaluator in 10-game series
- AI can produce a move + explanation for any legal position within reasonable time
