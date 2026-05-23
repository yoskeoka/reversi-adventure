# Align workflow-lint checkout pin with repo workflow standard

## Summary

The new repo-local `.github/workflows/workflow-lint.yml` uses the shared
workflow asset pin for `actions/checkout`, while the existing repo CI workflow
still uses an older pinned checkout revision.

## Details

- `.github/workflows/ci.yml` keeps the repository's current checkout pin.
- `.github/workflows/workflow-lint.yml` now uses the shared workflow pin copied
  from the workspace rollout.
- Current checks are green, so this is not urgent, but the repository now has
  mixed checkout pin revisions.

## Proposed Solution

Decide whether this repository should:

1. align all workflows to the shared workflow pin, or
2. intentionally keep a repo-specific older pin and document that exception

If alignment is chosen, update the repository workflow set together rather than
patching only `workflow-lint.yml` in isolation.
