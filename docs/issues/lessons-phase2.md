# Lessons Learned: Phase 2 (Reversi AI)

## Patterns from Phase 2 Implementation

### 1. gdext Type Renames

- **Mistake**: Used `Dictionary` type from gdext, which was renamed to `VarDictionary` in v0.4.5
- **Pattern**: API type names change between gdext versions
- **Rule**: Always check the current gdext version's changelog for type renames before using Godot bridge types
- **Applied**: `rust/reversi-godot/src/bridge.rs` — any method returning dictionaries to GDScript

### 2. Sized Bounds on Trait Object Generics

- **Mistake**: Generic bound `E: BoardEvaluator` rejected `&dyn BoardEvaluator`
- **Pattern**: Trait objects are `!Sized` but generic bounds default to `Sized`
- **Rule**: When a function accepts `&dyn Trait`, the generic must use `+ ?Sized`
- **Applied**: `SearchEngine::search()`, `Negascout` impl — any generic that takes a trait object reference

### 3. clone_on_copy Clippy Lint

- **Mistake**: Used `.clone()` on Board (a `Copy` type with two u64 fields)
- **Pattern**: Clippy `clone_on_copy` lint catches unnecessary clone calls on Copy types
- **Rule**: Use `*` dereference for Copy types, not `.clone()`
- **Applied**: `bridge.rs` — `*self.game.board()` instead of `self.game.board().clone()`

### 4. needless_range_loop Clippy Lint

- **Mistake**: Used indexed loop `for i in 0..N { arr[i] = ... }`
- **Pattern**: Clippy `needless_range_loop` prefers iterators when index is only used for array access
- **Rule**: Prefer `for item in arr.iter_mut()` over indexed loops
- **Applied**: `search/tt.rs` — Zobrist key initialization

### 5. Post-Task Review Belongs to the Same Branch

- **Mistake**: Created a separate branch for post-task review findings, splitting them from the feature branch that produced them
- **Pattern**: Misapplied "fresh branch per task" rule — treated the review as a separate task instead of part of the same deliverable
- **Rule**: Post-task review artifacts (issues, lessons, skill changes) discovered during a task belong on that task's branch. The "fresh branch" rule is about not mixing *unrelated* work, not about splitting a task's own outputs.
- **Applied**: Any post-task review after execution — commit findings on the feature/fix branch before creating the PR

### 6. Issue Tracking Location

- **Mistake**: Created GitHub issues via `gh issue create` without corresponding `docs/issues/` files
- **Pattern**: The AI-Centered Development workflow uses `docs/issues/` as the AI's memory, not GitHub issues alone
- **Rule**: Always create `docs/issues/<name>.md` first; optionally mirror to GitHub issues
- **Applied**: All post-task review findings

## Related

- GitHub Issue: https://github.com/yoskeoka/reversi-adventure/issues/10
