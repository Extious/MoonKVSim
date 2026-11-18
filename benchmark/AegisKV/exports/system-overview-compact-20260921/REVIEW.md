# Compact Overview — 2026-09-21

User correction: “Figure4 这种窄高的图像太丑了”.

Recomposed the editable source at 480×480 instead of 480×835. Kept the DAG, request identities, three policy components, directory/frontier, normal/retry paths, symmetric DP layer/block state, and shared DRAM/storage. Placed backing tiers side by side, combined DP/HBM title rows, and removed repeated storage-object decoration. The transfer strip exposes both tier paths and demotion/fetch. This is a design schematic, not data or a new experiment.

At unchanged 84.68 mm column width, native PDF height decreases from 144.28 mm to 83.02 mm (42.46%). Extracted minimum placed text remains 10.25 pt. No nonuniform scaling or type shrink was used. See `review/MEASUREMENTS.json`.

Native export round 1 was inspected; a second export adds breathing room around the Router labels. Reviewed the final native PNG, PDF rendered at column width in color/grayscale, and the embedded Figure 4 on manuscript page 4. No observed clipping or label/arrow overlap. Direct tier labels and selection outlines preserve grayscale meaning.

Synced only the Overview caption and companion paragraph. The paper still has four root TeX files and canonical `paper/main.pdf`; other figures and sections were retained. Canonical build succeeded without unresolved references or overfull boxes. Existing acmart spacing warnings remain unrelated to this revision.

Source: `sources/system-overview.drawio`; generator: `experiments/scripts/paper/build_overview_compact.py`. Before files remain in `before/`, initial native export in `review/round1/`. These paths are relative to this review directory unless a repository path is shown.
