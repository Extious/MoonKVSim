# Independent native Top-K operating-point extraction

Recomputed directly from integer counts in the original warm layer/window CSV. For each document, sum the covered and demanded counts across the first four layers and both fixed heldout windows, take their ratio, then average three document ratios equally. Min/max are document ranges, not confidence intervals. Exact document numerators/denominators are retained in document-recomputed.csv.

| Model | K | Method | Distinct historical blocks (%) | Query/block events (%) |
|---|---:|---|---:|---:|
| MiniCPM4.1-8B | 16 | Current | 4.056397 | 5.365230 |
| MiniCPM4.1-8B | 16 | Recency | 4.131747 | 11.451092 |
| MiniCPM4.1-8B | 16 | Oracle | 4.131747 | 11.451092 |
| MiniCPM4.1-8B | 64 | Current | 15.450866 | 22.354209 |
| MiniCPM4.1-8B | 64 | Recency | 16.516280 | 33.769082 |
| MiniCPM4.1-8B | 64 | Oracle | 16.526987 | 42.691356 |
| MiniCPM4.1-8B | 64 | Cumulative/no hysteresis | 12.298600 | 8.707050 |
| MiniCPM4.1-8B | 64 | Static cumulative | 12.298600 | 8.695882 |
| MiniCPM4.1-8B | 64 | Uniform | 12.717898 | 13.736254 |
| NOSA-8B | 16 | Current | 8.313284 | 15.696999 |
| NOSA-8B | 16 | Recency | 8.313284 | 15.182785 |
| NOSA-8B | 16 | Oracle | 8.313284 | 15.829740 |
| NOSA-8B | 64 | Current | 32.773274 | 59.901803 |
| NOSA-8B | 64 | Recency | 30.416268 | 33.774881 |
| NOSA-8B | 64 | Oracle | 33.253134 | 63.318959 |
| NOSA-8B | 64 | Cumulative/no hysteresis | 23.037585 | 40.507286 |
| NOSA-8B | 64 | Static cumulative | 22.972637 | 40.306020 |
| NOSA-8B | 64 | Uniform | 13.598829 | 13.684756 |
| NSA-8B | 16 | Current | 4.198740 | 11.457483 |
| NSA-8B | 16 | Recency | 4.198740 | 15.442751 |
| NSA-8B | 16 | Oracle | 4.198740 | 16.153054 |
| NSA-8B | 64 | Current | 16.762105 | 36.039959 |
| NSA-8B | 64 | Recency | 15.788691 | 34.370242 |
| NSA-8B | 64 | Oracle | 16.794959 | 53.604912 |
| NSA-8B | 64 | Cumulative/no hysteresis | 14.126493 | 15.477938 |
| NSA-8B | 64 | Static cumulative | 14.115656 | 15.475701 |
| NSA-8B | 64 | Uniform | 12.835441 | 13.871486 |

Distinct coverage counts each historical block once per layer/window; event coverage counts every query/block incidence, so repeatedly requested blocks have greater weight. Both exclude the new post-checkpoint tail. Neither metric is a total request hit rate, physical transfer measurement, or recovery/WCT result. Oracle chooses using the future window; it is an explicitly noncausal same-K coverage upper comparator.

The primary WCT campaign PLAN uses K=16 with Qwen3-8B L=11 and Qwen3-32B L=1. Its model/attention traces also differ: the native diagnostic uses NOSA-8B, NSA-8B and MiniCPM4.1-8B. Therefore even the K=16/L=4 extraction matches only K, not the WCT model or protected-layer depth. K=64/L=4 differs in both K and depth. The diagnostic cannot substantiate native recovery coverage at the primary WCT operating points, and the WCT runs cannot validate native sparse-cache hit rates.

Causal ranking sees only prior observed queries; Current is warm from q0, Recency uses historical positions, and Oracle is future-aware. This extraction introduces no reruns, parameter changes or sample selection; it reports all three fixed models and documents, including negative Current-versus-Recency differences.
