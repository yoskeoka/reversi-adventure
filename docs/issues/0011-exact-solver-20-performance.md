# Exact solver 20-empty performance follow-up

## What happened

While extending the default exact-solver threshold to 16 empty squares, the
same legal 20-empty position was solved independently as a supplemental check.
The project solver did not complete its exhaustive search within the explicit
five-minute verification budget.

## Evidence

- The deterministic legal position has Black to move and 20 empty squares.
  Its row-major board is
  `..B.W.....BBW.W....WWWWW..WWBBWWB.WBBWWW.BBWWBW.WWBWBBB.BBBBBBB.`.
- Pinned Egaroucid v7.8.1 `-solve` at fixed depth 20 reports a final
  root-side score of `+26` for Black.
- `EndgameSolver` with `SearchBudget::with_time_limit(Duration::from_secs(30))`
  returns the documented non-exact fallback.
- Repeating the same solve with a five-minute budget also returns non-exact;
  it has no partial exact score or PV.
- The 0026 exact-PVS candidate, which clears its timing gate, completes the
  same board with Black `+26` in 39.422 seconds and 16,744,258 nodes under a
  five-minute monotonic budget. The default threshold remains 16 while the
  performance series continues.

## Effect

The 16-empty default remains the supported exact-solver boundary. The
20-empty fixture now completes within the five-minute verification budget
after the accepted exact-search changes. This result alone does not establish
a supported 20-empty threshold across other positions.

## Next

- Write a dedicated execution plan before changing the threshold beyond 16.
- Finish parent plan 0020, including child 0029 and its final accumulated
  benchmark. Close this local issue with that plan once its completion
  conditions are verified.
- Use a separate plan and profiling across legal 17--20-empty positions before
  considering a higher supported threshold.
- Keep exhaustive final-disc correctness and the existing interruption result
  contract. Re-check candidate positions against the external oracle.

## Priority

The original five-minute fixture failure is resolved. A higher supported
threshold remains separate work.
