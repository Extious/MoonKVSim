Use case: infographic-diagram
Create a NEW AegisKV system overview figure in a restrained 2D systems-paper style. The user rejected BOTH extremes: an inventory of many named module boxes was too boxy, and a later illustration of large perspective GPU circuit boards was too elaborate. The target is the middle: a compact, precise scientific schematic with a few resource boundaries, actual KV layouts, clear arrows, and minimal visual ornament.

VISUAL STYLE
Pure white background, landscape about 3:2. Completely flat 2D, orthographic. Fine uniform charcoal lines, crisp simple sans-serif text. Muted blue for Peer KV, ochre for DRAM, gray for ordinary KV, small red dashed failure trigger. No gradients, shadows, glow, texture, photographs, 3D, perspective, circuit boards, hardware pins, decorative icons, document icons, badges, glossy UI, large title, or heavy colored panels. No architecture-band backgrounds.
There should be ONLY TWO large thin gray resource outlines (the source and retry GPU) and ONE slim DRAM strip. Do NOT fill the figure with boxes for every software module. Logical modules can be plain text with small arrows and no surrounding rectangle.

TOP: CONTROL CONTEXT, compact (~22% of image)
At upper left, a small five-node workflow DAG made from outlined circles and thin gray arrows: A forks to B and C, then joins D, then E. Direct label "Workflow DAG".
At upper center/right, use one understated unboxed line of logic:
"Workflow Tracker" -- dashed gray arrow labelled "Slack" --> "Placement Planner".
A small plain-text line under Placement Planner reads "Tier  •  layer prefix  •  hot blocks".
Keep the top simple. Do not add separate tier tables or another duplicate layer matrix.

MIDDLE: MAIN RESOURCES (~55% of image)
Two large plain thin-outline rectangles side by side, with clear titles "Source GPU g" and "Retry DP p(g)". These rectangles represent physical ownership, not software processes. Their interiors are mostly white.

Inside the SOURCE rectangle:
- A compact flat matrix of 4 layer rows by 8 KV tiles, directly labelled "Layer–block KV". Row labels "L1", "L2", "L3", "…". All tiles gray-outline with pale-gray fill except selected blue tiles only in L1 and L2; make selected positions vary across these two layers. The last column is unfilled/dashed to signify the unsealed active tail; direct label "Active tail". The selected blue tiles are sealed blocks.
- A tiny unobtrusive plain-text label "Block ranking" near the matrix. A thin gray dashed arrow starts at this label and points UP to Placement Planner.
- Placement Planner sends a separate thin dashed "Plan" arrow down toward source selected KV.
- No Hotness Counter box, Backup Agent box, attention box, or full component inventory.

Inside the RETRY rectangle:
- At the top, a horizontal row of blue tiles labelled "Peer KV", beside a separate row of gray tiles labelled "Foreground KV".
- Put a small bracket above the available peer area labelled "Budget B"; a thin gray dashed feedback line goes FROM that bracket UP to Placement Planner.
- Beneath the memory rows, three simple independent short horizontal execution lanes labelled r1, r2, r3, one per line, with rightward arrows. A small group label "Parallel retry". NO arrows between requests.
- No Recovery Loader box. A short direct annotation near incoming data reads "Layer-wise prefetch + demand fetch".

BOTTOM: MEMORY POOL
A slim plain pale-ochre horizontal strip below the GPUs, labelled "Host DRAM pool", with a few small KV tile outlines. This is an abstract memory pool, NOT a hardware DIMM or device drawing.

FOUR ESSENTIAL DATA ARROWS
1. A blue solid arrow starts at selected SEALED source KV tiles and ends at the blue "Peer KV" row on the retry GPU. Label "Peer copy". NEVER connect this arrow to Active tail or to the execution lanes.
2. A separate ochre solid arrow from source sealed KV goes DOWN to Host DRAM pool. Label "DRAM copy". Both copies originate at the source independently.
3. A short blue arrow entirely inside Retry DP goes from Peer KV into its execution lanes, label "Direct read".
4. An ochre arrow goes UP from Host DRAM pool into those SAME retry execution lanes, label "H2D fetch". It does not go into Foreground KV.
Put a SMALL red x next to the Source GPU title; draw a thin red dashed route FROM this x TO retry execution, with concise label "Failure / retry". This signal is visually secondary and must not obscure the KV copies.
Keep all connectors orthogonal or simple straight lines; avoid giant sweeping decorative arrows. Route through clear gutters; no arrow crosses a label.

SMALL LEGEND
At the bottom margin show line samples: blue solid "Peer KV"; ochre solid "DRAM KV"; gray dashed "Control"; red dashed "Failure". No giant legend container.

LAYOUT PRIORITIES
A balanced, readable academic figure at 178 mm width. Main labels should be comfortably readable; subordinate labels few and short. Whitespace should separate meanings, not make the figure sparse. Limit visual detail to what conveys workflow-aware protection, layer-block choice, independent backups, and parallel recovery. The result should resemble a hand-refined vector schematic in an OSDI/SOSP/EuroSys paper: sober, clear, informative, not a corporate flowchart and not a hardware illustration. All text English, exact spelling. No performance numbers or quantitative claims; tile counts are schematic.
