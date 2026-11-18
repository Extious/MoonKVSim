# Native raw-KV difference figure candidate

Use `native-transfer-differences.pdf` at **178 mm** width (77.47 mm high), preserving
Linux Libertine **10.3 pt** labels. PDF and text-preserving SVG are editable vector
exports; `render.py` is the plotting source and `figure-data.csv` contains all
36 plotted mean/range records. No paper source or existing package was changed.

Panels are NOSA-8B, NSA-8B, and MiniCPM4.1-8B. The x axis contains four equally
spaced **categorical** compute assumptions (0, 25.6, 256, 2560 µs/layer); it is not
a linear/log numeric spacing. Series are comparator − Current, with triangle
DRAM, square Recency, and diamond Oracle. A positive y value means Current has
lower component time. The same linear y limits (−280 to 450 µs) retain all positive,
zero, and negative means and document ranges. Horizontal offsets are display-only;
there are no connections between categories. Whiskers are document min–max, not CI.
Small ranges may be covered by their mean marker at the final display size.

Data come from the separately sealed `native-transfer-paper-summary-v1` summary.
First take a paired comparator − Current difference at the same model/book/M/BW/
compute; then average the two checkpoints within each book; finally calculate
mean/min/max over the three books. Each figure cell has n=3 documents; the same
three books appear across models. There are 36 plotted comparisons from 12
model/compute cells, not 36 independent experiments. The original 864 method
runs comprise 216 matched four-method conditions across all three bandwidths.
The figure uses only the declared 32 GB/s slice; other bandwidths remain in the
source summary and are not reclassified or discarded.

The component finish differences also equal differences in exposed transfer wait,
because total assumed compute is identical across methods. They do not equal
native token output times. Background transfer ordering is identical for all
methods, so this comparison isolates their prepared raw-KV residency under the
component assumptions. Initial fill and normal-time replacement costs are omitted.
All methods assume prepared selector/auxiliary state and local projected tail;
the 256 queries' demands are simultaneously revealed at each layer entry.
Per-object completion and fluid preemption differ from the core simulator's
atomic LoadBatch completion. Native full-prefill traces do not prove equivalent
chunked resume, especially across MiniCPM dispatch thresholds. Compute/hit-overlap
allocation is uncalibrated. The future-frequency Oracle is not latency-optimal.
No native-kernel execution, physical H2D calibration, full recovery, Agent latency,
or WCT claim is supported by this figure.

At zero compute, MiniCPM's Recency/Oracle difference is −2.389 µs (document range
−3.072 to −2.048), which appears close to zero on the shared scale; the exact
negative values remain in CSV. At 256 µs/layer, NOSA/NSA Recency differences are
−209.436/−218.124 µs. All adversarial and null outcomes are retained.

Actual PDF color/grayscale renders at 178 mm were inspected at 96 and 144 dpi;
`FIGURE_REVIEW.json` records files/hashes and the independent check. `PDF_INSPECTION.json`
records metadata only; the visual review is separate. Final compiled-paper
placement remains the root task's integration step.

Reproduce with `.venv/bin/python` and a copy of `render.py` in a fresh sibling
candidate directory. It verifies the source summary seal, copies the three input
files, and emits the figure and metadata without running any simulation. The
original summary/native seals and old outputs remain unchanged.
