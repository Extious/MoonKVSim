# Simulator resource costs at three workflow counts

All 12 points use the same frozen structural-campaign-v1 runtime, profile and summary-log mode. Each count includes seed-7 history_reuse under DRAM/AegisKV and F0/left.decode. The four points are different policy/fault cases, not four timing replicates. Each original DAG executes once.

| Workflows | Policy | Fault | Wall (s) | Process CPU (s) | Worker lifetime peak RSS (MiB) |
|---:|---|---|---:|---:|---:|
| 8 | aegiskv | F0 | 26.587152 | 26.462368 | 191.406250 |
| 8 | aegiskv | left.decode | 25.723208 | 25.621613 | 196.746094 |
| 8 | dram | F0 | 22.016876 | 21.903028 | 213.015625 |
| 8 | dram | left.decode | 21.698075 | 21.620060 | 196.746094 |
| 32 | aegiskv | F0 | 341.541586 | 339.109080 | 538.140625 |
| 32 | aegiskv | left.decode | 361.873503 | 359.478798 | 892.734375 |
| 32 | dram | F0 | 153.825299 | 153.285135 | 544.730469 |
| 32 | dram | left.decode | 273.425622 | 271.646253 | 535.312500 |
| 128 | aegiskv | F0 | 4606.913103 | 4587.885120 | 1563.753906 |
| 128 | aegiskv | left.decode | 4737.778271 | 4716.772082 | 1558.433594 |
| 128 | dram | F0 | 1477.157427 | 1472.439244 | 1435.082031 |
| 128 | dram | left.decode | 2459.666799 | 2446.164787 | 1388.156250 |

Wall and process CPU intervals start after workload/profile loading and include simulation plus result serialization. Four workers run concurrently on the shared host. RSS is Linux ru_maxrss for the worker's whole lifetime; a worker can retain prior input caches, so this is not a fresh-process or per-run-only peak. Raw values and all modeled WCT/resource metrics are retained in scale-resource-results.csv.

This frozen summary-only implementation still computes policy_sample estimates before discarding those detailed records. A later optimization was tested separately but is not applied to any of these 143 runs. These measurements characterize this simulator implementation, not GPU serving throughput or AegisKV's hardware overhead; modeled HBM/DRAM peaks have separate CSV columns. No cases or sizes were reduced.

## Host and interpretation

CPU: Intel(R) Xeon(R) Gold 6438Y+; 128 host logical CPUs, 128 allowed by process affinity. Host MemTotal: 2,164,163,125,248 B (1.968295 TiB). Python: 3.12.12 (main, Oct 28 2025, 12:10:49) [Clang 20.1.4 ]. Exact capture time and point-in-time load are in reports/SCALE_HOST_METADATA.json.

Concurrent campaigns shared this host. Each cell ran once; there are no timing repetitions or confidence intervals. These are simulator execution-scale measurements, not production-controller scalability, controller-only overhead, or GPU serving throughput. Worker-lifetime RSS includes earlier cases and cached inputs.

These results describe the original frozen runtime. The subsequently diagnosed recovery-selector domain issue can affect dense overlap fractions and sparse selected block identities; numerical recovery/WCT effects have not been measured by corrected runs. Completion, ledger and EOS checks establish historical-model accounting only, not repaired semantics. See RECOVERY_DOMAIN_ERRATUM.md at the campaign root.

| Workflows / Agents / invocations | CPU range over four distinct cases (s) | Wall range (s) | Worker-lifetime RSS range (MiB) |
|---|---:|---:|---:|
| 8 / 32 / 64 | 21.620060 to 26.462368 | 21.698075 to 26.587152 | 191.406250 to 213.015625 |
| 32 / 128 / 256 | 153.285135 to 359.478798 | 153.825299 to 361.873503 | 535.312500 to 892.734375 |
| 128 / 512 / 1024 | 1472.439244 to 4716.772082 | 1477.157427 to 4737.778271 | 1388.156250 to 1563.753906 |
