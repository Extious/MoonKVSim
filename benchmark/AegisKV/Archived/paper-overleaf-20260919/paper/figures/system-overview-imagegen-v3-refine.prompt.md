Refine this flat AegisKV schematic for a printed research paper. KEEP the sparse 2D structure: only two GPU ownership outlines, one layer/block matrix, one slim DRAM pool, a small DAG, and unboxed control labels. No hardware illustrations, no additional process boxes.

FIRST, replace the entire dark background and every glow with PURE WHITE (#FFFFFF). Remove ALL gradients, spotlights, haze, shadows, and bloom. GPU interiors also pure white. Use dark charcoal high-contrast text and thin charcoal outlines; flat muted blue Peer tiles, flat light-gray other tiles, and a pale flat ochre DRAM strip. This must look like crisp vector artwork on white paper, not a dark presentation slide.

CORRECT THESE CONNECTIONS:
- "Peer copy": the current arrow appears to originate from the unsealed Active tail. Erase that horizontal blue arrow. Draw the replacement starting at the BLUE SEALED L1 tile near (490,452), going UP to a clear routing corridor above the source matrix, across the central gap, and then into the LEFT EDGE of the first blue Peer KV tile near (910,463). The Active tail must have no outgoing copy arrow. Label the new arrow "Peer copy" in empty space. Do not draw over labels.
- "DRAM copy": start the ochre arrow just BELOW the entire source matrix, not inside a lower-layer tile; point down to the Host DRAM pool. Keep its copy path separate from the blue Peer copy.
- Add a thin dashed gray directed arrow from DAG node E to the unboxed Workflow Tracker label.
- Keep Workflow Tracker --Slack--> Placement Planner.
- Keep only ONE "Budget B" label at the bracket above Peer KV and ONE dashed feedback arrow from that bracket UP to Placement Planner. Remove the duplicate Budget B label and duplicate feedback arrow.
- The "Block ranking" feedback must originate at the SOURCE matrix and point to Placement Planner. The current floating vertical arrow above the retry GPU has no source connection; erase it and replace with a properly connected source-to-planner dashed arrow labelled "Block ranking". Route it through whitespace above the Source GPU.
- Keep a separate dashed "Plan" arrow from Planner down to the Source GPU.
- Preserve local Direct read, DRAM-to-retry H2D fetch, the three independent retry lanes, and source-to-retry red dashed failure signal.

Improve spacing: center the main resource titles over their interiors; align memory rows and retry lanes; keep every arrowhead visible. Main labels medium-bold, secondary labels normal weight, all easily readable at 178 mm width. No extra legend frame, decoration, boxes, hardware, or text.
