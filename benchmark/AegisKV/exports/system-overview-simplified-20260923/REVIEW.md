# Simplified System Overview

The user requested fewer mechanism details in the overview and DRAM instead of Peer DRAM. The Controller now uses only the names and brief roles of Tracker (Workflow state), Router (Placement), and KV Master (KV selection). Removed GBDT/CPM, their internal arrow, Slack bars, O1/O2 labels, selection mini-bars, and the explicit DP0-to-DP1 binding example. Adapter no longer includes O3/quota text; the application label is Agent workflow. Both host memory objects are labeled DRAM.

Black callouts 1-4, DP/TP resources, all inter-component and memory-transfer links, and host-owned memory boundaries remain. Detailed mechanisms and peer terminology remain in their manuscript sections. Only the figure accessibility description was adjusted to use DRAM.

Native source: exports/system-design-current/sources/system-overview.drawio. Regenerate with experiments/scripts/paper/build_design.py and render_design.sh system-overview, then build_paper.sh. Native color output, actual-column grayscale and compiled page 4 were visually reviewed. The vector figure remains 84.6825 by 88.2504 mm with minimum text 10.1697 pt. All 12 scoped checks pass; only page 4 changes in the eight-page manuscript. Scientific data, claims and other figure assets are unchanged.
