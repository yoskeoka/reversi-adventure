# Multi-Platform CI

## Description

CI workflow only runs on `ubuntu-latest` and verifies the Linux shared library (`.so`). Since the project targets Steam (multi-platform), CI should also verify macOS (`.dylib`) and Windows (`.dll`) builds.

## Current State

`.github/workflows/ci.yml` runs:
- `cargo test -p reversi-engine` (platform-independent, OK)
- `cargo clippy --workspace` (platform-independent, OK)
- `cargo build -p reversi-godot` (builds only Linux `.so`)
- `ls target/debug/libreversi_godot.so` (Linux-only verification)

## Proposed Solution

Add matrix strategy with `ubuntu-latest`, `macos-latest`, and `windows-latest`. Conditionally verify the correct library extension per platform:
- Linux: `libreversi_godot.so`
- macOS: `libreversi_godot.dylib`
- Windows: `reversi_godot.dll`

## Priority

Low — not blocking development. Linux CI catches most issues. Multi-platform builds become important closer to Steam release.
