# Clippy clone-on-copy baseline failure

`cargo +1.98.1 clippy -p reversi-ai --all-targets -- -D warnings` fails on
existing `rust/reversi-ai/src/player.rs:102`, where `Board::clone()` is called
although `Board` implements `Copy`. This is unrelated to the performance
benchmark scope and should be repaired in a focused CI-maintenance change.
