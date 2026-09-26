# Random-game reinforcement inputs (0032)

The complete production inputs and trained baseline are outside the
`reversi-adventure` checkout at
`/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.local/reversi-ai-inputs-0032/`.
The files are local evidence, not committed training data. Regenerate them
from the commands below if that path is unavailable. The separate 0019
human-operated cycle has not been started.

## Frozen generation

- Source commit: `bb74190953f3bdfc06b7182626d9d0c8fe51b268` (merged `main`).
- Generator SHA-256: `381f785922a68fb5db5b4d7bf422447c9b45da8ebb88cac6200543d22f364e7e`.
- License/source: `CC0-1.0`, `project-owned-random-games-v1`.
- Seed: `20260926`; games: train 2,048, validation 256, held_out 256.
- Start: eight placements; maximum: 128 turns including passes.
- The frozen manifest contains exact globally assigned game-id lists and the
  SHA-256-derived per-game seed, SplitMix64 move-index, and independent split
  shuffle rules.

An 8-game pilot took 0.55 s wall and 18,540 KB peak RSS. Before production,
the generation cap was set to 10 min wall and 1 GiB peak RSS. Production
generation took 2 min 17.63 s and 365,756 KB peak RSS. Full replay verification
took 4 min 33.00 s and 646,548 KB peak RSS. Training took 9 min 46.21 s and
1,525,808 KB peak RSS; the generation cap does not apply to training.

The verifier passed every game and output. The split summary from its report:

| Split | Games | Turns, including passes | Records | D4 duplicates | Opening | Midgame | Endgame | Target range |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| train | 2,048 | 123,621 | 107,123 | 114 | 26,489 | 49,105 | 31,529 | -58..58 |
| validation | 256 | 15,480 | 13,417 | 15 | 3,315 | 6,147 | 3,955 | -54..54 |
| held_out | 256 | 15,469 | 13,407 | 14 | 3,314 | 6,144 | 3,949 | -46..46 |

## Immutable identities

| File relative to evidence directory | SHA-256 |
| --- | --- |
| `manifest.json` | `8cca4fad573031bd9e0fdd7ef2aa392c3c71a2a4f6ce878d422e26acc991402e` |
| `output/games.jsonl` | `964f9e35e1e6b10650f573c26d7cc7d3021cc4db13b18d58966d93f477b86b81` |
| `output/train.jsonl` | `6068e80eed4d61155f2a0eb3d24737a3519c6caa9a3e19ea8340022d6384fe8d` |
| `output/validation.jsonl` | `a5fbc5a53323ce69009d5fa995076d3e8559206fc5a39a401b45a7d393d549cd` |
| `output/held_out.jsonl` | `a5ec55d4e33a65649a7c718a643cb79890111b91b2dce0700eeb12e498e8af11` |
| `output/trainer-manifest.json` | `c6adc4d2ad3795ec43883dc2d38a16a6fc034a204079a29ebd71fef724359c0f` |
| `output/report.json` | `05d7d9f2ab80a84cd934d1dd821d6f320d0a4755a1f93ac6ab47c826e95c1721` |
| `baseline.json` | `53fdb3a8d7b50c3bc8f1efded0a0989f0ae731b54e72f6c5e03e9f6c910c685d` |
| `baseline-report.json` | `b5bac69d20d6d9204ec6241e3a10430f28f51aa32389c04494067ac7c79a2f2d` |

The artifact declares `artifact_digest`
`530727f8931c81df4dff9762640d3b84fc8d8c0a77d417c2b7c2f3fd8e6293e8`.
The trainer report declares `report_digest`
`bc1f1065351662aa8e446f0912586f49f5a3dc0a333a837ea48205e98b5e34d6`.
Artifact validation passed. The held_out set covers 52 trainer phases and
contains 13,407 records. There are 228,454 nonzero sparse weights. Mean
squared error is 314.4795 for the trained artifact versus 316.7607 for zero
weights on the same held_out rows. This is diagnostic evidence and makes no
playing-strength claim.

## Reproduce and hand off

From the `reversi-adventure` checkout at the recorded generator version, set
`RANDOM_INPUT_MANIFEST` and `RANDOM_INPUT_OUTPUT_DIR` to new paths outside the
checkout, then run these separately:

```sh
make pattern-random-prepare RANDOM_INPUT_MANIFEST=/absolute/path/manifest.json
make pattern-random-generate RANDOM_INPUT_MANIFEST=/absolute/path/manifest.json RANDOM_INPUT_OUTPUT_DIR=/absolute/path/output
make pattern-random-verify RANDOM_INPUT_MANIFEST=/absolute/path/manifest.json RANDOM_INPUT_OUTPUT_DIR=/absolute/path/output
python3 tools/reversi-ai-training/training.py train --manifest /absolute/path/output/trainer-manifest.json --artifact /absolute/path/baseline.json --report /absolute/path/baseline-report.json
python3 tools/reversi-ai-training/training.py validate --artifact /absolute/path/baseline.json
```

The exact 0019 handoff is `baseline.json` and `output/validation.jsonl` at the
local evidence path above, with SHA-256 values from the table. Set 0019's
`REINFORCEMENT_VALIDATION_SOURCE=project-owned-random-games-v1`. The 0018
opening suite was not read.
