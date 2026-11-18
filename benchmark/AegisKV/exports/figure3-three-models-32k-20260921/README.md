# Figure 3: three-model access concentration

The user selected NOSA-8B, NSA-8B (the MiniCPM-4-8B-NSA checkpoint), and MiniCPM4.1-8B using the existing nominal 32K / 512-Query results. This integration runs no GPU experiments.

- Paper asset: `../../paper/figures/kv-access-concentration.pdf`; companion preview: `../../paper/figures/preview/kv-access-concentration.png`.
- Canonical manuscript: `../../paper/main.pdf`, Figure 3 on page 4 at review time.
- Editable renderer: `../../experiments/scripts/paper/render_kv_concentration.py`; SVG retained here.
- Data: `../../experiments/data/kv-access-concentration-8b-20260921/`. `MANIFEST.json` pins source and export hashes; `REVIEW.json` pins reviewed manuscript hashes and checks.
- Old Figure 3 and pre-edit manuscript: `before/`. The previous future-demand prediction/oracle evidence remains archived and is not relabeled as the new metric.

## Measurement and interpretation

The matched prefixes contain 32,704 tokens: 32,192 historical tokens and the final 512 Queries. There are 503 historical blocks per layer, with 64 tokens and all KV heads in each object. For each Query, merge duplicate selections across heads; count repeated references from separate Queries. Rank within each layer and observed window, normalize access shares per layer, average all 32 layers, then equally average the three PG19 texts. Bands show text min–max, not confidence intervals. Native selector budgets and sink/local rules remain unchanged. Compressed/selector state is excluded.

| Model | Top 10% (51 blocks) | Top 20% (101 blocks) | Top 40% (202 blocks) |
|---|---:|---:|---:|
| NOSA-8B | 51.75% | 87.64% | 99.31% |
| NSA-8B | 48.08% | 74.76% | 94.96% |
| MiniCPM4.1-8B | 34.55% | 56.54% | 83.01% |

These are retrospective access-frequency shares. They do not measure future-window prediction accuracy, attention mass, physical memory traffic, or failure-recovery speedup. They motivate studying selective Peer copies while retaining complete backing and an on-demand miss path. Three literary texts provide diagnostic evidence, not agent-workload generality.

## Integration and checks

English Design prose/caption/accessible description and the Chinese companion now use this metric and the selected models. An exact NSA checkpoint citation was added. The chart is rendered natively at one-column width, with a 10.048 pt minimum plot font after insertion. The actual page, reading-size crop, grayscale crop, and caption were inspected. The canonical build has no unresolved references/citations, missing graphics, or overfull boxes. Existing acmart spacing notices elsewhere remain outside this figure edit.

A concurrent task changed Tracker and other Design material during integration; those changes were preserved. Its initially missing Tracker asset was published before any local copying was required (`concurrent-dependency.json` is empty). Figure 9's existing pipeline and other unrelated assets were not edited by this task.

Reproduce with:

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_kv_concentration.py
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

The renderer writes review exports here. Publishing an intentional regeneration requires copying its PDF/PNG to the paper asset paths above before rebuilding.
