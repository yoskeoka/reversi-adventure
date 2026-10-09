# Reversi AI pattern training

This tool uses the Python standard library to build repeatable sparse weights
for the pattern evaluator. The tiny fixture uses `CC0-1.0` and supports tests
only. Use labelled final scores for training; the oracle corpus supplies move
sets for checks.

Run the bounded fixture twice and compare its declared output:

```sh
python3 tools/reversi-ai-training/training.py train \
  --manifest tools/reversi-ai-training/fixtures/tiny-winner-empty-manifest.json \
  --artifact /tmp/pattern-artifact.json --report /tmp/pattern-report.json
python3 tools/reversi-ai-training/training.py validate --artifact /tmp/pattern-artifact.json
```

Large datasets and mutable optimizer caches belong outside the checkout. A real
manifest must pin each data file digest and each record's source, license, and
source digest.

The emitted artifact has only sparse integer tables, a fixed
60-phase/64-feature contract, per-feature bounds no greater than one, and
canonical SHA-256 identity fields.

## Project-owned random-game baseline inputs

`random_inputs.py` draws complete legal games from the canonical initial board.
Its frozen manifest pins the exact clean producer checkout, merged-main base,
and digests of the generator and imported game/trainer modules, plus seed,
split game ids, random and split rules, `CC0-1.0` provenance, record start and
turn cap.

Defaults are 2,048 train, 256 validation, and 256 held-out games;
every split must cover opening, midgame, and endgame. The validation file is
separate from training and held-out inputs, with all production files stored
outside the checkout.

First run a small pilot with the same generator and use `/usr/bin/time -v` to
record elapsed time and peak memory use.

Set a production wall-clock and peak-memory cap from that measurement before freezing the production
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
Playing strength needs separate match evidence.

For 0019, record the exact baseline artifact and validation input
(`inputs/validation.jsonl`) paths and digests, while reserving the 0018 openings
for its acceptance run.

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
only a result above 25 match points continues to 200 games.

The production seed is newly generated and recorded in the manifest. It also
records six opening plies, the
accepted 12/12/12 match depth and 16-empty exact threshold, disabled book, a
five-minute per-move search limit, ten-million-node cap, 310-second protocol
timeout, and 7,680 total decisions.

Schema 6 gives each search setting its own prepare argument and Make variable.

| Setting | Make variable | Prepare argument | Range | Default |
| --- | --- | --- | --- | --- |
| Opening depth | `REINFORCEMENT_SELF_PLAY_OPENING_DEPTH` | `--self-play-opening-depth` | 1–64 | 12 |
| Midgame depth | `REINFORCEMENT_SELF_PLAY_MIDGAME_DEPTH` | `--self-play-midgame-depth` | 1–64 | 12 |
| Endgame depth | `REINFORCEMENT_SELF_PLAY_ENDGAME_DEPTH` | `--self-play-endgame-depth` | 1–64 | 12 |
| Exact threshold | `REINFORCEMENT_SELF_PLAY_EXACT_EMPTY` | `--self-play-exact-solver-empty-squares` | 0–30 | 16 |

Use midgame depth 8 when needed, or exact threshold 0 to disable solving.
Thresholds such as 18, 20, 22, and 24 set the number of empty squares at which
exact search starts.

Completion still depends on the frozen time and node limits. A failed or
interrupted game cannot supply training labels or a completed report.

Candidate matches, corpus regret, and later 0018 acceptance retain 12/12/12
and exact threshold 16. The manifest/report freeze all self-play settings, CLI SHA-256,
resource limits, and the turn cache policy. Flexible settings do not clear the
production freeze or its independent correctness gates.

New prepare/run and regret adoption require schema 6. Completed schema 3/4/5 reports require `verify --legacy-offline`; their frozen
producer replays the original raw disc-difference teachers. Schemas 3/4 retain
12/(8|12)/12 and exact 16; schema 5 retains its flexible settings.

Keep failed evidence from an interrupted schema 3/4 run.

Start a new schema 6 run with a separate manifest and output directory. Changing a manifest
after completion fails the report identity checks. Versions 1/2 are unsupported.

