# Reversi AI Clippy rejects an existing clone of a Copy board

## What happened

The required `cargo +1.98.1 clippy -p reversi-ai --all-targets -- -D warnings`
gate fails before this timing-profiler change is analyzed.

## Evidence

- `rust/reversi-ai/src/player.rs:102` calls `game.board().clone()` although
  `Board` implements `Copy`.
- Clippy 1.98.1 reports `clippy::clone_on_copy` and suggests dereferencing the
  returned board reference instead.
- The same source is present on `main` at
  `4710824988fb51efe4974e0768474e4efef655c4`.

## Effect

The focused profiler tests pass, but the all-target Reversi AI Clippy gate is
currently blocked by an unrelated pre-existing warning.

## Next

Create a focused plan to remove the redundant clone and re-run the affected
quality gate. Keep this timing-profiler execution scoped to its approved
contract.

## Priority

Low. This is a local quality-gate blocker without a runtime behavior change.

## 0047での任意all-targetsチェック（2026-10-10）

Rust 1.98.1の `cargo clippy --workspace --all-targets -- -D warnings` で
上記 `player.rs` の警告に加え、既存のendgameテストに次の2件を確認した。

- `endgame.rs:1337` の `transcript.as_bytes().chunks_exact(2)`:
  `clippy::chunks_exact_to_as_chunks`（constant chunk size）。
- `endgame.rs:1567` のclosure内 `return;`:
  `clippy::needless_return`（unneeded return statement）。

対象の式は0047で変更していない。CI必須の
`cargo clippy --workspace -- -D warnings`、engine/AI tests、Godot build、fmtは成功した。
任意all-targetsのtest lintは本score移行とは分離し、既存issueを未解決として保持する。
