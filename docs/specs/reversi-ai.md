# Reversi AI Specification

## Overview

Reversi AI engine providing pluggable evaluation strategies, Negascout search with iterative deepening, and move explanation. Lives in the `reversi-ai` crate, depends on `reversi-engine`.

## Evaluation

### Winner-empty score migration (current contract)

This section supersedes the legacy raw-disc-difference contracts below. New AI
search and training use `score_contract="winner-empty-v1"`. For a terminal
board with neither side able to move, let `d = own - opponent` and
`empty = 64 - own - opponent`; return `d + sign(d) * empty` from the queried
side's perspective. Draws and the empty board return zero, wipeouts return
±64, and full-board scores equal the physical disc difference. Exact and
heuristic terminal leaves, root/child values and legal pass/PV propagation
share this formula. Minimax rankings and PVs may change; old root values must
never be relabelled or corrected by a constant.

Physical `Board::count`, `Game::score`, Godot/UI scores, `disc_counts`, random
game `black`/`white`, and whole-game physical `score_black` retain actual disc
counts. Feature extraction/catalog, 64 features, 60 phases, bounds ±64,
normalization divisor 64, defaults/presets and turn-cache policy remain fixed.

New identities are mandatory and inconsistent combinations fail closed:

| Surface | Identity |
| --- | --- |
| Search/Advisor | semantics 2, `project-ai-advisor-v2`, score contract in context |
| Training | `reversi-ai-pattern-training-v2`, manifest/record schema2, target `winner_empty_v1_for_side` |
| Artifact/features | format2, `score_scale="winner_empty_v1"`, explicit score contract, trained runtime2 |
| Reinforcement | `reversi-ai-pattern-reinforcement-v4`, manifest6, game/report/checkpoint4 |
| Random inputs | `reversi-ai-random-inputs-v2`, `project-owned-random-games-v2`, manifest/output/game/record2 |
| Oracle | golden/analysis2 with score contract; corpus1 stays unchanged |
| Whole game | `reversi-ai-whole-game-v4`, manifest2, report4, evidence2 |
| Threshold/cache | `exact-threshold-assessment-v2`, `exact-cache-verification-v2`, new query/receipt contract |

New provenance validates the version-specific trainer/optimizer pair. Runtime
CLI/Godot reject format1 artifacts. Legacy Python artifacts, records and
evidence are accepted only through explicit `--legacy-offline` validation;
reinforcement run/regret-command/regret-timeout accept manifest6 only.
Legacy manifest3 retains no-policy shape; manifest4/5 retain turn policy and
manifest5's flexible settings. Their report/checkpoint3 and raw-disc training
targets retain their original semantics, including no solver wipeout rewrite.
Producer, schema, contract, scale, CLI SHA and source digest mismatches are
errors, even after a digest is resealed. Random v1 verification requires its
frozen source snapshot/commit, never replacing its source digest with new code.

Legacy golden/reference/data/receipts remain immutable offline evidence;
version-specific projections reproduce the original terminal formula and
preserve failed/incomplete status. New terminal-child validators independently
use winner-empty. Tiny new fixtures are separate files. Root minimax/golden
values cannot be migrated from terminal metadata alone. Any future data
migration writes a separate directory, records original digests and mapping,
and derives labels from a verified legal replay's terminal board.

Engine migration does not lift production freeze: 0040 independent root/child
correctness and resource-response gates, human configuration/performance
judgment, 0037 pilot, 0019 new baseline/validation/candidate cycle, and 0018
handicapped Oracle acceptance remain separate. `strong-engine-hcap-v1` stays
12/12/12 with exact16. Production regeneration/retraining, long Oracle solves,
game-cache adoption, default20 and strength claims are not migration evidence.

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
- A trained pattern score predicts the requested color's winner-empty terminal
  score. It is an integer in inclusive range `-64..=64`. Accumulation
  is deterministic integer arithmetic and an artifact is rejected when any
  contribution, declared aggregate bound, or checked aggregate cannot satisfy
  that range without overflow.
- A weight artifact is immutable and identifies its format version, catalog
  digest, phase definition, winner-empty score scale and contract, safe source
  provenance, and weight digest. Provenance may name a reproducible trainer,
  input-manifest digest, and licenses; it must not embed private input data.
  Its catalog, phase, scale, version, and weight identity are score-affecting
  context and therefore enter the future evaluator's
  `context_fingerprint()`.

Pattern scores have no human-factor attribution and must not be combined with
the explanatory evaluator or its explanation path.

### Trained evaluator runtime

現在採用する学習済みモデルは、0019 run `0019-20261020-02`のselected candidateとする。
artifact path・digest・独立検証・採用境界は[現行モデル記録](../references/reversi-ai-0019-adopted-model.md)に固定する。
これは0018の最終勝率受け入れとは別のモデル採用である。

`TrainedEvaluator` loads only the canonical JSON artifact emitted by the
project-owned training tool.  Loading validates the complete feature contract,
safe non-empty provenance, all 64 feature bounds, the sparse 60-phase table
shape and canonical decimal codes, every weight and aggregate score bound, and
the SHA-256 `weight_digest` and `artifact_digest` identities.  A load or
validation failure is a clear error; it never selects a fallback evaluator.

The evaluator sums the 64 sparse entries selected by `extract_features()` for
the board phase and requested color, returning a winner-empty prediction
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

- A version-2 input record is JSON Lines and states its score contract, record id, source id,
  SPDX license, source digest, 64-character row-major `B`/`W`/`.` board,
  side (`B` or `W`), winner-empty target for that side, and one of
  `train`, `validation`, or `held_out`. Optional candidate positions state the
  same board, side, and target fields and permit move-quality measurement.
  Targets are finite integers in `-64..=64`; the only accepted target semantic
  is `winner_empty_v1_for_side`. Version-1 raw-difference records remain legacy offline evidence.
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

### Frozen optimizer comparison (0052)

This section records the original 0052 training comparison and remains the
contract for verifying its immutable historical output. New comparisons and
reevaluations of a saved Adam candidate follow the match-led contract below.

The offline `pilot.py optimizer-compare` entrypoint compares the original
`bounded_td_v1` update (A) with `project_adam_v1` (B), starting from the same
0019 initial baseline, never from the adopted candidate. It has prepare, run
and verify operations and a matching Make entrypoint. Preparation pins the
completed 0019 manifest/report/all phase receipts, 0051 bundle/receipt, source
teacher rows, validation and held-out records, baseline/adopted artifacts,
candidate executable and Oracle identities. Source roots are read-only.
Only project-owned self-play terminal winner-empty targets become teachers;
external games, scores, weights and acceptance-0018 inputs are excluded.
Production requires exactly 3,364 teacher rows and 13,401 validation rows.
Validation and held-out are reconstructed with the original exclusions and
checked against teachers by canonical absolute-color D4 board and side keys.
Empty or overlapping splits fail closed. Original/admitted rows and excluded
keys retain source/game/score-perspective provenance. A must reproduce the
adopted candidate's weights and weight digest before B may start.

