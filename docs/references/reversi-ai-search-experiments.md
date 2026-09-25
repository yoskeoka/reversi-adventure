# Reversi search experiments not adopted

These experiments did not meet the performance adoption gate in the measured
workloads. This is a record of the tested candidates, not a claim that the
underlying methods are ineffective in every position or implementation. The
linked reports retain the measurements and comparison conditions.

| Experiment | Why it was not adopted | Evidence |
| --- | --- | --- |
| Search-owned principal-variation storage and a compact exact cache (0023) | The measured midgame gain did not clear the adoption gate, while exact solving became slower. The combined result did not isolate the storage and exact-path costs. A narrower follow-up remains in plan 0029. | [Report](reversi-ai-search-performance-0023.json), [retained candidate](https://github.com/yoskeoka/reversi-adventure/pull/200) |
| Aspiration windows around the previous iteration's score (0024) | Midgame savings were too small once failed-window retries were included. Exact solving does not use this method. | [Report](reversi-ai-search-performance-0024.json), [retained candidate](https://github.com/yoskeoka/reversi-adventure/pull/203) |
| Enhanced transposition cutoffs through child-position probes (0025) | The extra probes and identity checks cost more time than the reduced midgame search saved. Exact solving does not use this method. | [Report](reversi-ai-search-performance-0025.json), [retained candidate](https://github.com/yoskeoka/reversi-adventure/pull/207) |
| Proven stable-disc cutoff from corner runs and full edges (0028) | Exact search found too few cutoffs to repay the detector's repeated work. | [Report](reversi-ai-search-performance-0028.json), [retained candidate](https://github.com/yoskeoka/reversi-adventure/pull/211) |

Plan 0030 separately revisits implementation costs for selected rejected search
methods after the current performance series closes. Its result may change this
record later.
