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
| Unchecked transposition-table slot access (0032) | Against the safe equivalent, heuristic search was 1.29% slower and exact solving was 0.42% faster. Against the adopted `main`, heuristic search was 0.42% faster and exact solving was 1.00% slower. Neither comparison met the 5% adoption gate; the unchecked access adds a safety obligation. | [Safe checkpoint](https://github.com/yoskeoka/reversi-adventure/commit/5fc7473ce89fd237bec247694b80b093af6d1a33), [unsafe experiment commit](https://github.com/yoskeoka/reversi-adventure/commit/bbb425ef259e6c62e93f5294ed8d4f357a496c27), [measurement report](https://github.com/yoskeoka/reversi-adventure/blob/a24c797c8423464b813d2ae595fa546a9e9e9e5d/docs/references/reversi-ai-unsafe-cost-0032.md), [retained experiment PR](https://github.com/yoskeoka/reversi-adventure/pull/218) |

Plan 0030 separately revisits implementation costs for selected rejected search
methods after the current performance series closes. Its result may change this
record later.
