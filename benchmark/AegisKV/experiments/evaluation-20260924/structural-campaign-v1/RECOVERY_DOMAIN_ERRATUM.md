# Recovery causal-domain erratum

This is an appended evidence-scope correction. Original source snapshots, plans, seals, raw results and figure exports are preserved. These results are **not quantitative evidence for the corrected implementation**.

The independent [design-conformance spot-check](../reviews/DESIGN_CONFORMANCE_SPOTCHECK.md) found that checkpoint recovery passes only committed checkpoint blocks to the selector, instead of the full causal history. In dense mode this omits locally produced tail/self KV from the hit-compute fraction; with a domain-dependent sparse selector it can also change which old checkpoint blocks are selected. Hence even dense recovery timing/WCT can be affected. The direction and magnitude have not been measured by corrected runs.

The original 143-run campaign is allowed to finish under its original source; at the diagnosis snapshot 141 summaries existed (114 dense, 27 constructed-phase), with 63 dense and 12 constructed-phase checkpoint recoveries. Completion and the final accounting audit do not establish repaired selection semantics. The 8/32/128 execution-cost table describes this historical simulator version only.

Hash, completion, resource-ledger and EOS-boundary audits continue to describe internal consistency of the frozen implementation. They do not prove equivalence to a future domain correction. Healthy and Restart-only paths bypass the affected checkpoint branch; full case matching remains necessary before claiming a version-level result.

See the [matched-rerun plan](../reviews/RECOVERY_DOMAIN_RERUN_PLAN.md) and [diagnosis evidence](../reviews/demand-domain-draft/EVIDENCE.json). The JSON companion pins the reviewed documents as read when this erratum was written; later draft-review additions are not silently incorporated. No additional simulation is launched by this erratum. Frozen runtime SHA-256: `99250879835c64209a2ff7e5d668f2c44cc5c838ba671f6aef32b1803008c98b`.
