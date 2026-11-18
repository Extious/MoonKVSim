# Connector scope and Overview communication — 2026-09-21

User request: shorten Connector to its role executing KV Master decisions; make Overview connections visible, particularly two-way Master/Connector communication.

## Delivered

- Connector is now one 81-word paragraph, reduced from 223 words. It explains transfer execution and outcome feedback, checkpoint availability and recovery reads. Final snapshots at request completion/tool handoff are described with Master's placement events. English and Chinese match.
- Preserved Application/Controller/Engine, symmetric DP resources, single-column placement and black numbered callouts. Added a separate, bidirectional Master–Connector control path on the right, shown for DP1 and explained as symmetric in the caption. Adapter quota publication has its own route and a single arrow toward Master.
- Increased path visibility while retaining lighter regular Libertine text. Slightly widened the right control lane and maintained physical text size. Shortened the metadata strip to keep quota feedback clear of its text. Separated Slack and retry horizontal lanes and preserved actual source/target objects.
- The first native PNG showed oversized heads on short local KV links after thickening. The second export uses smaller heads and lighter strokes on short edges, while retaining stronger long paths. Both rounds remain in the review package.

## Checks

- Inspected the final native Draw.io PNG, PDF rendered at 84.7 mm, grayscale column rendering, and canonical manuscript pages 4 and 9. No observed text/arrow overlap or clipping in the revised deliverables. The standalone placed minimum text size is approximately 10.14 pt.
- Canonical build passed: 20 pages, no overfull boxes, undefined references/citations, duplicate labels or LaTeX errors in the checked log. All three pseudocode listings and all labels remain unchanged.
- Exactly five paper files changed: English Design, Chinese companion, canonical PDF, and the Overview PDF/PNG pair. All other figure assets and experimental evidence remain byte-identical to the before manifest. This task adds no empirical evidence.

## Reproduction and provenance

The generator `experiments/scripts/paper/build_connector_overview.py` reads the previous compact editable source and writes `sources/system-overview.drawio` here. Export with the installed official Draw.io wrapper, using this directory's `sources/fonts.conf`, `--crop -x -f png -e -b 1 -s 2` and `--crop -x -f pdf -e -b 1`. Publish to the existing paper figure paths and run `experiments/scripts/paper/build_paper.sh` from the repository root.

`before/` preserves the previous deliverables. `DOCUMENT_CHECKS.json`, `figure-checks.json` and `delivery-manifest.json` record checks and hashes; `review/` contains the actual renders.