B uses f64 weights and zero-initialized Adam m/v/global step, MSE averaged over
each batch, gradient `sum(2*(prediction-target)/batch_rows)` for each active
parameter, bias correction, and projection to [-1,1] after every step.
Defaults are learning rate .01, beta1 .9, beta2 .999, epsilon 1e-8, L2 0,
batch 256, seed 20261025, at most 20 epochs, patience 5. Learning rate, batch,
epochs, seed, patience and per-decision timeout are explicit operator controls.
Feature extraction occurs once in stable row order; each epoch uses a
deterministic shuffle. Unseen weights retain their baseline values. Each
epoch exports sparse format2 integers with half-away-from-zero rounding;
zero entries are omitted and each feature bound remains one (aggregate 64).
The explicit new trainer/provenance is validated by Python and Rust without
claiming the legacy optimizer identity. Non-finite state or invalid bounds
fail closed. Integer validation MSE selects the earliest best epoch; patience
counts epochs without strict improvement. Float checkpoints, optimizer state
and integer artifacts have separate digests.

Receipts cover prepare, input revalidation, control reproduction, optimization,
integer selection, matches and offline verification. Every completed batch and
epoch boundary is an atomic checkpoint containing weights, m/v, step, epoch,
shuffle/RNG state, next cursor, best epoch and patience. Resume verifies prior
phase outputs and restarts only unfinished work; changed learning settings
require a new attempt. Failure preserves completed checkpoints and diagnostics.
Progress is `optimizer-compare phase=... epoch=E/Emax batch=B/Btotal
games=G/Gtotal elapsed_seconds=S`; batch interval defaults to 10 and is
selectable with `--progress-every`. Phase boundaries and completed games always
emit progress. The requested epochs, maximum batch and game counts are printed
before execution. Limits are 20 epochs, 3,364 teachers and 20 games per match.

Reports record A/B training seconds, phase counts, changed/nonzero/saturated
weights, float and exported train/validation MSE and parameters whose changes
disappear in rounding. Held-out is fixed before optimization and evaluated
only for final selection, never for tuning. If exported validation MSE does
not strictly beat A, matches are `not-run` with a reason and zero completed
games. Otherwise B plays adopted A on ten unused, disjoint openings with
swapped colors (20 games), both bookless 12/12/12, exact16, turn cache,
300000ms/10000000 nodes. Only B match points >10/20 unlock at most 20 Oracle
games with separate new openings. Oracle is the pinned 0019 Egaroucid 7.8.1
binary/source with `oracle-0018-acceptance-v1` (6/6/6, exact12, no book,
one thread, hash25). Effective timeout and both executable SHA-256 identities
are frozen before each attempt. The existing twelve-position saved corpus
golden is diagnostic only. Improvement requires strict exported validation
improvement, final held-out MSE and corpus mean regret within 10% of A
(zero must remain zero), and B match points >10/20. Skipped games are never
counted as completed. No result automatically replaces the adopted model or
claims general strength or 0018 acceptance.

A human starts long-running comparisons. Agents do not start or monitor them.
Offline verify launches neither training, candidate CLI nor Oracle: it
reconstructs artifacts, metrics, gates and verdict from saved immutable
inputs/state/outputs and rejects tampering. Tooling/fixture verification and
human production comparison are recorded separately; 0052 stays active until
the completed human outputs have been independently verified and their result
and next decision recorded, including a valid negative result.

### Match-led evaluation of a completed 0052 run (0053)

The completed 0052 optimizer run remains immutable historical evidence. Its
existing report and `not-run` comparison result are not rewritten. A separate
evaluation attempt may reuse its selected Adam candidate without rerunning the
trainer, teacher generation, or epoch selection. Preparation requires a
completed 0052 run and a new, empty evaluation root, and revalidates the source
manifest, report, candidate artifact, adopted baseline, and pinned executable
and Oracle identities. The new manifest pins the complete source-run digest and
candidate artifact digest. Missing or changed inputs fail closed with the
identity that needs repair or rebuilding.

Validation MSE, held-out MSE, and corpus regret remain reference diagnostics;
they never skip the candidate-versus-baseline match. The first stage always
plays 20 games on ten unused opening pairs, with candidate and baseline
switching seats within each pair. At 10/20 match points or higher, an explicit
operator continuation may add 180 games on 90 more pairs in the same attempt.
At 9.5/20 or lower, the attempt stops after 20 games. The 100-pair opening
plan is frozen before play; all pairs are disjoint from training teachers,
validation, held-out, corpus, 0018 acceptance, and Oracle openings. Every game
records its timeout, opening, participant artifact and executable identities,
and seat. Completed games and the 20-game receipt are immutable. Resume accepts
only the verified contiguous prefix with identical settings and digests; a
settings change needs a new evaluation root.

The 200-game result is improved only when the candidate scores strictly more
than 100 match points. Exactly 100 is not an improvement. Only a completed
result above 100 points permits the operator to run the separate 20-game
Oracle diagnostic, using the pinned Egaroucid 7.8.1 binary/source and
`oracle-0018-acceptance-v1` profile (6/6/6, exact12, no book, one thread,
hash25). Oracle openings are disjoint from every other match. Its wins, losses,
draws, points, and compared identities are diagnostic only; they do not decide
0018 acceptance.

The evaluation report preserves source validation/held-out MSE and corpus
diagnostics, reports each baseline-match stage and its continuation decision,
and reports Oracle outcomes or the exact reason they were not run. It does not
automatically adopt the candidate, claim general strength, or change the
historical 0052 report. `optimizer-compare evaluate prepare|run|verify` is the
explicit evaluation-only interface. `prepare` and `verify` are offline;
`run` is human-operated and supports an explicit continuation to 200 and an
explicit Oracle diagnostic. Offline verification reconstructs the report and
gates from saved inputs, openings, identities, receipts, and completed games;
it starts no trainer, candidate CLI, or Oracle process.

### Bounded pattern reinforcement cycle

New production baseline and validation inputs must be generated from complete,
legal, project-owned random games under a frozen version-2 generator manifest.
It pins the exact producer checkout commit, its merged-main base commit, SHA-256
for the generator and both imported game/training modules, `CC0-1.0` provenance,
master seed, game-id lists for `train`, `validation`, and `held_out`, and the
record start placement and turn cap. A SHA-256-derived per-game seed and a
separate seeded split shuffle give independent, repeatable streams. Each move
is selected uniformly by index from sorted legal moves; a pass occurs only
when no move exists. A game must reach the actual terminal board within its
turn cap. Its complete log records moves, passes, terminal disc counts and a
digest. Every emitted nonterminal record has the final winner-empty score
signed for its side to move, including games ending in an early wipeout.

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

