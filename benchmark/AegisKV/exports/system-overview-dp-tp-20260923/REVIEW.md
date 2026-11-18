# System Overview: DP and TP deployment

The 2026-09-23 user request is to expand System Overview into DP + TP, show different KV shards on different TP ranks, and avoid a narrow, tall figure. This is an architecture illustration, not an experimental result.

## Content and source

- The current fixed-Peer design is the authority: `paper/system_design.tex`. The visual predecessor is `exports/fixed-peer-lazy-credit-20260921/sources/system-overview.drawio`; the original assets and affected writing are preserved in `before/`.
- Application, Controller and Engine remain the three bands. Callouts 1–4 still identify Tracker, Router, KV Master and Adapter. The palette and regular Libertine secondary labels are retained.
- Two DP replicas each contain TP0 and TP1. Every rank shows its local execution KV, selected Peer objects, and a Connector. The example assumes compatible head-sharded layouts: shard 0 and shard 1 cover different KV heads at the same token positions. It does not claim this partition for every attention architecture or TP configuration.
- Two straight Peer links connect corresponding rank-level Connectors: DP0/TP0 ↔ DP1/TP0 and DP0/TP1 ↔ DP1/TP1. For the illustrated DP0-to-DP1 takeover, DP1/TPi retains the selected layer/block objects from source shard i. Both DPs retain symmetric capabilities; this is not a dedicated standby deployment.
- Local execution KV is distinct from the managed checkpoint objects. Peer is a selected subset; the remaining objects stay in shared DRAM/storage outside both DP boundaries. The block glyphs are schematic K/V rows, not measured counts or a complete physical layout.
- Adapter is grouped once per DP for presentation. The explicit Master–Connector control link enters DP1/TP0 separately from its blue KV link. The metadata strip was omitted to make room for ranks; policy metadata and ownership semantics remain in the manuscript.
- English overview, caption and Description, and the Chinese companion are synchronized.

## Reproduction

Run `bash benchmark/AegisKV/experiments/scripts/paper/render_dp_tp_overview.sh` from the repository root. The generator is `build_dp_tp_overview.py` in the same script directory. It writes native editable cells, then uses the installed Draw.io Desktop exporter with a process-local Fontconfig that resolves Linux Libertine O to TeX's Libertine OTF.

Editable source: `sources/system-overview.drawio`. `system-overview.png` and `system-overview.svg` embed the native drawing. The cropped native PDF is `system-overview.native.pdf`. Canonical column-sized PDF/preview are published to `paper/figures/system-overview.pdf` and `paper/figures/preview/system-overview.png`.

Rebuild the canonical paper with `sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh`.

## Actual export and page review

- Column size: **84.6825 × 88.2505 mm**, height/width **1.042**. Additional rank detail uses near-square geometry instead of smaller typography.
- Minimum figure font: **10.1697 pt** in the exported PDF; checked rank labels are **10.1700 pt** in the compiled manuscript. The figure remains vector/text, with no embedded raster image.
- Inspected the native/PDF-derived color export, actual-column 144 dpi color and grayscale previews, and the full compiled page. No clipped or overlapping figure labels were found. Corresponding-shard links remain straight and distinct; the lower-tier link is horizontal. The Master control port and shared-tier data port are separated after the first review.
- The figure is **Figure 8, page 7** in the reviewed 20-page manuscript. The final paper build succeeded with no undefined references or overfull-box diagnostics. The existing class-wide missing-image-description warning remains; this figure has an updated Description.
- `review/structure-checks.json` records the native rank ownership, four Connectors, two matching-rank Peer links, and callouts 1–4. `review/figure-inspection.json` records metadata checks; `review/paper-placement.json` records actual placement and final hashes. These checks validate the diagram and its integration, not an implemented recovery protocol or measured benefit.
