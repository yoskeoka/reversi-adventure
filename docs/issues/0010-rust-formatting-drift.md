# Rust formatting drift in existing workspace files

## Summary

`cargo fmt --all -- --check` reports formatting differences in existing Rust
files under `rust/reversi-engine`, `rust/reversi-ai`, and `rust/reversi-godot`.

## Observed

- The differences were present before this execution branch changed Rust code.
- The requested workflow-artifact retention change does not require Rust source
  edits.
- The targeted engine and AI tests and workspace Clippy checks pass.

## Proposed Resolution

Run `cargo fmt --all` in a separate maintenance change, review the complete
formatting diff, and include the resulting changes only if the project adopts
that formatting baseline.

## Discovered During

Historical workflow artifact retention execution.
