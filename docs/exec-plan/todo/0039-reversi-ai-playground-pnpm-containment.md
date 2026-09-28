# Confine Reversi AI playground pnpm artifacts
> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## Objective and completion boundary

Make the local Reversi AI playground's Node dependency lifecycle unambiguous and reproducible from the repository root. `pnpm install` must run in `tools/reversi-ai-playground`; its committed manifest and lockfile stay there, and the root remains free of npm manifests and lockfiles. A successful implementation provides root-level Make entry points for install and startup, documents both forms of invocation, and verifies that they select the playground directory.

This plan covers the development-only playground tooling only. It does not change Godot, Rust, release dependencies, or the already committed playground dependency versions.

Addresses: N/A

## Current evidence

- `tools/reversi-ai-playground/package.json` defines the private `reversi-ai-playground` package and pins pnpm 10.17.1.
- `tools/reversi-ai-playground/pnpm-lock.yaml` is the committed lockfile for that package; `tools/reversi-ai-playground/.gitignore` excludes its `node_modules/` and `dist/` output.
- `tools/reversi-ai-playground/README.md` lines 7-12 documents `pnpm install` and `pnpm dev` only after changing to the playground directory.
- `Makefile` lines 1-6 defines `PLAYGROUND_DIR := tools/reversi-ai-playground` and `make playground`, but has no install entry point.
- The reported root `package.json` is the empty `npm init` template and its root `pnpm-lock.yaml` has only importer `.`. They are untracked local artifacts and are not playground inputs.

## Change map

- `(MODIFY) docs/specs/reversi-ai-local-playground.md` — state package ownership: the manifest and lockfile live only in the playground directory, generated dependencies are local ignored output, and root-level setup uses Make.
- `(MODIFY) tools/reversi-ai-playground/README.md` — put root-level `make playground-install` and `make playground` instructions first, retain explicitly directory-scoped pnpm commands, and state that root npm files are not inputs or committed artifacts.
- `(MODIFY) Makefile` — add a phony `playground-install` target which changes to `$(PLAYGROUND_DIR)` and runs `pnpm install`; retain `playground` as the startup target in the same directory.
- `(DELETE, local generated artifacts) repository-root package.json, pnpm-lock.yaml, node_modules/` — remove the reported untracked accidental files from the affected checkout during execution; do not add an ignore rule that hides a wrong-root package manifest.

## Black-box specification changes

`docs/specs/reversi-ai-local-playground.md` will guarantee:

1. The only committed Node manifest and pnpm lockfile for this tool are `tools/reversi-ai-playground/package.json` and `tools/reversi-ai-playground/pnpm-lock.yaml`.
2. `make playground-install` resolves dependencies in that directory; `make playground` starts the installed tool in that directory.
3. `tools/reversi-ai-playground/node_modules/` and its build output are local ignored artifacts. Repository-root npm manifests, pnpm lockfiles, and `node_modules/` are neither tool inputs nor output contracts.

## Execution steps

1. On a fresh `fix/reversi-ai-playground-pnpm-containment` worktree created after this plan merges, update the black-box spec first with the ownership and root Make-entry-point contract.
2. Add `playground-install` to the Makefile, reusing `PLAYGROUND_DIR`, and confirm both install and startup target commands run after changing to the playground directory.
3. Rewrite the playground start documentation so a user at the repository root can install and run it without manually locating the package. Keep the direct commands with an explicit `cd tools/reversi-ai-playground` prefix.
4. Remove only the reported untracked root artifacts in the checkout where they exist. Do not commit them and do not create root package-manager configuration to mask future invocation mistakes.
5. Run the focused checks below and inspect `git status --short` to ensure that a correct package install produces only the ignored playground `node_modules/` directory, with no root `package.json` or `pnpm-lock.yaml`.
6. Delete this plan as part of the execution closeout after verification and PR preparation, as required by the active-only plan lifecycle.

## Dependencies and parallelism

The spec update must precede Makefile and README changes. Documentation and Makefile edits can then proceed together. Cleanup occurs only in the checkout containing the reported untracked artifacts.

## Verification

```sh
make -n playground-install
make -n playground
pnpm --dir tools/reversi-ai-playground install --frozen-lockfile
pnpm --dir tools/reversi-ai-playground test
pnpm --dir tools/reversi-ai-playground lint
pnpm --dir tools/reversi-ai-playground build
git status --short
```

The dry-run output must include `cd tools/reversi-ai-playground`. After installation, Git status must not report root `package.json`, root `pnpm-lock.yaml`, or root `node_modules/`; the lockfile at `tools/reversi-ai-playground/pnpm-lock.yaml` must remain unchanged.
