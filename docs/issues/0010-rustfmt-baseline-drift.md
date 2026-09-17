# Rust fmt drift

## What happened

The Rust fmt check fails on code already in `main`.
This is not part of the CI fix.

## Test

- Rust 1.98.1
- `cargo fmt --all -- --check`

The check lists old code in `rust/reversi-ai`, `rust/reversi-engine`, and
`rust/reversi-godot`. It does not change files.

## Effect

The fmt check stays red until a full fmt pass.
The `CI / test` job does not run fmt. Its Clippy, tests, build, and file check
pass.

## Next

Use a new task to set one fmt style for the whole repo.
