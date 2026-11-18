# AegisKV System Overview — imagegen candidate

![AegisKV System Overview](system-overview-imagegen-v1.png)

Generated with the built-in `image_gen` tool at the user's explicit request. This is a raster design schematic based on the current `paper/draft/system_design.md`, not a performance result or implementation validation. The existing `system-overview.drawio`, PNG, PDF, SVG, and paper references remain the established version; this file provides a separate candidate for review.

## Deliverables

- PNG: `system-overview-imagegen-v1.png`, 1536 × 1024 pixels, copied byte-for-byte from the final model output.
- PDF: `/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-imagegen-20260917/system-overview-imagegen-v1.pdf`, 178 × 118.67 mm. The PDF embeds the raster; it is not an editable vector reconstruction. Effective image resolution is about 219 dpi at this width.
- Metadata and hashes: `/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-imagegen-20260917/artifact-metadata.json`.

## Full prompt sequence

1. [Initial generation specification](system-overview-imagegen-v1.prompt.md).
2. [Independent copies, parallel retries, and flat print styling](system-overview-imagegen-v2.prompt.md).
3. [Request routing and metadata/control directions](system-overview-imagegen-v3.prompt.md).
4. [Final one-way Peer Budget arrow correction](system-overview-imagegen-v4.prompt.md).

The model produced one initial image and three successive edits. No diagram labels, connectors, or other image content were painted or reconstructed in Python. Python copied the final PNG and embedded it in the PDF; PDF renders were used only for review.

## Caption candidate

**AegisKV system overview.** The application supplies LLM requests and workflow metadata. The control plane combines workflow Slack, block rankings, offline profiles, and the retry GPU's available Peer budget to plan KV protection. The source independently copies sealed KV to the designated retry GPU's Peer Region and the host DRAM pool. Following source failure, the Recovery Manager initiates parallel retries on the designated DP. The Recovery Loader directly reads resident Peer KV and fetches missing KV from DRAM, while the retry GPU continues to own its foreground workload. Colored solid arrows denote KV paths, gray dashed arrows control messages, and red dashed arrows failure and retry signals. Block tiles illustrate memory objects and do not encode measured capacity ratios.

## Visual review

Inspected the final native PNG and the delivered PDF rendered at 178 mm width / 144 dpi in color and grayscale. Checked the application/control/engine boundaries; the two independent source copy destinations; local Peer reads versus DRAM H2D fetches; the direction of Slack, block-ranking, placement-plan, and budget signals; the source failure trigger; three independent retry branches; and the legend's scope. Labels and physical containers are not clipped. Direct labels preserve the meaning of data paths in grayscale. Smaller subtitles should retain the full two-column insertion width.

The initial model output incorrectly connected the Peer copy to the loader, linked retries sequentially, and routed LLM requests through the tracker. Successive model edits corrected these. The last edit removed an extra arrowhead into Peer Budget so its report is directed to the planner. These are drawing corrections, not changes to the AegisKV algorithm.

This candidate does not show every ACK, commit, reclamation, or tail-replay event. Their protocol remains defined in the design text. Raster output has no individually editable text or connector objects; the prompt sequence is retained for further model-based revisions. The existing native Draw.io source was preserved.
