Edit the attached AegisKV System Overview figure. This is a TERMINOLOGY-ONLY revision. Preserve the exact three-tier architecture, layout, panel geometry, clean paper style, white background, colors, tables, KV tiles, workflow nodes, and ALL arrow paths and directions. Do not add or remove components.

Replace the following labels exactly, using compact two-line text when necessary:
MODULES:
- "Backup Agent" -> "KV Transfer" on line 1 and "Engine" on line 2.
- "Hotness Counter" -> "KV Access" on line 1 and "Monitor" on line 2.
- "Placement Planner" -> "KV Placement Planner".
- "Workflow Tracker" -> "Workflow Analyzer".
- "Recovery Manager" -> "Recovery Coordinator". Use two lines if needed to keep readable font size inside its existing box. Keep its subtitle "Schedules retry".
- "Recovery Loader" -> "KV Restore Engine". Keep its subtitle "Prefetch + demand fetch".
RESOURCES AND GROUPS:
- "Engines" (the large bottom-tier title) -> "Inference Engines".
- "Source GPU g" -> "Source DP g". Keep the red failure X just after the title.
- "Retry DP p(g)" -> "Recovery DP p(g)".
- "Peer Region" inside blue HBM bar -> "Peer KV Cache".
- "Host DRAM pool" -> "DRAM KV Store".
INPUT AND OPERATION LABELS:
- "Offline profiles" -> "Offline calibration".
- The two-line report "Peer Budget" / "Budget B" -> "Peer capacity" / "Budget B".
- "Peer copy" on the blue arrow -> "P2P copy".
- "DRAM copy" on the gold arrow -> "D2H copy".
- "Direct read" on the short downward blue arrow -> "Local KV read".

Keep all other labels exactly unchanged, including Failure Detector, Agent runtime, CPM, Slack, Foreground KV, Block ranking, Plan, H2D fetch, Parallel retry, r1/r2/r3, and the legend. The legitimate application Agent runtime name should remain, whereas the transport module must no longer say Agent.

Critical invariants: the Plan dashed arrow points DOWN into the top of the new KV Transfer Engine box; Block ranking and Peer capacity point UP into the planner; Slack points RIGHT; the blue P2P copy arrow goes from the transfer module to the BOTTOM of Peer KV Cache, pointing UP into that memory bar; a separate Local KV read arrow points DOWN from Peer KV Cache to KV Restore Engine. Gold D2H copy goes DOWN to DRAM KV Store and gold H2D fetch goes UP from store to restore module. Three retry lanes remain parallel. Do not change arrowheads while changing labels. No redesign, no decorations, no new generic boxes.
