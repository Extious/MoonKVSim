# System Overview arrow routing

The user requested cleaner arrows. Run and Retry now descend from Router with two intermediate points each, avoiding the former outer loops and heading crossings. The Tracker/Master control lane remains separate from the execution paths. The equivalent DP1 Adapter now illustrates quota feedback through an inner right-side lane; bidirectional Master/Connector control uses the outer lane. All other edge endpoints and all objects remain.

Host DRAM connections use the outside of each worker, with separate bottom Connector ports, instead of overlapping the inter-worker copy paths. TP1-to-DRAM links are straight. DRAM rectangles were centered and narrowed by 20 source units to provide equal side clearance. Short HBM/Connector segments no longer have cramped opposing arrowheads. Workflow join ports are separated, and arrow sizes/strokes are consistent. Component callouts, role diagrams and all visible labels are preserved.

Editable source: exports/system-design-current/sources/system-overview.drawio. Generator: experiments/scripts/paper/build_design.py; native scoped export: render_design.sh system-overview. The accessibility description was updated for the new control paths.

All 14 scoped checks pass. There are no geometric intersections or overlaps between the host-DRAM paths and the rank-matched inter-worker copy paths. Both control directions of Master/Connector remain. Native color output, actual-column grayscale and compiled page 4 were visually reviewed. The vector figure remains 84.6825 by 88.2504 mm, minimum text 10.1697 pt. The manuscript remains eight pages, only page 4 changes, and there are no unresolved references or overfull boxes. This is a routing/layout change, not a system mechanism or measurement change.
