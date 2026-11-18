# AegisKV System Overview — object-centered revision

![AegisKV System Overview](system-overview-imagegen-v2.png)

User correction: “感觉效果不是很好，都是方框图”. This revision replaces the module-card layout with concrete workflow, memory, and execution objects. It was generated anew with the built-in `image_gen` tool, followed by two model-based edits. The final PNG was copied unchanged; no diagram content was drawn or retouched programmatically.

## Files and prompts

- [PNG](system-overview-imagegen-v2.png): 1536 × 1024 pixels.
- [PDF, 178 mm wide](/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-imagegen-20260917/system-overview-imagegen-v2.pdf): the generated raster embedded unchanged, not an editable vector source; about 219 dpi at this width.
- [Generation prompt](system-overview-imagegen-v2-design.prompt.md).
- [White-background and physical-object refinement](system-overview-imagegen-v2-refine.prompt.md).
- [Sealed-block copy endpoints and ranking feedback correction](system-overview-imagegen-v2-wiring.prompt.md).
- Metadata/hashes: `output/pdf/aegiskv-imagegen-20260917/artifact-metadata-v2.json`.

## Intended interpretation

This is a design schematic based on `paper/draft/system_design.md`. The workflow and Slack graphic summarize request-level protection tiers. The layer/block inset illustrates per-layer selection. The source GPU holds sealed KV and an unsealed active tail; selected sealed blocks are proactively copied to the designated retry GPU, independently of the DRAM copy. On failure, that same retry GPU uses its resident Peer KV and DRAM H2D fetches to support parallel requests while retaining its foreground KV.

The five illustrated layers, block counts, foreground-memory sizes, workflow topology, and three retry lanes are explanatory examples, not measured configuration values or a capacity diagram. The hardware drawings indicate ownership; they do not specify a commercial GPU, exact HBM wiring, or DRAM topology. Component inventories, offline calibration, copy ACKs, commit/reclamation details, and tail replay remain in the system-design text.

## Caption candidate

**AegisKV system overview.** Workflow Slack determines protection tiers and request priority; layer order and sparse block rankings determine which sealed KV blocks occupy the designated retry GPU's Peer memory. Source-to-Peer and source-to-DRAM copies are independent. Following source failure, retries run concurrently on the designated DP, directly reading resident Peer KV and obtaining missing blocks from DRAM through prefetch and demand fetch. Foreground KV remains owned by the retry GPU. Layers, tiles, and request lanes are schematic; colors and arrow labels identify paths rather than measured quantities.

## Review

Viewed the final native PNG and rendered the delivered 178 mm PDF at 144 dpi in both color and grayscale. Checked label readability and clipping; early-layer selection in the source/inset; sealed-block rather than active-tail replication; the independent Peer and DRAM destinations; local Peer reads; upward H2D fetch direction; source fail-stop; Budget B/ranking feedback; three independent retry lanes; and legend scope. Direct path labels remain readable without color. The updated composition is a candidate for user review; no claim of user acceptance or publication readiness is made.

The correction is scoped to this AegisKV Overview: avoid making a module-box inventory the dominant visual structure. Physical KV tiles and memory-board outlines remain appropriate. This does not prohibit rectangles or conventional block diagrams in other figures.
