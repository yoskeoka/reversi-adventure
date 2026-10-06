# Reversi AI Specification

## Overview

Reversi AI engine providing pluggable evaluation strategies, Negascout search with iterative deepening, and move explanation. Lives in the `reversi-ai` crate, depends on `reversi-engine`.

## Evaluation

### EvalFactors

Score breakdown for human-readable explanation.

```rust
struct EvalFactors {
    corner_control: i32,
    stability: i32,
    mobility: i32,
    edge_control: i32,
    parity: i32,
    piece_count: i32,
}
```

- `EvalFactors::total()` — Returns the sum of all factors.

### EvalResult

```rust
struct EvalResult {
    score: i32,
    factors: EvalFactors,
}
```

### BoardEvaluator Trait

```rust
trait BoardEvaluator {
    fn evaluate(&self, board: &Board, color: Color) -> EvalResult;
    fn name(&self) -> &str;
    fn context_fingerprint(&self) -> u64;
}
```

Implementations must return evaluation from the perspective of `color` (positive = good for `color`).

`context_fingerprint()` must:

- stay stable for the same score context;
- include the evaluator version and all score-affecting parameters;
- exclude object addresses and other process-local state.

`StrategicEvaluator` includes its version and evaluation weights.
`NoviceEvaluator` includes its version and seed.

### Pattern-evaluator artifact contract

The project-owned trained-pattern evaluator is a future `BoardEvaluator`
implementation. This contract defines its input representation only; it does
not change the strategic or novice evaluators, invoke an explanatory
evaluator, or assign human-readable factors to a pattern score.

- The catalog contains exactly 64 features: eight project-defined base square
  patterns expanded through all eight dihedral symmetries of the 8-by-8 board.
  Every feature contains at most ten squares. The catalog digest identifies
  both the square order and this expansion order.
- A square is ternary encoded from the requested color's perspective: empty
  is `0`, the requested color is `1`, and the opponent is `2`. A feature code
  is the square values accumulated in listed-square order as a base-three
  integer.
- Before extraction, the board is put in the lexicographically smallest of its
  eight absolute-color symmetry orientations (ties use the lowest symmetry
  number). Ternary codes remain relative to the requested color. Consequently
  symmetric positions produce the same 64 feature codes, in catalog order, and
  changing requested color swaps ternary `1` and `2` without changing feature
  alignment.
- There are exactly 60 discrete phase tables. Their indexes are the occupied
  disc count minus four, covering occupied counts `4..=63`. A pass leaves the
  phase unchanged; terminal 64-disc positions have no pattern phase. Scores
  must not interpolate between phase tables.
- A trained pattern score predicts the requested color's final disc
  differential. It is an integer in inclusive range `-64..=64`. Accumulation
  is deterministic integer arithmetic and an artifact is rejected when any
  contribution, declared aggregate bound, or checked aggregate cannot satisfy
  that range without overflow.
- A weight artifact is immutable and identifies its format version, catalog
  digest, phase definition, final-disc-difference score scale, safe source
  provenance, and weight digest. Provenance may name a reproducible trainer,
  input-manifest digest, and licenses; it must not embed private input data.
  Its catalog, phase, scale, version, and weight identity are score-affecting
  context and therefore enter the future evaluator's
  `context_fingerprint()`.

Pattern scores have no human-factor attribution and must not be combined with
the explanatory evaluator or its explanation path.

### Trained evaluator runtime

`TrainedEvaluator` loads only the canonical JSON artifact emitted by the
project-owned training tool.  Loading validates the complete feature contract,
safe non-empty provenance, all 64 feature bounds, the sparse 60-phase table
shape and canonical decimal codes, every weight and aggregate score bound, and
the SHA-256 `weight_digest` and `artifact_digest` identities.  A load or
validation failure is a clear error; it never selects a fallback evaluator.

The evaluator sums the 64 sparse entries selected by `extract_features()` for
the board phase and requested color, returning a final-disc-difference score
with default (empty) `EvalFactors`.  Its context fingerprint includes a
trained-runtime version plus the artifact's immutable identity, so retained
transposition-table entries cannot cross artifacts or feature contracts.

The oracle candidate CLI selects this evaluator only with `--evaluator trained
--trained-artifact PATH`.  It uses `SearchEngine` directly, remains bookless,
and preserves all four `AiConfig` controls.  A named profile supplies all four
controls and rejects any explicit control rather than ignoring it.  Trained
mode neither constructs `AiPlayer` nor exposes explanation output.

### Pattern-evaluator training contract

`tools/reversi-ai-training` is an offline, manifest-driven producer of a
future pattern-weight artifact. It is not loaded by the game or GDExtension,
and neither its datasets nor caches are runtime dependencies.

- A version-1 input record is JSON Lines and states a record id, source id,
  SPDX license, source digest, 64-character row-major `B`/`W`/`.` board,
  side (`B` or `W`), final-disc-difference target for that side, and one of
  `train`, `validation`, or `held_out`. Optional candidate positions state the
  same board, side, and target fields and permit move-quality measurement.
  Targets are finite integers in `-64..=64`; the only accepted target semantic
  is `final_disc_difference_for_side`.
- A versioned manifest pins each input pathname, SHA-256 digest, license,
  trainer version, random seed, feature-contract digest, optimizer parameters,
  and split names. The manifest digest is the SHA-256 of its canonical JSON
  serialization. Records with a missing license, an input digest mismatch, an
  invalid board/schema, non-finite number, or incompatible feature contract
  are rejected.
- The canonical absolute-color D4 board key, together with side to move,
  identifies a position for split checking. A duplicate key anywhere in the
  inputs, including a symmetry-equivalent position in another split, is a
  leakage error. Calibration and acceptance corpora are held-out inputs and
  are never training or optimizer-tuning inputs.
- The trainer consumes the fixed 64 features and 60 discrete phases above and
  emits a sparse JSON artifact plus a JSON validation report. The report uses
  only `held_out` records (never `validation`) and records the manifest digest,
  trainer version, seed, feature-contract digest, optimizer parameters, input
  licenses, per-phase loss, and candidate top-target agreement. Its sparse
  per-phase/per-feature tables use integer weights; each
  feature's declared absolute bound is at most one and all 64 bounds sum to at
  most 64, so every selected aggregate is representable on the required
  `-64..=64` scale without overflow.
- Artifact metadata includes a canonical weight digest and artifact digest.
  Validation recomputes both, validates the feature contract, phase count,
  score scale, provenance, bounds, and every feature-vector prediction. A
  rerun with identical manifest and input bytes must produce identical declared
  artifact and report digests. Corruption, NaN, overflow, or a contract-mismatched
  artifact fails closed.

### Bounded pattern reinforcement cycle

The production baseline and validation inputs are generated from complete,
legal, project-owned random games under a frozen version-1 generator manifest.
It pins the exact producer checkout commit, its merged-main base commit, SHA-256
for the generator and both imported game/training modules, `CC0-1.0` provenance,
master seed, game-id lists for `train`, `validation`, and `held_out`, and the
record start placement and turn cap. A SHA-256-derived per-game seed and a
separate seeded split shuffle give independent, repeatable streams. Each move
is selected uniformly by index from sorted legal moves; a pass occurs only
when no move exists. A game must reach the actual terminal board within its
turn cap. Its complete log records moves, passes, terminal disc counts and a
digest. Every emitted nonterminal record has the final black-minus-white disc
count signed for its side to move, including games ending in an early wipeout.