The historical version-3 reinforcement contract uses an immutable manifest
(new prepare/run use schema6 as defined under Explicit search settings below).
It records the baseline artifact identity and SHA-256, candidate executable
SHA-256, trainer and update-rule versions, feature contract, trained evaluator,
all three search depths, exact-solver threshold, disabled book, self-play and
match limits, D4/color-pairing policy, per-decision timeout, maximum decisions,
and an actual random seed. These identify the method and the compared inputs;
the producer source commit and reproducing the generated openings from a seed
are not acceptance gates. Version-1 and version-2 manifests and reports are never evidence
for version-3 candidate selection, although version-1 and version-2 baseline artifacts remain
valid inputs to that historical producer only. Version-3 pins `reset_contract` with protocol `new_game-v1`,
cache lifetime `one-game`, and the same candidate executable SHA-256. Prepare
checks a control acknowledgement without playing a game. Every self-play and
candidate-match game resets each participating player before any move; its
record preserves the game ID and acknowledged reset events. Offline
verify rejects a missing contract, an unsupported manifest, mismatched binary identity,
or missing per-game reset evidence. Version-1 and version-2 trained artifacts
remain usable baselines in explicit legacy offline verification, and the frozen
artifact loaders accept version-3 reinforcement provenance. New runtime and
prepare/run require format2 and current producer identities.

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

### One-command 0019 production execution

The production path is one human-operated `pattern-reinforcement-execute`
invocation implemented by extending `pilot.py execute`. It consumes the
verified 0051 bundle and its successful `bundle-verify` receipt using the
current verifier, without requiring the producer checkout or matching active
code to producer source hashes, including the Oracle preparation receipt's
producer digest. It verifies the bundle, receipt, candidate CLI, baseline,
corpus, golden, validation, and held-out artifacts by digest and semantic
consistency; the Oracle source archive, saved runtime identity, and raw evidence
remain validated. Producer commits and source hashes remain provenance
metadata only. The command records the execution checkout's commit
(`git rev-parse HEAD`) in the run manifest, along with executable identities,
baseline artifact, validation input, search and update settings, seed, resource limits,
pairing rules, and requested game counts. Its run root is a new absolute path
outside the source checkout. The command refuses to replace an existing run
root. `pattern-pilot-execute` retains its bounded pilot counts and behavior.

The production Make defaults are 64 self-play games, 200 baseline-comparison
games, and 20 direct Oracle-match games. Their Make variables are
`REINFORCEMENT_SELF_PLAY_GAMES`, `REINFORCEMENT_COMPARISON_GAMES`, and
`REINFORCEMENT_ORACLE_GAMES`. Counts must form complete color-swapped pairs,
with caps of 64 self-play, 200 comparison, and 200 Oracle-match games; the
production Oracle-match count must be positive. The immutable manifest records
initial requested counts; phase receipts and the final report record actual
counts, including the 50-game early-stop result. Each pair uses legal openings with the
declared D4 rotation and color swap; every game, decision, pass, terminal
score, failure, and digest is retained. A timeout, malformed response,
resource-limit breach, illegal move, or incomplete pair fails the cycle.

The command runs `input-verification`, `self-play`, `candidate-update`,
`baseline-match`, `candidate-selection`, `corpus-regret`, `oracle-match`, and
`offline-verification` in that order. It verifies and records each phase's
outputs before moving on. A failed or interrupted attempt is retained but
cannot produce a candidate report. The final report is published only after
offline verification succeeds and includes the selected and baseline artifact
digests, all input identities, requested and completed counts, match results,
validation metrics, corpus regret, and 0019 exposure keys. Selection uses the
predeclared baseline-versus-candidate match gate; a tie or failed gate selects
the baseline. Validation remains disjoint from self-play tuning and 0018
openings and does not become a substitute for the match gate.

`--resume-from PHASE` accepts only the phase names above. The immutable
schema version 2 manifest identifies the original inputs and initial settings;
it remains readable without migration. Each new attempt records its phase,
resume source, effective settings, input identities, predecessor receipt digests,
and the actual clean checkout commit (40 lowercase hexadecimal characters) in
`provenance.json` before expensive work. A different clean commit is allowed.
Missing or invalid commits and dirty checkouts are rejected before execution.
Receipts and failure records bind this provenance and all partial outputs by
digest. Prior attempts and the manifest are never rewritten.

Operators choose timeout, resource limits, progress interval, seed and counts
at invocation time. Retained predecessor outputs are verified using their own
settings and commit, receipt digests and semantic replay. A change affecting a
retained predecessor requires resuming from the earliest affected phase; input
identity changes require a new run root. Offline verification checks the entire
receipt dependency chain and failed-attempt digests, and exposes per-phase
settings/commits and per-game Oracle provenance in the final report.

An Oracle retry validates the immediately preceding failed attempt and carries
only its contiguous completed game prefix. Game, pair and member numbers remain
global; the interrupted game restarts at its opening with the new timeout.
Each carried game retains its originating attempt, commit, settings, input
identities and game digest in a separate provenance record. Legacy schema
version 2 attempts derive this information from their original manifest.
Invalid, missing, duplicated or out-of-order games end the reusable prefix;
subsequent games are replayed. The new attempt produces a complete game list
and report; the old failure and partial output remain unchanged. This includes
human run `0019-20261020-02` and its seven completed Oracle games. Starting,
resuming and monitoring production runs remain human-operated.

The direct Oracle match runs the raw updated candidate whether or not it is
selected, against `oracle-0018-acceptance-v1`: Oracle 6/6/6 with exact solving
from 12 empty squares, and project candidate 12/12/12 with exact solving from
16 empty squares. Both executable and search profiles are pinned. The Oracle
uses one thread, hash 25, and no book. Each color-swapped pair has one
predeclared legal opening kept disjoint from training, validation, corpus, and
0018 held-out exposure. The report records configured depths and exact
thresholds, actual completed depth and exactness for each decision, wins,
draws, losses, match points, and opening/decision/terminal exposure keys.
This match is diagnostic and does not replace 0018's acceptance gate.

All phase and completed-game progress is flushed to stderr and excluded from
manifests, reports, records, and digests. Stage boundaries use
`stage NAME start elapsed=S.s` and
`stage NAME done stage=S.s elapsed=S.s`. Completed game lines include the
phase, pair and member, `N/total`, per-game elapsed time, and cumulative
elapsed time. `--progress-every` defaults to one and accepts a positive
interval; the final completed game is always reported. The manifest and
outputs, rather than progress output, establish completion.

Before handing the production command to a human, the summary gives a
pilot-grounded core-cycle estimate for the manifest's self-play and
baseline-comparison counts, separately measures representative positions
under the pinned Oracle-match profiles, and reports the Oracle-stage and
combined estimate. These are projections, not runtime guarantees. A human
starts the production command in a separate terminal. An AI agent may prepare
the immutable inputs and validate completed outputs, but does not start,
wait for, poll, monitor, or claim completion of the production run.

