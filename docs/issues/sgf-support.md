# SGF (Smart Game Format) Support

## Description

Add support for importing and exporting game records in SGF format, which is the standard format for board game records (Go, Othello, etc.).

## References

- SGF specification: https://www.red-bean.com/sgf/
- SGF for Othello overview (Japanese): https://qiita.com/tanaka-a/items/b7fb505b881857b04983

## Why

- SGF is widely used in the Othello community for sharing game records
- Enables importing professional game records for study/replay
- Useful for the puzzle system (Phase 4) — problems can be distributed as SGF
- Interoperability with existing Othello tools and databases

## Scope

- Parse SGF files into Game state
- Export Game state to SGF format
- Handle SGF properties relevant to Othello (B, W, AB, AW, SZ, etc.)

## Priority

Low — not blocking any current milestone. Can be planned as a future execution task.
