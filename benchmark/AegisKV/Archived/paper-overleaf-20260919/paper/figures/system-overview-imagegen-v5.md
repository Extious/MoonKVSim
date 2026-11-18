# AegisKV System Overview — functional module names

![AegisKV System Overview](system-overview-imagegen-v5.png)

This revision responds to the user's correction that Backup Agent is a KV transfer module and that other figure labels should describe their responsibilities more clearly. The three-tier composition and data/control topology of v4 are retained. These are candidate presentation names; this revision does not rename implementation classes or integrate the candidate into the canonical draft figure.

## Module names

| Previous label | Revised label | Responsibility |
|---|---|---|
| Backup Agent | KV Transfer Engine | Execute planned KV transfers, track completion, and publish committed copies. |
| Hotness Counter | KV Access Monitor | Observe sparse-selector block accesses and report per-layer block rankings. |
| Placement Planner | KV Placement Planner | Assign protection tiers and choose the KV objects and destinations. |
| Workflow Tracker | Workflow Analyzer | Track DAG progress, estimate node durations, and compute Slack. |
| Recovery Manager | Recovery Coordinator | Submit affected requests to the designated DP and coordinate recovery. |
| Recovery Loader | KV Restore Engine | Manage layer-wise prefetch, demand fetch, and readiness for replay. |

Failure Detector and Agent runtime retain their names: their roles are already explicit. KV Transfer Engine is a generic architectural role, not a claim that a particular transfer library is integrated. KV Restore Engine describes recovery-side orchestration; it does not imply an additional GPU or a distinct physical transport backend.

## Resource and operation names

- Peer Region → Peer KV Cache; Host DRAM pool → DRAM KV Store. These denote storage, not active controllers.
- Engines → Inference Engines; Source GPU g → Source DP g; Retry DP p(g) → Recovery DP p(g). DP denotes a data-parallel inference replica; a replica may contain a TP group as discussed in the design.
- Offline profiles → Offline calibration. The input includes hot-set sizes as well as cost parameters.
- Peer Budget → Peer capacity on the report arrow, retaining Budget B as the reported value. The arrow denotes the capacity report rather than depicting a separate controller box.
- Peer copy → P2P copy; DRAM copy → D2H copy; Direct read → Local KV read. H2D fetch remains unchanged.

## Caption candidate

**AegisKV system overview.** Applications issue LLM requests with workflow and DAG-node metadata. Workflow Analyzer derives Slack; KV Placement Planner combines Slack, offline calibration, block rankings, and Peer capacity to select protection tiers and KV placement. In each inference engine, KV Access Monitor observes block accesses, and KV Transfer Engine copies planned sealed KV objects independently to Peer KV Cache and DRAM KV Store. Following source failure, Recovery Coordinator submits concurrent retries on the designated recovery DP. KV Restore Engine uses resident Peer KV locally and prefetches or demand-fetches DRAM objects, while the DP retains its foreground KV. Blue and ochre solid arrows show Peer and DRAM data movement; gray dashed arrows show control messages; red dashed arrows show failure-triggered recovery. Workflow nodes, layers, blocks, memory proportions, and retry lanes are illustrative.

## Deliverables and review

- PNG: `system-overview-imagegen-v5.png`, 1402 × 1122 pixels, copied unchanged from the built-in image_gen output.
- PDF: `/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-imagegen-20260918/system-overview-imagegen-v5.pdf`, 178 mm wide, approximately 200 effective dpi; raster, not editable vector.
- Exact edit prompt: `system-overview-imagegen-v5-terminology.prompt.md`.
- Source hashes, complete naming map, and export metadata: `/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-imagegen-20260918/artifact-metadata-v5.json`.

One built-in image_gen edit was used. Viewed the selected PNG and color/grayscale renders of the actual PDF at the assumed 178 mm insertion width and 144 dpi. Checked every replacement, label fit, module boundaries, upward ranking/capacity reports, downward placement plan, independent backup paths, local Peer read, H2D fetch, and parallel retry lanes. All updated labels remain readable at that width. Color contrast is reduced in grayscale, with direct labels and solid/dashed paths preserving the key distinctions. This is a design schematic, not evidence of an implemented or measured system.
