# Restore Rust CI compatibility with the stable toolchain

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Restore the `CI / test` check for pull requests and `main` when it runs the
repository's configured stable Rust toolchain. The completed change must retain
the existing legal-move bitmask behavior while making
`cargo clippy --workspace -- -D warnings` pass under the current stable
toolchain. This plan does not change Reversi rules, public APIs, or the toolchain
selection policy.

The reported failure is independent of PR #173: its merge commit
`9a5504a9718856b49170790488689a342a2aecae` combines workflow-only head commit
`b7e4198200e9dce726713ee2af9d2a1d55945c71` with `main` base
`b6d61b255fe8b9190a721bbeaa00ca8bc8ae4d21`. The failed `CI / test` log reports
Rust 1.98.1 rejecting the source already present on the base at
`rust/reversi-engine/src/moves.rs:20` as `clippy::manual_isolate_lowest_one`.

## Contract and design boundary

Black-box specification changes: none. `docs/specs/reversi-engine.md` defines
the legal-move result, but not its internal bit-extraction implementation; the
replacement must continue to return the same `u64` legal-move mask. No new
architectural decision is needed because this is a standard-library equivalent
of an existing local implementation and does not alter the Godot + Rust
architecture recorded in `docs/design-decisions/adr.md`.

## Change map

- (MODIFY) `rust/reversi-engine/src/moves.rs:16-29` — replace the manual
  lowest-set-bit isolation in `legal_moves` with the equivalent standard Rust
  integer API required by current Clippy.
- (DELETE) `docs/exec-plan/todo/0003-fix-rust-ci-main.md` — remove this resolved
  execution plan on the implementation branch after verification and PR
  preparation; its history remains in the implementation PR and Git.

## Execution steps

1. On a fresh `fix/fix-rust-ci-main` worktree created after this plan merges,
   update the internal lowest-set-bit expression at
   `rust/reversi-engine/src/moves.rs:20`. Preserve the candidate iteration and
   all resulting legal move bits; do not suppress the Clippy lint or relax
   `-D warnings` in `.github/workflows/ci.yml:20`.
2. Keep `docs/specs/reversi-engine.md` unchanged because the observable
   `legal_moves(board, color) -> u64` contract is unchanged. The existing
   `moves.rs` legal-move tests are the behavioral regression boundary.
3. Run formatting, the exact CI Clippy command, both package test commands,
   the GDExtension build, and the shared-library existence check. Use a
   task-specific writable Cargo home/target directory if the environment's
   default cache is read-only.
4. Delete this plan after implementation verification, prepare the execution
   PR through `/review-task`, and confirm its latest-head CI result. There is
   no linked local or external issue to close.

## Verification

Run from the repository root with a writable task-specific Cargo cache:

```sh
cargo fmt --all -- --check
cargo clippy --workspace -- -D warnings
cargo test -p reversi-engine
cargo test -p reversi-ai
cargo build -p reversi-godot
test -f target/debug/libreversi_godot.so
```

Then verify the implementation PR's latest `CI / test` check is successful.
