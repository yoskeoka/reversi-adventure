# Historical workflow artifact retention

> **Execution**: Follow the Plan First and PR rules in `AGENTS.md`; this repository has no checked-in `/execute-task` or `/review-task` skill.

## Objective

Remove completed plans and local issues from the working tree, retaining their
review trail in Git and PRs instead of `done/` directories or commit-message
copies.

## Change map

- (MODIFY) `AGENTS.md` completion guidance, `docs/exec-plan/todo/README.md`, `docs/issues/README.md`, and `docs/issues/0007-self-retrospective.md`, which currently documents the `todo/` to `done/` transition.
- (MODIFY) `tools/workflow-lint.sh`; (NEW) `tools/test-workflow-lint.sh` as a POSIX shell fixture harness that invokes the linter against temporary Git repositories and covers mandatory active plans, compliant closeout deletion, omitted linked local issues, and external closure metadata.
- (DELETE) `docs/exec-plan/done/**`, `docs/issues/done/**`, and their empty directories.

## Verification

Verify compliant and non-compliant closeout diffs plus active-plan enforcement; run `cargo test -p reversi-engine`, `cargo test -p reversi-ai`, `cargo clippy --workspace -- -D warnings`, workflow-linter checks, `git diff --check`, and Git-history retrieval of a removed artifact.