Records start after eight placements by default. Phases use placement counts:
opening 8-20, midgame 21-44, endgame 45-59. Canonical absolute-color D4
board-and-side duplicates are retained in game logs but emitted only once,
across all splits in global game and turn order. Every split must have all
three phases and at least one record. The separate validation JSONL is
disjoint from both training and trainer-held-out positions. The generator
emits canonical JSONL, a trainer manifest with SHA-256 and source/license for
each split, and a report written last. Its verifier replays every game,
recomputes records, targets, split assignment, digests, counts and phase and
legal-move distributions, and rejects partial or changed outputs. Frozen
inputs must reproduce byte-identical outputs. A local pilot establishes time
and memory caps before producing the 2,048/256/256-game baseline inputs.

The offline trainer consumes these inputs to produce the baseline artifact.
Its held-out loss, phase coverage, nonzero-weight count, and comparison with
zero weights are diagnostics, not a playing-strength claim. The separate 0019
cycle uses the exact baseline and validation digests; 0018 acceptance openings
remain unread until their own gate.

The offline reinforcement producer accepts a version-3, immutable manifest.
It records the baseline artifact identity and SHA-256, candidate executable
SHA-256, trainer and update-rule versions, feature contract, trained evaluator,
all three search depths, exact-solver threshold, disabled book, self-play and
match limits, D4/color-pairing policy, per-decision timeout, maximum decisions,
and an actual random seed. These identify the method and the compared inputs;
the producer source commit and reproducing the generated openings from a seed
are not acceptance gates. Version-1 and version-2 manifests and reports are never evidence
for version-3 candidate selection, although version-1 and version-2 baseline artifacts remain
valid inputs. Version-3 pins `reset_contract` with protocol `new_game-v1`,
cache lifetime `one-game`, and the same candidate executable SHA-256. Prepare
checks a control acknowledgement without playing a game. Every self-play and
candidate-match game resets each participating player before any move; its
record preserves the game ID and acknowledged reset events. Run and offline
verify reject a missing contract, an old manifest, mismatched binary identity,
or missing per-game reset evidence. Version-1 and version-2 trained artifacts
remain usable baselines, and the artifact loaders also accept version-3
reinforcement provenance.

The `strong-engine-hcap-v1` candidate label requires all three depths to be
12 and the exact-solver threshold to be 16. Its decision protocol timeout must
exceed the candidate search time limit. Corpus regret uses that frozen timeout.

The producer validates the recorded artifact and executable identities before
any game. A human starts the production command in a separate terminal. An
agent may prepare the manifest and validate completed files without running or
monitoring that command.

The reinforcement `run` command writes flushed diagnostic progress only to
stderr. It writes `stage NAME start elapsed=S.s` and `stage NAME done
stage=S.s elapsed=S.s` for self-play, replay/tuning extraction, validation,
artifact update, metrics/selection, report serialization, and atomic output
publication. After each completed terminal self-play game and its digest, the
default `--progress-every 1` writes `progress self-play pair=P member=M
N/total game=S.s elapsed=S.s`, where `total` is the manifest individual game
count. A positive larger interval writes completed-game lines only at interval
multiples and at the final game. These monotonic-clock diagnostics do not
enter the candidate protocol, manifest, reports, records, digests, or output
bytes, and cannot make a failed or interrupted cycle valid.

- Each self-play opening is generated from a separate random stream and yields exactly two
  games: one original position and one color-swapped D4 rotation. The report
  records the opening, every decision and pass, terminal board and disc counts,
  final score, and a digest for each game. Any illegal move, timeout, malformed
  response, resource-cap breach, or incomplete pair fails the whole cycle.
- One deterministic update pass uses nonterminal self-play positions and their
  final-disc-difference targets. For each phase, feature, and code, it adds the
  rounded mean residual divided by 64 to the baseline integer weight, clamped
  to `-1..=1`. Updates are simultaneous against baseline predictions. The
  resulting sparse artifact retains the existing 64-feature, 60-phase,
  `-64..=64` score and canonical digest contracts.
- Validation positions that share a canonical board-and-side key with tuning
  are excluded from MSE diagnostics and their IDs and remaining count are
  reported. An empty remainder makes MSE unavailable, not a failed run; MSE is
  never a selection metric and validation data never enters the update.
- Candidate-comparison openings come from another random stream. Roots that
  occur in tuning are excluded, with the pool attempts and exclusions recorded,
  before complete color-swapped D4 pairs are admitted. Coincident positions
  reached later in independent games are valid. The baseline and candidate use
  identical CLI/search/resource settings. At 25 complete pairs (50 games),
  candidate match points must exceed 25 to continue for 75 more pairs. At 100
  complete pairs (200 games), candidate match points must exceed 100 to be
  selected; ties select the baseline. A non-continuing 50-game result selects
  the baseline.
- The 50-game result is written as an atomic version-3 checkpoint containing
  manifest identity, game digests, aggregate and continuation decision. It is
  diagnostic evidence, not resume input. A run accepts only a nonexistent or
  empty output directory; it rejects checkpoints, partial files, and temporary
  files without overwrite. A completed report and selected artifact are
  published atomically only after the selected comparison completes. The
  independent verifier replays every game and recomputes updates, MSE
  diagnostics, pairings, match result, decision, and all digests; it rejects a
  checkpoint-only or mismatched output.
- Corpus regret under `strong-engine-hcap-v1` is a separate evaluation-only
  report for the selected artifact. The 0018 held-out opening suite is not read
  during generation, update, selection, or corpus regret.

### Random-game input batch progress

The existing random-input `generate` and `verify` commands can process up to
2,560 complete games. They write flushed stderr-only diagnostics with the
same positive `--progress-every` rate control (default `1`). For each terminal
game, generation writes `progress random-inputs generate game=ID split=S
N/total game=S.s elapsed=S.s`; verification writes the corresponding
`progress random-inputs verify game=ID split=S N/total game=S.s elapsed=S.s`.
Both commands write start and done stage lines using the same stage-line forms
above. These diagnostics are excluded from frozen manifests, reports, records,
digests, and generated output bytes; a report written last remains the only
completion evidence. Verification's required replay rebuild emits the same
interval-controlled form with `verify-rebuild` as its action.

### Existing batch-tool progress

The offline pattern trainer writes flushed stderr-only start/done stage lines
and, by default, a line for every validated and prediction-checked record:
`progress pattern-training ACTION record=ID split=S N/total record=S.s
elapsed=S.s`. `train --progress-every N` is a positive interval override; its
diagnostics are not artifact or report content. The release comparator writes
`progress benchmark position=ID repetition=R N/total pair=S.s elapsed=S.s`
after each completed baseline/candidate pair, plus measurement, aggregation,
and publication stages; `--progress-every` defaults to one.

Oracle analysis and benchmark-reference commands write flushed stage start and
done diagnostics around their indivisible external solve batches, without
changing query ordering or adding artificial solve units. Oracle `match` and
`ci` write `progress oracle-match game=N N/total game=S.s elapsed=S.s` after
each terminal game; their positive `--progress-every` interval defaults to
one. All of these lines are diagnostic stderr only and never establish a
successful report or alter its bytes.

### StrategicEvaluator

Hand-tuned weights based on known Othello strategy. Evaluates:

- **Corner control**: +/- for each corner owned/opponent-owned. Penalizes C-squares and X-squares adjacent to empty corners.
- **Stability**: Counts stable discs (can never be flipped). Corner-anchored stability propagation.
- **Mobility**: Legal move count differential. Most important midgame factor.
- **Edge control**: Edge disc patterns. Rewards controlled edges.
- **Parity**: Empty region parity. Last-move advantage in endgame.
- **Piece count**: Disc differential. Only significant in endgame (stone count > 50).

### NoviceEvaluator

Simulates a beginner player:

- Heavily weights piece count (more discs = "winning").
- Grabs edges eagerly (positive edge weight, ignores C/X-square danger).
- Ignores mobility (weight = 0).
- No stability calculation (weight = 0).
- Adds slight randomness (small random perturbation to score).

