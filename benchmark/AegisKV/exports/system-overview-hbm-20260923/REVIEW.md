# Explicit HBM resources in System Overview — 2026-09-23

User correction: “而且当前 System Overview 图像中也没有绘制出 HBM 的样子”. The existing execution and replica boxes showed KV contents without an explicit enclosing HBM resource.

Added one native editable HBM shell to each TP rank, with a three-plane memory icon and HBM label. Reparented both execution and replica allocations into their rank's HBM shell. Connectors remain outside HBM; host DRAM remains a separate resource in each host. This expresses shared physical HBM with different allocation roles rather than two independent memories. All KV block counts, shapes, fill states, invocation DAG nodes, Controller objects and existing link endpoints are preserved.

Expanded the two equal TP rows by 25 source units each and extended the host/Engine canvas downward. Figure width and text sizes are unchanged: 84.6825 mm wide, 95.0250 mm high, minimum type 9.0183 pt, vector graphics. Preserved the lower 14-unit Connector/DRAM gap and separated outer DRAM routes; adjusted the Master/Connector control endpoint to the shifted Connector center. Updated the caption, accessibility description and `peer-topology.json` resource ownership metadata.

Inspected the native color PNG, actual-column grayscale image, and color/grayscale render of manuscript page 4. HBM shells and icons are visible and label/region boundaries do not collide. `checks.json` records 17 passing scoped checks for hierarchy, containment, symmetry, unchanged KV and workflow objects, routes, typography, intended paper-file changes and clean compilation. The manuscript remains eight pages; pages 4–8 reflow after the taller Overview and revised caption. These are architecture/layout checks, not performance evidence.

Generator: `experiments/scripts/paper/build_design.py`; source: `exports/system-design-current/sources/system-overview.drawio`. Published `paper/figures/system-overview.pdf`, its PNG preview and `paper/main.pdf` using native Draw.io export and the canonical paper build.
