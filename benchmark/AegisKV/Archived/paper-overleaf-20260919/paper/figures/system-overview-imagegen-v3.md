# AegisKV System Overview — restrained 2D revision

![AegisKV System Overview](system-overview-imagegen-v3.png)

The user found v1 dominated by module boxes, then found v2's hardware illustration excessive. This v3 candidate uses two plain GPU ownership boundaries, a layer/block KV matrix, a DRAM strip, unboxed control labels, and explicit backup/recovery arrows. It removes circuit-board drawings, perspective, and decorative hardware details. The user has not yet accepted this candidate.

Generated using the built-in `image_gen` tool: one new generation and three model edits. The selected PNG is copied unchanged. The PDF embeds that raster and is not an editable vector source. Python was used only for copying, metadata, PDF placement, and review renders.

## Deliverables

- [PNG](system-overview-imagegen-v3.png), 1536 × 1024.
- [PDF at 178 mm width](/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-imagegen-20260917/system-overview-imagegen-v3.pdf), approximately 219 effective dpi.
- [Initial prompt](system-overview-imagegen-v3-design.prompt.md).
- [Background and topology refinement](system-overview-imagegen-v3-refine.prompt.md).
- [Final layout/endpoint cleanup](system-overview-imagegen-v3-cleanup.prompt.md).
- [Slack arrow repair](system-overview-imagegen-v3-slack-arrow.prompt.md).
- Hashes and source provenance: `output/pdf/aegiskv-imagegen-20260917/artifact-metadata-v3.json`.

## Caption candidate

**AegisKV system overview.** Workflow metadata supplies Slack estimates to the Placement Planner, which combines them with block rankings and the retry DP's available Peer budget. Selected sealed layer/block KV objects are copied from the source GPU to the designated retry DP; the source independently maintains DRAM protection. Following source failure, requests retry concurrently on that DP, reading resident Peer KV directly and obtaining missing data from DRAM through layer-wise prefetch and demand fetch. The retry DP retains its own foreground KV. Blue and ochre solid arrows denote Peer and DRAM data paths; gray dashed arrows denote control signals, and the red dashed path denotes failure-triggered retry. The displayed layers, tiles, and request lanes are schematic, not measured sizes or counts.

## Review and scope

Inspected the final native PNG and the delivered PDF rendered in color and grayscale at 178 mm width / 144 dpi. Checked the Slack/Plan/ranking/budget directions, sealed-block rather than active-tail Peer-copy origin, independent Peer/DRAM backups, local Direct read, upward H2D fetch, distinct foreground KV, and three independent retry lanes. Five blue source tiles and five Peer tiles make the selected-object illustration consistent. Labels are readable at the full intended width and not clipped.

This is a design schematic based on `system_design.md`, not runtime or performance evidence. Offline profiles, individual engine modules, commit/ACK details, and tail recomputation are explained in the design text rather than expanded into additional boxes. The drawing illustrates resource ownership and core paths; it is not a complete implementation wiring map. Existing native Draw.io assets and prior candidates remain available.
