# Random-game reinforcement inputs (0032)

The complete production inputs and trained baseline are outside the
`reversi-adventure` checkout at
`/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.local/reversi-ai-inputs-0032-v2/`.
The files are local evidence, not committed training data. Regenerate them
from the commands below if that path is unavailable. The separate 0019
human-operated cycle has not been started.

## Frozen generation

- Producer checkout: `790209d9c69fc109141a9d5190e694b52edd1794`.
- Merged-main base: `bb74190953f3bdfc06b7182626d9d0c8fe51b268`.
- Generator SHA-256: `fc0392c2a04a39cf19b310337002cf558b6b4b556be870fbec8cc16890e06e45`.
- Imported source SHA-256: `reinforcement.py`
  `137c7f24c96b06a3fb673fe0c7a220a276d94a6ded1ad8ca797470d37db2cb0a`,
  `training.py`
  `e78b93123a85f957c59783c0897d9605b41efbf777ea3a5236dd9b48360e7293`.
- License/source: `CC0-1.0`, `project-owned-random-games-v1`.
- Seed: `20260926`; games: train 2,048, validation 256, held_out 256.
- Start: eight placements; maximum: 128 turns including passes.
- The frozen manifest contains exact globally assigned game-id lists and the
  SHA-256-derived per-game seed, SplitMix64 move-index, and independent split
  shuffle rules.

An 8-game pilot took 0.55 s wall and 18,540 KB peak RSS. Before production,
the generation cap was set to 10 min wall and 1 GiB peak RSS. Production
generation took 2 min 19.01 s and 365,836 KB peak RSS. Full replay verification
took 4 min 35.46 s and 639,600 KB peak RSS. Training took 9 min 40.51 s and
1,526,416 KB peak RSS; the generation cap does not apply to training.

The verifier passed every game and output. The split summary from its report:

| Split | Games | Turns, including passes | Records | D4 duplicates | Opening | Midgame | Endgame | Target range |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| train | 2,048 | 123,621 | 107,123 | 114 | 26,489 | 49,105 | 31,529 | -58..58 |
| validation | 256 | 15,480 | 13,417 | 15 | 3,315 | 6,147 | 3,955 | -54..54 |
| held_out | 256 | 15,469 | 13,407 | 14 | 3,314 | 6,144 | 3,949 | -46..46 |

## Immutable identities

| File relative to evidence directory | SHA-256 |
| --- | --- |
| `manifest.json` | `bbf627931acd1b3ca45ee6f635a3b6a89a6cfce5f30516ebafe333e035b3969f` |
| `output/games.jsonl` | `964f9e35e1e6b10650f573c26d7cc7d3021cc4db13b18d58966d93f477b86b81` |
| `output/train.jsonl` | `4700cafaaabc985a862cd62ad050fef0337bceb9c012b1dd01136ac54079361b` |
| `output/validation.jsonl` | `efc3a83a008dec92d494cd82214d9ebbc73baa307443ff6bdac4e72b7f3a0303` |
| `output/held_out.jsonl` | `49328cc7f2793efed6e05c1c956d5336757ac190817b56686f2f07333709e83a` |
| `output/trainer-manifest.json` | `ec0c7f3c17d8a3488ef7baa67a83aa53052b88dae499a7ccfc285e439d4d3dc8` |
| `output/report.json` | `9824cad357151fb763f5ae1dcf565c97966565c31add5aca967084453c96706a` |
| `baseline.json` | `d206b9bf5a86c7670c1e7c9e2cdbbeb442a94d18ba3d8efeb3423b11cbb3eb8f` |
| `baseline-report.json` | `6946ab2d8a2f8393b3f26285d7587a22e4ea665c74eb737310fb7262bb96d9a8` |

The artifact declares `artifact_digest`
`c817cd6d3fe582394649716c61335f185084558d30c1a7ec988dbc33102a0f77`.
The trainer report declares `report_digest`
`ab35ae6784c6b490a41f7b629ec784cf908c918e681f6f478a0c1b6a1343e29a`.
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
