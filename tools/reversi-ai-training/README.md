# Reversi AI pattern training

This standard-library-only tool creates a deterministic sparse weight artifact
for the pattern-evaluator contract. Its fixture is legal to retain (`CC0-1.0`)
and deliberately too small for strength claims. Do not use the oracle corpus as
training input; it is a move-set fixture, not labelled final-score data.

Run the bounded fixture twice and compare its declared output:

```sh
python3 tools/reversi-ai-training/training.py train \
  --manifest tools/reversi-ai-training/fixtures/tiny-manifest.json \
  --artifact /tmp/pattern-artifact.json --report /tmp/pattern-report.json
python3 tools/reversi-ai-training/training.py validate --artifact /tmp/pattern-artifact.json
```

Large datasets and mutable optimizer caches belong outside the checkout. A real
manifest must pin each data file digest and each record's source, license, and
source digest. The emitted artifact has only sparse integer tables, a fixed
60-phase/64-feature contract, per-feature bounds no greater than one, and
canonical SHA-256 identity fields.

## Project-owned random-game baseline inputs

`random_inputs.py` draws complete legal games from the canonical initial board.
Its frozen manifest pins the exact clean producer checkout, merged-main base,
and digests of the generator and imported game/trainer modules, plus seed,
split game ids, random and split rules, `CC0-1.0` provenance, record start and
turn cap. Defaults are 2,048 train, 256 validation, and 256 held-out games;
every split must cover opening, midgame, and endgame. The validation file is
separate from training and held-out inputs. All production files stay outside
the checkout.

First run a small pilot with the same generator and use `/usr/bin/time -v` to
record elapsed time and maximum resident set size. Set a production wall-clock
and peak-memory cap from that measurement before freezing the production
manifest. If the estimated production run exceeds either cap, choose new
counts and freeze a new manifest before generation.

```sh
make pattern-random-prepare RANDOM_INPUT_MANIFEST=/tmp/random-pilot/manifest.json \
  RANDOM_INPUT_TRAIN_GAMES=4 RANDOM_INPUT_VALIDATION_GAMES=2 RANDOM_INPUT_HELD_OUT_GAMES=2
/usr/bin/time -v make pattern-random-generate \
  RANDOM_INPUT_MANIFEST=/tmp/random-pilot/manifest.json RANDOM_INPUT_OUTPUT_DIR=/tmp/random-pilot/output
make pattern-random-verify \
  RANDOM_INPUT_MANIFEST=/tmp/random-pilot/manifest.json RANDOM_INPUT_OUTPUT_DIR=/tmp/random-pilot/output
```

Use fresh paths for production. `prepare` refuses to overwrite a manifest;
`generate` refuses a nonempty output directory and writes `report.json` last.
Only a successful `verify` establishes complete input evidence.

```sh
make pattern-random-prepare RANDOM_INPUT_MANIFEST=/absolute/path/input-manifest.json
make pattern-random-generate RANDOM_INPUT_MANIFEST=/absolute/path/input-manifest.json \
  RANDOM_INPUT_OUTPUT_DIR=/absolute/path/inputs \
  RANDOM_INPUT_PROGRESS_EVERY=1
make pattern-random-verify RANDOM_INPUT_MANIFEST=/absolute/path/input-manifest.json \
  RANDOM_INPUT_OUTPUT_DIR=/absolute/path/inputs
make pattern-random-train RANDOM_INPUT_MANIFEST=/absolute/path/input-manifest.json \
  RANDOM_INPUT_OUTPUT_DIR=/absolute/path/inputs \
  RANDOM_INPUT_ARTIFACT=/absolute/path/baseline.json \
  RANDOM_INPUT_TRAIN_REPORT=/absolute/path/baseline-report.json \
  PATTERN_PROGRESS_EVERY=1
```

Record the SHA-256 of the generator manifest, all output files, trained
artifact and trainer report. The trainer report measures held-out error only;
compare that error against zero-weight predictions on the same held-out rows.
These metrics do not establish playing strength. Give 0019 the exact baseline
artifact and `inputs/validation.jsonl` paths and digests. Keep 0018 openings
unread until its acceptance run.

The trainer writes flushed stderr progress for validated and prediction-checked
records, with start and done boundaries for loading, aggregation, metrics, and
publication. `PATTERN_PROGRESS_EVERY=N` is a positive interval override;
diagnostics never change the artifact or report bytes.

## One bounded reinforcement cycle

Build a project-owned `reversi-ai-cli` from the accepted, merged source commit.
Keep the baseline artifact, a separate licensed validation JSONL, and all
outputs outside the checkout. Validation rows use the training record schema,
`split: "validation"`, and a `source` distinct from the later 0018 opening
suite.

A versioned tiny validation input and fake CLI under `fixtures/` exercise the
protocol in unit tests. They are too small for strength evidence.

Freeze a manifest. The Make defaults record 64 self-play games in 32
color-swapped D4 pairs and a separately generated 50-game candidate match;
only a result above 25 match points continues to 200 games. The production
seed is newly generated and recorded in the manifest. It also records six opening plies, the
accepted 12/12/12 match depth and 16-empty exact threshold, disabled book, a
five-minute per-move search limit, ten-million-node cap, 310-second protocol
timeout, and 7,680 total decisions.