- `NoviceEvaluator::new()` — Constructor with default seed `12345`.
- `NoviceEvaluator::with_seed(seed: u64)` — Constructor with explicit seed for deterministic testing.

## Configuration

### AiConfig

```rust
struct AiConfig {
    opening_depth: u8,    // stone count 4-20
    midgame_depth: u8,    // stone count 21-44
    endgame_depth: u8,    // stone count 45-64
    exact_solver_empty_squares: u32,
}
```

`exact_solver_empty_squares` is the exact-solver start threshold. When the
decision position has at most this many empty squares, every evaluator is
bypassed and the engine attempts a complete final-disc solve. It is not an
endgame search depth. The default and the named `strong-engine-hcap-v1`
candidate profile use `16`. The external-only `ci-smoke-v1` calibration keeps
its recorded 12-empty threshold through an explicit candidate CLI option.

- `AiConfig::depth_for_phase(stone_count: u32)` — Returns the appropriate depth based on stone count.

### Game Phase Detection

Phase is determined by total stone count on the board:
- Opening: 4-20 stones
- Midgame: 21-44 stones
- Endgame: 45-64 stones

### Decision move phase configuration and advisor analysis

`DecisionMoveConfig` is a reusable AI search policy with opening depth 1–12,
midgame depth 1–16, and an exact-solver threshold of 0–30 empty squares.
Values must be integers in these inclusive ranges and are rejected rather than
rounded. Legacy single-depth inputs map to equal depths and accept only 1–12.
Match and Advisor configurations share these limits.

Configuring depth 16 or
a 30-empty threshold does not guarantee completion, speed, or strength;
existing search budgets apply and interrupted exact search remains inexact.
Ordinary `AiConfig` defaults and named strength, training, and benchmark
profiles remain unchanged.

The policy has no endgame depth. The next move number is the number of occupied squares minus
three; passes do not advance it. Moves 1–20 use the opening depth and moves
21–60 use the midgame depth. The decision position alone selects the depth
and whether exact solving applies.

Advisor analysis and CLI move search with
`--decision-move-phases` use this policy. The existing `AiConfig` phase boundaries
and ordinary move-search defaults remain unchanged. The advisor configuration
and evaluator identity are included in the analysis `config_id`. The policy is
part of the shared Rust AI and can be used by Godot when the main game adopts
this interaction; no separate playground-only search policy is needed.

In advisor mode, `--print-advisor-config-id` validates the evaluator, trained
artifact, and search settings, prints that same `config_id` as one line, and
exits without reading stdin. It is invalid outside advisor mode.

For a nonterminal position, analysis evaluates every legal root move from the
current side's perspective. Heuristic results share one completed root depth;
an immediately terminal child may instead report its proven exact value. One
monotonic deadline and node budget cover the entire set. Only the last fully
completed set may be returned; if no complete set finishes, analysis fails.
In the exact region, a set succeeds only after every candidate is proven.
Pass and game-over positions return an empty score set with an explicit outcome.
Advisor values are evaluator-specific and are not comparable across AIs or
between heuristic and exact searches.

## Search

### Adopted search acceleration methods

The search uses the following methods. Phase names describe where each method
does useful work; the exact solver is selected by remaining empty squares,
which is distinct from the stone-count phase labels above.

[Methods not adopted](../references/reversi-ai-search-experiments.md)

| Method | Where it helps |
| --- | --- |
| Portable bitboard move generation and reuse of computed flips | Legal moves and successor boards are needed throughout play; repeated generation makes this especially relevant to opening and midgame search. |
| Iterative deepening with principal variation search | In opening and midgame search, completed shallower searches guide move order, and narrow probes avoid full-window work for later moves when their bounds suffice. |
| Transposition caching and move ordering by cached moves, corners, opponent mobility, and positional value | In opening and midgame search, repeated positions and promising early moves improve reuse and alpha-beta pruning. |
| Exact-position caching | In exact endgame search, previously proved positions and bounds can avoid repeating equivalent proof work. |
| Exact endgame principal variation search | With few empty squares, narrow probes of later moves reduce work when they prove a bound; a full search still establishes an exact result where needed. |
| Empty-region parity ordering | In exact endgame search, odd empty regions guide the order in which candidate moves are proved. |
| Specialized search for the last four empty squares | At the end of an exact solve, the small remaining position uses direct move and pass handling. |

### TranspositionTable

Hash table storing previously evaluated positions.

```rust
struct TtEntry {
    hash: u64,
    depth: u8,
    score: i32,
    bound: Bound,       // Exact, LowerBound, UpperBound
    best_move: Option<Position>,
}

enum Bound {
    Exact,
    LowerBound,
    UpperBound,
}
```

- `TranspositionTable::new(capacity: usize)` — Create with given capacity.
- `TranspositionTable::probe(hash: u64)` — Look up entry. Returns `Option<&TtEntry>`.
- `TranspositionTable::store(hash: u64, entry: TtEntry)` — Store entry. Replaces if new depth >= existing depth.
- `TranspositionTable::clear()` — Clear all entries.

Each TT entry is scoped to:

- the board;
- the side to move;
- the evaluator and search context that produced it.

`SearchEngine` combines the evaluator's `context_fingerprint()` with the active
`AiConfig` and search-semantics version. It clears the TT when that context
changes. Scores, bounds, and best moves must not cross context boundaries.

### Zobrist Hashing

```rust
struct ZobristKeys {
    // pre-computed random u64 values: 2 colors × 64 squares + 2 side keys
}
```

Board and side-to-move hashing for transposition table lookup.

- Pre-computed random `u64` values for each (position, color) combination plus one value for each side to move: 128 board values + 2 side keys.
- Hash computed incrementally: XOR in/out pieces as moves are made.
- `ZobristKeys::new()` — Generate a new set of random Zobrist keys.
- `ZobristKeys::hash(&self, board: &Board, color: Color) -> u64` — Compute hash from scratch for the given board position and side to move. The same discs with different sides to move produce different keys.

### Move Ordering

Moves are ordered for maximum pruning efficiency:

1. TT best move (from previous iteration or shallower search)
2. Corner moves (positions 0, 7, 56, 63)
3. Moves sorted by opponent mobility (ascending — fewer opponent moves = better)
4. Static positional value (pre-defined 8x8 weight table)

- `order_moves(board: &Board, color: Color, moves_mask: u64, tt_move: Option<Position>, depth: u8)` — Returns `Vec<Position>` in priority order. When `depth < 3`, the expensive opponent-mobility calculation is skipped.
- Heuristic Negascout reuses each successor board generated for full
  opponent-mobility ordering, rather than generating that same successor a
  second time before recursive search. This implementation detail preserves
  the documented ordered positions and does not apply to exact endgame search.

### Portable move primitives

Internal move generation uses only stable, architecture-neutral `u64`
operations with explicit board-edge masks. It produces the same canonical
legal-move mask and, for each generated move, its exact flip mask. Search may
apply that internal descriptor directly to construct a successor without
recomputing flips. Public legality checks, `make_move`, `Game`, board
orientation, coordinate notation, deterministic ordering, and pass/game-over
semantics remain unchanged. The optimized implementation is continuously
checked against an independent straightforward reference implementation.

### Negascout

Negascout (Principal Variation Search) with iterative deepening.

```rust
struct Negascout<'a, E: BoardEvaluator + ?Sized> {
    evaluator: &'a E,
    tt: &'a mut TranspositionTable,
    zobrist: &'a ZobristKeys,
}
```

Low-level search implementation. Typically used via `SearchEngine` rather than directly.

