# Three-layer System Overview revision

## Scope and provenance

User correction: “我还是想要 Application，Controller，Engine 三层架构的形式绘制。”

The figure answers where the workflow, control responsibilities, execution resources, and recoverable KV state live. It is a **design schematic**, with illustrative Agents A–D and DP 0/1. There are no experimental observations or statistical samples in this figure. The preceding resource-oriented version is retained under `before/`; its reference study remains in `../system-overview-architecture-20260921/REFERENCE_STUDY.md`. The supplied reference papers inform resource-object styling, not algorithms or measured claims.

## Layout and semantics

- Three native Draw.io groups labeled exactly Application, Controller, Engine.
- Application provides workflow metadata and requests. Tracker computes Slack; KV Master values state and maintains rent; Router routes requests and activates compatible recovery targets.
- Controller owns surviving directory/token-log metadata. Only representative messages are shown; this is not a complete protocol sequence.
- Engine groups execution and KV movement. Its two equal-capability DP groups each contain a GPU/TP abstraction and HBM. DRAM and SSD/storage are outside the DP groups and must satisfy the manuscript's actual fault-domain conditions.
- Blue bidirectional arrows are KV movement; dark dashed arrows are control/metadata; the red dashed path is an example retry. Native DAG dependencies are separate thin gray arrows.
- The HBM outline/tail encodings remain schematic and do not restore Peer HBM, a common L, or standalone Adapter/Connector policy components.

## Iteration and actual-output review

1. Generated the three-layer native source and inspected its native PNG. Found Run/Retry labels too close to paths and storage labels on the Engine boundary. Preserved this export as `review/round1.png`.
2. Repositioned labels, expanded bottom padding, and removed an unnecessary crossing metadata connection. Inspected the revised native PNG.
3. Simplified the Application-to-Tracker route and aligned the DRAM/storage transfer. Re-exported native PNG and embedded vector PDF; inspected final-width color and grayscale PDF renders and the actual manuscript page in both modes.

At the manuscript column width of **84.68 mm**, the figure is **90.93 mm high**, with minimum extracted text **10.43 pt**. No clipping or label/line overlaps were observed in the final inspected outputs. Line styles, resource placement, and explicit Run/Retry labels preserve interpretation in grayscale. Font sizes and extracted labels are recorded in `review/MEASUREMENTS.json`.

Updated only the Overview paragraph/caption/accessibility description and corresponding Markdown explanation, plus figure assets and provenance. The canonical `paper/main.pdf` compiled successfully; Figure 4 is on page 4. No overfull boxes or undefined references were reported. Existing acmart warnings about vertical spacing elsewhere remain. This is a delivered visual revision, not a claim of user aesthetic acceptance or implementation validation.

## Reproduction

From the repository root:

```sh
python3 benchmark/AegisKV/experiments/scripts/paper/build_overview_three_layer.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f png -e -s 2 -b 0 -o benchmark/AegisKV/exports/system-overview-three-layer-20260921/figures/system-overview.png benchmark/AegisKV/exports/system-overview-three-layer-20260921/sources/system-overview.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f pdf -e --crop -b 0 -o benchmark/AegisKV/exports/system-overview-three-layer-20260921/figures/system-overview.pdf benchmark/AegisKV/exports/system-overview-three-layer-20260921/sources/system-overview.drawio
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

The matching generated PDF/PNG are copied to `paper/figures/system-overview.pdf` and `paper/figures/preview/system-overview.png` before the manuscript build. Editable source, generator, snapshots and reviews remain outside the Overleaf directory.