The Oracle runtime projection measures the first frozen Oracle-match opening,
an ordinary midgame target at 30 occupied squares, and a late-game target at
48 occupied squares. A target reached before game end uses that exact legal
position. If deterministic replay ends before a target, the projection uses
the most advanced nonterminal position reached from that opening where the
side to move has a legal move. It never measures a terminal board. Each
representative measurement in `representative_searches` reports
`requested_occupied_count` and `actual_occupied_count` alongside the existing
`opening`, `midgame`, or `endgame` phase and Oracle/candidate timings. The
opening's requested count is its frozen occupied count. Forced passes change
the side to move without advancing the occupied count. Failure to obtain a
legal position for any representative stops the estimate before starting any
Oracle or candidate search. Representative selection does not mutate the
frozen opening or change the three measured profiles.

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
and elapsed time. New records explicitly include `score_contract` and
`search_semantics_version=2`; old profiler samples retain their original
binary identity and must not be relabelled as winner-empty evidence.

The move-only CLI retains its stdout protocol and existing
`search_diagnostic_v1` fields. It additionally writes
`score_contract_v1<TAB>position_id=ID<TAB>score_contract=winner-empty-v1<TAB>search_semantics_version=2`
to stderr for each search. New benchmark queries require that matching identity.

The deterministic comparison projection excludes elapsed time and requires
the same outcome, score, PV, completed depth, nodes searched, and exact flag
for a repeated run in the same search context. Elapsed time is a supplemental
same-host release-build measurement only. The profiler is neither game code
nor an oracle candidate protocol and does not change the public move-only CLI.

`--node-limit` remains the required, deterministic diagnostic mode. Its JSON
record retains its deterministic fields and adds the score identity. `--time-limit-ms` is a
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

Fresh reinforcement manifests may explicitly select a self-play search profile
independently of candidate matching and 0018 acceptance. The selected profile
for preparing TrainedEvaluator self-play is `8/8/8`, exact threshold 16, with
the production `turn` exact-cache policy. The `strong-engine-hcap-v1` candidate
profile and its match/acceptance conditions remain `12/12/12`, exact16. This
choice does not change global defaults or reinterpret earlier manifests.
The version-6 production manifest and version-4 report identify the selected
self-play depths, exact threshold, cache policy, and executable SHA-256.
`prepare`, `run`, and `verify` reject mismatched identities. Heuristic
positions at different depths are different workloads. A schema-v4 report must
explicitly record its evaluator, opening/midgame/endgame depths, and game sample;
verification rejects a missing identity field instead of supplying a default.
The efficiency sample has no per-decision search-time or node-count budget, so
each configured search depth can finish. Its 600-second per-decision protocol
timeout is a separate watchdog for a stalled response.

Before starting the larger TrainedEvaluator learning batch, measure the
selected search profile with `StrategicEvaluator` and the current whole-game
producer. This measurement targets the shared search engine and game harness;
it does not benchmark TrainedEvaluator artifact loading or claim a trained
model's playing strength. StrategicEvaluator supplies a directional heuristic
for search and has comparable per-position evaluation cost, so no separate
TrainedEvaluator weight JSON passed with `--trained-artifact` is required.
Measure the fixed eight-game sample (four openings, both seat assignments) to
completion and report its arithmetic mean and nearest-rank P95. The mean goal is 180 seconds; P95 reaching 300 seconds is a signal to
consider search optimization. These are whole-game efficiency references,
never game deadlines or acceptance cutoffs. With this eight-game sample,
nearest-rank P95 is the slowest observed game and is only a rough tail signal.
The CLI diagnostic's `elapsed_us` includes board-specific configuration as well
as search. Time and node counts are observations, not per-decision budgets, and
verification does not reject a completed game because either value is large.
The per-decision protocol response timeout is 600 seconds and detects a search
that does not respond; it is separate from the whole-game references and total
learning-batch duration.
If the baseline is far from the mean goal or its P95 reaches the
review threshold, try up to three bounded midgame-search improvements, verify
each candidate's search results, then remeasure the same games and evaluator.
If those attempts still miss, record the best result and remaining tradeoff
before choosing a compromise profile.

Within one configuration, baseline and candidate must
agree on move, score, and completed exactness for the same positions; exact
scores are checked against the independent oracle. Performance evidence
reports the selected self-play profile, every completed game's wall time, the
sample mean, and its P95 before the larger learning batch is started. A slow
game completes and remains in those statistics; a per-decision watchdog may
end a game only when an individual search response stalls.

The first fixed `efficiency8` sample completed on 2026-10-13: its eight
StrategicEvaluator games averaged 3.7699 seconds, with nearest-rank P95 at
8.0750 seconds. The 132 exact positions were checked by 252 exact Oracle root
and selected-child queries, and the saved report and Oracle evidence were verified.
This is well below the 180-second mean goal and 300-second P95 review point, so
it gives no reason to optimize this search profile before training. It does not
measure TrainedEvaluator evaluation cost, total learning-batch duration, or
Egaroucid full-game self-play speed. See
[`reversi-ai-efficiency8-closeout-2026-10-13.md`](../references/reversi-ai-efficiency8-closeout-2026-10-13.md)
for the pinned run and evidence digests.

### 0040 one-command efficiency closeout

The human-operated 0040 efficiency run has one entrypoint. From a clean Linux
checkout it pins the full source revision, builds the release `reversi-ai-cli`,
then runs these stages serially: the fixed eight-game `efficiency8` sample;
offline verification of its canonical report; independent external Oracle
root/selected-child checks for every exact decision in that report; offline
verification of the Oracle evidence; and publication of a canonical completion
summary. It accepts the Oracle binary and working directory, output directory,
host RSS cap, and progress interval as explicit inputs. It uses StrategicEvaluator,
8/8/8, exact16, `turn`, no search-time or node budget, and a 600-second
per-decision CLI response watchdog. Each external Oracle root/child solve has a
separate 600-second query watchdog. The same RSS cap applies to each CLI seat
process and each external Oracle solve process. It never starts a training
batch or makes an adoption decision.

Every stage validates existing artifacts against source, CLI and Oracle binary
digests, settings, score contract, and upstream report digests before skipping
it. Whole-game progress reuses the verified per-game checkpoints. Oracle
root/selected-child evidence is checkpointed by exact decision and can resume
only after validating each saved query and its identities. Each Oracle query
records search elapsed time and nodes plus process wall time, user/system CPU,
peak RSS, and the execution host (node, machine, and Linux kernel/platform).
Before the CLI preflight process starts, the runner verifies any saved whole-game
report, per-game/segment checkpoint, Oracle evidence, and every existing Oracle
query checkpoint offline; malformed saved data cannot trigger a new CLI or Oracle
process.
Oracle evidence schema 4 checkpoints pin the 600-second query watchdog and
shared RSS cap; offline verification checks these settings, resource
observations, host provenance, limits, and score evidence. A checkpoint from
the prior schema-3 Oracle evidence contract is upgraded only after its saved
query data and old checkpoint digest verify; existing queries retain the host
from the saved run identity, while new queries record the current host.
If interruption occurs while checkpoint schemas are being upgraded, the next
invocation accepts and completes the validated mixed-schema migration before
it publishes schema-4 evidence.