- `Negascout::new(evaluator: &'a E, tt: &'a mut TranspositionTable, zobrist: &'a ZobristKeys)` — Constructor.
- `Negascout::nodes_searched(&self) -> u64` — Returns total node count from the last completed search.
- `Negascout::search(board: &Board, color: Color, max_depth: u8, budget: &SearchBudget)` — Internal budgeted iterative deepening search. Returns the root outcome and the last wholly completed iteration.
- TT probes and stores use a Zobrist key that includes the current `color`, including when a pass keeps the board unchanged.
- Internally runs depth 1, 2, ..., up to `max_depth`.
- At each depth: Negascout with alpha-beta window.
  - First move (PV node): search with full window [alpha, beta].
  - Remaining moves: null-window search [alpha, alpha+1]. If fails high, re-search with full window.
- PV extracted by tracking best move at each depth level.

### Deterministic search profiling

`reversi-ai-search-profile` is a diagnostics-only binary that reads the
versioned external-oracle JSON Lines corpus and writes one JSON object per
input position. It runs every position with a fresh `SearchEngine`, strategic
evaluator, supplied search configuration, and a fixed node-only limit. Each
record includes the source position id and board digest plus
the selected outcome, score, PV, completed depth, nodes searched, exact flag,
and elapsed time.

The deterministic comparison projection excludes elapsed time and requires
the same outcome, score, PV, completed depth, nodes searched, and exact flag
for a repeated run in the same search context. Elapsed time is a supplemental
same-host release-build measurement only. The profiler is neither game code
nor an oracle candidate protocol and does not change the public move-only CLI.

`--node-limit` remains the required, deterministic diagnostic mode. Its JSON
record and deterministic projection remain unchanged. `--time-limit-ms` is a
separate, positive, mutually exclusive full-depth timing mode: every input
position receives a fresh `SearchEngine` and a time-only monotonic
`SearchBudget`, never a node ceiling. A timing-mode record identifies its
`time_limit_ms` and includes `timing_success` plus a null failure reason on
success. A heuristic timing sample succeeds only when it completes the
configured phase depth with `exact = false`. An exact timing sample succeeds
only when it completes the board's remaining empty-square count with
`exact = true`; the exact solver does not use phase depth. A timeout,
cancellation, or incomplete search is a failed sample with a stable failure
reason, and is not a completed timing measurement.

### Search performance benchmark corpus

The checked-in `positions-v1.jsonl` corpus contains exactly sixteen legal
decision positions: four positions at 20, 40, 44, and 48 occupied discs from
each of four pinned self-play games. Every record has the version-1 corpus
schema, its legal moves and outcome, and replayable provenance including its
source-game number and complete coordinate transcript. Records are canonical
JSON Lines, have the expected game/count identity set, and must not duplicate
one another directly or under an 8-by-8 D4 symmetry.

The corpus generator starts each game from the initial board, uses the pinned,
bookless, one-thread Console oracle at level 6, and randomizes only its first
six plies. It replays every resulting transcript legally before publishing
records. Console self-play's implicit passes are replayed as state
transitions, even though they are absent from its coordinate transcript. The
generator and validator fail closed for a malformed transcript, an illegal
move or pass transition, an incomplete root set, malformed records,
duplicates, D4-equivalent boards, or non-canonical output. This self-play
profile is distinct from and does not alter `strong-engine-hcap-v1`.

`make benchmark-oracle-setup` provisions the pinned external Console tool,
`make benchmark-corpus` regenerates the corpus, and
`make benchmark-corpus-verify` validates the checked-in artifact without
performing reference analysis or timing measurement.

### Search performance evidence

`search-performance-reference-v1` is a separate, versioned oracle-analysis
profile. It pins the verified source digest, bookless default evaluation, one
thread, hash level 25, and 100-percent depth 12 for the 20-, 40-, and
44-occupied roots. Its 48-occupied roots require the complete remaining
16-placement solve. It is distinct from both the corpus self-play profile and
`strong-engine-hcap-v1`; neither profile's depth ranges change.

The canonical reference JSON Lines report records the full profile object and
its SHA-256 digest for every corpus position. A heuristic record is reference
analysis only. An exact record additionally requires every root evaluation to
be exact, the final root-side score, and the complete equal-value
`optimal_moves` set. The reference validator rejects a noncanonical report,
wrong corpus or profile digest, an incomplete root-move set, or exact metadata
that does not satisfy the 16-empty contract.

`reversi-ai-search-comparator-v1` accepts explicit, already-built release
profiler binaries for a baseline and a candidate. It runs one unrecorded
warm-up per binary and corpus board, then at least five measured repetitions,
alternating binary order for every board. Every invocation uses the profiler's
time-only mode with depth 12 and the 16-empty exact threshold. A failed timing
sample fails the comparison; it is never silently excluded.

Its canonical JSON report identifies both binary paths and SHA-256 digests,
runner version, repetitions, time limit, Rust/build flags, OS, architecture,
CPU model, every raw profiler sample, per-position baseline/candidate elapsed
medians and candidate-to-baseline ratio, and geometric-mean ratios for the
`heuristic-depth-12` (20/40/44 occupied) and `exact-16` (48 occupied)
workloads. The raw sample retains nodes, outcome, score, PV, completed depth,
and exactness so a human can review semantic equality independently of timing.
CI tests validate report schema, digests, deterministic fields, ordering, and
arithmetic with synthetic samples only. No CI assertion may require a wall
clock speed, ratio, or threshold; a documented same-host release run is the
only performance evidence.

The Rust cost reassessment measures the same corpus as twelve
`heuristic-depth-12` and four `exact-16` positions. A diagnostic profiler may
select `strategic` or `trained`; trained mode requires a validated artifact and
is reported separately from the strategic release comparison. Artifact loading
is outside the search interval. Exact solving makes no evaluator calls.

Diagnostic instrumentation records ordered search decisions and resource costs
but is disabled in release timing. For a cost-only change, original and tuned
node-only runs must have matching ordered trace digests, node counts, outcome,
score, PV, depth, and exactness, including pass, collision, interruption, and
cancellation cases.

On Linux each measured profiler invocation has a sibling `resource_usage`
object with positive process elapsed time, nonnegative user and system CPU
time, and positive peak RSS from that child's `wait4` result. The report
identifies the measurement method, host, binary digests, and build flags.
Process metrics cover startup through exit. Profiler elapsed time covers search
after evaluator construction. Warm-ups are excluded from the aggregates.

For each position the report gives binary medians of
search elapsed and CPU time and candidate-to-baseline ratios. Each workload
gives geometric means of those ratios and maximum peak RSS for each binary.

Missing or invalid resources, incomplete positions or repetitions, mismatched
measurement context, unfinished depth, or any result, node, or required trace
mismatch rejects the comparison. The report presents both workloads and
resource changes; a cost-only candidate requires at least a 5% search-time
improvement in one workload before it is offered for adoption.

The exact solver searches the first ordered move with the full integer score
window. It probes later moves with a one-point window and repeats a probe with
the full window when the result can raise alpha without proving a cutoff.
Only proven bounds may be reused from these probes; a bounded result never
becomes a completed exact root score or a fabricated principal variation.
An EXACT entry proves both the node value and its selected continuation. A
LOWER/UPPER entry proves only an inequality and carries no played PV. A cached
lower bound may prove a cutoff, but must not raise the search window's alpha
when the remaining search is responsible for proving the best move: a fail-low
continuation equal to that bound does not prove that move achieves the value.
A completed full-window root must return a legal selected child whose value,
converted back to the root side (including passes), equals the reported best
score. The legal PV must carry that proof through to termination; score alone
or PV length alone does not justify `exact=true`. An interrupted attempt exposes
no exact score or PV, including when a retained bound was available.
Move ordering and strict greater-than tie breaking preserve the chosen move
and complete principal variation; exact move ordering is independent of
transposition hits so extra probes cannot change equal-score choices.
Every probe and retry obeys the same search
budget; interruption discards the whole exact attempt. Profiler diagnostics
count exact null-window calls, fail-highs, and full re-searches separately
from searched nodes. These counts are diagnostic and may change when the
search tree changes.

