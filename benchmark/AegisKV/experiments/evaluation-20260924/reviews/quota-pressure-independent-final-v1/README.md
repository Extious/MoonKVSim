# Independent final O3 artifact review

PASS; no substantive error found. This review reads the sealed `quota-pressure-postreview-v1` artifacts directly, without importing or running the simulator. It does not modify the source package or paper.

- Rehashed all 1,061 files bound by `FINAL_AUDIT.json`, before and after the review; checked frozen sources, protocol/plan inputs, and all 72 run completion bindings.
- Recomputed pressure from raw control-entry worker/rank flags: 12/36 F0 runs and 0/36 F1 runs. Every admission succeeded; no capacity-denied admission occurred. Admission pressure fields are sticky-after-attempt observations, not counts of new pressure triggers. Static low headroom is not counted as pressure.
- Identified exactly two native adaptive multiplicative decreases, at margin 32 MiB in F0 (one per DMA setting): 32 MiB to 24 MiB. Both match their raw control records and the declared factor 0.75.
- All 12 runs with observed pressure have their first control pressure flag and first observed sticky admission flag strictly after target workflow `ebe557cd696ab6ea` completes. First pressure control is at 11.3 s; target finishes at 7.671430958 s (DMA 0) or 7.683694634 s (DMA 0.005).
- All 24 adaptive/fixed comparisons have exactly equal decoded workflow endpoint dictionaries: 6 conditions (3 margins × 2 DMA shares) × 2 fault modes × 2 comparators (`fixed128`, `fixed4096`). This is 96 exact per-workflow comparisons, including start, finish, and WCT. The null result is retained.
- Verified the actual online predictor identifier, serialized model hash, all 52 deployed role priors, and guard 910,471,105 ns. The four input workflows are disjoint from model training workflows. Relative to the original workload, only `prior_ns` changes.
- Independently compared the separately declared observer validation with its matching official run: summary bytes and decompressed events/flows bytes are equal; flows contain 61,559 lines. This one validation run is outside the 72 formal conditions.

Statistical unit: four dependent workflows and one fixed logical fault identity, reused across parameter/policy/fault conditions. The 72 conditions, 24 comparison pairs, and 96 per-workflow comparisons are not independent repetitions. These results establish neither pressure during F1 recovery nor an adaptive recovery advantage under pressure. They remain simulator evidence, not native-kernel or physical deployment measurements. The full resource-ledger integration is covered by the separately sealed accounting auditor; this bounded review independently checks the counts, endpoints, timing, bytes, and bindings listed above.

Source `FINAL_AUDIT.json` SHA-256: `a095d6ea57f70cd52cb37f08e548eb93727df370a4c5a20699d4afeaf63113e0`.

Source `INDEPENDENT_ACCOUNTING_AUDIT.json` SHA-256: `29ced822617d3dab286dbddee1606a9a66830fa2a1af41ae0e8206d81659b877`.

Serialized model SHA-256: `e6e2e9d3f96a75bd9df911f37c8ca751e54f41d421997eb4f74f550111e04368`.

`audit.py` is the executable independent source. `run-counts.csv` records every formal condition; `pressure-timing.csv` preserves all 12 pressure-versus-target timings; `adaptive-fixed-pairs.csv` and `adaptive-fixed-workflows.csv` preserve all 24 and 96 exact comparisons. `ADAPTIVE_DECREASES.json`, `OBSERVER_BYTE_COMPARISON.json`, and `REVIEW.json` retain the remaining checks. `SEAL.json` binds the review outputs and audit source.
