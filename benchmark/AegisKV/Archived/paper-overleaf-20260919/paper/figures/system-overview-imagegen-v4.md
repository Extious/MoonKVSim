# AegisKV System Overview — three-tier reference revision

![AegisKV System Overview](system-overview-imagegen-v4.png)

The user supplied a three-tier architecture reference and requested clearly separated tiers with appropriate AegisKV details. This v4 candidate follows that composition: Applications, Control plane, and Engines, with compact tables, a workflow DAG, a layer/block KV matrix, memory bars, and explicit backup/recovery paths inside the tiers. It is a new candidate, not yet accepted by the user.

The content follows `../draft/system_design.md`, especially §3.1 and §3.5. The reference supplies composition, not algorithm semantics: applications provide workflow/node/dependency metadata; the control plane computes Slack. PP-rank duplication, application-side Slack, and the reference's cache/load scheduling policy are not part of this drawing.

## Files and provenance

- PNG: `system-overview-imagegen-v4.png`, 1402 × 1122 pixels.
- PDF: `/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-imagegen-20260918/system-overview-imagegen-v4.pdf`, 178 mm wide, approximately 200 effective dpi. This embeds the unchanged raster; it is not an editable vector source.
- Generation prompts: `system-overview-imagegen-v4-reference.prompt.md`, followed by `v4-wiring`, `v4-endpoints`, `v4-ranking`, and `v4-plan` prompt files.
- Reference, design-source, PNG, and PDF hashes: `/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-imagegen-20260918/artifact-metadata-v4.json`.

Created with the built-in image_gen model: one reference-guided redesign and four local model edits. Python only copied the selected PNG, embedded it in a PDF, produced review renders, and wrote metadata. Existing canonical Draw.io assets and earlier candidates remain available.

## Caption candidate

**AegisKV system overview.** Applications issue LLM requests carrying workflow and DAG-node metadata. In the control plane, Workflow Tracker derives Slack from duration estimates and DAG progress; Placement Planner combines Slack, offline profiles, block rankings, and the retry DP's Peer budget to assign protection tiers and select layer-prefix hot sets. In the engine layer, Backup Agent independently copies sealed KV objects to the designated retry DP's Peer Region and the host DRAM pool. After source failure, Recovery Manager submits concurrent retries on that DP. Resident Peer KV is read locally; Recovery Loader prefetches DRAM objects and fetches missing objects on demand, while the retry DP retains foreground KV. Blue/ochre solid arrows denote Peer/DRAM data paths, gray dashed arrows denote control messages, and red dashed arrows denote failure-triggered recovery. Layers, blocks, memory proportions, workflow nodes, and retry lanes are illustrative, not measurements.

## Review and scope

Viewed the final PNG and the delivered PDF rendered in color and grayscale at the assumed 178 mm insertion width, 144 dpi. Checked three-tier separation, module labels, upward block-ranking/budget reports, downward placement plan, rightward Slack input, independent Peer/DRAM copy paths, Peer-copy termination inside Peer Region, local direct read, upward H2D fetch, and independent retry lanes. Labels and endpoints remain legible at that width. Grayscale colors lose some contrast, but labels, positions, and solid/dashed paths preserve the core distinctions.

This is a design overview, not implementation or performance evidence. Detailed routing, heartbeat transport, ACK/commit states, selector auxiliary state, admission control, and tail recomputation remain in the accompanying text. Peer Budget is represented by its labeled report rather than a separate module box. The final width is an explicit working assumption; the image has not been tested in a specific conference template.
