# Resource-oriented Overview review — 2026-09-21

## Scope and references

The user rejected the preceding square Overview as a program flowchart and supplied two visual references. Read both PDF texts, downloaded the complete files, and inspected LiveUpdate Figure 7 (page 6), RACER Figure 7 (page 5), and RACER Figure 3 (page 3). See [REFERENCE_STUDY.md](REFERENCE_STUDY.md) for exact URLs and the design reasoning. The new figure is independently constructed native Draw.io XML, not reproduced reference artwork.

## Architecture representation

- A workflow feeds global routing; the Router displays KV-map and node-load state.
- Separate control services contain Tracker, KV Master, directory and token log. Metadata and control paths have distinct dashed routing lanes.
- Two equally capable DP worker boards visibly contain GPU resources and HBM KV blocks. The GPU icon abstracts a GPU/TP group. Retry arrows describe an example rather than permanent source/standby roles.
- Shared DRAM and SSD/storage use concrete memory/storage symbols and remain outside worker boundaries. Blue paths terminate at these resources through a shared transfer fabric; tier movement is explicit.
- Added representative worker-state feedback to Router and a bidirectional plan/status link to KV Master. These are logical control paths; the drawing introduces no measured topology or new hardware guarantee.
- The caption preserves the requirement that metadata and backing copies survive the protected compute-worker fault. Physical host/SSD failure limits remain in the section opening.

## Iteration and final-size review

Round 1 revealed wrapped headers, crowded Tracker text and an unsuitable built-in cylinder rendering. Shortened figure labels while keeping full names in prose; replaced the cylinder with a native stacked metadata object. Moved an SSD link away from the fabric label. Round 2 and final reviews separated the Slack label from its arrow, nested control elements inside their editable service group, and checked feedback lanes outside the worker boundaries. Early native exports are retained under `review/round1` and `review/round2`.

Inspected the final native PNG, vector PDF at the paper's actual column width, grayscale render, and embedded manuscript page 4 after the final export. No observed clipping, label/arrow overlap, or missing component. Direct labels, line patterns and block outlines preserve grayscale semantics. Geometry remains approximately 84.68×81.67 mm with minimum extracted figure text 10.44 pt; values are in `review/MEASUREMENTS.json`. These visual checks do not constitute user acceptance of the aesthetic.

## Delivery

Updated only the Overview asset, introductory sentence, caption/description, matching companion paragraph and current source pointers. The canonical build succeeded; existing unrelated acmart spacing warnings remain, with no unresolved reference or overfull-box error. Concurrent Evaluation content was preserved. The manuscript currently has 25 pages; this task imposes no page limit.

Current source: `sources/system-overview.drawio`. Generator: `experiments/scripts/paper/build_overview_architecture.py`. Deliverables remain `paper/figures/system-overview.pdf`, `paper/figures/preview/system-overview.png` and `paper/main.pdf`. The preceding version is in `before/`. No new experiment or algorithm validation was performed.
