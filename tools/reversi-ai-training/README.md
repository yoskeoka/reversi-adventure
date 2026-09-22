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
