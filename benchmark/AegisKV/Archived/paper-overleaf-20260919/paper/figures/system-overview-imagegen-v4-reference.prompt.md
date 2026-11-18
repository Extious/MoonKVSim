Redesign the attached architecture figure into a NEW AegisKV system overview. The attached image is a LAYOUT AND STYLE REFERENCE. Preserve its strong three-level hierarchy, broad rounded outer frames, compact informative interiors, simple black outlines, large bold section titles, restrained pale colors, and flat academic drawing style. Replace its old component details with the specification below.

IMPORTANT VISUAL TARGET:
Three unmistakable horizontal architectural tiers, top to bottom. Top two tiers are full-width frames; the bottom tier groups two DP/GPU resources side by side and a shared DRAM strip. Similar density and proportions to the reference. White canvas and white/light-gray flat panel fills. Black high-contrast typography. Pale blue for Peer KV, pale ochre for DRAM, a small red failure X. This is a traditional systems research architecture diagram with meaningful nested structure. It is NOT an open hardware illustration and NOT a loose collection of floating labels. No GPU circuit boards, no perspective, no 3D, no gradients, no glow, no drop shadows. Keep the white background of the reference absolutely white. Use English text, clearly readable at a 178 mm print width. Do not retain reference-specific alpha/beta variables, PP ranks, numeric slack values, cache-hit/workload balance scales, or numbered badges.

TIER 1 — "Applications" (about top 23%)
At left: a pale-blue request metadata card, with exactly these lines:
"LLM request"
"Workflow ID"
"Request ID"
"DAG dependencies"
Do NOT put Slack in this card: the application does not supply Slack.
At right: a broad light-gray "Agent runtime" panel containing a compact branching "Workflow DAG". Show five simple small nodes A, B, C, D, E: A forks to B and C, both join D, then E. A few nodes on one path can have a pale-rose highlight, as in the reference. No performance numbers.
A small arrow from this runtime panel to the metadata card identifies "DAG metadata". A downward control arrow from the metadata card reaches Workflow Tracker in tier 2.

TIER 2 — "Control plane" (about next 25%)
Use three coordinated groups with informative contents, not an equal-sized row of empty boxes.
Left: "Workflow Tracker", with two small inline labels "Duration estimates" -> "CPM", and output label "Slack".
Center, slightly wider: "Placement Planner", with a small three-row decision table:
"Tier R   Recompute"
"Tier D   DRAM"
"Tier P   Peer + DRAM"
A short footer within the group says "Layer prefix + hot blocks".
Above or beside this planner, a small understated tab "Offline profiles" feeds it.
Right: two small stacked modules "Failure Detector" and "Recovery Manager", with a red dashed arrow FROM Failure Detector TO Recovery Manager.
Connect Workflow Tracker -> Placement Planner using a gray dashed arrow labelled "Slack".
The control plane also has a plain small label "Request routing" next to a downward request-dispatch arrow toward the Source GPU. Actual requests reach the engine, not a recovery queue.

TIER 3 — "Engines" (about remaining 47%)
A broad outer frame encloses TWO side-by-side resource panels and a shallow shared DRAM strip beneath them. Both resource panels have enough interior detail to show state ownership, like the DP-rank panels in the reference, but use the current design below.

LEFT resource: "Source GPU g".
Inside a light-gray inner region, show "Local KV" as a small layer-by-block matrix: three rows of sealed tiles, with selected BLUE tiles in the first two rows. A dashed empty last-column tail can be labelled "Active tail". These are illustrative physical KV objects, not text boxes.
Place two compact engine modules alongside this matrix: "Hotness Counter" and "Backup Agent".
Hotness Counter sends a gray dashed "Block ranking" report UP to Placement Planner.
Placement Planner sends a DIFFERENT gray dashed "Plan" path DOWN to Backup Agent.
KV tiles feed Backup Agent.
Put a small red failure X next to the Source GPU title.

RIGHT resource: "Retry DP p(g)".
At top, a flat segmented HBM bar clearly separates a BLUE "Peer Region" on the LEFT from GRAY "Foreground KV" on the RIGHT. A compact "Peer Budget" module reports "Budget B" UP to Placement Planner on a gray dashed arrow.
Below the bar, show a compact "Recovery Loader" module and three tiny independent request lanes r1, r2, r3, each with its own rightward arrow. Label the lanes "Parallel retry". Do NOT connect the requests to one another. A short label below the loader reads "Prefetch + demand fetch".

SHARED MEMORY:
Within the Engines frame, below BOTH resource panels, draw one long shallow pale-ochre strip labelled "Host DRAM pool". It is outside the GPU ownership panels. Do not show PP=2 or duplicate DRAM pools.

ESSENTIAL DATA AND FAILURE CONNECTIONS:
- BLUE SOLID "Peer copy": Backup Agent on source -> BLUE Peer Region on retry GPU. Correct endpoint is Peer MEMORY, never Foreground KV or Recovery Loader.
- OCHRE SOLID "DRAM copy": Backup Agent on source -> shared Host DRAM pool. This copy is independent of Peer copy.
- Short BLUE SOLID "Direct read": Peer Region -> Recovery Loader, entirely within Retry DP.
- OCHRE SOLID "H2D fetch": Host DRAM pool -> Recovery Loader, pointing UP.
- RED DASHED "Retry": Recovery Manager in tier 2 -> Recovery Loader in tier 3.
Failure Detector denotes detection of the marked source fail-stop; if there is room, use one thin red dashed source-to-detector signal, avoiding crossings. Correct ownership and readability take priority over adding another long connector.

STYLE OF EDGES AND TEXT:
Normal request arrows dark solid; control messages gray dashed; Peer data blue solid; DRAM data ochre solid; failure/retry red dashed. Keep edge labels brief and attached to their paths. Use routing gutters between groups; arrowheads clearly touch their intended destinations, never go through text. A compact legend at bottom can state "KV data: solid / Control: dashed", with failure indicated separately if room.
Preserve the REFERENCE'S recognizable three-layer architecture and confident large labels. Moderate rounded corners on enclosing architectural boundaries; tiny internal boxes only for genuine modules, and actual memory bars/matrices and the DAG carry the rest of the information. Create a clean, balanced final image suitable for a systems conference paper.
