# Native raw-KV transfer: paper summary candidate

This is a new descriptive summary of the sealed `native-transfer-postreview-v2`
results, with no simulation, source-package, or paper changes. Source delivery
SHA256 is `94917e6157bda55e25e5ba95f3e9e31ca542a107a566d7a1cfd59460234d1cad`.
All 2,630 sealed files were rehashed; all 864 CSV rows were matched field by field
to case JSON and to the corresponding trace and completion identity. The existing
216-row paired comparison table and all original sign counts were reproduced.

## Exact aggregation and counting

For each comparator B, define Δ = finish(B) − finish(Current), in µs, pairing
model, document, checkpoint, bandwidth, and declared compute exactly. Positive
means Current is faster; negative means the comparator is faster. Because assumed
compute is identical between methods, each finish difference also exactly equals
the difference in exposed transfer wait. Each document value is the equal mean of
M=32000 and M=32256; then take the equal mean, minimum, and maximum across the
three document values. The range is not a confidence interval or the extremes of
six raw checkpoint observations. Integer nanosecond sums are retained beside
microsecond columns for exact recomputation.

- 864 method runs = 3 models × 3 documents × 2 checkpoints × 3 bandwidths × 4 compute assumptions × 4 methods.
- 216 matched four-method conditions = 72 per model; the three comparator columns yield 648 contrasts, not 648 experiments.
- Averaging checkpoints produces 108 document/parameter rows = 36 per model.
- Aggregating documents produces 36 model/BW/compute rows = 12 per model; the 32 GB/s table has 12 rows.
- Each table cell has n=3 PG19 documents. The same three book IDs are reused across models; these are not nine independent books. Checkpoints, models, bandwidths, compute assumptions, layers, and queries do not add document replication.

This requested checkpoint-averaged view is post-review descriptive sensitivity.
The original sealed primary analysis used M=32000; this summary does not silently
replace that estimand. `checkpoint-pairs.csv` retains both checkpoint outcomes.
No population inference or CI is claimed.

## 32 GB/s: mean [document range]

| Model | Assumed layer compute (µs) | DRAM − Current (µs) | Recency − Current (µs) | Oracle − Current (µs) |
|---|---:|---:|---:|---:|
| NOSA-8B | 0 | 131.072 [131.072, 131.072] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| NOSA-8B | 25.6 | 131.072 [131.072, 131.072] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| NOSA-8B | 256 | 73.475 [72.699, 74.043] | -209.436 [-210.783, -208.077] | -6.161 [-6.764, -5.040] |
| NOSA-8B | 2560 | 286.323 [258.628, 302.334] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| NSA-8B | 0 | 131.072 [131.072, 131.072] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| NSA-8B | 25.6 | 131.072 [131.072, 131.072] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| NSA-8B | 256 | 67.192 [64.204, 68.689] | -218.124 [-221.286, -215.810] | -203.141 [-205.391, -199.674] |
| NSA-8B | 2560 | 377.004 [347.127, 391.978] | -34.610 [-62.060, -12.575] | -56.897 [-84.993, -42.642] |
| MiniCPM4.1-8B | 0 | 128.683 [128.000, 129.024] | -2.389 [-3.072, -2.048] | -2.389 [-3.072, -2.048] |
| MiniCPM4.1-8B | 25.6 | 131.072 [131.072, 131.072] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| MiniCPM4.1-8B | 256 | 131.072 [131.072, 131.072] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| MiniCPM4.1-8B | 2560 | 217.689 [190.623, 241.936] | -102.323 [-127.686, -79.588] | -102.323 [-127.686, -79.588] |

At zero compute the raw-demand boundary saves 131.072 µs for NOSA and NSA,
but only 128.683 µs for MiniCPM after the requested two-checkpoint averaging.
The latter differs intentionally from the original M=32000-only 127.659 µs.
All models save 131.072 µs at 25.6 µs/layer, and tie Recency/Oracle there.
At 256 µs/layer, Current is 209.436/218.124 µs slower than Recency for
NOSA/NSA; MiniCPM ties. At 2560 µs/layer, Current ties Recency for NOSA and
is 34.610/102.323 µs slower for NSA/MiniCPM. These effects cannot be summarized
as a universal advantage of the Current selector.

Across all bandwidth/compute settings, the original per-model Current-versus-
Recency faster/equal/slower counts are 0/42/30, 0/42/30, and 6/33/33 (72 paired
condition rows per model, not independent n). After averaging the two checkpoints
within each document, they are 0/21/15, 0/21/15, and 3/15/18 across 36 rows.
After averaging documents as well, they are 0/7/5, 0/7/5, and 1/5/6 across the
12 parameter cells per model. `SIGN_COUNTS.json` keeps all levels and all three
comparators; positive MiniCPM sensitivity cases are retained even though B32
contains no positive Current-versus-Recency cells.

## Interpretation and possible figure

A compact three-panel Evaluation figure would add more directly relevant evidence
than another coverage plot: one model per panel, shared linear y axis for
comparator − Current component time, a visible zero line, and categorical x
positions for the four declared layer-compute settings at 32 GB/s. Show all three
comparator series and three document means per setting; a mean symbol with a
thin document min–max range is sufficient if points become dense. Do not label
these ranges as uncertainty intervals. Use categorical positions or markers to
avoid implying a measured continuous compute response; distinguish the zero-
compute raw-transfer boundary. Do not hide the negative Recency contrasts.
The 8/16 GB/s results belong in the accompanying CSV/sensitivity table.

This would be a component-timing figure, not native attention or WCT validation.
Existing coverage remains useful as selector-behavior evidence, so the new figure
should replace an Evaluation coverage panel only if the intended question is
whether residency changes exposed transfer time. It should not replace native
selector correctness/coverage evidence. No figure was created in this task.

The component uses per-object readiness and fluid transfer preemption; current
core recovery releases an entire LoadBatch atomically. Identical selector
lifecycle and background ordering therefore do not establish timing equivalence.
All methods share the same Current-ranked background stream. DRAM has no prepared
raw-KV residency; the other methods each have 4 MiB (K=16, L=4). Every method assumes
equally prepared selector/auxiliary state, sufficient destination workspace,
local projected tail, and all 256 query demands revealed at layer entry.
Preparation, normal-time replacement, native auxiliary-state cost, and physical
H2D calibration are excluded. Nonzero compute and hit-overlap allocation are
uncalibrated assumptions. Native full-prefill traces do not prove equivalent
chunked resume; MiniCPM's dense dispatch threshold remains a boundary. The
future-frequency reference is not latency-optimal; no queue/TP/full recovery,
first generated token, Agent latency, or WCT claim follows from these results.

## Files and review

- `paper-32GBps-summary.csv`: 12 requested headline cells with all three signed means/ranges.
- `model-bandwidth-compute-summary.csv`: all 36 sensitivity cells.
- `document-checkpoint-means.csv`: all 108 document-level values.
- `checkpoint-pairs.csv`: all 216 exact paired conditions, with original integer-nanosecond endpoints and contrasts.
- `CANDIDATE_PARAGRAPH.md`: 165-word English candidate; not inserted into the paper.
- `SOURCE_AUDIT.json`: exact seal/source/result checks and counting definitions.
- `INDEPENDENT_CHECK.json`: independent stdlib recomputation of the 72 B32 DRAM/Recency mean/min/max values, performed before seeing these outputs.
- `summarize.py`: reproducible stdlib-only calculation; no simulator imports.
- `SEAL.json`: file hashes of this new summary candidate.

Validation: source and all case bindings PASS; old paired values/sign counts PASS;
independent B32 recomputation PASS; Ruff PASS. Source seal reverified after writing.
