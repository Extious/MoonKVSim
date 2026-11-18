# Direct revaluation: manuscript integration and Peer-HBM assessment

Date: 2026-09-21. User decision: “直接选择价值重估”. The accompanying Peer-HBM question is an assessment request; the active paper remains DRAM plus SSD/shared storage.

## Integrated change

- KV Master now uses current complete-plan values, a bounded rotating victim scan, finite lower-tier relief, whole-DAG comparison, configured migration/uncertainty margins, version validation, reservations and asynchronous safe transitions. No rent level, credit, expiration or renewal state is part of the selected controller.
- The three-layer Overview changes Rent to Revalue while preserving Application / Controller / Engine, symmetric DP workers and shared backing outside compute-worker boundaries.
- `placement-competition` replaces the rental mechanism example. It is an explicitly additive, constructed equal-size example: candidate saving 6 s, victim costs 2/5 s, migration cost 1 s, yielding complete-plan changes −3/0 s. A physical read lease excludes a lower-cost victim. This illustrates comparison and safety, not measured performance or a general additive workflow objective.
- Abstract, Introduction, Design, relevant Evaluation/Related Work prose, Chinese companion, experiment matrix and current project instructions agree on direct revaluation. The Evaluation still has eight selected figures and seventeen subsections. Its unfavorable rental result is preserved as a compared alternative, with all values unchanged.
- Clarified that the isolated stream's 396 revaluations are scalar replacement-value checks, not full DAG traversals or CPU measurements. The static, additive and layer models do not validate the newly specified complete controller.
- Previous paper sources, PDF and replaced figure assets are in `before/`. Old rental drawing sources remain in prior export directories. `paper/` contains the new compilation assets and previews, with exactly four root TeX files.

## Checks performed

Generated editable Draw.io XML with `experiments/scripts/paper/build_direct_value_design.py`; exported native PDF and embedded-XML PNG with the installed official Draw.io CLI. Checked native PNG, actual-column color and grayscale exports, and compiled manuscript pages 5, 9 and 15. Figure text minima are 10.26 pt (Overview) and 10.43 pt (replacement example) at 84.68 mm width; see `review/FIGURE_METRICS.json`.

Canonical `paper/main.pdf` builds successfully and has 20 pages. The final LaTeX log contains no overfull boxes, undefined references/citations or fatal errors. Existing class spacing warnings and incomplete bibliographic metadata warnings remain. The companion contains every LaTeX figure asset and the explicitly retained extra sparse-model survey. Its Background/Motivation prefix is unchanged from the snapshot.

This revision changes the manuscript specification and figures. It does not implement the runtime policy, run new GPU experiments, retrain the Tracker, or establish end-to-end recovery performance. The prior review's unresolved segment-prediction, profile calibration, coupled-queue and protocol-validation requirements remain.

## Peer HBM: recommendation and evidence boundary

Recommendation: retain DRAM/storage as the main design for now; treat Peer HBM as an optional extension whose incremental benefit must be shown. Adding a storage tier does not itself establish novelty. Removing a tier does not automatically remove a systems contribution either.

The technically relevant Peer increment is eliminating still-exposed DRAM-to-HBM transfer, after matching reliable coverage, replay work, overlap and target selection. DRAM already avoids reconstructing the committed prefix. If its transfer is hidden by replay or the remaining delay is absorbed by workflow slack, an additional Peer copy need not advance WCT. It also consumes serving HBM, copy bandwidth and control work; a useful comparison must count those healthy-service costs and the placement/target-affinity constraint.

Existing physical evidence: `experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/measured.csv`, 1,010,000 context tokens, gives resident HBM 1.3050 s and serialized DRAM 2.6632 s. The difference is 1.3582 s in that microbenchmark. The protocol uses no transfer/compute overlap and no fault injection, backup creation cost, multi-request contention or workflow completion measurement. Resident HBM is not a measured Peer-backup implementation. Do not extrapolate its relative improvement to AegisKV WCT.

Related-work checks were made against primary sources:

- [TOPAS](https://arxiv.org/abs/2608.25523) already scores normal-service prefix retention/execution using remaining service paths, expected reuse and movement cost. Merely adding Slack or direct value scoring to a cache is insufficient differentiation.
- [LUMEN](https://arxiv.org/abs/2606.17787) coordinates checkpoint placement, interrupted-request distribution and serving-capacity restoration with load awareness. A load-aware retry router alone is insufficient differentiation.
- [GhostServe](https://proceedings.mlsys.org/paper_files/paper/2026/hash/d99e8e80a6c41e148db686918dd7eab3-Abstract-Conference.html) protects streaming KV with erasure-coded parity in host memory. Fault-tolerance contributions need not require a dedicated Peer-HBM tier; the distinct problem and mechanism matter.

The proposed AegisKV claim should focus on jointly valuing a common worker failure over a workflow DAG and shared recovery resources; selecting sparse/layer state by removable exposed delay under finite DRAM/storage capacity; and applying demotion versus last-copy fallback without invalidating recovery. Ordinary hierarchy, direct revaluation, layer overlap, manifests and leases are individually building blocks, not automatically independent novel contributions. The third part needs concrete implementation and correctness evidence rather than only architectural naming.

Before restoring Peer HBM to the main design, compare the current DRAM/storage policy with (i) a clearly labelled favorable Peer-residency reference and (ii) a causal selective Peer implementation. Match total hardware/HBM, fault domains, checkpoint coverage and recovery endpoints; account for reduced foreground capacity and copy overhead. Sweep committed context, actual tail, load, sparse demand and H2D rate; inspect exposed wait and final WCT, including unrelated workflows sharing resources. A reference with negligible incremental WCT gain argues against the added mechanism; a causal implementation with repeatable net gain and a distinct design problem can justify its return. This is an experiment criterion, not a request to run new physical experiments now.
