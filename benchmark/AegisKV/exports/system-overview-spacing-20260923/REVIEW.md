# System Overview worker spacing — 2026-09-23

User correction: “布局不是很均匀，有些地方很拥挤，有些地方有空白”, with crops of crowded shard labels/KV blocks and the large Connector-to-DRAM gap.

Updated the editable generator and native Draw.io source. Both workers now use equal 94-unit TP rows, equal 90 × 47 execution/replica boxes, padded shard labels and KV blocks, and centered 238 × 28 Connector footers. The short HBM-to-Connector gap is 10 units; the lower Connector-to-DRAM gap is 14 units, reduced from 42. The short lower memory link uses a plain segment to avoid crowded arrowheads. Outer DRAM paths and rank-matched peer-copy paths remain separate.

Inspected the native color export, final-column grayscale export, and color/grayscale renders of compiled manuscript page 4. Labels fit, KV marks remain contained, and both worker layouts match. The outer figure remains 84.6825 × 88.2504 mm with minimum PDF text 10.1697 pt and no embedded rasters.

`checks.json` records 19 passing scoped checks: object/link/label and KV inventory preservation; unchanged four callouts, component icons and control roles; uniform row/column geometry; centered Connectors and padded contents; aligned local links; separated DRAM/peer-copy routes; unchanged figure size; unchanged manuscript text and other figures; eight pages with only page 4 visually changed; and no LaTeX errors, overfull boxes, or unresolved references.

Published `paper/figures/system-overview.pdf`, `paper/figures/preview/system-overview.png`, and `paper/main.pdf`. Source: `exports/system-design-current/sources/system-overview.drawio`; generator: `experiments/scripts/paper/build_design.py`. This is a constructed architecture diagram; review validates layout and preserved relationships, not measured system behavior.
