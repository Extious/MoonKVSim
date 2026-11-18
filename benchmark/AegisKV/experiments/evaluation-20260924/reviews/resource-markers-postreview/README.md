# Peer DRAM capacity marker candidate

Ready standalone replacement: `sensitivity-resources.pdf`, at **178 mm** width with **10.3 pt** labels.
Only panel (b) removes connecting lines. The tested points, numbers, policy encoding,
other two panels, and layout are unchanged. The 84-row `figure-data.csv` is byte-identical
to the old source figure. Source/old artifacts remain untouched; no DES was run.

This is a rendering-only revision of `sensitivity-campaign-v2-corrected`, which used
`causal-current-prompt-plus-training-role-output`, the old service proxy. It is **not**
a `walltime-primary-v3` result. The capacity sweep has one fixed fault and only
0.25, 1, and 256 GiB/host observations. No intermediate capacity points are added.
`CAPTIONS.md` retains the existing numeric interpretation and adds:

> Capacity markers show only the tested settings; no interpolation between capacities is implied.

The high-resolution PNG and actual PDF color/grayscale renders were viewed at
178 mm. `FIGURE_REVIEW.json` records the scope and boundaries. `DATA_AND_RASTER_CHECK.json`
proves the data equality and changes confined to the capacity panel;
`BACKWARD_COMPATIBILITY.json` shows the default still reproduces old raster exports.
The companion control exports are retained solely to keep all 84 data rows and
prove that this change did not affect their rendering. PDF creation metadata may
change on re-export even where pixels are identical.

Reproduce into a fresh output directory from the repository root, using the two
pinned local scripts (do not re-export into this sealed candidate):

```bash
.venv/bin/python benchmark/AegisKV/experiments/evaluation-20260924/reviews/resource-markers-postreview/plot_corrected_sensitivity.py \
  --source benchmark/AegisKV/experiments/evaluation-20260924/sensitivity-campaign-v2-corrected \
  --out /tmp/resource-markers-reproduced \
  --no-capacity-lines
```

`INPUTS_SHA256.json` binds all 126 existing run summaries and input/review sources.
`SEAL.json` binds every candidate file and both live plotting scripts at delivery.
Paper integration remains the root task's decision; no paper source or asset was changed.
