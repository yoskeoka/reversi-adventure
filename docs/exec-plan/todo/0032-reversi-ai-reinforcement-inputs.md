# Child plan: prepare project-owned random-game inputs for reinforcement

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Produce one repeatable baseline pattern artifact and one separate validation
JSONL for the human-run 0019 cycle. Draw labelled positions from complete,
legal random games. Freeze the seed, game split, source version, and file
digests. Later tests will measure playing strength against the 0018 target.

The checked-in `tiny` trainer and validation files serve as test fixtures.
This plan creates fresh data for the production baseline and selection set.
It ends when the inputs, trainer output, and independent checks are recorded.
The human runs the separate, long 0019 command.

## Existing references

- `docs/specs/reversi-ai.md:118-194` -- training record, artifact, and 0019
  validation contracts.
- `tools/reversi-ai-training/training.py:162-309` -- manifest and record
  validation, split leakage checks, sparse artifact generation, and report.
- `tools/reversi-ai-training/reinforcement.py:58-124` -- project-owned legal
  move, move application, D4, and deterministic opening helpers.
- `tools/reversi-ai-training/reinforcement.py:291-308` -- validation record
  requirements and canonical position keys.
- `tools/reversi-ai-training/fixtures/tiny-manifest.json` and
  `tools/reversi-ai-training/fixtures/reinforcement-validation-v1.jsonl` --
  bounded test fixtures only.
- `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md:1-105`
  -- downstream human-run manifest and candidate boundary.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- generated-game provenance, split,
  replay, target, and digest contracts for 0019 inputs.
- (NEW) `tools/reversi-ai-training/random_inputs.py` and focused tests --
  deterministic legal random games, complete replay, disjoint record files,
  trainer manifest, and fail-closed verification.
- (MODIFY) `tools/reversi-ai-training/README.md` and `Makefile` -- separate
  prepare/generate/verify/train commands with output paths outside the checkout.
- (MODIFY) `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md`
  -- require the verified 0032 inputs before freezing the production manifest.
- (NEW) a tiny versioned generator fixture and a compact immutable input
  report schema. Production records remain outside the checkout.

## Black-box contract and work

1. Freeze a versioned generator manifest before play. It identifies the merged
   source commit and generator digest, `CC0-1.0` project-owned provenance,
   master seed, per-game seed derivation and random-move rule, split game
   counts, record start ply, maximum turns,
   and output schema. The initial bounded configuration is 2,048 training,
   256 validation, and 256 trainer-held-out games with records beginning after
   eight legal placements: at most about 133,000 sampled decisions before
   duplicate removal. The command may override counts only before the
   manifest is frozen; each split must contain complete games. A small timing
   pilot must establish a wall-clock and peak-memory cap before production
   generation; if the configuration exceeds the cap, revise and freeze a new
   manifest before generating production records.
2. Derive an independent PRNG seed for each game from the master seed and a
   globally unique game id using a specified stable algorithm. Distinct game
   ids must produce distinct seeds. Start every game from the canonical initial
   board. Select uniformly among sorted legal moves with that game's PRNG.
   Pass only when required, finish at the actual game-over state, and use the
   final black-minus-white disc
   count to label each recorded position from its side's perspective. Do not
   replace this target with the search engine's wipeout `+64/-64` score.
   Record every move, pass, terminal board, disc counts, game seed/id, and a
   game digest. A malformed, timed-out, or incomplete game fails the set.
3. Assign whole games to `train`, `validation`, or `held_out` before generation.
   Emit nonterminal version-1 records only after the configured start ply.
   Deduplicate by the canonical absolute-color D4 board plus side key across
   all splits in deterministic game/turn order, while retaining all skipped
   decisions in replayable game logs. Require nonempty records in each split
   and report per-split, per-phase and legal-move-count distributions, plus
   duplicate counts. Require coverage of opening, midgame, and endgame
   positions in every split; fail before training if any phase is empty. The
   validation JSONL must have the provenance fields expected by 0019 and
   remain disjoint from both training and held-out records.
4. Emit canonical JSONL, a version-1 training manifest that pins each split
   input's SHA-256/source/license, and a report that pins every game, split,
   output digest, record count, phase count, and target range. Write the report
   last as the completion marker. A verifier independently replays games,
   recalculates targets and canonical keys, and rejects missing, extra, changed,
   or cross-split records. Identical frozen inputs produce byte-identical
   outputs.
5. Run the existing offline trainer on these inputs. Validate the resulting
   baseline artifact and report, record their SHA-256 and declared digests,
   held-out metrics, phase coverage, and nonzero-weight counts. Compare the
   trained artifact against a zero-weight baseline on the held-out records;
   report whether its held-out error improves. These diagnostics are
   not a strength claim. Give 0019 the exact baseline artifact
   and separate validation JSONL paths/digests. Keep 0018 openings unread;
   0018 later compares its suite keys with these positions and 0019 evidence.

## Dependencies and sequencing

- Requires merged PR #221 and precedes the production 0019 manifest and its
  human-operated self-play. It neither starts that cycle nor changes its
  bounded update rule.
- Do not use the strategic evaluator as the sole data policy. The user chose
  legal random games to broaden position coverage; their outcome labels still
  describe random continuations and may yield a weak baseline.
- AlphaZero-like repeated self-play, search-guided targets, and model/policy
  updates remain successor experiments if the 0018 acceptance gate misses.
  They need a new executable plan and fresh validation data; the 0018 suite
  cannot be used to tune them.

## Verification

- Unit tests for reproducible but distinct per-game random streams, uniformly
  indexed legal move choice,
  passes, terminal replay, actual disc-difference targets, game-level split
  assignment, D4 duplicate handling, and malformed/partial output rejection.
- Run a small fixture twice and compare raw game, record, manifest, and report
  bytes; independently recompute every declared digest and aggregate.
- Run the bounded production generation after a local timing preflight, then
  the existing trainer and artifact validator. Verify that the 0019 manifest
  accepts the generated baseline/validation inputs without starting self-play.
- Applicable Python/Rust tests, Clippy, workflow lint, and `git diff --check`.

## Addresses

- N/A