All accepted manifests pin `new_game-v1` and the binary digest. Prepare checks
the reset acknowledgement. Each player resets before every game, and the
verifier checks those reset events.

Set time and node caps explicitly if the host needs different limits. The
match profile still requires depths 12/12/12 and the 16-empty threshold. The
protocol timeout must exceed the search time limit, and the resulting manifest
is immutable.

```sh
make pattern-reinforcement-prepare \
  REINFORCEMENT_BASELINE_ARTIFACT=/absolute/path/baseline.json \
  REINFORCEMENT_VALIDATION_INPUT=/absolute/path/validation.jsonl \
  REINFORCEMENT_CANDIDATE_EXECUTABLE=/absolute/path/reversi-ai-cli \
  REINFORCEMENT_VALIDATION_SOURCE=project-owned-validation-v1 \
  REINFORCEMENT_MANIFEST=/absolute/path/cycle-manifest.json
```

A human starts the following long-running command in another terminal and
stops it by terminating that process.

A failed or interrupted cycle has no valid `report.json`; its 50-game checkpoint is diagnostic only, never resume input.
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
individual games.

Use a positive `REINFORCEMENT_PROGRESS_EVERY=N` to log every Nth game and the
final game. Progress stays on stderr, separate from the candidate protocol and
output files; final verification is still required.

After the human run finishes, a later task validates the immutable outputs and
records the SHA-256 of the manifest, five output files, and regret report.

The verifier replays every legal move, recomputes each game digest and the bounded
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

## Winner-empty migration and preserved evidence

New trainer manifests and records use schema 2, training-v2, explicit
`score_contract="winner-empty-v1"`, and `target.semantics="winner_empty_v1_for_side"`.

Artifact/feature format 2 uses `score_scale="winner_empty_v1"`; only training-v2
(sparse_mean_v1) or reinforcement-v4 (bounded_td_v1) may produce it.

Random-inputs-v2 emits schema 2 manifests, records, games and reports under
project-owned-random-games-v2. Reinforcement-v4 uses manifest 6 and game/report/
checkpoint 4.

Teachers use the legally replayed terminal board:
`own - opponent + sign(own - opponent) * empty`. Random `black`/`white` and
reinforcement `disc_counts` still count physical discs, with draws scoring zero.

Old source bytes are preserved in `legacy_offline/`, with pinned source digests.
The explicit offline adapter loads these isolated producers for verification:

```sh
python3 tools/reversi-ai-training/training.py validate --legacy-offline --artifact OLD_ARTIFACT
python3 tools/reversi-ai-training/training.py validate --legacy-offline --manifest OLD_TRAINER_MANIFEST
python3 tools/reversi-ai-training/random_inputs.py verify --legacy-offline --manifest OLD_MANIFEST --output-dir OLD_OUTPUT
python3 tools/reversi-ai-training/reinforcement.py verify --legacy-offline --manifest OLD_MANIFEST --output-dir OLD_OUTPUT
```

These entry points verify saved data offline, without CLI calls or data
conversion. Runtime, prepare, train, generate, run, regret-command and
regret-timeout reject old inputs.

Keep old digests and root/minimax scores intact. The source snapshot preserves
the producer bytes, random seeds, source digest, raw labels, policy presence
and report shapes.

Original fixtures stay unchanged. A separate tiny winner-empty fixture stores
four legal random-game replays and their labels for regression checks.
Production data generation, training and 0037/0019/0018 human gates remain frozen.

The bundled random snapshot reproduces the pre-0047 producer. Older production
manifests (including 0032) may pin an earlier producer commit. Check out the
manifest's exact `source_commit` in a separate checkout and point the adapter
to that checkout's original source directory:

```sh
python3 tools/reversi-ai-training/random_inputs.py verify --legacy-offline \
  --legacy-source-dir /original-checkout/tools/reversi-ai-training \
  --manifest OLD_MANIFEST --output-dir OLD_OUTPUT
```

Before import, all three original producer files must match the manifest's
`generator_sha256` and `producer_sources`, after which the original verifier
checks its checkout ancestry and complete output bytes.

Keep the original manifest and digests intact. A source directory with different
producer bytes is rejected; `--legacy-source-dir` requires `--legacy-offline`.
