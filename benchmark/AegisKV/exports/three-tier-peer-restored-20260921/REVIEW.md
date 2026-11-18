# Three-tier Peer restoration review

The user explicitly restored Peer HBM / DRAM / Shared storage and confirmed that complete DRAM checkpoints may demote as a whole. This supersedes the prior no-Peer recommendation. Direct value revaluation remains selected.

## Delivered design

- Seven Design subsections: Insights, Overview, Tracker, Recovery-aware Router, KV Master (three subsubsections), windowed-capacity Adapter, safe-transfer Connector.
- Per-request L and per-layer K describe Peer hot replicas only. DRAM and storage retain complete checkpoint manifests; immutable sharing/incremental transfer does not weaken completeness. Z remains configured. The Adapter chooses only total Peer capacity.
- Normal request competition respects running logical Peer pins. Self hot-set updates and Adapter shrink may override them; physical leases still drain. Valid backing avoids redundant D2H. Last-backing deletion withdraws dependent Peer claims. Adopted Peer objects transfer to execution accounting without double charging bytes.
- Arrival-time takeover/Peer binding and safe fallback/rebind coexist with load/locality routing.
- Existing Evaluation figures and negative rental results are unchanged. Their Peer-disabled / isolated-mechanism scope is explicit, including the old partial-DRAM layer model. New matched three-tier cells are planned in the paper and experiment matrix; no physical run was started.

## Figures and review rounds

Editable diagrams: `sources/`; generator `experiments/scripts/paper/build_three_tier_peer.py`. The competition diagram derives from the preserved direct-value source. Numerical schedules: `model_peer_overlap.py`; assumptions in `data/model.json`, exact events/frontier tables in `data/`.

Round 1 native export exposed a wrapped Router title and a misleading Layer-3-to-Peer arrow. The title was shortened to Router, the false dependency removed, and Connector paths straightened. Round 2 checked final-column color/grayscale and corrected Adapter capacity feedback to KV Master. Final exports and main.pdf pages 4, 8, 9, 10 and 16 were rendered and inspected; the page-4 grayscale view was also checked. The architecture retains Application / Controller / Engine and symmetric DP resources.

All six changed figures are single-column at 84.68248 mm, minimum actual text 10.26 pt or larger. Full metrics: `review/FIGURE_METRICS.json`. No text was shrunk to repair layout. Final LaTeX build: 22 pages, zero overfull boxes and zero undefined-reference mentions. Four root .tex files and included figure paths checked. These checks concern the research draft, not submission readiness or runtime correctness.

Analytical model: four equal demand groups, H2D 4 ms/group and compute 3 ms/layer, full DRAM baseline and separate four-group transient workspace, correct demand at t=0. Baseline / late Peer / early Peer = 19 / 18 / 15 ms. Resource exclusivity, dependency readiness and unchanged layer computation are checked by the generating code. Tail and rates are declared examples, not calibrated hardware or a fault-phase distribution. Curves retain matched L=0 points and plateaus.

## Preservation and delivery

`before/` and `BEFORE.json` retain the complete previous manuscript/assets and local instructions. Canonical delivery remains `paper/main.pdf`; source and Chinese companion are synchronized to the restored tier semantics. Logs, editable sources, CSVs and reviews remain outside the Overleaf folder. Existing Evaluation PDF hashes are unchanged (`review/VALIDATION.json`). Unrelated ongoing Motivation/appendix edits were retained.
