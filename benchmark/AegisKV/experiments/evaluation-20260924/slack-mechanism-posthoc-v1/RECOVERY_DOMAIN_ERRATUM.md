# Recovery causal-domain erratum

This is an appended evidence-scope correction. Original source snapshots, plans, seals, raw results and figure exports are preserved. These results are **not quantitative evidence for the corrected implementation**.

The independent [design-conformance spot-check](../reviews/DESIGN_CONFORMANCE_SPOTCHECK.md) found that checkpoint recovery passes only committed checkpoint blocks to the selector, instead of the full causal history. In dense mode this omits locally produced tail/self KV from the hit-compute fraction; with a domain-dependent sparse selector it can also change which old checkpoint blocks are selected. Hence even dense recovery timing/WCT can be affected. The direction and magnitude have not been measured by corrected runs.

All ten experiments are historical dense-demand runs, with three checkpoint recoveries. The pre-fault checkpoint selection/retirement snapshots and capacity arithmetic remain observed historical mechanism evidence. The reported 110.748459 ms matched WCT difference and recovery-service numbers must not be presented as evidence for a corrected recovery implementation. Both base/observer controls validate equality within this same historical version.

Hash, completion, resource-ledger and EOS-boundary audits continue to describe internal consistency of the frozen implementation. They do not prove equivalence to a future domain correction. Healthy and Restart-only paths bypass the affected checkpoint branch; full case matching remains necessary before claiming a version-level result.

See the [matched-rerun plan](../reviews/RECOVERY_DOMAIN_RERUN_PLAN.md) and [diagnosis evidence](../reviews/demand-domain-draft/EVIDENCE.json). The JSON companion pins the reviewed documents as read when this erratum was written; later draft-review additions are not silently incorporated. No additional simulation is launched by this erratum. Frozen runtime SHA-256: `9afc8e74ec1e206cca9b05ae75ae1ffee757a2d0e3e4e76498dbc7addef0d98a`.
