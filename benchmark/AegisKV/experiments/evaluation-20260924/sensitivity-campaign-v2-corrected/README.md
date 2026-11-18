# Corrected matched replacement: sensitivity-campaign

This directory replays the same 126 conditions as `sensitivity-campaign-v1` under
`checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`. It is a replacement version, not added independent
samples. Historical outputs and their negative results remain intact.

`MATCHED_INPUTS.json` binds old/new plans and manifests, exact job identities,
profile bytes, decoded workload, priors and failure configurations. Only the
old sensitivity matrix gains explicit `slack_mode=dag`, its historical default.
All three corrected auxiliary groups use identical Python source snapshots.

The manifest identifies GridDurationProfile with the pinned AIConfigurator
HYBRID table and the actual foreground DMA slowdown settings. Timing is
modeled and uncalibrated; no GPU/model execution or production implementation
is established by these runs. The same four complete heldout workflows execute
once, with one fixed logical-progress failure identity.

Completion is recorded in `STATUS.json`; the runner writes `AUDIT.json`, raw
run metrics and paired workflow results after all conditions finish. Read the
actual status/audit rather than inferring completion from this README. All
negative paired outcomes are retained.

Frozen resume/verification command from the repository root:

```bash
.venv/bin/python benchmark/AegisKV/experiments/evaluation-20260924/sensitivity-campaign-v2-corrected/source_snapshot/benchmark/AegisKV/experiments/scripts/current_design/run_sensitivity_campaign.py run --out /home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/evaluation-20260924/sensitivity-campaign-v2-corrected --workers 16
```

This command verifies and skips already-completed jobs. Preserve any partial
run for inspection; do not delete it or turn a resumed job into another sample.
The worker limit applies across concurrent auxiliary commands.