### Whole-game self-play performance

The version-1 whole-game corpus consists of four fixed legal openings reached
from the standard black-to-move board, each played with both seat assignments.
The eight games retain their opening transcript, seat colors, passes, every
decision board and side, final board and score, and a canonical input digest.
An interrupted or partial game is never a completed sample.

The benchmark records three independent workloads: pinned bookless, single
thread Egaroucid against itself; a baseline project CLI against itself; and a
candidate project CLI against itself. In the comparable workload, each seat
has one process for exactly one game. Process startup and shutdown are measured
separately from decision time. A second CLI workload keeps the same process
across all games, matching the reinforcement runner. Runs are serial on one
host with pinned binary and evaluator artifact SHA-256, search settings,
timeouts, and resource caps.

Each completed game reports wall time, user and
system CPU, peak RSS, each decision time, search count, and exact-cache probes,
hits, and stores. Missing CPU or RSS rejects a performance adoption claim.
Raw per-game data and aggregates are independently recalculable. CLI stderr
diagnostics stay out of GTP responses; structured per-decision search metadata
is retained in game records and their digests. The long-running eight-game
measurement is started by a human in a separate
terminal. A stopped reinforcement run supplies no candidate evidence.

The benchmark independently replays each decision before accepting CLI search
diagnostics. At a nonterminal forced pass below the exact-solver threshold,
the CLI records `outcome=pass`, `score=null`, `completed_depth=0`, and
`exact=false`. At a forced pass in the exact region it records `outcome=pass`,
an integer root-side score, `completed_depth` equal to the remaining empty
squares, and `exact=true`. Both retain nonnegative elapsed time, node count,
and cache counters in the game record and report digest. A pass where the
current side has a legal move, a move outcome for a forced pass, or an
inconsistent pass diagnostic invalidates the report. Every legal-move decision
requires `outcome=move`, an integer score, and the configured phase depth (or
the exact empty-square depth); a fallback or incomplete search invalidates the
measurement. Offline verification applies the same conditions.

Exact-solver reuse is confined to a bounded table owned by a `SearchEngine`.
An entry identifies the complete board and side to move, carries a score from
that side's perspective, a proved bound and legal best move, and is checked
against the full identity after a hash probe. Reuse across roots and passes
must preserve root-relative signs. Context changes invalidate reused search
state, and timeout or interruption cannot turn a bound or unfinished root into
an exact answer or principal variation. Capacity and replacement are fixed and
observable, including when collisions occur; ordinary heuristic TT depth
semantics are unchanged.

Production cross-decision exact-cache reuse remains suspended. Every default
`search_with_budget` and every `analyze_with_budget` call
clears the exact table once at entry, including pass, terminal and interrupted
requests. Heuristic TT entries survive when the search context is unchanged.
Recursive solving and all candidate comparisons within one Advisor call may
reuse exact entries. This shared boundary also protects AiPlayer, Godot,
Playground and self-play callers.

The CLI defaults to `--exact-cache-scope turn`. Explicit `game` is an experimental
diagnostic opt-in to a separately constructed engine that retains exact entries
between search decisions; a companion `exact_cache_policy_v1` stderr record
identifies the position id, effective scope and `diagnostic-game-v1` policy for
every search decision. Existing `search_diagnostic_v1` fields and encoding remain
unchanged for current production parsers. Default and explicit turn records
identify `turn` and `exact-cache-cross-decision-suspended-v1`. Advisor rejects
game and always uses the default per-call clearing boundary. `new_game` and
search-context changes clear both tables under either scope. This opt-in is
for the separate correctness verification (0045), and does not re-enable
production adoption or change the default shared AI/training policy.
New reinforcement preparation and execution pin effective `turn`, the
`exact-cache-cross-decision-suspended-v1` policy and executable SHA-256 in a
new manifest version. Older manifests cannot resume or supply adoption evidence
with the current executable. Completed historical reports remain verifiable
offline under their original version and identities. New whole-game preparation
and measurement reject current-CLI `game` conditions during preflight.
The move-only stdout protocol is unchanged.

Self-play may select depth `12/8/12` with the 16-empty exact threshold while
candidate matches and 0018 acceptance retain their separately frozen search
settings. A version-4 production manifest and version-3 report identify the selected
self-play depths, exact threshold, and executable SHA-256. `prepare`, `run`,
and `verify` reject a mismatched binary or manifest, including an older
manifest lacking these identities. The report's manifest digest includes the
version-4 safety policy; artifact/update and report encoding retain version 3.
Heuristic positions at depth 8 and 12 are
different workloads.

Within one configuration, baseline and candidate must
agree on move, score, and completed exactness for the same positions; exact
scores are checked against the independent oracle. The report states both
workload times, measured cause of any improvement, and the available settings
if the 2–3 minute guide is missed. The guide becomes an acceptance threshold
only after the oracle's whole-game result has been measured.

### Durable whole-game measurement and game boundaries

Prepared measurement manifests pin source and harness revisions; absolute paths
and SHA-256 identities of the CLI, external oracle, evaluator and opening corpus;
search depths, exact threshold and cache scope; ordered seat assignments;
process lifetime; timeout and RSS caps; host identity; and output directory.
Preparation writes a manifest and an executable script without starting measurement.
The script validates all pinned inputs and harness identity on every invocation,
then runs serially on the same host. Explicitly registered version-1 reports
remain immutable reference evidence. Canonical encoding, report digest, all eight
legal games, resource data and registered identities must verify before skipping.
Corrupt or mismatched existing evidence fails closed rather than being replaced.
Verified comparisons and oracle checks can likewise be skipped.

A CLI game starts with `new_game\t<game-id>`; after clearing both search tables
and retained search context, the CLI flushes `new_game\t<game-id>\tready`.
Move requests and responses retain their existing format. Both seats must
acknowledge before a game's first decision. Reinforcement self-play and candidate
matches use the same boundary; prepare/run/verify pin `one-game` cache lifetime,
reset protocol and executable identity, and reject manifests lacking them.
Interrupted or failed preparation leaves no published reinforcement manifest.
Within a game heuristic search state survives between decisions; the suspended
cross-decision policy clears exact entries at each public decision boundary.
Across games no search
state survives, even when seat processes remain alive. Reports record reset
identity, duration and acknowledgement; unsupported or missing acknowledgement
rejects new measurement conditions. Resumable external Oracle measurements
record the actual `gtp-clear-board` boundary; only project CLI workloads claim
`new_game-v1`. Legacy CLI measurement is unavailable in the reset runner, while
its completed v1 reports remain independently verifiable. Legacy persistent reports retain their
original cross-game cache semantics and cannot represent reset conditions.

Each completed game durably records its opening and assignment identity,
positions, sides, moves, diagnostics, terminal result, wall and CPU time, RSS,
startup/shutdown, condition and manifest digests, and session/segment identity.
The runner writes a temporary file in the destination directory, flushes and
fsyncs it, atomically renames it, and fsyncs the directory before advancing the
completed-game count. An exclusive lock rejects simultaneous runners. On
interrupt or crash, independently verified completed games are reused; unfinished
temporary files do not count. Corruption, duplicate games, missing identities and
changed inputs reject resume. Only all eight verified games produce an atomic
completed report with recalculable aggregates and report digest.

