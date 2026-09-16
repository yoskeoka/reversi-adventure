# Workflow linter specification

## Goal

The workflow linter makes the repository's execution-plan lifecycle observable
before push and in CI. It reports workflow findings as warnings and always exits
successfully so a finding remains reviewable without becoming an implicit merge
gate.

## Interface and warning behavior

The linter accepts the following commands:

```text
tools/workflow-lint.sh --mode=pre-push
tools/workflow-lint.sh --mode=ci [--pr-title=TITLE] [--pr-body=BODY] [--report-file=PATH]
```

It resolves the comparison base from `origin/${GITHUB_BASE_REF}` when that
environment variable is set, otherwise from `origin/main`. If the base or the
comparison cannot be resolved, it reports an advisory warning and skips only
diff-dependent checks. Branch and active-plan checks still run. The process
always exits with status 0 for a valid invocation. Invalid arguments or a
missing mode return a usage error.

Warnings identify a primary finding, its rationale, and (for fixable findings)
the expected remediation. When a report path is supplied, the same findings
are emitted as JSON Lines together with a summary count.

## Active workflow records

- A `feat/<name>` or `fix/<name>` branch has a matching active execution plan in
  `docs/exec-plan/todo/` whose filename ends in `-<name>.md`.
- Active plans and issues use `<sequence>-<name>.md` filenames. `README.md` is
  exempt from this naming check.
- `plan/*`, `chore/*`, and `docs/*` branches do not require an execution plan.
- Normal repository discovery considers only active plans and unresolved issues.
  Completed records are not recreated under a historical archive directory.

## Completion closeout

An execution branch completes its matching plan by deleting the active plan in
the branch diff. The linter accepts that deletion as the closeout state and
uses the matching plan content from the diff's merge-base side when it needs
completion metadata. A plan without linked issues may be deleted on its own.

The implementation PR and Git history are the retrieval path for completed
plans and resolved local issues. The linter warns if a historical archive
directory is present and does not require a replacement file there.

## Linked issue metadata

If the deleted plan's `Addresses:` entry names local paths under
`docs/issues/`, every explicitly linked issue is deleted in the same branch
diff. The entry may list paths on the same line or on following bullet lines.
The PR body may instead identify a linked issue and explicitly explain that it
remains open.

If the deleted plan's `Addresses:` entry names a full external GitHub issue URL,
CI requires a matching closing keyword in the PR body (`Closes #123` for a
same-repository issue or `Closes <full-url>` for another repository), unless
the PR body explicitly explains why the issue remains open. Local pre-push
checks do not require PR-body metadata.

These checks apply only to the execution branch whose description matches the
deleted plan. The linter does not infer completion from unrelated file changes.

## Exit behavior

The linter always exits 0 for a valid invocation, including when it reports
fixable or advisory warnings. Invalid arguments and a missing mode return a
usage error.
