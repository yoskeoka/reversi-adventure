# pinact cannot pin `dtolnay/rust-toolchain@stable`

## Summary

During the `pinact` rollout, `pinact run .github/workflows/ci.yml` failed on this step:

```text
.github/workflows/ci.yml:15
- uses: dtolnay/rust-toolchain@stable
```

`pinact` still pinned the surrounding `actions/checkout` and `Swatinem/rust-cache` references, but it could not rewrite the floating `@stable` ref.

## Impact

- The repository now follows the `pinact` operator path for supported action references.
- `dtolnay/rust-toolchain@stable` remains mutable and outside the current rollout's automatic pinning.

## Follow-up

- Confirm whether `dtolnay/rust-toolchain` has a supported immutable release/tag strategy that `pinact` can manage.
- If not, decide whether this workflow should keep `@stable`, switch to a different supported ref policy, or adopt an explicit exception mechanism.