Schema-5 manifests accept independent self-play settings through
`REINFORCEMENT_SELF_PLAY_OPENING_DEPTH`, `REINFORCEMENT_SELF_PLAY_MIDGAME_DEPTH`,
`REINFORCEMENT_SELF_PLAY_ENDGAME_DEPTH` (each 1..64), and
`REINFORCEMENT_SELF_PLAY_EXACT_EMPTY` (0..30). Defaults remain 12/12/12 and
exact threshold 16; explicit midgame depth 8 remains supported. These correspond to the
`--self-play-opening-depth`, `--self-play-midgame-depth`,
`--self-play-endgame-depth`, and `--self-play-exact-solver-empty-squares`
prepare arguments. Exact 0 disables solving; 18/20/22/24 select an empty-square
switch threshold, independently of heuristic depth. Selecting 24 does not
promise completion within the frozen time/node limits. Failed or interrupted
self-play never supplies training labels or a completed report.

Candidate matches, corpus regret, and later 0018 acceptance retain 12/12/12
and exact threshold 16. The manifest/report freeze all self-play settings, CLI SHA-256,
resource limits, and the turn cache policy. Flexible settings do not clear the
production freeze or its independent correctness gates.

New prepare/run and regret adoption require schema 5. Completed schema 3/4
reports remain offline-verifiable under their original 12/(8|12)/12 and exact threshold 16
contract; they are never silently migrated. Interrupted schema 3/4 runs cannot
resume or run again with this producer: preserve their failed evidence and
prepare a separate schema 5 identity in a fresh output directory. Changing a
manifest after a completed run fails its report identity checks. Versions 1/2
are unsupported. All accepted manifests pin `new_game-v1` and the reset-capable
binary digest. Prepare checks its reset acknowledgement; self-play and matches
reset each player before every game, and verification checks reset evidence.

Set time and node caps explicitly if the host needs different limits. The
match profile still requires depths 12/12/12 and the 16-empty threshold. The
protocol timeout must exceed the search time limit. The resulting manifest is
immutable.

```sh
make pattern-reinforcement-prepare \
  REINFORCEMENT_BASELINE_ARTIFACT=/absolute/path/baseline.json \
  REINFORCEMENT_VALIDATION_INPUT=/absolute/path/validation.jsonl \
  REINFORCEMENT_CANDIDATE_EXECUTABLE=/absolute/path/reversi-ai-cli \
  REINFORCEMENT_VALIDATION_SOURCE=project-owned-validation-v1 \
  REINFORCEMENT_MANIFEST=/absolute/path/cycle-manifest.json
```

A human starts the following long-running command in another terminal. Stop it
by terminating that process. A failed or interrupted cycle has no valid
`report.json`; its 50-game checkpoint is diagnostic only, never resume input.
Start over from self-play in a fresh output directory. `run` rejects a
nonempty directory, including one containing a checkpoint.

An agent and the test targets leave this run to the human operator.

```sh
make pattern-reinforcement-run \
  REINFORCEMENT_MANIFEST=/absolute/path/cycle-manifest.json \
  REINFORCEMENT_OUTPUT_DIR=/absolute/path/cycle-output \
  REINFORCEMENT_PROGRESS_EVERY=1
```

The runner writes flushed stderr diagnostics: one completed-game line by
default, plus start and done lines for each later stage. `N/total` counts
individual games, not pairs. Set `REINFORCEMENT_PROGRESS_EVERY=N` (a positive
integer) to retain every Nth game and the final game for log-limited callers.
Progress is not part of the candidate protocol or any output artifact and does
not replace final verification.

After the human run finishes, a later task validates the immutable outputs and
records the SHA-256 of the manifest, five output files, and regret report. The
verifier replays every legal move, recomputes each game digest and the bounded
update, checks validation exclusions, the checkpoint, match points, and selection.
The report includes validation position keys for 0018 to compare with its
acceptance suite and the replayed self-play positions.

Validation MSE is diagnostic only. The candidate is selected only after more
than 25 match points at 50 games and more than 100 at 200 games; otherwise the
baseline wins.

```sh
make pattern-reinforcement-verify \
  REINFORCEMENT_MANIFEST=/absolute/path/cycle-manifest.json \
  REINFORCEMENT_OUTPUT_DIR=/absolute/path/cycle-output
make pattern-reinforcement-regret \
  REINFORCEMENT_MANIFEST=/absolute/path/cycle-manifest.json \
  REINFORCEMENT_OUTPUT_DIR=/absolute/path/cycle-output \
  REINFORCEMENT_REGRET_REPORT=/absolute/path/corpus-regret.jsonl
```

The regret command uses the frozen CLI and selected artifact with the frozen
search controls and protocol timeout under oracle profile
`strong-engine-hcap-v1`. It reads the
existing oracle corpus only; the 0018 held-out openings stay unopened until
their separate acceptance run.
