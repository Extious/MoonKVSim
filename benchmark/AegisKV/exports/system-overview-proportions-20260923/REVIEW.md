# System Overview typography and object proportions — 2026-09-23

User correction: “有些字体很大，有些方块很小，很不和谐”, with a full Overview screenshot. The preceding spacing revision still used one 26.5-unit text size everywhere while the HBM block marks were only 11 × 4 units.

The editable generator now distinguishes band titles, component names and internal labels. At the existing 84.6825 mm column width, their actual sizes are 10.170, 9.594 and 9.018 pt; numbered callouts use 9.210 pt. The current user's request to reduce visual text dominance supersedes the previous uniform Overview typography. The 9 pt internal-label choice is scoped to this draft figure and does not change other figures or establish venue compliance.

HBM KV blocks grew to 14 × 8 units (2.545 times their previous area), with their original count and fill states preserved. The memory boxes grew from 47 to 52 units high. Controller DAG, routing and selection objects and the host DRAM blocks were also enlarged. Both workers retain equal TP rows, padded shard labels, centered Connector footers, the 14-unit lower DRAM gap and separate outer DRAM routes. The Master-to-Connector endpoint was adjusted to the new Connector center.

Inspected native Draw.io color output, the final-column grayscale output, and color/grayscale renders of manuscript page 4. The block marks are now distinct rectangular objects rather than hairline strips; labels fit inside their boxes and component graphics retain clearance from their headers. Four black callouts remain visible. `checks.json` records 12 scoped checks, including preserved object identities/labels/endpoints/fills, symmetric worker geometry, contained enlarged blocks, separated DRAM/peer-copy routes, hierarchy and text bounds, vector canvas, and a clean eight-page LaTeX build. Only manuscript page 4 changes.

Published the active `paper/main.pdf`, `paper/figures/system-overview.pdf` and its PNG preview. The editable source remains `exports/system-design-current/sources/system-overview.drawio`. This review concerns a constructed architecture diagram and its visual proportions, not measured system performance.
