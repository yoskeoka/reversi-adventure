# Exact solver does not complete the 20-empty fixture within the verification budget

## What happened

While extending the default exact-solver threshold to 16 empty squares, the
same legal 20-empty position was solved independently as a supplemental check.
The project solver did not complete its exhaustive search within the explicit
five-minute verification budget.

## Evidence

- The deterministic legal position has Black to move and 20 empty squares.
- Pinned Egaroucid v7.8.1 `-solve` at fixed depth 20 reports a final
  root-side score of `+26` for Black.
- `EndgameSolver` with `SearchBudget::with_time_limit(Duration::from_secs(30))`
  returns the documented non-exact fallback.
- Repeating the same solve with a five-minute budget also returns non-exact;
  it has no partial exact score or PV.

## Effect

The 16-empty default remains the supported exact-solver boundary. The
20-empty position is evidence that the present search speed is insufficient to
raise that threshold safely.

## Next

- Write a dedicated execution plan before changing the threshold beyond 16.
- Profile the solver on legal 17--20-empty positions and identify sound
  ordering, cache, parity, or stability improvements.
- Keep exhaustive final-disc correctness and the existing interruption result
  contract. Re-check candidate positions against the external oracle.

## Priority

Medium. This is a strength and responsiveness follow-up, not a correctness
regression in the supported 16-empty profile.
