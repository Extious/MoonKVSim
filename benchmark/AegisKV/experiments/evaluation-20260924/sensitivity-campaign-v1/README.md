# Four-workflow sensitivity campaign

This campaign preserves four complete native-context FanOutQA heldout workflows,
in source order, with 52 single-invocation Agents. Each DAG executes once. Prompts
were constructed from public human decompositions/evidence; this is not an
observed Agent serving trace. The same pinned Qwen3-8B TP1 timing grid, 12-workflow
training priors, slack guard, L=11 and K=16 are used across conditions. DP=8 and
the training-derived arrival interval 2,369,773,505 ns are fixed. This small
cohort studies local mechanism/resource boundaries, not population saturation.

## Prespecified matrix

Twenty-one unique conditions each run `none`, `dram`, and `aegiskv` with F0/F1:
126 runs. Common central settings are reused by factor aliases, not rerun as
additional samples. Conditions vary one configured factor at a time:

| Factor | Values | Fixed center |
| --- | --- | --- |
| H2D bandwidth, GB/s | 8, 16, 32, 64 | 32 |
| Peer DRAM per host, GiB | 0.25, 1, 256 | 256 |
| Replica HBM cap per rank, MiB | 0, 32, 128, 4096 | 4096 |
| Online prediction multiplier | 0.5, 1, 2 | 1 |
| Modeled DMA/compute slowdown | 0, 0.05, 0.1 | 0 |
| Failure detection delay, ms | 1, 10, 100 | 1 |
| Protection tolerance, seconds | 0, 0.01, 1 | 0.01 |
| Checkpoint interval Z, tokens | 64, 256, 1024 | 256 |

The separate staleness pair holds TTL at 100 ms and changes prediction latency
from 0.1 to 200 ms. It has its own fresh-response control; it is not compared
as a single-factor change to the core's 120-second TTL. Submitted role priors
and the fixed guard remain unchanged when online predictions are multiplied.

The HBM initial quota is `min(128 MiB, cap)` so each cap is valid. Offline depth
L=11 stays fixed in the H2D sweep. Z=64 also forces prefill segments of at most
64 tokens; Z=1024 retains the fixed maximum prefill chunk of 256 tokens. Thus
the Z intervention changes compute chunking as well as checkpoint/decay cadence.
It must not be described as an isolated transfer-amortization effect.

## Fixed failure and statistics

The target is `ebe557cd696ab6ea/50561e1583fe6cb4`, the longest-prompt Agent in the
third selected workflow (source-order ties). This selection reads only prompt
length, not output length or policy outcomes. Its prompt is 20,283 tokens,
recorded output 2, total 20,285. Every F1 run interrupts invocation 0 at logical
token `ceil(0.8 * 20285) = 16228`, in prefill, failing that worker's TP group.
Policy-specific wall-clock failure times may differ. The failed worker remains
unavailable, so F1 also includes collateral capacity loss.

F1 is paired to its own condition/policy's F0, retaining all four workflow IDs,
arrivals, token sequences and output limits. There is **one fixed fault identity**
per condition. The four workflows share a run and are not independent fault
samples. Results are descriptive, with no population confidence intervals or
deterministic reruns counted as extra samples. Negative deltas remain.

## Source freeze and evidence

`PLAN.json`, `PROTOCOL.json`, `PRIORS.json` and copied inputs are hash-bound in
`MANIFEST.json`. The runner re-executes its copy under `source_snapshot/` and
workers import only those Python sources. This campaign uses design version
`checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1`, runtime SHA-256
`fe775b1608e5305db90e2456673e4d75110129c475327021515dd3a4511f1d2d`.
It is separate from the older core snapshot. Partial results are preserved and
never silently overwritten; resume revalidates the job, config, failure, workload,
profile, priors, summary and recorded artifact hashes.

`raw-runs.csv` retains all metrics and per-resource peaks. `paired-workflows.csv`
retains exact F0/F1 workflow deltas. `binding-diagnostics.csv` reports existing
DRAM append waits/reselections, per-host peaks, actual protection at failure,
HBM replica peaks, copied bytes and checkpoint commits. The runtime does not
expose a complete master-budget denial count; this table does not invent one.
Staleness is checked from coarse prediction return timestamp minus submission
timestamp, compared to the configured TTL. An accepted publication can still be
stale for Slack; return-age counts are not exact timeout or fallback-cause counts.

The only detailed event/flow logs are the two central AegisKV F0/F1 controls;
other runs retain coarse events and summary counters. Audit does not claim an
independent reconstruction of every per-flow interval for summary-only runs.
Compute and transfers remain modeled, with no new GPU execution or integrated
physical calibration.

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_sensitivity_campaign.py run --out benchmark/AegisKV/experiments/evaluation-20260924/sensitivity-campaign-v1 --workers 24
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_sensitivity_campaign.py summarize --out benchmark/AegisKV/experiments/evaluation-20260924/sensitivity-campaign-v1
```