Persistent seats save diagnostics and cumulative CPU differences after each game.
RSS is the absolute cumulative process/segment peak, never a per-game difference
or an independent per-game peak. Segment closure records wait4 CPU and peak RSS
for reconciliation, including enforcement of the RSS cap against the final
segment peak. Persistent reports label completed-game checkpoint aggregates
separately from segment aggregates. Raw wait4 RSS remains separate from sampled
VmHWM. Either peak may be larger, and sampled peaks need not be monotonic.
Both are capped; game RSS
aggregates use the largest available raw observation, including the largest
polling sample retained during a decision. CPU differences remain
monotonic and reconcile against segment CPU totals. Segment totals include process
overhead and measured work in an interrupted game. After process loss, remaining games start from empty caches,
without replaying completed games. The interrupted game is measured again in full.
Session/segment startup and shutdown distinguish resumed segments from one
uninterrupted eight-game process lifetime.

Progress is flushed on stderr using
`progress whole-game stage=<prepare|inputs|measure|aggregate|compare|oracle|verify> condition=<id|none> conditions=<done>/<total> games=<done>/8 status=<measuring|saved|skipped|interrupted|verified|failed> elapsed_s=<value>`.
The completed work unit is one durably saved game; each condition totals eight
games, and the manifest fixes the condition total. Stages without games use
`games=0/8`. The default emits every saved game. `--progress-every N` limits
ordinary progress only; failures, interruptions and completion always flush.
Long-running production measurements remain human-operated.

### Reduced exact-cache correctness verification

The dedicated `exact-cache-verification-v1` manifest and report use exactly
three ordered games: opening-1/assignment-0, opening-2/assignment-0 and
opening-4/assignment-0. They never masquerade as eight-game v1/v2 reports.
Two serial conditions use the same repaired binary, evaluator, host and
12/8/12 depths with experimental exact20; turn remains the production default
and game uses diagnostic opt-in. Each seat has one process per game, acknowledges
`new_game-v1`, and records effective scope and policy. Source, harness, binaries,
artifact, corpus, sample, saved evidence and all output identities are pinned.
Decision timeout is 310 seconds and seat peak RSS is at most 1,572,864 KiB;
there is no node cap. Preparation verifies a clean locked release build against the supplied CLI digest,
records its build receipt, and writes an input-filled human-operated script.
Agents do not launch, wait for or monitor the long measurement.

The saved counterexample and its root/a4/a7 Oracle queries are checked offline
under their original producer identities. A short repaired warm-bound regression
requires root +4 and selected-child +4 without issuing new Oracle queries.
Immutable failed receipts retain their original failure status.

Each completed game preserves legal replay, resets, per-decision diagnostics,
legal counts/phases, raw CPU/RSS observations, wall/startup/shutdown time and
exact nodes/cache/time. Only three completed games produce a condition average.
Turn/game histories, boards, selected moves, scores, depths, exactness and
outcomes must agree. Failures remain evidence and prohibit adoption.

For each completed diagnostic-game sample, select, in order, the first exact
nonterminal root with at most 12 empties, the first with at most 8, and the last
with at most 12. Missing selectors are omitted without substitutes or additional
games. Deduplicate positions in that order: at most three roots per game and
nine roots total. Independently solve each root and its nonterminal selected
child; terminal children use the defined terminal value. Reuse completed queries
only when board, effective side, Oracle binary digest, profile digest and score
contract match. Freeze the ordered actual positions and the number of remaining
queries (including zero) before the Oracle stage. There are at most 18 new
queries, each with a 30-second timeout and 1,572,864-KiB RSS cap, no node cap
and no automatic timeout extension. Unresolved score-contract differences,
incomplete queries, value/selected-child disagreement and resource overruns
are preserved failures. No uniform score offset hides a mismatch.

One game or one query is atomically checkpointed with file and directory fsync
under an exclusive lock. Resume verifies and skips saved success and failure;
only interrupted units restart. Changed identities, unknown/duplicate outputs,
missing raw resources and corrupt derived summaries fail closed before search.
Existing eight-game and 0041 evidence stays immutable; new output uses
`.local/reversi-ai-exact-cache-correctness/`.

Progress flushes on stderr as
`progress exact-cache-verification stage=<inputs|regression|games|oracle|verify> condition=<turn|game|none> unit=<fixture|game|position> done=<n> total=<n> status=<running|saved|skipped|interrupted|verified|failed> elapsed_s=<value>`.
Games total three per condition; Oracle total is the frozen remaining-query
count; regression total is the fixed fixture count. `--progress-every N`
defaults to one and thins ordinary progress only; failures, interruption and
completion always flush. No retries add conditions, games or query positions.

The report separates exact work from whole-game time and identifies the
single-run sample bias. Equal heuristic node counts with different timing do
not prove a cache effect. Unselected exact roots are not independently Oracle
verified. Historical timing retains its original digest/settings and is not a
control for the new binary. Even successful evidence leaves production adoption,
the unresolved score-contract issue and time-budget decisions to 0040 and the
human; experimental exact20 does not authorize changing production exact16.

### Experimental exact-threshold assessment

Thresholds 16, 20 and 24 are separate experimental workloads. Production
reinforcement keeps its 16-empty contract.

Both seats acknowledge empty heuristic and exact tables at each window or game
start. Later roots within that unit may reuse proofs. Turn scope clears the
exact table at each decision; other settings stay equal.

Preparation freezes four distinct legal 24-empty roots from a verified game-8
report. It selects the first two black and first two white roots in
opening/assignment/turn order.

If only one distinct white root exists, preparation adds its first distinct
transform in the fixed order rotate-180, main-diagonal reflection,
anti-diagonal reflection. Each transform preserves the standard initial board
and colors.

The runner stores and legally replays the transformed opening and every history
board and move. It keeps the source root identity and transform name. The two
white windows form a correlated symmetry pair, which the report identifies.

Preparation pins legal source histories, source and harness revisions, binaries,
artifact, openings, host, cache capacity, timeout, RSS and output identities.
It writes a human-operated script and leaves measurement to the human.

Pilot depth is 12/8/12, with no node cap, a 310-second decision timeout
and a 1,572,864-KiB seat peak RSS cap. All six threshold/scope conditions use the
same four roots, for 24 windows total.

Windows end at 12 or fewer empties or legal game-over. Passes stay in the
history and leave the empty count intact. Each window starts with empty caches.
Pilot timing is reported separately from full-depth speed.

Each decision keeps its legal-move count, phase, move, root score, depth,
exactness, outcome, nodes, cache counters, wall/CPU and RSS observations.
Schema-v2 verification requires this decision evidence on every saved step;
legacy optional fields are accepted only for genuine schema-v1 reports.
An unfinished exact attempt is recorded as a failed unit.

Failed units keep partial history and observed resources. The runner verifies
and skips saved failures on resume. It retries interrupted units and verifies
saved completed units before skipping them.

Unknown, corrupt or mismatched evidence stops the run. Unit publication uses
file and directory fsync plus atomic rename under an exclusive lock.

Turn/game comparisons within one threshold require equal positions, seat
histories, moves, scores, depths, exactness and outcomes. Fixed bookless,
single-thread Oracle profiles completely solve each exact root and its selected
continuation. Incomplete or timed-out solves remain failed evidence.

Oracle positions are saved individually, with their total fixed by source
reports. A threshold reaches full measurement only after all four windows in
both scopes match and have complete Oracle evidence.
Failed Oracle receipts also verify every retained query and process observation
against the stage reached, including raw output, command, exit and resource
evidence. A score mismatch preserves independently valid root/continuation
values rather than requiring them to match the project score.

The gate freezes a full-stage manifest with 32 games per admitted threshold,
at most 96. It covers depths 8/12, scopes turn/game and eight games each.
Full search also has no node cap and keeps the pilot timeout/RSS limits.

Threshold-16 controls use the new binary and its pinned identity. Legacy
reports keep their original identities. Averages and improvement ratios require
all eight verified games; failures remain visible in the condition report.