An interrupted efficiency8 run may resume from an explicitly supported prior
runner version when the current source revision descends from the saved
revision, the saved build/CLI and all workload inputs still match, and the
current host has the same node, machine, and Linux platform except for a changed
numeric kernel release. Compatibility for closeout runner v1 is restricted to
source revision `b82b04d691bffd1866cc02e28416eaebaf2b4680`. The runner
preserves the original run identity and build receipt, verifies the pinned CLI
and Oracle runtime, and records each
invocation host in stage state and the final summary. Unknown runner versions,
unrelated source histories, node or machine changes, platform changes, changed
settings/openings/CLI/Oracle resources, corrupt checkpoints, failed exact
solves, resource-limit breaches, or score disagreements fail closed. No
completed game or query is rerun merely because the process or Linux kernel
changed, and prior score/resource observations are not replaced.
All eight games must finish. The 180-second mean goal and 300-second
nearest-rank P95 review point never stop a game. The final summary records all
game times, mean, P95, exact Oracle positions and subprocess queries checked,
per-query and aggregate Oracle search/process resources, evidence digests, and
elapsed time for each stage and for the full invocation.

The runner writes flushed stderr progress with these stable forms:

```text
progress efficiency8 stage=<stage> status=<started|verified|completed|failed> elapsed_s=<seconds> [identity=<digest>]
progress efficiency8 stage=self-play game=<game-id> done=<n> total=8 game_s=<seconds> elapsed_s=<seconds>
progress efficiency8 stage=oracle-check position=<position-id> done=<n> total=<exact-position-count> query_elapsed_ms=<milliseconds> elapsed_s=<seconds>
progress efficiency8 stage=complete games=8 mean_s=<seconds> nearest_rank_p95_s=<seconds> oracle_positions=<n> elapsed_s=<seconds>
```

`--progress-every` is a positive interval, defaults to 1, and always emits stage
boundaries and the final completion line. A human starts this command in a
terminal and may wait for it to finish; no CI job or background process starts
the long measurement.

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

Heuristic transposition-table reuse within one game is separate from the exact
table's decision scope and remains enabled. Keep the exact-table `game` scope
available for a future bounded diagnostic when a training method selects its
exact threshold. The `efficiency8` result only covers exact16 with `turn`; it
does not determine whether game-scope reuse helps at a higher threshold such as
30 empties. Do not adopt it as the production policy or remove the capability
based on this sample; the current production policy remains exact16/`turn`.

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

Completed 0035, 0041 and 0045 reports retain their original score contracts.
Their timing and Oracle receipts do not prove winner-empty performance or
winner-empty Oracle agreement. Until the human accepts the settings, cache
policy and time budget, production remains at 12/12/12, exact16 and turn, with
cross-decision reuse suspended.

The report separates exact work from whole-game time and identifies the
single-run sample bias. Equal heuristic node counts with different timing do
not prove a cache effect. Unselected exact roots are not independently Oracle
verified. Historical timing retains its original digest/settings and is not a
control for the new binary. Even successful historical evidence leaves
production adoption, winner-empty Oracle/performance comparison and time-budget
decisions to 0040 and the human; experimental exact20 does not authorize
changing production exact16.

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

## Training method pilot (0037)

The pilot has its own versioned prepare/run/verify manifest and single-stage
comparison. It never uses the production reinforcement 50/200-game checkpoint.
All new inputs and teachers use `winner-empty-v1` and artifact format 2.
The frozen production denominators are 64 self-play games, 7,680 teacher rows,
and 200 comparison games. Floor division by ten fixes pilot caps at 6, 768,
and 20. Run and offline verification reject overages; teacher rows count the
unique positions actually passed to the one `bounded_td_v1` update.

Random opening collection is separate from teacher production. Every game
starts from the standard board with Black to move and records a legally
replayable opening. Self-play uses six independent legal continuations by the
baseline project AI. Teachers are its completed terminal winner-empty score,
signed for the recorded side, rather than random-rollout or per-position exact
labels. Search depth/threshold, time/node caps, response timeout, turn cache,
reset protocol, seed, input/CLI/source digests, optimizer and update count are
frozen before execution. Timeouts, invalid moves and unfinished games fail
closed. No 30-empty exact-label method is enabled without separate bounded
feasibility evidence. The initial self-play profile is 8/8/8, exact16, turn;
comparison and corpus decisions retain 12/12/12, exact16.

Prepare pins the baseline's trainer manifest and verifies its input identity;
its train position keys are reserved. Independent validation and held-out
inputs have explicit schema2 provenance and split. Canonical D4 position keys
are deduplicated and overlaps with training, tuning, corpus and comparison
inputs are excluded with recorded IDs. Empty independent metrics fail closed.
The 0018 opening suite is reserved by its independently pinned position keys;
the runner rejects a prefix or continuation reaching a reserved root before
requesting an AI decision, and offline verification rejects it too. The shared
standard initial board is not an opening reservation. Independent metrics also
exclude each game's terminal board from both color perspectives.
Ten complete comparison pairs replay the
same legal Black-start opening twice with candidate and baseline changing
seats. Color-inverted intermediate boards are never treated as legal starts.

Corpus regret uses a pinned Oracle position corpus and schema2 saved golden move values,
validated offline with the existing Oracle validator. Corpus positions overlapping
baseline training, reserved openings or played positions are excluded with IDs;
at least one independent legal-move root must remain. No new Oracle teacher
queries are made. Every baseline/candidate decision records its position and
legal move so offline verification recomputes regret from the saved values.
The manifest pins Oracle source/version/profile and score semantics. Fixture
and smoke corpora establish tooling correctness only, not strength evidence.
Legacy pilot manifests retain `tooling_only=true`, `strength_inputs=false`, and
`improvement_observed=false`, including inputs labeled `production`. New pilot
manifests pin the complete input bundle described below. Only a full offline
reconstruction of a production bundle and matching CLI build identity enables
`strength_inputs=true`; caller labels, resealed hashes, metadata or a context
boolean alone cannot enable it. This is reproducibility of a trusted local
human execution of reviewed producers, not authentication of hostile producers.

The report records before/after validation and held-out sample counts and
squared errors, corpus regret sum/count, match wins/draws/losses/points, actual
counts, exclusions, all game/input/artifact digests and deterministic update
identity. The pilot's primary completion evidence is that the bounded
prepare/run/verify pipeline finishes and its outputs can be independently
reconstructed; the small sample is not expected to demonstrate a strength
improvement. Its predeclared improvement rule is lower held-out MSE, with
validation MSE and mean corpus regret no more than 10% worse (zero baselines
require zero), and candidate points at least 10/20. This rule labels a
diagnostic result only: it does not gate pilot completion or an independently
authorized 0019 batch. Only complete production inputs and a strong-engine
corpus with independently authenticated provenance can permit recording
`improvement_observed=true` after bundle reconstruction. A false value does not
mean the pipeline failed or that the method is ineffective. Preserve the
candidate and all measurements; 0019 uses a fresh manifest and output directory
and never carries the pilot candidate forward. Neither pilot nor production-cycle
evidence alone claims the 0018 strength target.

