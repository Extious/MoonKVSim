# Qwen3-8B vLLM forward calibration bundles

This directory is the no-clobber publication root for the pinned, forward-only
AIConfigurator calibration harness.  It is deliberately limited to one
assigned and process-isolated Slurm-visible NVIDIA L40S, TP=1, PP=1, bfloat16,
FlashAttention, 16-token blocks, and Qwen3-8B's native 40,960-token context
mode.  It does not run or validate the proposed static-YaRN 131,072-token mode.

Job `142289` reached wrapper preflight but failed before the harness or model
ran because its `--exclusive` request expanded the allocation to both L40S
GRES.  The failure is preserved in `142289-preflight-failure.json`.  Corrected
job `142291` requests exactly one GRES without `--exclusive` and is currently
only a dependency-waiting scheduler submission; it is not a physical result.

The checked-in minimal campaign inputs are:

- `configs/physical/aiconfigurator/qwen3-8b-l40s-native-40960/shape-plan.json`;
- `configs/physical/aiconfigurator/qwen3-8b-l40s-native-40960/residual-thresholds.json`.

The plan has seven exact ordered shapes: three prefill, three decode, and one
mixed observation.  It covers batch sizes 1 and 2, extensions 1/128/512, and
past-KV lengths 0/127/511.  Each shape receives one untimed feasibility pass,
five timed warm-ups, and twenty measured repeats.  Mixed measurements are kept
as a separate observation; they are not represented as the sum of prefill and
decode predictions.  The minimal driver intentionally fails with exit 5 for
nonzero-past prefill shapes or mixed vectors whose decode members do not appear
before zero-past prefill members.

Submit only from the repository root, after reviewing the allocation request:

```bash
sbatch --job-name=moonkv-aic-l40s-tp1 \
  --partition=short --nodes=1 --ntasks=1 --cpus-per-task=16 \
  --gres=gpu:l40s:1 --constraint=l40s \
  --mem=96G --time=04:00:00 \
  --export=ALL,HF_HUB_OFFLINE=1,TRANSFORMERS_OFFLINE=1 \
  scripts/physical/run_aiconfigurator_vllm_forward_calibration.sbatch \
  --hardware-profile l40s --tp-size 1 --pp-size 1
```

The wrapper does not submit, cancel, requeue, release, or inspect unrelated
jobs.  It captures only its own Slurm job description, the `short` partition
description, and the spooled batch script; stages immutable inputs in a
verified-writable job-specific directory beneath `/tmp`; and checks the
assigned GPU for leaked compute processes after the harness exits.  Because
Slurm executes a spooled copy, the wrapper never derives the repository from
`BASH_SOURCE`; it fails closed unless `SLURM_SUBMIT_DIR` resolves exactly to
`/home/comp/zhanzhao/MoonKVSim`.  A failed run keeps its `/tmp` staging
directory for diagnosis; a successfully published run removes only that exact
`mktemp` directory.

The first submission showed that `#SBATCH --exclusive` expands this cluster's
allocation to both node GPUs while `short` still reports
`OverSubscribe=FORCE:4`; it therefore cannot prove isolation and is no longer
requested; whole-node exclusivity is not claimed or used as evidence.  The
enforced isolation boundary is the assigned GPU only: the job record must
bind exactly one `gpu:l40s` GRES, CUDA must expose one device, torch/NVML must
identify it as an L40S, and both pre/post NVML snapshots must contain no foreign
GPU process.  `environment.json` and `manifest.json` preserve this boundary and
the partition/job `OverSubscribe` fields explicitly.

A successful numeric job directory contains at least `shape-plan.json`,
`residual-thresholds.json`, `raw-forward.jsonl`, `step-metadata.jsonl`,
`held-out-split.json`, `environment.json`, `manifest.json`, `SHA256SUMS`, the
executed harness bytes, and the actual Slurm-spooled wrapper.  It is consumable
only when `PUBLICATION_COMPLETE.json` exists, `PUBLICATION_INCOMPLETE` does not,
and `sha256sum --check SHA256SUMS` passes.  `raw-forward.jsonl` has the exact
sample field set in the physical plan; the sidecar preserves scheduled budget,
prompt counters, request count, and the model-runner input fingerprint for
every feasibility, setup, warm-up, and measured scheduler step.

Exit codes are fixed: 2 invalid/noncanonical input, 3 source/model/runtime or
provenance drift, 4 GPU/profile/co-residency mismatch, 5 exact scheduler shape
not constructed, 6 CUDA-event timing failure, 7 OOM feasibility outcome, and 8
no-clobber publication failure.  An exit-7 bundle contains an audited
`feasibility.json` and no latency JSONL.

Every manifest states `formal_use_allowed=false`.  This harness never writes a
calibrated profile or a residual report.  A separate offline reducer must bind
the exact detected hardware fingerprint, raw predictions, observed durations,
the frozen split, and the predeclared thresholds before the E3 loader can be
considered.  The threshold file's profile fingerprint is the pre-allocation
campaign identity; it is not an E3 `PredictionProfile` fingerprint, because an
exact detected hardware profile and materialized vLLM database do not exist
before this run.  Rebinding that identity is an explicit remaining promotion
gate.  Static tests and a successful physical run still do not establish
E4 end-to-end simulator validity or paper-ready evidence.

Budget four hours in Slurm.  The seven-shape TP1 campaign is expected to finish
in roughly 30–90 minutes once the model is resident, but startup/JIT variance,
FlashAttention compatibility, exact scheduler ordering, GPU clock policy, and
the pinned environment's available KV-cache capacity remain runtime risks.
