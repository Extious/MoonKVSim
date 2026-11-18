# Figure 2: matched physical reconstruction costs

The 2026-09-21 revision replaces the four Qwen3-14B static costs with
Qwen2.5-7B-Instruct-1M measurements matching the execution configuration of
Figure 1(c), whose original four-path allocation is Slurm 1517208.
Only Prefill latency is physically measured. Trace-relative WCT increments
remain conditional single-branch counterfactuals.

## Frozen inputs and endpoint

- Model revision: `e28526f7bb80e2a9c8af03b831a9af3812f18fba`.
- Hardware: two NVIDIA A100-PCIE-40GB GPUs, TP2, BF16 weights/KV, batch one.
- SGLang 0.5.10rc0; identical model, DCA, MInference sparse configuration,
  sparse adapter, SM80 library and grouped-GQA execution sources.
- One fixed repeated synthetic `TEXTS[0]`, not a replay of Claude prompts.
- History lengths in A1/A2/A3/A4 order: 105920/100864/108864/113664.
  They are frozen trace hash-block count times 64, not exact original
  tokenizer lengths or measured KV frontiers at the failure instant.
- Total measured length is exactly `C=M+1`. Full Prefill starts from empty
  KV, processes M tokens in at-most-8192-token chunks, and executes one
  separate token. Endpoint is synchronized model-body completion with all
  C-token KV resident, before vocabulary projection.
- Timed contexts in ascending order: 100865, 105921, 108865, 113665.
- One full-length warmup and three timed full prefills per length.
  Full-Prefill output agreement and the original matched HBM/DRAM state
  checks are retained. HBM/DRAM also retain one warmup and three timings;
  the new Figure 2 plots only Full Prefill.

## Bounded execution

Initial submission: `blsc/submit_motivation_exposure.py`, Slurm job **1517915**.
Hard limit: two GPUs for 12 minutes, no requeue or automatic resubmission.
The remote ledger reserved 1560 GPU-seconds including termination margin,
against 1573 remaining GPU-seconds at submission. This initial allocation did not
require a further increase of the recorded 5.5 GPU-hour cap. User permission
to add time if needed remains distinct from allocation or actual spending.
No shared-storage KV file is created by this experiment.

The initial job's TERM handler ran at 05:47:44 +08:00, 49 seconds before
the recorded 05:48:33 hard deadline. It completed and sealed the first
three lengths, but stopped during the last length's third timed repetition.
Slurm reports FAILED, 676 allocated seconds and 1352 GPU-seconds. The raw
failed run and incomplete-point timings remain intact. Only the three
sealed contexts are used; their raw snapshot hashes are verified. The
append-only repeat-validation log's first 1197 bytes match its sealed
snapshot exactly; later partial-point records are not silently substituted.

Follow-up job **1517917**, submitted with `--resume-last-context`, measures
only 113665 tokens under the same kernel/configuration, with a new warmup
and all three timings. Its two-GPU hard limit is seven minutes, reserving
960 GPU-seconds with shutdown margin. The recorded cap was increased by
0.25 GPU-hours to 20700 GPU-seconds under the user's standing instruction
"gpu 小时不够可以继续加". The two allocations are explicitly identified in
the data and manuscript protocol. No automatic retry is configured.

The batch rejects a different GPU model before loading the model. It
retains the existing verified native/compat driver gate and process-group
termination handler. Model/runtime setup is reused; no separate GPU
allocation for build preparation or exploratory tuning is scheduled.
Exact sources are archived under `sparse-archive/1517915/` at submission.

## Analysis and limits

`build_motivation_measured_exposure.py` verifies per-context completion, raw hashes,
all timing samples, repeated-output checks, model/runtime/kernel equality
with allocation 1517208, and the four exact trace-prefix mappings. The
matched configuration does not imply the same physical node/allocation
or the same warmup/repetition schedule as Figure 1(c).

For each branch independently, insert the measured median Prefill duration
as an additional pause into the frozen schedule at 29.452 s after the fork.
Assume an all-branch join and hold other execution and queues fixed. If
offline slack is sigma and inserted delay is R, the WCT increment is
`max(0,R-sigma)`, checked independently by recomputing the delayed join.
The four counterfactuals must not be summed as one simultaneous failure.
Whiskers are the min/max of three timings of the same input, not a
confidence interval or independent-workflow variability.

The example was selected for four parallel branches and a gap near 100 s;
it is not its workflow's maximum-gap group. Combining new Qwen costs with
Claude timing positions illustrates dependency sensitivity, not observed
failure recovery, original-model prompt replay or population benefit.
Original static costs and trace selection records remain unchanged and
are superseded only as the source for the current Figure 2 costs.

## Reproduction

After the allocation is terminal, collect only this named job:

```sh
python3 benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/motivation_exposure_remote.py sync --job-id 1517915
python3 benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/motivation_exposure_remote.py sync --job-id 1517917
python3 benchmark/AegisKV/experiments/scripts/paper/build_motivation_measured_exposure.py --measured benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517915/measured.json benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517917/measured.json
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_compact.py --only exposure --output-dir benchmark/AegisKV/exports/motivation-measured-exposure-20260921/figures
```

These collection/analysis commands do not allocate GPUs. They preserve the
Figure 1 assets and write the new Figure 2 exports outside the paper before
review and publication. Terminal accounting is stored with the raw data.

## Terminal outcome

Job 1517917 completed in 232 allocated seconds (464 GPU-seconds).
Together, the two revision jobs used 1816 GPU-seconds (0.504444 GPU-hours).
The remote ledger reconciles to 20043 GPU-seconds used under the registered
20700-GPU-second cap, with no active AegisKV job. All four plotted lengths
have three complete timings after a full warmup; there are twelve plotted
full-Prefill timing samples, not twelve independent experiments.
No shared-storage KV was created. See the matched mapping in
`../motivation-compact-cc/recovery-costs-measured.json` and the final audit
in `exports/motivation-measured-exposure-20260921/review/AUDIT.json`.
