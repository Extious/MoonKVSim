# Independent primary-figure numeric audit

PASS: all 180 summaries, 9,300 same-ID workflow pairs, 180 plotted numbers (150 scenario means + 30 HBM differences), and all six model/load headline cells were independently recomputed.

The reference subtracts integer nanoseconds before converting units; it does not import the plotter or upstream auditor. Source and summary hashes, every control exception, group means/ranges and the 30 HBM pairs are retained in the JSON.

Each workflow-delay value first averages 62 own-policy F1-F0 workflow pairs. The figure then shows the mean and min/max across five fixed fault identities, not a CI. The HBM figure uses target-workflow DRAM F1-AegisKV F1; all corresponding target F0 records are identical.

Negative values retained: 525 workflow pairs, 5 plotted scenario means, 1 HBM target differences.

| Model | Load | All-DRAM / DRAM exceptions | Static-HBM / AegisKV exceptions |
|---|---:|---:|---:|
| Qwen3-8B | 0.3 | 0 / 372 | 0 / 372 |
| Qwen3-8B | 0.65 | 0 / 372 | 0 / 372 |
| Qwen3-8B | 0.9 | 0 / 372 | 0 / 372 |
| Qwen3-32B | 0.3 | 0 / 372 | 0 / 372 |
| Qwen3-32B | 0.65 | 0 / 372 | 0 / 372 |
| Qwen3-32B | 0.9 | 2 / 372 | 0 / 372 |

Exception: Qwen3-32B, load 0.9, all_dram-vs-dram, F1-4, workflow `3118a657689d83a5`: left-minus-right WCT = -4.113432720 s.

Exception: Qwen3-32B, load 0.9, all_dram-vs-dram, F1-4, workflow `d88a046051e878a4`: left-minus-right WCT = 4.113432720 s.

Six condition means (seconds; full precision remains in the JSON):

| Model | Load | Healthy mean, all policies | Restart delta | All-DRAM / DRAM delta | Static-HBM / AegisKV delta |
|---|---:|---:|---:|---:|---:|
| Qwen3-8B | 0.3 | 6.225912049 | 0.101173248 | 0.093417005 | 0.093413140 |
| Qwen3-8B | 0.65 | 8.313899299 | 0.744162768 | 0.765713138 | 0.765709069 |
| Qwen3-8B | 0.9 | 16.085086414 | 3.956454395 | 3.587245580 | 3.598215471 |
| Qwen3-32B | 0.3 | 7.472924299 | 0.141073377 | 0.136188999 | 0.136188445 |
| Qwen3-32B | 0.65 | 9.554179725 | 1.140454406 | 1.144100101 | 1.144099535 |
| Qwen3-32B | 0.9 | 16.648399020 | 5.126116426 | 5.026995169 | 5.026993532 |

Each comparison checks all 62 workflows in F0 and five F1 runs, including start, finish and WCT. Equality of completion records does not imply equal traffic or measured zero overhead. All exceptions, if present, are listed with original records in the JSON.

This is CPU simulation-data validation. It does not validate numerical model outputs, hardware accuracy or visual layout.