Reports distinguish each seat's first exact root from its later roots. They show
exact node/time changes, whole-game fractions, phase depths and legal-move counts.

Per-decision CPU samples use process-counter differences and process peak RSS.
The raw sampled VmHWM and final wait4 RSS are separate observations; either may
be larger. Sampled VmHWM need not be monotonic. Each raw peak is checked against
the cap, and the unit RSS aggregate is their maximum, including the largest
polling sample retained during a decision. CPU counters retain their
monotonic and wait4 reconciliation checks.

If Oracle exits between a nonblocking wait and a live RSS sample, the runner
rechecks wait4. If the kernel reports an exiting process before wait4 can reap
it, the runner retains that raw exit observation and polls until the existing
deadline. It accepts only status zero and final resources within the cap.
Missing RSS from a process without an observed exit remains a failure.
Receipts retain the exit status;
stdout and resource data alone do not recover a failed historical receipt
whose exit status was not recorded.

A harness correction may import saved pilot units through an explicitly pinned
source manifest and unit files. Binary, source, artifact, host, roots, caps and
search conditions must match. Each source unit is independently verified;
the new receipt retains its source digest and changes only manifest binding
and recalculated resource aggregate. Source files remain immutable.

Reports limit their claims to the measured run and state the lack of repeats.

Plan 0040 leaves adoption to the human. Raising production thresholds needs a
separate specification/manifest update.

Progress is flushed on stderr as
`progress exact-threshold stage=<pilot|full|oracle|verify> threshold=<16|20|24> scope=<turn|game> unit=<window|game|position> done=<n> total=<n> status=<running|saved|skipped|interrupted|verified|failed> elapsed_s=<value>`.

Stage manifests fix the totals. The default emits every completed unit.
`--progress-every N` limits ordinary updates; failure, interruption and stage
completion always flush.

Long measurements are started by a human. Agents leave startup, waiting and
monitoring to the human.

### SearchEngine

Wrapper around `Negascout` managing the transposition table and Zobrist keys.

```rust
struct SearchEngine {
    tt: TranspositionTable,
    exact_table: ExactTable,
    zobrist: ZobristKeys,
    context_fingerprint: Option<u64>,
}
```

- `SearchEngine::new()` — Create with default TT capacity (~1M entries).
- `SearchEngine::search_with_budget<E: BoardEvaluator + ?Sized>(board: &Board, color: Color, evaluator: &E, config: &AiConfig, budget: &SearchBudget)` — Run iterative deepening search within the supplied budget. Returns `SearchResult`.
- `SearchEngine::clear_tt()` — Clear both heuristic and exact tables.
- `SearchEngine::new_game()` — Clear both tables and discard the prior search context before acknowledging a new game.
- `SearchEngine::clear_exact_cache()` — Clear only the exact table for diagnostic turn-scoped comparison.

### SearchBudget

```rust
struct SearchBudget {
    deadline: Instant,
    node_limit: Option<u64>,
    cancellation: Option<Arc<AtomicBool>>,
}
```

- The deadline is monotonic and is the primary turn budget. `SearchBudget::with_time_limit` creates it from the current monotonic clock. A duration beyond the platform deadline range becomes an immediate deadline.
- `node_limit` is an optional secondary, deterministic ceiling for tests, CI, corpus, and tuning runs. A fixed node limit must reproduce the result metadata, PV, and completed depth for the same search context.
- `SearchBudget::with_node_limit_only` supplies that fixed ceiling without a
  wall-clock deadline for diagnostics and tests. Product callers use a
  monotonic deadline through `with_time_limit`.
- `cancellation` is an optional, cloneable token owned by the caller. Another thread may set its `AtomicBool`; the search only reads it and owns no callback or worker.
- Search polls all three limits during expansion. Reaching a deadline or node limit, or observing cancellation, interrupts the current iteration.

### SearchResult

```rust
struct SearchResult {
    outcome: SearchOutcome,
    score: Option<i32>,
    pv: Vec<Position>,
    leaf_eval: Option<EvalResult>,
    completed_depth: u8,
    nodes_searched: u64,
    elapsed: Duration,
    exact: bool,
}

enum SearchOutcome {
    Move(Position),
    Pass,
    GameOver,
}
```

- A state without a legal move returns `Pass` when the opponent can move and
  `GameOver` otherwise. It never exposes a sentinel `Position`. A root
  `GameOver` returns the terminal score from the root side's perspective in
  both heuristic and exact search, with an empty PV and no `leaf_eval`.
- Terminal scoring applies at the root and within search, before a heuristic
  depth-zero evaluation. If one color has no discs and the other has at least
  one, the winner scores `+64` and the loser `-64`, regardless of empty squares.
  All other terminal positions use the difference between the discs actually
  on the board; an empty board scores `0`. `Game::score()` continues to report
  the actual disc counts for display.
- For a legal-move state, search selects a legal root fallback before deeper work. If interrupted before depth 1 completes, it returns that fallback, an empty PV, no score or leaf evaluation, `completed_depth = 0`, and `exact = false`.
- After each wholly completed depth, the result atomically advances to that
  iteration's move, PV, score, and leaf evaluation, including a missing
  `leaf_eval` when the completed line ends at a terminal position. A partial
  iteration is never returned or stored as the completed PV.
- Heuristic iterative deepening always reports `exact = false`, including when
  its configured maximum depth completes. `exact = true` is reserved for a
  completed final-disc proof from the endgame solver.

### Exact endgame solving

- At or below `AiConfig::exact_solver_empty_squares`, `SearchEngine` uses the
  shared, evaluator-independent endgame solver instead of heuristic iterative
  deepening. The default threshold is 16 empty squares. The representative
  16-empty-square oracle-checked fixture must complete within 1,000,000 solver
  nodes; this is a profile evidence ceiling, not a replacement for a caller's
  deadline, node limit, or cancellation token.
- A completed endgame result has `exact = true`, its `score` follows the
  terminal scoring rule above from the root side's perspective, and its PV
  contains only played positions (a pass is represented by
  `SearchOutcome::Pass`, never by a sentinel position).
- The solver handles forced passes without consuming an empty square and
  returns `GameOver` only when neither side can move. A terminal endgame score
  is exact.
- Exact search tracks the remaining empty squares and their orthogonally
  connected regions. A placement removes one square and updates region
  membership even when that removal splits a region; a pass leaves both
  unchanged. When a transposition move is supplied, ordering places it first;
  otherwise it favors odd regions, then uses the established secondary order
  and deterministic equal-score choice. Exact search currently supplies no
  transposition move so cache probes cannot change equal-score choices.
- With one through four empty squares, the solver uses bounded scalar search
  for legal placements and forced passes. It returns the same root-side terminal
  score and complete played-move PV as the general exact search,
  including when both sides have no move before the board fills. Larger
  positions use the general exact path.
- Every recursive exact search invocation, including a scalar position or
  pass, checks the same deadline, cancellation, and node ceiling before
  consuming one searched node. A terminal root returned without recursive
  search keeps the existing zero-node behavior. An interrupted scalar search
  cannot publish a partial exact score or PV.
- Exact endgame cache entries are private to the solver and are never read as
  heuristic transposition-table entries. Heuristic TT entries must likewise
  never cause `exact = true`.
- If the supplied `SearchBudget` interrupts an endgame solve, the result keeps
  the legal root fallback or the last wholly completed result, has `exact =
  false`, and exposes no partial PV or partial exact score.

## Explanation

### ExplainTag

```rust
enum ExplainTag {
    CornerGrab,
    CornerSetup,
    MobilityGain,
    StabilityGain,
    EdgeControl,
    ParityAdvantage,
    PieceAdvantage,
    ForcedMove,
    ExactEndgame,
}
```

