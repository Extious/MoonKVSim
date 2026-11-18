# Timing metadata erratum: slack-mechanism-posthoc-v1

`MANIFEST.json` retains the generic `timing` value:

> configured linear compute and shared weighted max-min fair byte flows

The **configured linear compute** wording is incorrect for this campaign.
The frozen runner actually constructs and supplies `GridDurationProfile`.
All **10** sealed summaries name that provider, and each
COMPLETE marker binds the same profile hash. The runtime's constant
`prefill_ns_per_token` / `decode_ns_per_token` branch applies only when no profile
is supplied; its presence in the saved config does not make it the active model.

The correct interpretation is: **Qwen3-8B TP1 GridDurationProfile using pinned AIConfigurator HYBRID operator estimates, bounded prefix/extend interpolation and per-token decode summation; shared weighted max-min fair byte-flow DES. Not end-to-end calibrated; configured compute-DMA slowdown applies separately when nonzero.**
This is Qwen3-8B TP1, batch-size-one A100 SXM operator estimation with a pinned
vLLM backend database tag. It does not mean vLLM or an A100 was executed here.
Prefix/extend interpolation is linear *within the bounded shape grid*; decode
cost is summed per token. Native context is 40,960; the longer profile grid is
performance-shape evidence only, not model quality or runtime validation.

## Bound evidence

- Original manifest SHA-256: `bde984cb2314137ca1ead59b8b38025d854dd4faeab14235b714aa5b50c006bb`.
- Profile: `profiles/Qwen3-8B.json`, SHA-256 `1307a2b8be1b86dbb41acde6c8c068145d5f67e216ec209ce93b3e73e687c17c`.
- Frozen runner(s): `run_slack_mechanism_diagnostic.py`.
- The JSON annex records line-numbered frozen runner/provider/runtime evidence,
  all 10 summary/config/COMPLETE hashes and the original
  audit, seal, tabular result and plot hashes checked during this review.

Configured DMA slowdown values are `[0.0]`. The inherited
`foreground_dma_compute_interference` description says
`omitted; healthy zero slowdown is not measured overhead`. Where a nonzero value
exists, that generic omission text is also inaccurate: the saved config and
summary describe the explicit event-start slowdown sensitivity model. It is
still not calibrated interference. The shared max-min byte-flow description
remains valid.

This is an appended metadata correction, **not a rerun**. No original manifest,
seal, audit, source, profile, result or plot was changed. Numerical results are
unchanged; calibration status remains false. Original artifact hashes were
read back after appending this record. The original manifest remains available
so its erroneous field and seal can be independently reproduced.
