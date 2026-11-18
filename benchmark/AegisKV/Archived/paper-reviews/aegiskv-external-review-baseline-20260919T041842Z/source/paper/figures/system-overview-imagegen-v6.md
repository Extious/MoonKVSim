# AegisKV System Overview — symmetric DP0 / DP1

![AegisKV System Overview](system-overview-imagegen-v6.png)

The user requested two corrections: remove the confusing `Offline calibration → KV Placement Planner` relationship, and show DP0/DP1 as similar complete replicas, each with two HBM regions plus its own Adapter and Connector. This v6 candidate implements those presentation changes. It is not yet user accepted.

## Architecture shown

The three tiers remain Applications, Control plane, and Inference Engines. The external calibration node and arrow are removed. The Planner instead contains the explanatory lines “Recovery cost estimates” and “Select layers & hot KV blocks”; calibration constants remain documented in the design text, without being depicted as an online service.

DP0 and DP1 have the same component inventory, mirrored to put their Connectors next to each other:

| Object | DP0 | DP1 |
|---|---|---|
| Local KV HBM region | Own requests | Own requests |
| Peer KV HBM region | Backups received from DP1 | Backups received from DP0 |
| Adapter | KV management and recovery integration | KV management and recovery integration |
| Connector | KV transfer integration | KV transfer integration |

The two HBM regions are partitions of each DP's memory, not two GPUs. DP0 and DP1 are replica identities rather than permanent source/recovery roles. Blue bidirectional transfer connects their Connectors; each Connector independently connects to the shared DRAM KV Store. Bidirectional arrows denote supported operations, not simultaneous transfers during a failure. The red path shows one example: DP0 fails and concurrent retries are submitted to DP1's Adapter.

Adapter and Connector are the user's requested overview interfaces. This drawing groups the earlier access-monitoring, placement-enforcement, and restore responsibilities under Adapter, and KV movement under Connector. That is a presentation-level grouping, not evidence that implementation classes have been added or renamed. Local black connections denote in-engine access/integration; Peer KV remains locally readable on the hosting DP, without a second cross-GPU copy. Only representative control reports are drawn; both DP replicas have equivalent capabilities.

## Caption candidate

**AegisKV system overview.** Applications provide workflow and DAG-node metadata. Workflow Analyzer estimates Slack; KV Placement Planner uses recovery-cost estimates, block rankings, and available Peer capacity to choose protection tiers and KV placement. Each inference replica, DP0 or DP1, contains Local KV and Peer KV HBM regions, an Adapter for engine KV management and recovery, and a Connector for KV transfer. Connectors support peer backup and independent transfers to/from the DRAM KV Store. The red path illustrates DP0 failure followed by concurrent recovery on DP1, which reads its resident Peer KV locally and obtains other required KV through its Connector. Blue/ochre solid arrows show Peer/DRAM data movement; gray dashed arrows show control messages; red dashed arrows show failure-triggered recovery. Memory proportions, blocks, and workflow nodes are schematic.

## Files and review

- [PNG](system-overview-imagegen-v6.png), 1402 × 1122.
- [PDF, 178 mm wide](/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-imagegen-20260918/system-overview-imagegen-v6.pdf), approximately 200 effective dpi, raster rather than editable vector.
- Built-in image_gen prompts: [redesign](system-overview-imagegen-v6-symmetric-dp.prompt.md), [mirror and wiring correction](system-overview-imagegen-v6-wiring.prompt.md), [control-line endpoint edit](system-overview-imagegen-v6-endpoints.prompt.md).
- Source and artifact hashes: `/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-imagegen-20260918/artifact-metadata-v6.json`.

Created with three built-in image_gen calls. The selected PNG was copied unchanged; Python only packaged it in PDF, rendered reviews, and recorded metadata. Viewed the selected PNG and actual PDF color/grayscale renders at the assumed 178 mm insertion width and 144 dpi. Checked the absent calibration node, DP labels, mirrored component inventories, two HBM partitions on each DP, both Connector-to-DRAM paths, Connector-to-Connector Peer path, and recovery arrow into DP1 Adapter. Labels remain readable at that width; direct labels and line styles preserve distinctions in grayscale. The figure is a design schematic and has not been checked in a specific conference template. Existing canonical assets and earlier candidates remain available.
