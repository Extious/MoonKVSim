Use case: infographic-diagram
Asset type: a new system architecture figure for a top systems conference research paper (OSDI / SOSP / EuroSys visual style).
Primary request: Draw a publication-quality AegisKV system overview, faithfully encoding the architecture below. This is a scientific DESIGN SCHEMATIC, not experimental evidence. Use English text only.

STYLE AND OUTPUT
Create a wide landscape image, approximately 3:2 aspect ratio, high resolution ideally 3000 x 2000 or larger. Pure white canvas; flat vector-like technical drawing with razor-sharp lines and crisp Helvetica/Arial-like typography. Restrained muted slate, teal-blue, and ochre with dark charcoal labels; red used only for failure signaling. Extremely clean alignment, balanced whitespace, consistent medium-weight strokes. No photorealism, no 3D/isometric servers, no gradients, no shadows, no marketing decoration, no glossy UI cards. No enormous title or caption inside the figure. The image must remain readable when inserted at 178 mm width: short labels, generous text, no microscopic notes, no paragraphs, no equations beyond g, p(g), and B. Intentional precise architecture, not a generic flowchart. Layer boundaries and physical memory ownership must be immediately clear.

LAYOUT
Three horizontal architectural bands: a compact top APPLICATION LAYER (~15% height), middle CONTROL PLANE (~26%), and spacious bottom ENGINE LAYER (~51%); small legend in the remaining bottom margin. Label each band at the left edge; use very light tinted band backgrounds or understated horizontal dividers.
Application contains an "Agent runtime" and a small five-node "Workflow DAG": A1 forks into A2, A3, A4, then joins A5. DAG dependency arrows are thin gray solid lines. Label outgoing metadata "DAG metadata". A separate short path labelled "LLM requests" descends toward the Source GPU; do not route request execution through the Placement Planner.
The control plane contains these four exact modules aligned horizontally: "Workflow Tracker", "Placement Planner", "Failure Detector", "Recovery Manager". Placement Planner can be slightly wider. A compact "Offline profiles" tab feeds the planner from above. Workflow Tracker feeds Planner with a dashed gray arrow labelled "Slack". Under the planner's name, use only a small one-line subtitle "Tier • layer prefix • hot blocks".
The engine layer contains two large outlined physical containers side by side, labelled "Source GPU g" on the left and "Retry DP p(g)" on the right. Below both GPUs, a long shallow ochre-outlined "Host DRAM pool" memory strip spans most of the figure width. This is one memory pool, not a third GPU.

SOURCE GPU CONTENTS
Inside Source GPU: "Sparse attention" feeds selected indices into "Hotness Counter"; a compact grid of "Sealed KV blocks" feeds "Backup Agent". Arrange these four items cleanly with enough space for arrows. Show tiny block tiles as the concrete KV object representation, not just abstract boxes. Hotness Counter reports "Block ranking" to Planner on a dashed gray control path. Planner sends "Placement plan" to Backup Agent on a different dashed gray path.

RETRY GPU CONTENTS
Clearly show "Peer Region" as a blue HBM memory region, labelled "Selected KV"; a separate "Foreground KV" region for the retry GPU's pre-existing workload; a small "Peer Budget" module adjacent to Foreground KV. Foreground KV supplies its occupancy to Peer Budget. Peer Budget reports "Budget B" to Planner through a dashed gray control path.
Show a "Recovery Loader" within the SAME Retry DP container. Immediately under it, show three small parallel request lanes r1, r2, r3 with rightward arrows and the label "Parallel retries". These lanes have no arrows between them: each request proceeds independently. A small subtitle for the Recovery Loader is "Layer-wise prefetch + demand fetch". The Peer Region and loader must be separate objects so the local direct-read path is explicit.

EXACT NORMAL AND RECOVERY PATHS
1. Agent runtime's DAG metadata -> Workflow Tracker (gray dashed control).
2. Agent runtime's LLM requests -> Source GPU (gray solid request arrow).
3. Workflow Tracker -> Placement Planner, label Slack (gray dashed).
4. Offline profiles -> Placement Planner (gray dashed).
5. Hotness Counter -> Placement Planner, label Block ranking (gray dashed).
6. Peer Budget -> Placement Planner, label Budget B (gray dashed).
7. Placement Planner -> Backup Agent, label Placement plan (gray dashed).
8. Backup Agent -> Peer Region (blue SOLID arrow, label "Peer copy"). This is an independent source-to-peer copy, never from DRAM.
9. Backup Agent -> Host DRAM pool (ochre SOLID arrow, label "DRAM copy"). This is independent of the peer copy, never a Peer-to-DRAM chain.
10. Peer Region -> Recovery Loader (short blue SOLID arrow entirely inside Retry DP, label "Direct read"). No transfer to another GPU.
11. Host DRAM pool -> Recovery Loader (ochre SOLID arrow directed UP into Retry DP, label "H2D fetch").
12. On failure: indicate a small red x beside the Source GPU title, with a red DASHED "Fail-stop" signal leading to Failure Detector. Failure Detector -> Recovery Manager red dashed arrow. Recovery Manager -> Recovery Loader red dashed arrow labelled "Retry".
Use distinct source and destination ports and external routing corridors. Keep all arrowheads unambiguous; never run any arrow over text. Minimize crossings and do not connect arrows at incidental crossings. There is no KV data passing through the control-plane modules.

LEGEND
Small clean line samples at the bottom: blue solid "Peer KV", ochre solid "DRAM KV", gray dashed "Control", red dashed "Failure / retry". DAG edges are visually thin and gray and contained in the Workflow DAG. Include no quantitative data, performance claims, percentages, rent/Credit/Landlord, serial recovery queues, fourth architecture band, extra GPU, logos, watermark, or figure number.

Make the physical regions, independent backup copies, and local versus H2D recovery paths especially clear. Maintain exact spelling of all module names. Prioritize faithful connections and final-size legibility over ornament.
