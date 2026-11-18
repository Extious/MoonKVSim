# Complete-history results

L=4, K=64. Coverage is equal-document mean after within-document ratio-of-sums. Replacement is the logical entering footprint from M32000 to M32256.

| Model | Method | Distinct demand (%) | Query-block events (%) | Entering (MiB) |
| --- | --- | ---: | ---: | ---: |
| NOSA-8B | decay_hysteresis | 32.77327 | 59.90180 | 0.14583 |
| NOSA-8B | cumulative_no_hysteresis | 23.03758 | 40.50729 | 0.10417 |
| NOSA-8B | frequency_static | 22.97264 | 40.30602 | 0.00000 |
| NOSA-8B | recency | 30.41627 | 33.77488 | 1.00000 |
| NOSA-8B | uniform | 13.59883 | 13.68476 | 12.75000 |
| NOSA-8B | future_oracle | 33.25313 | 63.31896 | 0.64583 |
| NSA-8B | decay_hysteresis | 16.76211 | 36.03996 | 0.87500 |
| NSA-8B | cumulative_no_hysteresis | 14.12649 | 15.47794 | 0.04167 |
| NSA-8B | frequency_static | 14.11566 | 15.47570 | 0.00000 |
| NSA-8B | recency | 15.78869 | 34.37024 | 1.00000 |
| NSA-8B | uniform | 12.83544 | 13.87149 | 12.75000 |
| NSA-8B | future_oracle | 16.79496 | 53.60491 | 5.18750 |
| MiniCPM4.1-8B | decay_hysteresis | 15.45087 | 22.35421 | 1.18750 |
| MiniCPM4.1-8B | cumulative_no_hysteresis | 12.29860 | 8.70705 | 0.08333 |
| MiniCPM4.1-8B | frequency_static | 12.29860 | 8.69588 | 0.00000 |
| MiniCPM4.1-8B | recency | 16.51628 | 33.76908 | 1.00000 |
| MiniCPM4.1-8B | uniform | 12.71790 | 13.73625 | 12.75000 |
| MiniCPM4.1-8B | future_oracle | 16.52699 | 42.69136 | 7.58333 |

Current-minus-Recency distinct coverage: +2.36, +0.97, and -1.07 pp.
Warm-minus-matched-cold Current: -0.47986, +0.04393, and -0.87176 pp.
The MiniCPM negative result remains. These are descriptive differences (n=3 documents/model).

Independent checks recomputed all 648 document ratios, 216 summaries, and 5,184 set transitions; all passed. Legacy result and PDF/PNG hashes are unchanged.