### MoveExplanation

```rust
struct MoveExplanation {
    best_move: Position,
    pv: Vec<Position>,
    score: i32,
    factors: EvalFactors,
    primary_reason: ExplainTag,
}
```

### Explanation Generation

1. Search produces `SearchResult` with PV and `leaf_eval`.
2. Evaluate the current position to get `current_factors`.
3. Compute factor deltas: `leaf_eval.factors - current_factors`.
4. The factor with the largest positive delta becomes `primary_reason`.
5. Special cases:
   - If only one legal move exists: `ForcedMove`.
   - If best move is a corner: `CornerGrab`.
   - If best move is adjacent to a corner and PV leads to corner take: `CornerSetup`.
   - For an exact endgame result, show its root-side terminal score under the
     rule above and PV with `ExactEndgame`; do not derive a heuristic-factor
     delta.

- `generate_explanation(board: &Board, color: Color, search_result: &SearchResult, evaluator: &dyn BoardEvaluator)` — Returns `MoveExplanation`.

## AiPlayer Facade

```rust
struct AiPlayer {
    evaluator: Box<dyn BoardEvaluator>,
    config: AiConfig,
    engine: SearchEngine,
}
```

- `AiPlayer::new(evaluator: Box<dyn BoardEvaluator>, config: AiConfig)` — Constructor.
- `AiPlayer::think(&mut self, board: &Board, color: Color, budget: &SearchBudget)` — Run search and return `SearchResult`. Requires `&mut self` due to TT mutation.
- `AiPlayer::explain(&mut self, board: &Board, color: Color, budget: &SearchBudget)` — Run search and return `Option<MoveExplanation>`. It returns `None` when search has no move or no completed evaluation. Requires `&mut self` due to TT mutation.
- `AiPlayer::evaluator_name(&self) -> &str` — Returns the name of the current evaluator (e.g. `"strategic"`, `"novice"`).

## External Oracle Analysis

The project uses a pinned Egaroucid Console build as a development and
evaluation oracle. It is an external tool, not an AI engine dependency:

- No Rust source file may link to, invoke, or embed Egaroucid.
- `reversi-ai`, `reversi-engine`, and `reversi-godot` remain buildable without
  downloading or installing the oracle.
- The oracle executable and its mutable resources/cache are kept outside the
  checkout and are absent from product, GDExtension, and release artifacts.
- Make targets, scripts, and CI may use the oracle to play matches against a
  project AI, to provide an evaluation opponent, and to score a project AI's
  selected move.

The versioned corpus and normalized report use the following wire contract:

- A board is a 64-character row-major string from `a1` through `h8` using `B`,
  `W`, and `.`. `side_to_move` is `B` or `W`.
- `legal_moves` is the complete legal move set in canonical coordinate order
  (ASCII ascending, e.g. `a1`, `a2`, ..., `a8`, `b1`, ..., `h8`).
- `phase` is `opening` for 4–20 stones, `midgame` for 21–44 stones, and
  `endgame` for 45–64 stones.
- `outcome` is `MoveSet` with the legal moves, `Pass` when the side to move
  has no move but the opponent does, or `GameOver` when neither side can move.
- `provenance` identifies how the position was produced and is retained in
  every normalized report.
- Before `-solve`, the adapter converts each query to Egaroucid's
  current-player-relative `X`/`O`/`-` alphabet and appends `X` for the side to
  move, while preserving the canonical `a1` through `h8` cell order.

An oracle analysis reports one record for each legal root move and derives the
full equal-value `optimal_moves` set. Scores are signed Egaroucid search values
from the root side's perspective; when `exact` is true, the value is the final
disc difference, while an incomplete search value is heuristic. A project AI's
selected move may be included as `selected_move`; its `selected_value` is the
corresponding oracle value and `regret` is `best_value - selected_value`. Each
selected/root evaluation contains `completed_depth`, `nodes`, `elapsed_ms`, and
`exact`. `exact` is true only when the reported depth reaches all remaining
placements under Egaroucid's search-depth convention, rather than when the MPC
probability merely reaches a threshold. The pinned Egaroucid search does not
decrement this depth for a forced pass. A move
in `optimal_moves` has zero regret and is an agreement even if it is not the
oracle's displayed first move. The versioned golden projection may omit
`elapsed_ms` (and other runtime-only fields) but retains all score, move, depth,
node-count, and exactness data. The solve parser requires exactly one expected
table header and one terminal `total` summary; its node count and NPS must
match the row aggregates, and its elapsed time must match them within the
oracle's six-significant-digit formatter rounding.

The adapter must fail closed on a missing or hash-mismatched oracle, a modified
cached source or binary, a process timeout, unexpected output, malformed
board/corpus data, or an incomplete root-move set. The expected source digest is
derived from the verified archive rather than from a mutable cache manifest;
the executable is rebuilt from that verified source before use. The adapter
must not pass the oracle's ignored time-limit option; the wrapper process
timeout is the only wall-clock safety limit.

### Versioned strength profiles

`strong-engine-hcap-v1` is the reproducible calibration profile. Every oracle
analysis and match report serializes the complete profile object alongside the
pinned source digest. It fixes Egaroucid Console v7.8.1, source digest,
bookless operation, one thread, hash level 25, no evaluation override, and no
oracle time-control argument. A subprocess timeout is only a safety failure
boundary, never a fairness budget.

Its Egaroucid fixed-depth, 100%-probability ranges are move numbers 1--41 at
depth 8 and 42--60 at depth 12. An Egaroucid move number is `occupied_discs -
3` in the decision position before the move, so the latter range starts at 45
occupied discs. The adapter must reject a legacy numeric-level response when a
custom-depth response is required, and must reject any mismatch of the profile,
source, book/eval setting, hash/thread setting, corpus, or report metadata.

The candidate half of `strong-engine-hcap-v1` uses heuristic depth 12 for every
non-exact decision position (including the opening and the 17--19-empty-square
interval), starts exact solving at at most 16 empty squares, and accepts a
caller-owned monotonic deadline. An optional node ceiling is a deterministic
tuning or CI limit, not the production fairness budget. Interrupted exact
searches retain only a legal fallback or wholly completed result, with
`exact = false` and no partial exact score/PV.

The profile is a calibration baseline, not proof of the final strength target.
That target must be evaluated separately on a declared held-out,
color-swapped, opening-rotated suite and report `wins / all games >= 0.50`
separately from match points (where a draw is 0.5), with a sample-size and
confidence rule. `ci-smoke-v1` remains a distinct small, bounded profile and
cannot be used to assert calibration or final strength.

## GDScript Bridge Additions

Added to the existing `ReversiGame` GDScript class:

```gdscript
# AI setup
game.set_ai(evaluator_name: String, opening_depth: int, midgame_depth: int, endgame_depth: int) -> bool
# evaluator_name: "strategic" or "novice"
# Returns false if evaluator_name is unknown
game.ai_think_with_budget(time_limit_millis: int, node_limit: int) -> Vector2i
# Returns (-1, -1) for Pass, GameOver, or no AI. node_limit <= 0 disables the node cap.

# AI move
game.ai_think() -> Vector2i
# Returns best move (row, col). Returns (-1, -1) if no AI is set or game is over.

# AI explanation
game.ai_explain_move() -> Dictionary
# Returns:
# {
#   "best_move": Vector2i,
#   "pv": Array[Vector2i],
#   "score": int,
#   "primary_reason": String,   # ExplainTag as lowercase string
#   "factors": {
#     "corner_control": int,
#     "stability": int,
#     "mobility": int,
#     "edge_control": int,
#     "parity": int,
#     "piece_count": int,
#   }
# }
# Returns empty Dictionary if no AI is set or game is over.
```
