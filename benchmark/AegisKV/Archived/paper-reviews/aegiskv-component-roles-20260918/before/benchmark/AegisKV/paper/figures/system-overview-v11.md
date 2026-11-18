# AegisKV overview: editable revision v11

This is the figure used by `draft/system_design.md` and
`sections/system_overview.tex`. The user found v10 too simple. This revision
retains three architectural tiers and adds mechanism detail through objects
inside them: workflow dependencies, slack bars, a placement matrix, parallel
retry requests, and layer/block layouts. It is a logical design schematic;
the bars, block counts, and memory proportions are not measurements.

## What the drawing explains

- Applications supply request identity, dependencies, and progress. Slack
  is computed by the Workflow Tracker.
- The Router dispatches requests using load and KV locality. The AegisKV
  Controller owns workflow, placement, directory, and recovery state.
- The Planner chooses R/D/P protection tiers, layer/block sets, destinations,
  and transfer plans. The miniature matrix illustrates block selection.
- Local KV is shown by layer and block. Blue outlines identify selected
  sealed blocks in early layers; the gold last column is the unsealed tail.
  Each smaller Peer region contains replicas from the other DP.
- Each Adapter accesses its own Local and Peer regions and invokes its
  Connector. Connectors execute policy; they do not select a backup tier or
  destination. A target reads resident Peer KV locally during takeover.
- Peer copies follow Local KV → Connector → peer Connector → Peer KV.
  DRAM copy and restore paths connect independently to both Connectors.
  Local interfaces are bidirectional so restoration back into Local KV is
  explicit. There is no Peer-to-DRAM cascade.
- The Recovery Manager combines replica state and health signals. Its fork
  illustrates concurrent retry submission, not an ordered recovery queue.

Control arrows show representative instances; both DPs have the same
capabilities. The two memory layouts are mirrored to keep Peer paths short.
The repeated Adapter and Connector interfaces are retained deliberately.

## Paper annotations and editing

| Badge | Component | Section |
|---|---|---|
| 1 | Workflow Tracker | 3.3 |
| 2 | KV Placement Planner | 3.4–3.5 |
| 3 | Recovery Manager | 3.6 |
| 4 | Adapter, DP0 only | 3.7 |

Each badge appears once. Connector has no badge or separate subsection.
The four circles occupy an independent `Paper annotations` layer and can
be hidden or moved without changing the architecture. System elements are
native shapes, text, groups, and edges, not an embedded raster image.
Groups use local coordinates and edges bind to native cells.

## Export review

1. The first native PNG added the mechanism miniatures. Review found a
   controller footer on its frame, a detached metadata label, and status
   text near the DP heading. The directory label moved into the Controller
   header; line labels and gutters were aligned.
2. The second PNG used wider space between DPs, added Adapter-to-Connector
   execution interfaces and direct local Peer access, and separated the
   Peer label from frame borders. Review found an HBM label too close to
   an access arrow and a missing local restore direction.
3. The final native export moves that access port, makes local restoration
   bidirectional, and uses vertical Connector-to-Peer and DRAM paths.
   The PNG, PDF rendered at 177.8 mm, grayscale view, and Figure 4 in the
   rebuilt paper were inspected. The four annotation cells and embedded
   PNG XML were checked against the editable source.

At 7-inch placement the minimum PDF text size is approximately 10.43 pt.
The PDF contains no raster images. Review artifacts, previous candidates,
build output, and the integrated page are under
`output/pdf/aegiskv-overview-v11/`. This review covers drawing semantics and
rendering, not end-to-end system validation or user acceptance of the style.

## Rebuild

From the repository root:

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_system_overview_v11.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f png -e -b 0 -s 2 -o benchmark/AegisKV/paper/figures/system-overview-v11.drawio.png benchmark/AegisKV/paper/figures/system-overview-v11.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f pdf -e --crop -b 0 -o benchmark/AegisKV/paper/figures/system-overview-v11.drawio.pdf benchmark/AegisKV/paper/figures/system-overview-v11.drawio
sh benchmark/AegisKV/paper/build.sh
```

Direct Draw.io editing is supported; re-export after editing. Running the
Python generator replaces manual edits. The v10 source and its generator
remain available as the previous revision.

## Current single-column placement (2026-09-18)

The paper now uniformly scales this original vector PDF to a 84.65 mm column;
its aspect ratio is unchanged and the placed height is about 76.2 mm.
The tall single-column reflow remains as an unused candidate.
Uniform scaling also reduces the smallest text to about 5 pt. This follows
the user's explicit proportion preference; it is not a 10 pt readability pass.