Run refuses nonempty output directories and publishes the report last. Verify
replays openings and games, checks resets and full pair/count identities,
deduplicates the same teacher rows, recomputes the artifact and every metric,
and compares all output bytes/digests without starting a CLI or Oracle.
Long real runs remain human-operated; agents prepare inputs/commands and
verify completed immutable output only. Unit fixtures are bounded tooling
checks and cannot satisfy the pilot's external completion boundary.

For a human-operated one-command execution, `make pattern-pilot-execute`
accepts the verified input bundle, its successful final `bundle-verify` receipt,
the pinned candidate executable, and a new absolute run-root path outside the
source checkout. It creates `<run-root>/manifest.json`, runs the bounded pilot
once into `<run-root>/output/`, and runs the offline verifier in that order.
The run root must not already exist. The command stops at the first failure and
keeps a successfully prepared manifest and any produced output for diagnosis;
a retry uses a new run root. It reserves the run root atomically before
preparation so concurrent invocations cannot share a manifest or output
directory. A zero exit status means the offline verifier completed. Success
prints `pilot verified report=<absolute-path> digest=<sha256>` to stdout. This
entry point consumes the existing 0051 bundle and never regenerates its
production inputs or starts additional Oracle solves.

The production entry point is `make pattern-reinforcement-execute`, a thin
wrapper around the same `tools/reversi-ai-training/pilot.py execute` path used
by `make pattern-pilot-execute`; there is no production-mode switch or second
orchestrator. The pilot target passes its bounded 6 self-play / 20 comparison /
0 direct Oracle-match counts. The production target passes overrideable Make
variables `REINFORCEMENT_SELF_PLAY_GAMES` (default 64),
`REINFORCEMENT_COMPARISON_GAMES` (default 200), and
`REINFORCEMENT_ORACLE_GAMES` (default 20). The direct CLI requires explicit
`--self-play-games`, `--baseline-comparison-games`, and `--oracle-match-games`
values. Production requires a positive Oracle-match count; game counts must
preserve color-swapped pairs. The runner pins requested and actual counts in
the manifest and report, so operators can change counts without editing
Python source.

A human starts a new cycle once with the verified 0051 bundle and receipt, the
pinned candidate executable, an absolute run-root path outside the checkout,
and the requested counts. It creates the 0019 manifest, verifies inputs, runs
self-play, baseline comparison and selection, corpus regret, and the
unconditional 0018-profile Oracle match, then performs offline verification
and publishes the report. It stops at the first failure and preserves partial
attempt evidence. The command does not require separate manual reinforcement
prepare/run/verify or Oracle-match commands and does not regenerate the 0051
production input bundle.

For `--resume-from PHASE`, the operator supplies the existing run root and
the desired settings. Supported phases are `input-verification`, `self-play`,
`candidate-update`, `baseline-match`, `candidate-selection`, `corpus-regret`,
`oracle-match`, and `offline-verification`. Make exposes the same option as
`REINFORCEMENT_RESUME_FROM`. Changed settings apply to the selected and later
phases; changes affecting retained outputs require an earlier resume phase.
Oracle timeout retries preserve verified completed games and restart the first
unfinished game. Final offline verification precedes report publication.

Progress is flushed on stderr with `stage <name> start/done elapsed=<seconds>s`
and `progress <kind> pair=<n> member=<n> <done>/<total> game=<seconds>s
elapsed=<seconds>s`. Completed games are the work unit (6 self-play and 20
comparison games for the bounded pilot; production totals come from its
manifest);
corpus queries count one player's completed decision, totaling twice the retained
position count. Default interval is one;
positive `--progress-every N` limits ordinary updates and always emits the last
unit. Loading, teacher extraction, update, independent metrics, corpus,
comparison and publication have explicit stage boundaries.
The one-command entry point also emits
`stage pilot-prepare start/done elapsed=<seconds>s`; its game progress uses the
same format and defaults to one completed game per update, controlled by
`PILOT_PROGRESS_EVERY`.

## Production reinforcement batch and Oracle distance (0019)

The production cycle remains one bounded update with denominators of 64
self-play games, 7,680 unique teacher rows, and 200 candidate-versus-baseline
games. The 0037 pilot's primary goal is to verify that the prepare/run/verify
pipeline completes and its outputs can be independently reconstructed within
the small-run caps. Its sample is too small to expect a strength improvement;
before/after metrics are diagnostic, not a production gate. A successfully
verified pilot therefore establishes pipeline feasibility even when
`improvement_observed=false`. The 0037 artifact is never used as the 0019
candidate or selected model. The production cycle uses its own pinned baseline,
inputs, manifest, output root, validation, and artifact-selection gates.

Every 0019 production run also plays the raw post-update candidate against the
pinned Oracle, regardless of the candidate-versus-baseline result or which
artifact the baseline-selection gate selects. This direct match is diagnostic
evidence for distance to the project goal; it does not change 0019's artifact
selection and does not replace 0018 acceptance. The Make default is 20 complete
games from ten predeclared legal openings, with each opening replayed once per
color. `--oracle-match-games` selects another positive even game count, using
one legal opening per color-swapped pair. The suite is disjoint from self-play,
candidate-selection inputs, and 0018 held-out openings. Record the requested
and completed game counts and the Oracle-match opening, decision, and terminal
exposure keys in the 0019 report so 0018 can exclude them. The existing Oracle
corpus-regret analysis remains a separate metric.

The Oracle opponent profile for the 0019 diagnostic and the later 0018
acceptance is `oracle-0018-acceptance-v1`. It pins Egaroucid identity, bookless
operation, one thread, hash level 25, score semantics, and resource limits.
The Oracle uses 6/6/6 opening/midgame/endgame depths and starts exact solving
at 12 or fewer empty squares. A position in that exact region counts as solved
only when the saved result is exact and completed depth equals the remaining
empty squares. The project candidate uses 12/12/12 and exact16, matching the
candidate side of the planned 0018 comparison. Record both sides' configured
and completed depths, exact thresholds, and per-position exact flags.

The 0019 match is a distance diagnostic and does not apply a pass/fail win-rate
gate; its default sample size is 20 games and the manifest records any override.
The final goal remains 0018's held-out `candidate wins / all games >= 0.50`
under the same Oracle and candidate search profiles, with its predeclared
sample size and confidence rule. A 12/12/12 exact16 strong-AI
teacher-evaluation setting is a separate training-data use; it is not the
Oracle opponent profile for this goal-distance match.

