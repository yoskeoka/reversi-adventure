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

## One bounded reinforcement cycle

Build a project-owned `reversi-ai-cli` from the accepted, merged source commit.
Keep the baseline artifact, a separate licensed validation JSONL, and all
outputs outside the checkout. Validation rows use the training record schema,
`split: "validation"`, and a `source` distinct from the later 0018 opening
suite.

A versioned tiny validation input and fake CLI under `fixtures/` exercise the
protocol in unit tests. They are too small for strength evidence.

On the clean source checkout, freeze a manifest. The Make defaults record 64
games in 32 color-swapped D4 pairs, seed `20260926`, six opening plies, the
accepted 12/12/12 depth and 16-empty exact threshold, disabled book, a
five-minute per-move search limit, ten-million-node cap, 310-second protocol
timeout, and 7,680 total decisions.

Set resource variables explicitly if the host needs different caps. The
resulting manifest is immutable.

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
`report.json`; start over with a fresh output directory and the same frozen
manifest.

An agent and the test targets leave this run to the human operator.

```sh
make pattern-reinforcement-run \
  REINFORCEMENT_MANIFEST=/absolute/path/cycle-manifest.json \
  REINFORCEMENT_OUTPUT_DIR=/absolute/path/cycle-output
```

After the human run finishes, a later task validates the immutable outputs and
records the SHA-256 of the manifest, four output files, and regret report. The
verifier replays every legal move, recomputes each game digest and the bounded
update, checks the disjoint validation input, and recomputes selection metrics.

Only a strictly lower validation mean squared error selects the candidate.
The baseline wins a tie.

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
search controls under oracle profile `strong-engine-hcap-v1`. It reads the
existing oracle corpus only; the 0018 held-out openings stay unopened until
their separate acceptance run.
