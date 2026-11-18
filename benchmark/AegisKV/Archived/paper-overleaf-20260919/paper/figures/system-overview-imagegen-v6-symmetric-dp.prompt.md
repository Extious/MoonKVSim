Redesign the attached AegisKV figure to implement two explicit corrections while preserving its restrained flat systems-paper style and THREE strongly separated horizontal architectural tiers.

PRIMARY CORRECTIONS:
1. Completely remove the "Offline calibration" box and its outgoing arrow. Do not replace it with another floating profiles/table/calibration node. Calibration is configuration, not a runtime service. Inside the existing KV Placement Planner panel, show the plain explanatory line "Recovery cost estimates" and the selection line "Select layers & hot KV blocks", below its R/D/P table. No unexplained arrows from an abstract process into Planner.
2. Replace the asymmetric source/recovery engine drawings with TWO MATCHING DP panels labeled exactly "DP0" and "DP1". Each DP is a complete inference engine, capable of normal serving, backup, and recovery. Each MUST visibly contain its OWN HBM split into TWO named regions, its OWN Adapter, and its OWN Connector. Do not make one DP only a sender and the other only a receiver.

STYLE AND LAYOUT:
White background, flat 2D, crisp dark outlines, modest rounded outer frames, black typography, pale gray local KV and pale blue peer KV, ochre DRAM, red only for failure/retry. Follow the reference's three broad bands: Applications at top, Control plane in middle, Inference Engines at bottom. The bottom band can be slightly taller to keep labels comfortably readable. No circuit boards, perspective, gradients, shadows, decorative GPU icons, or unexplained glyphs. Keep visual complexity modest.

TOP TIER "Applications":
Retain the current left request-metadata card with exact lines "LLM request", "Workflow ID", "Node ID", "DAG dependencies".
Retain the right "Agent runtime" panel and its A -> {B,C} -> D -> E workflow DAG. A,B,D,E pale pink; C white. Retain the right-to-left metadata arrow. A downward Request routing arrow enters the control-plane tier.

MIDDLE TIER "Control plane":
Keep the four current functional panels:
- "Workflow Analyzer": Duration estimates -> CPM -> Slack.
- "KV Placement Planner": table "Tier R | Recompute", "Tier D | DRAM", "Tier P | Peer + DRAM". Below the table, plain text "Recovery cost estimates" then "Select layers & hot KV blocks". Everything is inside the Planner boundary. No Offline calibration anywhere.
- "Failure Detector": subtitle "Detects GPU failure".
- "Recovery Coordinator": subtitle "Schedules retries".
Slack gray dashed arrow goes RIGHT from Analyzer to Planner. Failure Detector red dashed arrow goes DOWN to Recovery Coordinator.

BOTTOM TIER "Inference Engines":
Two equally sized DP panels, visually symmetrical, with the same inventory and matching component sizes. Labels exactly DP0 and DP1, no "Source DP" or "Recovery DP".
In EACH panel:
- one large horizontal bar labeled "HBM", clearly partitioned into TWO regions: "Local KV" (pale gray, for that DP's own requests) and "Peer KV" (pale blue, for backups received from the other DP). These are regions of one HBM allocation, not two GPUs. Tiny blocks inside each region are optional only if they improve clarity.
- a clearly labeled module "Adapter" with subtitle "KV management & recovery".
- a clearly labeled module "Connector" with subtitle "KV transfer".
The Adapter/Connector pairs must be present in BOTH DP0 and DP1. Mirror the module placement if useful to put the two Connectors next to the central gutter; this makes a short, direct inter-DP transfer arrow possible. The memory partitions may be mirrored accordingly. The pairs must still look like the same replicated engine, not different special-purpose devices.
Remove the previous separate KV Access Monitor, KV Transfer Engine, KV Restore Engine, source-only KV matrix, and recovery-only request lanes. Their overview responsibilities are now represented by the matching Adapter/Connector pair on each DP.

CONNECTIVITY / READABILITY:
- Put one blue solid DOUBLE-HEADED arrow directly BETWEEN the two Connector boxes through clear space, labeled "Peer KV transfer". It represents the reciprocal backup capability of the two complete DP engines. Both arrowheads must touch Connector boundaries; do not run through an Adapter or label.
- Put a shared shallow ochre "DRAM KV Store" strip BELOW both DP panels but INSIDE the Inference Engines tier. Each DP's Connector has its OWN ochre two-way connection to this shared store, labeled "D2H / H2D". Both DPs can save and fetch KV. Do not draw a serial Peer -> DRAM pipeline.
- In each DP, use short local connections from Adapter and Connector toward their own HBM/each other only as needed to show local integration. Do not imply Peer KV must be copied to another DP after failure. Directly annotate inside EACH DP the short phrase "Local read of Peer KV" if that is clearer than adding another arrow.
- For the normal-control example, a gray dashed "Placement plan" arrow points DOWN from Planner to DP0 Adapter; a separate gray dashed "Block ranks" arrow points UP from DP0 Adapter to Planner; a gray dashed "Peer capacity" arrow points UP from DP1 Adapter to Planner. These selected example arrows do not change the symmetric modules.
- Small red X beside DP0 title, and red dashed arrow from Recovery Coordinator to DP1 Adapter, labeled "Concurrent retries". This is one example failure direction. Both panels retain identical normal-serving capabilities.
- Avoid crossings by routing in gutters; use short labels and whitespace. All arrows must have obvious endpoints.

Bottom small legend: blue solid double-arrow "Peer KV transfer"; ochre solid double-arrow "DRAM transfer"; gray dashed arrow "Control"; red dashed arrow "Failure recovery".
Use ordinary line connections for workflow DAG and do not confuse them with the colored KV data paths.

This is an architecture overview of two symmetric replicas, not a detailed algorithm flowchart. The final image should communicate the two corrections immediately: no mysterious external calibration arrow, and DP0/DP1 each visibly owning the same split HBM + Adapter + Connector architecture.