Every human-facing Reversi AI match, board, or score summary (including 0037,
0019, and 0018 results) identifies the evaluated artifact and opponent, game or
position count, opening/midgame/endgame search depths, exact-solve threshold in
remaining empty squares, and whether each reported position actually completed
an exact solve. A bare score or win rate without these settings is incomplete
evidence.

The 0037 run `0037-20261018-01` produced report digest
`2ea9ef8c77dc9ee8f2dae385a238dfa2aac37577ec3c30d382e197b515f1a29e`; its
human-run progress log reported 991.8 seconds through final offline
verification for 6 self-play games, 326 teacher rows, 20 candidate comparison
games, and 12 Oracle corpus positions. Linear scaling to 64 self-play games
(64/6 = 10.67x) and 200 candidate comparison games (200/20 = 10x) gives an
initial 0019 core-cycle estimate of 9,918–10,579 seconds (2h45m–2h56m),
including the pilot-style offline verification. This estimate uses game-count
scaling, assumes the Make defaults of 64 self-play and 200 comparison games,
and is not a runtime guarantee. Recompute it from the manifest counts whenever
an operator overrides either value. It does not include the default 20-game
match under `oracle-0018-acceptance-v1` (Oracle 6/6/6, exact12; candidate
12/12/12, exact16). The 0037 elapsed time does not isolate this paired profile.
Before handing the human-operated production command over, report a separate
projection for the manifest's Oracle-match game count using representative
positions under these settings and show both the core estimate and combined
estimate. Do not present the core estimate as the total runtime.

The human-operated one-command runner writes flushed diagnostics to stderr
only; they never enter manifests, game records, reports, or digests. It reuses
the existing stage forms `stage NAME start elapsed=S.s` and
`stage NAME done stage=S.s elapsed=S.s`. Stage names are `input-verification`,
`self-play`, `candidate-update`, `baseline-match`, `candidate-selection`,
`corpus-regret`, `oracle-match`, `offline-verification`, and `publication`;
emit both boundary lines for every stage, including the final stage.
`--progress-every N` is a positive integer,
defaults to `1`, and controls each progress stream independently. Emit an item
at each interval multiple and force the final item for every game/phase even
when it is not an interval multiple.

After a completed search at each played Oracle-match root, report the moving
engine's actual result as
`progress oracle-match game=G root_decision=D engine=ENGINE empties=E configured_depth=C completed_depth=A exact_threshold=T exact=BOOL root=S.s elapsed=S.s`.
`G` and `root_decision` are one-based within the match and game; `ENGINE` is `candidate` or
`oracle`; depths are in plies; `E` is remaining empty squares. Count root
decisions separately per game for rate limiting, and always emit that game's
last root decision. Forced passes do not create search-root records. Match
completion still writes the existing game-level `progress oracle-match
game=N N/total game=S.s elapsed=S.s` update, including the last game.

During offline verification, use the same flushed stderr and stage-boundary
forms. Replayed game progress is
`progress offline-verification phase=PHASE game=G completed=N/total game=S.s elapsed=S.s`,
where `PHASE` is `self-play`, `baseline-match`, or `oracle-match`; each phase's
total comes from the frozen manifest/report. Oracle root replay uses
`progress offline-verification phase=oracle-root game=G root_decision=D completed=N/total-root-decisions root=S.s elapsed=S.s configured_depth=C completed_depth=A exact_threshold=T exact=BOOL empties=E`.
Corpus replay uses
`progress offline-verification phase=corpus position_id=ID completed=N/total-positions item=S.s elapsed=S.s`.
Rate-limit each phase independently using `--progress-every N`, and force the
final game, root, or position update for each phase. A missing game, mismatched
depth/exactness record, or incomplete required exact solve fails the
direct-match/verification stage without silently substituting the weaker
corpus profile.

## Training input bundle (0050)

A frozen preparation manifest pins winner-empty schema2 producers, source commit,
merged-main ancestry, producer file bytes, CC0-1.0 license, seeds, split game IDs,
and stage budgets. The producer checkout must be clean and on merged main.
Calibration has 4/2/2 games; production requires 2048/256/256. Reduced inputs are
always tooling. Random terminal winner-empty labels remain bootstrap teachers;
they are distinct from the pilot's baseline-AI continuation teachers.

Generator output contains exactly its existing six files. Preparation manifests,
stage logs, baseline artifact/report and Oracle evidence live in sibling
directories. Generated counts and output SHA are pinned in a new trainer-stage
manifest; frozen manifests are never extended. Completion manifests enumerate
every generator/trainer input and output, source/license, schema, score contract,
seed, counts and SHA. Offline verification uses the pinned producer to replay
and regenerate every game and split, deterministically reconstruct the baseline
and trainer report, and compare validation/held-out bytes with pilot inputs.
Neither validation nor held-out participates in baseline updates. Source changes
require a new bundle. Partial outputs and self-reported verified flags fail closed.

The corpus uses an independent seed/domain of legal Black-start random complete
games. In game-ID/turn order, at most 256 candidate games yield four roots each
at 20, 40 and 48 occupied squares. Each root has 2..16 legal moves and a
nonterminal child. D4 duplicates, all three split keys and existing reservation
keys are excluded before observing scores. Full candidate logs and selection
and exclusion IDs are saved and independently regenerated; insufficient roots
fail without replacement. Later pilot comparison openings exclude this corpus.
The corpus stage reads split JSONL one record at a time and retains only
canonical exclusion keys, rather than a decoded split or all of its source
lines. Blank lines, malformed/non-object/non-finite JSON diagnostics and D4
exclusions retain their existing meaning. The 256 MiB ceiling remains fixed.
Source changes still require a newly merged producer and fresh run manifests;
old completed and failed stage originals must not be relabelled or overwritten.

Strong-engine-hcap-v1 Oracle analysis retains its existing 8/12 depth contract,
distinct from project CLI 12/12/12 exact16. Each of 12 roots is a separate solve
batch with a 300-second timeout, at most 192 nonterminal child queries overall.
Terminal children use winner-empty directly. Evidence preserves problem bytes,
root/child/side/sign mapping, argv, cwd, stdout/stderr, exit state and complete
binary/resource SHA before and after execution. The existing parser reconstructs
schema2 golden entirely offline. Missing queries, incomplete/invalid output,
runtime changes or exceeded budgets retain failure originals and publish no
completed golden. Relabelled smoke/legacy golden is insufficient.
Production runtime preparation reuses the pinned Egaroucid archive/source
validation, fresh build and version check, preserving an immutable setup
receipt with archive/source identity and actual binary/resource hashes. Raw
analysis and completion bundles pin that receipt and match its runtime before
and after execution. Offline receipt validation reads saved archive evidence
without building or launching Oracle. Fake runtimes without this route remain
tooling regardless of game counts or profile labels.

