# Timing metadata review

Three campaigns inherited a generic linear-compute manifest description while their sealed execution used GridDurationProfile. These appended errata preserve the original seals, sources, profiles, summaries and plots; no numerical rerun was performed.

| Campaign | Verified runs | Erratum |
|---|---:|---|
| `sensitivity-campaign-v1` | 126 | [MD](../sensitivity-campaign-v1/TIMING_METADATA_ERRATUM.md), [JSON](../sensitivity-campaign-v1/TIMING_METADATA_ERRATUM.json) |
| `capacity-slack-ablation-v1` | 32 | [MD](../capacity-slack-ablation-v1/TIMING_METADATA_ERRATUM.md), [JSON](../capacity-slack-ablation-v1/TIMING_METADATA_ERRATUM.json) |
| `slack-mechanism-posthoc-v1` | 10 | [MD](../slack-mechanism-posthoc-v1/TIMING_METADATA_ERRATUM.md), [JSON](../slack-mechanism-posthoc-v1/TIMING_METADATA_ERRATUM.json) |

All three use profile SHA-256 `1307a2b8be1b86dbb41acde6c8c068145d5f67e216ec209ce93b3e73e687c17c`. This pinned AIConfigurator HYBRID table is not end-to-end calibrated. The provider performs bounded shape-grid interpolation and per-token decode summation; the generic constant-ns/token fallback was not selected.

The sensitivity group additionally includes DMA slowdown 0.05 and 0.1, so its inherited generic interference-omitted description must be read with the actual config and summary. Capacity and post-hoc groups use slowdown zero.

`formal-core-v1` and `structural-campaign-v1` already override the manifest timing field to describe their grid-based timing; no corresponding correction was identified. Future runner metadata fixes must not rewrite these frozen historical manifests.

Review script: `audit_timing_metadata.py`. It verified the original manifest/profile, frozen call chain, all 168 summary/config/COMPLETE records, and original artifacts before and after publishing only the new errata. The recorded vLLM version is a profile database/backend tag, not evidence of serving-system execution.
