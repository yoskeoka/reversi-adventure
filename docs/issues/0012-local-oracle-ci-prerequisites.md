# Local oracle CI cannot complete without its build prerequisites

## What happened

While verifying PR #191 locally, `make oracle-ci` could not complete in the
development sandbox. The repository CI completed the same external-oracle
harness successfully on the PR head.

## Evidence

- The default local Rust 1.95.0 cannot compile the existing
  `isolate_lowest_one` call in `rust/reversi-engine/src/moves.rs`.
  `cargo +1.98.1` compiles the workspace and candidate CLI.
- The oracle's default Egaroucid cache at
  `~/.cache/reversi-adventure/egaroucid/7.8.1` is read-only in the sandbox.
  Setting `REVERSI_ADVENTURE_ORACLE_CACHE` to a writable `/tmp` directory
  passes that cache-creation step.
- The Egaroucid bootstrap then stops because `cmake` is unavailable. The
  oracle harness reports `required external command is unavailable: cmake`.

## Effect

Local end-to-end `make oracle-ci` verification is unavailable in this
environment. The focused oracle harness tests can run, and the PR's remote
`Verify external AI oracle harness` check is the current end-to-end evidence.

## Next

- Before changing setup behavior, create an execution plan for a reproducible
  local oracle prerequisite check. It should define the required Rust
  toolchain, writable cache location, and Egaroucid build tools such as CMake.
- Keep the Egaroucid binary and source cache external to Rust, GDExtension, and
  release code.

## Priority

Medium. This blocks local oracle CI reproduction but does not change the
project AI's search or oracle contracts.
