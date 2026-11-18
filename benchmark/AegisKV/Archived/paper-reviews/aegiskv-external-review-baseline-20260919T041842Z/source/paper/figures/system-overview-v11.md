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
- The Recovery Manager binds each request's retry target and Peer DP rank at
  arrival. The KV Master chooses R/D/P tiers, each request's layer depth,
  and hot-block candidates at configured checkpoint and policy events. The miniature matrix illustrates these candidates.
- Local KV is shown by layer and block. Blue outlines identify selected
  sealed blocks in early layers; the gold last column is the unsealed tail.
  Each smaller Peer region contains replicas from the other DP.
- Each Adapter controls only its local Peer budget at each capacity-window boundary, accesses Local/Peer KV, and invokes its Connector.
  Connectors execute copies; they do not select a backup tier or destination.
  A target reads committed Peer KV locally during takeover.
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
| 2 | Recovery Manager | 3.4 |
| 3 | KV Master | 3.5 |
| 4 | Adapter, DP0 only | 3.6 |

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

## Component ownership update (2026-09-18)

The current labels and badges follow the reordered design sections. The
Recovery Manager sends target assignments to the KV Master; policy goes
to Adapters, and rankings/residency return to the controller. The 2026-09-18 labels assigned both budget and layer control to Adapters;
the 2026-09-19 revision below supersedes that ownership. The three-tier layout,
DP symmetry, data paths and independent annotation layer are retained.
The current review is in `output/pdf/aegiskv-component-roles-20260918/`;
the original review above describes the previous labels. Current insertion
remains 84.65 mm wide, with the same known small-text limitation.


## Request-specific depth update (2026-09-19)

KV Master now chooses each request's L_r and hot blocks at fixed-Z checkpoint and policy events. Adapters update only Peer capacity budgets. The Master label reads Depth / hot blocks; both Adapter labels read Peer budget. The canvas, geometry, paths, independent badges and proportional single-column insertion are preserved. Current native export and paper review: output/pdf/aegiskv-request-depth-20260919/.