Linux stage supervision covers the process group. Wall and observed aggregate
RSS ceilings stop the group; unavailable metrics fail closed. RSS is sampled
each second and is an observed peak, not a guarantee about instantaneous peaks.
Stage records preserve CPU, wall, peak observed RSS, exit/timeout, manifest and
raw stdout/stderr. A completion report is published last after verification.
SIGTERM cancellation terminates and reaps the worker process group and preserves
a failure report, with the previous signal handler restored afterward.
No generator, trainer or Oracle stage resumes partially completed work: retain
failure originals and restart into a new directory. Completed verified previous
stages may be reused. No failure automatically starts another stage.

| Stage | Wall seconds | Observed RSS ceiling |
| --- | ---: | ---: |
| calibration-generate | 120 | 256 MiB |
| calibration-verify | 120 | 512 MiB |
| calibration-train | 300 | 1 GiB |
| generate | 600 | 1 GiB |
| verify | 1200 | 2 GiB |
| train | 1800 | 3 GiB |
| corpus | 120 | 256 MiB |
| oracle | 4200 | 3 GiB |
| bundle-verify | 2400 | 3 GiB |
| cli-probe | 10 | 3 GiB |

The total budget is 10870 seconds excluding build/preparation, not an estimated
duration. Human operators start stages individually; agents and CI run only
bounded fixtures and verify completed saved outputs. Existing internal progress
is retained. Wrapper stderr uses exactly `progress input-bundle stage=<stage>
done=<n> total=<n> status=<running|saved|verified|failed> elapsed_s=<value>
rss_bytes=<value>`. Wrapper completion counts 0/1. Internal totals are 8/2560
games, 12 Oracle roots, and the verified trainer record count. Start/end and
resource heartbeats appear with `--heartbeat-seconds` default 5; positive
`--progress-every N` defaults to 1 and always emits the last internal unit.
Diagnostics never enter canonical identities.
Finalization produces a preliminary reconstructable bundle. Pilot preparation
and replay additionally require a successful bounded `bundle-verify` completion
receipt tied to the exact bundle and CLI identities. The pilot manifest pins
that receipt separately from the bundle to avoid a circular hash. Missing,
failed or mismatched final-stage receipts cannot enable input eligibility.

Acceptance reservation is explicitly `not-yet-selected` with empty keys until
0018 creates its suite after candidate selection. `reserved` requires a real
versioned suite artifact, path/digest and nonempty reconstructed keys; neither
a synthetic opening nor the standard initial board represents that suite.
The bundle reconstructs exposure keys separately for train, validation,
held_out, Oracle roots and children. Pilot reports reconstruct opening,
decision and terminal keys. 0018 checks chosen opening roots against these and
0019 exposure keys before freezing its suite. Future suite creation is not a
prerequisite for input generation.

CLI identity pins merged source, Cargo.lock, build recipe and actual binary SHA.
A single preselected validation opening (first eligible row, at most 20 discs,
legal move, outside existing reservation) probes reset acknowledgment and a
legal move with 1/1/1, exact16, turn, 100ms/1000nodes, a two-second response
watchdog and ten-second stage ceiling. Raw protocol responses, position, argv
and binary/artifact SHA are saved separately. Offline verification launches
neither CLI nor Oracle. Verified production inputs still require all six pilot
games, at most 768 update rows, ten complete comparison pairs, independent
metrics and output reconstruction before recording improvement or failure.
`production_authorized=false` remains mandatory. Tooling completion leaves
0051 input generation, 0037 real pilot, 0019 cycle and 0018 acceptance open.

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
from the root side's perspective; when `exact` is true, the value is the
winner-empty terminal score, while an incomplete search value is heuristic. A project AI's
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

`strong-engine-hcap-v1` is a calibration/reference profile, not proof of the
final strength target. The 0018 acceptance Oracle is separately pinned as
`oracle-0018-acceptance-v1`: Egaroucid Console v7.8.1, bookless, one thread,
hash level 25, fixed 6/6/6 across opening/midgame/endgame, and exact solving
from 12 or fewer empty squares. The project candidate uses 12/12/12 and
exact16, preserving the search-cost handicap. The 0019 Oracle distance match
uses this same pair of search profiles (default 20 games; the manifest pins
the selected count); 0018 later
tests the final candidate on its held-out suite and requires
`wins / all games >= 0.50`, reported separately from match points (where a draw
is 0.5), with its predeclared sample-size and confidence rule. A 12/12/12
exact16 setting used to compare stronger-AI teacher evaluations is a separate
training-data use and does not define the Oracle opponent. `ci-smoke-v1` remains
a distinct small, bounded profile and cannot establish calibration or final
strength.

### Explicit search settings and score-contract audit

通常 CLI の正の u8 深度・u32 exact 引数、および Advisor/decision/Playground の
opening 1..12、midgame 1..16、exact 0..30 は維持する。exact 0 は無効化であり、
20/24 は heuristic depth ではなく空き数による切替閾値である。既定 exact16 は変更しない。

Godot の `set_ai_with_exact_threshold(evaluator, opening, midgame, endgame, exact)` は
各深度 1..64、exact 0..30 を変換前の整数で検証する。不正値・未知 evaluator は false を
返し、既存 AI を変更しない。旧 `set_ai` の呼出契約と既定 exact16 は維持する。

Reinforcement の新規 prepare/run は schema6 を使用する。自己対局専用の opening、
midgame、endgame 深度は各 1..64、exact は 0..30 を独立に指定でき、既定は
12/12/12・exact16。manifest/report は全設定、CLI SHA-256、資源上限、turn policy を
固定し、run は記録値を実行する。candidate-match/regret/0018 の
`strong-engine-hcap-v1` は常に 12/12/12・exact16。schema3/4/5 の完成 report は元の
設定範囲・policy の意味で offline 検証する。旧 manifest で新 run を開始できず、
中断 run の別 identity による再開も認めない。reset ack と timeout/未完了時の
fail-closed は維持し、部分 exact score を教師値へ使わない。

旧 Project の終局 score は両色生存時の実石数差、wipeout のみ ±64、空盤は 0。
新 Project は固定 Oracle Egaroucid v7.8.1 と同じ勝者空き加算を採用する。旧証拠は両契約を区別して保存し、
root へ一律 ±1 を足す補正は行わない。合法 continuation、terminal leaf、root と
選択 child の独立再計算を根拠に、調査結果を「score 契約差を terminal/root/child
まで確認」「符号/手番/validator の誤りを確認」「solver 誤りの証拠あり」
「上限内で未確定」に分類する。旧失敗 receipt は変更しない。
未解決の正確性条件は 0040 の本番 freeze gate に残す。score 意味の変更、本番 game
cache 再利用、学習成功、閾値24の時間内完了はこの設定 API から導かない。

## GDScript Bridge Additions

Added to the existing `ReversiGame` GDScript class:

```gdscript
# AI setup
game.set_ai(evaluator_name: String, opening_depth: int, midgame_depth: int, endgame_depth: int) -> bool
game.set_ai_with_exact_threshold(evaluator_name: String, opening_depth: int, midgame_depth: int, endgame_depth: int, exact: int) -> bool
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
