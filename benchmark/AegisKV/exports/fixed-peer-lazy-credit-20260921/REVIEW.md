# KV Master fixed-quota and lazy-credit revision

Canonical manuscript: `../../paper/main.pdf` (21 pages).
SHA256: `1e615749277bc3a08757e03ea82cbd62175417b8530f9f5ad049f1be52b06d09`.

## Delivered narrative

1. Slack- and Access-aware KV Priority: request urgency times selection probability; distinguish causal opportunity counts from lifetime frequency and preserve equal dense access factors.
2. Renewable Credit with Lazy Updates: normal reuse, multi-Agent shares, per-use renewal, versioned grants, pressure clocks and bounded low-key/rotating refresh.
3. Greedy Peer Protection: calibrated fixed L/K/Z; zero guarded Slack eligibility; ended slots then descending active Slack; stable admission ties, mandatory-shrink recency ties; no Peer rent.
4. Online Three-Tier Management: event processing, lower-tier admission/rent, Peer slots, physical reservation, cascades and transfer feedback.

Abstract, Introduction, Adapter demand trigger, relevant Evaluation/Related Work/Conclusion, Chinese companion, experiment matrix and project notes were synchronized. Removed current-policy claims of per-request L/K search and complete-plan WCT optimization; retained these as reference comparisons where explicitly labeled.

## Figure and numerical review

- Figure 5 retains Application/Controller/Engine, symmetric DP resources, callouts 1–4, Master/Connector control directions. Shortened an initially wrapping Master label to Credit / Slack; final native export inspected.
- Figure 8 has exactly L=2/K=2 and one owner per layer/block cell; layer-1 B0/B1/B2 map to Peer/DRAM/storage.
- Figure 9 includes storage read, H2D and GPU schedules. Reused only the archived MiniCPM replay mean; transport rates and demand counts are declared assumptions. Four cases retain 1,024 MiB unique history; Peer moves 147 MiB out of lower tiers. The sparse case is slower than full-layer pipelining (186.9 vs 177.4 ms); retained that adverse result. Matched sparse Peer completes in 171.9 ms. No physical experiments or new native-demand captures.
- Figure 10 retains the checked credit arithmetic, now explained with lazy settlement. All Evaluation figure files and the historical 462.96/506.39 result are unchanged.

Renderer assertions verify per-resource serialization, read-before-H2D, use-after-transfer, causal demand release, H2D/storage byte totals, equal unique capacity and fixed replay work. They validate the constructed schedule, not a serving controller.

## Layout and consistency

Native PNG/PDF inspected at 84.68 mm in color and grayscale; effective minimum fonts are 10.15–10.34 pt. Lightened exposed-wait color to distinguish it from compute in grayscale. Shortened the pipeline caption to eliminate an Algorithm 2 column overflow, then rebuilt and reviewed the actual pages. Final log has no overfull boxes or undefined references; existing acmart spacing notices and bibliography metadata warnings remain.

Four root TeX files, six Design subsections, four KV Master subsubsections and three algorithms retained. Figure numbers 5/7/8/9/10 and Markdown image paths checked. Editable sources, data, snapshots and review material stay outside the Overleaf folder. `REVISION_CHECKS.json` records the final manuscript hash and scope.

## Evidence limits

This is a manuscript/design revision with an analytical figure. Normalized demand prediction, lazy-victim quality, fixed-quota generalization and integrated three-tier WCT remain evaluation tasks. The product priority is not exact joint WCT, and the adapted rental policy inherits no Landlord guarantee. The latest experimental protocol includes same-value direct revaluation, GDS/Landlord, eager refresh, raw-count normalization controls, fixed-slot ordering and adaptive-depth references; no result is invented for these comparisons.
