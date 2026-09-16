# Establish measurable Reversi AI strength and a strong independent engine

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Make the Rust AI's result correct, measurable, and progressively tunable from
the current hand-tuned opponent to an independently trained pattern evaluator.
The work starts with a transposition-table correctness repair, then establishes
a pinned external oracle, budgeted search and exact endgame solving, a
self-play parameter-optimization pipeline, and a separately trained pattern
evaluator.

Completion requires reproducible local/CI evidence for each stage: TT results
must distinguish side to move; the selected external oracle must score a fixed
position corpus; bounded search must return a result from the last completed
iteration and solve its supported endgames exactly; parameter candidates must
be ranked by balanced self-play; and the trained evaluator must be compared
against the same oracle at an explicitly recorded compute budget. This plan
does not modify the pending Rust CI repair, migrate Godot, or port the engine
to the ai-arena player.

## Scope and ordering

1. Correct TT identity before using any cached search score for strength work.
2. Introduce an oracle corpus and reproducible measurement before optimizing
   engine logic or weights.
3. Add node/deadline-budgeted iterative deepening and an exact endgame solver.
4. Make the independent evaluator parameterized, then optimize its parameters
   with balanced self-play.
5. Add the strongest, independently trained phase/pattern evaluator and
   evaluate it under the same corpus and budget contract.

`Egaroucid` is the single external oracle. Its official console supports Linux,
which covers WSL2 and GitHub Actions, and its CLI reports move/value/depth/node
data. It is GPL-3.0-or-later, so it is an isolated development/CI tool only:
do not link, bundle, or expose it through the Steam product or any submitted
player artifact. Pin the exact release, download URL, and SHA-256 in the
harness. Do not rely on its currently ignored time-limit option; impose the
project's own process timeout.

## Existing references

- `rust/reversi-ai/src/search/tt.rs:20-62` hashes only board discs even though
  `TtEntry` stores side-dependent score and best-move data.
- `rust/reversi-ai/src/search/negascout.rs:39-164` owns iterative deepening,
  TT probe/store, pass handling, and terminal evaluation.
- `rust/reversi-ai/src/search/mod.rs:37-62` maps the fixed per-phase depth in
  `AiConfig` to the public `SearchResult` but drops node/completion metrics.
- `rust/reversi-ai/src/config.rs:9-31` defines the present fixed depth
  configuration.
- `rust/reversi-ai/src/eval/strategic.rs:8-231` contains the six currently
  hand-tuned strategic weights and feature extraction.
- `rust/reversi-ai/src/player.rs:37-121` has only a single Strategic-vs-Novice
  self-play assertion; it is not a strength benchmark.
- `docs/issues/0004-endgame-solver.md:1-28` records the intended initial
  16-empty exact-solve boundary and specialized 1--4-empty handling.
- `docs/issues/0005-trained-evaluator.md:1-36` records the deferred
  Egaroucid/Logistello-style trained evaluator.
- `docs/specs/reversi-ai.md:39-147` documents the externally observable search
  and evaluation contracts that must be revised before implementation.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- define side-aware TT identity,
  `SearchBudget`, completed-depth/nodes/exact-result metadata, supported exact
  endgame behavior, evaluator identifiers, and observable analysis results.
- (MODIFY) `docs/design-decisions/2026-03-02-reversi-ai-design.md` -- replace
  fixed-depth-only strength assumptions with the measurement, oracle,
  self-play, and trained-evaluator architecture.
- (MODIFY) `rust/reversi-ai/src/search/tt.rs`, `search/negascout.rs`,
  `search/mod.rs`, and `config.rs` -- make TT keys side-aware; preserve the
  last fully completed iterative-deepening result under node/deadline budgets;
  expose search metrics; and route supported low-empty positions to exact
  solving.
- (NEW) `rust/reversi-ai/src/search/endgame.rs` and focused fixtures -- exact
  negamax/PVS endgame search, pass handling, empty-region parity ordering, and
  specialized 1--4-empty handling. Begin at 16 empty squares only after corpus
  performance confirms the configured budget; retain a lower configurable
  threshold for constrained presets.
- (MODIFY) `rust/reversi-ai/src/eval/strategic.rs` and `eval/mod.rs` -- turn
  existing independent-engine feature weights and phase breakpoints into a
  serializable parameter vector while retaining explanation factor names.
- (NEW) `rust/reversi-ai/src/eval/pattern.rs` and a versioned compact weight
  artifact -- an independently implemented phase/pattern evaluator; no
  Egaroucid or Edax code, weights, binary, or runtime dependency is imported.
- (NEW) `tools/reversi-ai-oracle/` -- pinned Egaroucid acquisition/verification,
  an Othello-position corpus format, CLI adapter, normalized analysis records,
  and a process-level timeout.
- (NEW) `tools/reversi-ai-tune/` -- deterministic balanced self-play tournament,
  genetic candidate generation/selection/mutation, seed recording, opening
  rotation, side swapping, result aggregation, and machine-readable reports.
- (NEW) AI corpus, golden-result fixtures, and CI workflow steps scoped to the
  new tools -- tracked positions must include side to move, expected legal
  action, and source/provenance; external binary/cache directories remain
  untracked.
- (MODIFY) `rust/reversi-ai/src/player.rs`, `rust/reversi-godot/src/bridge.rs`,
  and their tests -- select an evaluator/budget through the supported API and
  surface only project-owned search result metadata needed for explanation.
- (DELETE) `docs/issues/0004-endgame-solver.md` and
  `docs/issues/0005-trained-evaluator.md` -- remove each local issue on the
  implementation branch after its scoped work and verification are complete;
  the implementation PR preserves their history.
