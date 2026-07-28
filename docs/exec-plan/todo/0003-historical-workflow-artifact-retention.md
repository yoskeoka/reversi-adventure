# Historical workflow artifact retention

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective

Remove completed plans and local issues from the working tree, retaining their
review trail in Git and PRs instead of `done/` directories or commit-message
copies.

## Change map

- (MODIFY) `AGENTS.md` completion guidance, `docs/exec-plan/todo/README.md`, `docs/issues/README.md`, and current workflow docs.
- (MODIFY) `tools/workflow-lint.sh` and focused tests to distinguish mandatory active plans from closeout deletion; parse the deleted matching plan's explicit `Addresses:` links and require deletion of resolved local issues while retaining external issue closure metadata.
- (DELETE) `docs/exec-plan/done/**`, `docs/issues/done/**`, and their empty directories.

## Verification

Verify compliant and non-compliant closeout diffs plus active-plan enforcement; run `cargo test -p reversi-engine`, `cargo test -p reversi-ai`, `cargo clippy --workspace -- -D warnings`, workflow-linter checks, `git diff --check`, and Git-history retrieval of a removed artifact.
