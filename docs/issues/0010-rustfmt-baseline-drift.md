# Existing Rust source is not rustfmt-clean under stable 1.98

## Summary

The execution-plan formatting check fails on Rust source that is already on
`main`. The failure is unrelated to the Rust CI Clippy fix in
`rust/reversi-engine/src/moves.rs`.

## Evidence

- Toolchain: Rust 1.98.1 (`rustc 1.98.1`)
- Command: `cargo fmt --all -- --check`
- Representative existing differences: `rust/reversi-ai/src/config.rs`,
  `rust/reversi-ai/src/eval/novice.rs`, `rust/reversi-engine/src/moves.rs`,
  and `rust/reversi-godot/src/bridge.rs`
- The check reports formatting diffs but does not modify files.

## Impact

The repository-wide formatting gate cannot pass without a separate formatting
cleanup. The configured `CI / test` workflow does not run `cargo fmt`; its
Clippy, package-test, GDExtension build, and shared-library checks are
unaffected.

## Follow-up

Handle the repository-wide rustfmt baseline in a separate scoped change after
deciding whether the current stable formatter output should become the project
formatting standard.