- (DELETE) `docs/exec-plan/todo/0004-reversi-ai-strength.md` -- remove this
  resolved plan after verification and PR preparation.

## Execution steps

### 1. Correct TT semantics and lock it with a regression

- Extend `ZobristKeys` with a side-to-move key and make all probe/store calls
  hash `(board, color-to-move)`. A score and `best_move` can then only be used
  for the same position and side to move.
- Add a pass-position fixture proving that identical discs with opposite sides
  to move do not hit the same entry or return the other side's action/score.
- Keep color-inversion/canonical-position reuse out of this change. It is a
  separate optimization requiring an explicit transformation of board,
  perspective, score, and best move; omitting the side key is not such a
  transformation.

### 2. Establish the evaluation contract and Egaroucid oracle

- Create a legal, versioned corpus spanning opening, midgame, near-endgame,
  forced pass, and solved endgame positions. Record position notation, side to
  move, legal moves, and provenance.
- Implement an Egaroucid console adapter with fixed engine options and a
  version/SHA verification step. It must parse best move, value, depth, nodes,
  and exact-search status where reported, and fail closed on unexpected output.
- Run the adapter in WSL2 and Linux CI with a wrapper timeout. Store normalized
  oracle output as reviewed fixtures, not a runtime dependency.
- Define reports for exact best-move agreement, value/regret of the selected
  move, completed depth, nodes, and wall-clock time per phase. The first report
  is the baseline against which later parameter candidates are compared.

### 3. Add budgeted iterative deepening and exact endgame solving

- Replace fixed-depth-only execution with a `SearchBudget` that supports a
  deterministic node ceiling and an optional monotonic deadline. Preserve
  phase defaults as presets; deterministic test and tuning runs use nodes.
- Check cancellation at node expansion and return the best result from the
  last wholly completed iteration, never a partly searched PV. Include
  completed depth, nodes, and whether the score is exact in `SearchResult`.
- Implement exact endgame search for pass-aware Reversi, scored as final disc
  differential. Add parity-region ordering and 1--4-empty special cases.
- Gate the initial 16-empty threshold by the defined budget/report; lower it
  per preset when necessary rather than returning a heuristic score labelled
  exact.

### 4. Rebuild and optimize the independent evaluator

- Review the existing logic before adding features: corner/X/C exposure,
  mobility and potential mobility, frontier discs, stable discs, edge patterns,
  disc differential, and empty-region parity. Each accepted feature must have
  a deterministic definition, phase behavior, and explanation mapping.
- Represent feature weights and phase cutoffs as a versioned parameter vector.
  Keep the baseline vector so a tuned candidate can be rejected or reproduced.
- Build a genetic search that evaluates candidates through many fixed-seed,
  balanced games: rotate openings, swap colors, pair candidates in both
  directions, and report confidence-relevant game counts rather than a single
  win rate. Preserve generation seeds, candidate vectors, opponent set, and
  raw game results.
- Promote a vector only when it improves the declared tournament metric and
  does not regress the Egaroucid corpus beyond its declared selected-move
  regret limit. Record the metric, corpus version, budget, and acceptance
  limit with the promoted artifact.

### 5. Train and validate the strongest pattern evaluator

- Define compact, symmetry-normalized board patterns and phase buckets in the
  repository; add a reproducible feature extractor and artifact schema.
- Generate training labels from project-owned self-play and/or the pinned
  oracle fixtures under recorded budgets. Keep data provenance, split policy,
  trainer version, random seed, and weight checksum with every artifact.
- Train phase/pattern weights independently of external-engine source or
  assets, implement `PatternEvaluator: BoardEvaluator`, and keep its output
  compatible with explanation factors or explicitly document unavailable
  factor detail.
- Compare the trained evaluator plus its declared search budget against the
  same held-out oracle corpus and balanced internal tournaments. The acceptance
  threshold for "near parity" must be recorded as corpus-level regret and
  head-to-head result before a trained artifact replaces the independent
  evaluator as the strongest preset.

## Dependencies and parallelism

- Step 1 is a hard prerequisite for all cached-search measurements.
- Step 2 can begin after Step 1 and supplies the corpus, oracle, and reporting
  contract used by Steps 3--5.
- Step 3 depends on Step 2's metrics and corpus fixtures.
- Step 4 depends on the Step 2 harness; it may tune the existing depth search
  while Step 3 is implemented, then must rerun against the budgeted solver.
- Step 5 depends on Steps 2 and 4's artifact/report format and should be
  evaluated after the exact-endgame boundary is stable.

## Verification

- Run `cargo test -p reversi-engine`, `cargo test -p reversi-ai`,
  `cargo build -p reversi-godot`, and `cargo clippy --workspace -- -D warnings`.
- Add unit and integration coverage for side-aware TT keys, pass positions,
  fixed node budgets, deadline cancellation, incomplete iteration fallback,
  final-disc scoring, 1--4-empty cases, and the supported exact-solve
  threshold.
- Re-run the same corpus with identical oracle version/SHA, fixture version,
  parameter vector, seed, and node budget; verify byte-for-byte stable
  normalized results where deadlines are not used.
- Verify the Egaroucid tool is absent from product/GDExtension/release
  artifacts and that an unavailable, checksum-mismatched, or unparsable oracle
  fails the measurement job rather than silently changing results.
- Verify each self-play tournament balances colors/openings, persists raw
  results, and can reproduce the winning candidate from its report.
- Verify the Godot bridge continues to reject unknown evaluators and returns a
  legal move plus documented project-owned analysis metadata for supported
  presets.
- Run `git diff --check` and the repository workflow-linter before the plan PR.

## Addresses

- `docs/issues/0004-endgame-solver.md`
- `docs/issues/0005-trained-evaluator.md`
