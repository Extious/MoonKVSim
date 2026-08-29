# Qwen3-8B vLLM forward calibration harness and Slurm plan

Status: wrapper preflight executed; no model-forward measurement completed.
Job `142289` failed exact-one-GPU allocation validation before the harness ran,
and corrected job `142291` is pending behind Qwen functional probe `142290`.
Neither failure nor scheduler state is measurement evidence, and
`SRC-BLOCK-001` remains open.

## Fixed inputs and fail-closed boundary

- Model: `Qwen/Qwen3-8B`, revision
  `b968826d9c46dd6066d109eabc6255188de91218`.
- Engine source: vLLM commit
  `644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504`; installed semantic file hashes
  must match `reference/source-lock.json` before importing vLLM.
- Predictor source: AIConfigurator `0.9.0`, commit
  `4b9d9dc51e02b5e9d4acc3688f3edf41693834c6`.
- Context modes are separate profiles: native 40,960 and the proposed 131,072
  static-YaRN configuration. A run in one mode cannot calibrate the other.
- A hardware profile binds GPU product, memory size, UUID, driver, CUDA, torch,
  vLLM version, TP/PP, dtype/KV dtype, block size, attention backend, clocks,
  and power policy. `a100_sxm` cannot stand in for an A100 PCIe allocation.
- Only GPU model-forward time is measured. Scheduler CPU, tokenizer, queueing,
  connector, Store, RPC, H2D/D2H/D2D, RDMA/TCP, and recovery stay outside the
  predictor boundary.

The harness must stop before measurement if the allocation has another process
on the visible GPU, a source/model hash differs, CUDA events are unavailable,
the requested shape is truncated, or a requested phase cannot be constructed
exactly.

## Exact next implementation step and instrumentation point

The next code change is one bounded physical harness, not a predictor artifact:
`scripts/physical/qwen3_8b_vllm_forward_calibration.py` plus
`scripts/physical/run_aiconfigurator_vllm_forward_calibration.sbatch`. Do not
implement or run it without one matching Slurm-assigned GPU whose process
isolation is verified.  On this cluster the `short` partition advertises
`OverSubscribe=FORCE:4`; the first submission demonstrated that
`#SBATCH --exclusive` expands the allocation to both GPUs without establishing
whole-node or CPU exclusivity, so later TP1 submissions must not request it.
The recorded evidence boundary is the assigned L40S GRES plus pre/post NVML
rejection of foreign GPU processes; whole-node exclusivity must remain false.

At vLLM commit `644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504`, instrument:

- file `vllm/v1/worker/gpu_model_runner.py`;
- git blob `109ee6e7c836f23282df90937d5b9387b5380cdb` and decoded-file SHA-256
  `960efef5498b41e59ab9a27e3c75367ad3ea2bb83caf6f8a9799a6f496b35297`;
- symbol `GPUModelRunner._model_forward` (defined at commit-file line 7650),
  invoked by `GPUModelRunner.execute_model` at commit-file line 8350.

Record CUDA events immediately before and after `_model_forward`, then
synchronize the end event before publishing the sample. This is the precise
GPU forward boundary; timing the outer `execute_model`, HTTP, or
`LLM.generate` is invalid because those include input preparation, scheduling,
sampling, or queueing. The outer `execute_model` hook may only carry
`SchedulerOutput` metadata into the inner timing hook. After `_update_states`
and before `_model_forward`, derive each ordered shape from
`scheduler_output.num_scheduled_tokens`, `input_batch.req_ids`,
`input_batch.num_computed_tokens_cpu`, and `input_batch.num_prompt_tokens`.
Fail if these identifiers or lengths cannot be joined one-to-one.

For every scheduler step, capture the pre-step request counters and preserve:

- phase (`prefill`, `decode`, or an explicitly separate `mixed` observation);
- ordered `extend_lengths` and `past_kv_lengths` vectors;
- scheduled token budget and request count;
- TP/PP rank and model-runner input fingerprint;
- warm-up flag, repeat index, CUDA-event duration in nanoseconds, and any
  concurrent model-internal collective declared by the profile;
- `nvidia-smi -q`, GPU UUID, active-process snapshot before/after, driver/CUDA,
  torch/vLLM versions, Slurm job/node/GRES, and hashes of every input artifact.

The harness writes append-only JSONL into a new staging directory, fsyncs it,
then publishes a no-clobber run bundle with `manifest.json` and `SHA256SUMS`.
It never writes a calibrated profile directly. A separate offline reducer
validates and converts raw samples into the profile-selection schema.

### Canonical input interface

The harness takes `--shape-plan <canonical-json> --output-root <new-directory>`
and refuses an existing output. The shape-plan schema is this exact closed
object (the arrays below are illustrative values, not measurements):

```json
{"attention_backend":"FLASH_ATTN","block_size":16,"calibration_method":"phase_shape_residual_table","context_mode":{"max_model_len":40960,"rope_scaling":null},"dtype":"bfloat16","engine":{"installed_version":"1.2.2+aegiskv.sm89","source_commit":"644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"},"hardware_profile_id":"l40s-exact-detected-profile","held_out_split_seed":20260830,"kv_dtype":"bfloat16","measured_repeats":20,"model":{"id":"Qwen/Qwen3-8B","revision":"b968826d9c46dd6066d109eabc6255188de91218"},"phases":{"decode":[{"extend_lengths":[1],"past_kv_lengths":[8191]}],"mixed":[{"extend_lengths":[512,1],"past_kv_lengths":[0,8191]}],"prefill":[{"extend_lengths":[512],"past_kv_lengths":[0]}]},"pipeline_parallel_size":1,"schema":"moonkvsim.aiconfigurator-forward-shape-plan.v1","tensor_parallel_size":1,"threshold_declaration":{"path":"residual-thresholds.json","sha256":"<64 lowercase hex>","size_bytes":1},"warmup_repeats":5}
```

Every shape is a pair of equally sized ordered positive/non-negative vectors;
`batch_size` is their length and is never supplied independently. Pure prefill
requires every extension to be greater than one or a request still inside its
prompt; pure decode requires every extension to equal one and every request to
be past prompt completion. `mixed` requires at least one member of each phase.
The runner rejects a scheduler-produced vector that differs from the requested
vector instead of relabeling, padding, or truncating it. Native-40,960 and
static-YaRN-131,072 plans are separate files and separate run bundles.

### Raw output interface

One measured scheduler step is one canonical JSONL record with these exact
top-level fields:

```json
{"batch_size":2,"cudagraph_mode":"NONE","duration_ns":123,"extend_lengths":[512,1],"hardware_profile_fingerprint":"<sha256>","measurement_method":"cuda_events_gpu_model_runner_model_forward","model_runner_source_sha256":"960efef5498b41e59ab9a27e3c75367ad3ea2bb83caf6f8a9799a6f496b35297","past_kv_lengths":[0,8191],"phase":"mixed","pipeline_parallel_rank":0,"profile_fingerprint":"<sha256>","repeat_index":0,"request_ids_sha256":"<sha256>","schema":"moonkvsim.aiconfigurator-forward-sample.v1","shape_id":"<sha256>","tensor_parallel_rank":0,"warmup":false}
```

`duration_ns` is a positive integer converted from the CUDA event without wall
clock substitution. The run directory must contain `shape-plan.json`,
`residual-thresholds.json`, `raw-forward.jsonl`, `held-out-split.json`,
`environment.json`, `manifest.json`, and `SHA256SUMS`. `manifest.json` binds
the exact harness/wrapper bytes, pinned vLLM/model inputs, GPU/Slurm inventory,
all raw files, and a `formal_use_allowed=false` evidence label. A separate
offline reducer alone may produce `held-out-residual-report.json`; the E3 loader
then verifies all referenced regular-file sizes/hashes and report semantics.

The harness exit codes are fixed: `2` invalid/noncanonical input, `3` source or
model hash drift, `4` GPU/profile/co-residency mismatch, `5` exact shape not
constructed, `6` CUDA timing failure, `7` OOM feasibility outcome, and `8`
no-clobber publication failure. Exit `7` writes only an audited feasibility
record and never a latency sample.

## Shape matrix and split

Use phase-specific shapes. At minimum, sweep:

- prefill: batch size `{1,2,4,8}`, extension `{128,512,2048,8192,16384,32768,
  65536,98304,131072}` where memory permits, and past KV `{0,8192,32768}` for
  chunked/prefix cases;
- decode: batch size `{1,2,4,8,16,32}`, extension exactly `1`, and past KV
  `{127,511,2047,8191,16383,32767,65535,98303,131071}`;
- mixed: preserve the full per-request vectors emitted by the pinned scheduler;
  do not add prefill and decode predictions unless the measured mixed profile
  explicitly supports that composition.

OOM is a recorded feasibility outcome, not a latency sample. Do not shrink,
truncate, or pad a requested shape. Use at least five warm-ups followed by a
predeclared number of measured repeats. Freeze a deterministic shape-level
train/held-out split before looking at residuals; the split manifest receives a
SHA-256 and must contain both phases and all three axes: batch size, extension
length, and past-KV length.

Calibration may use phase/shape-bucketed residual tables. One global scale
factor is forbidden. Preserve raw prediction, calibrated prediction, observed
duration, signed residual, and absolute residual for every held-out sample.
Acceptance thresholds must be declared in the run config before measurements;
until both phase coverage and those thresholds pass, `formal_use_allowed` stays
false.

## Slurm launch templates (do not submit from this plan)

L40S TP=1 candidate:

```bash
sbatch --job-name=moonkv-aic-l40s-tp1 \
  --partition=short --nodes=1 --ntasks=1 --cpus-per-task=16 \
  --gres=gpu:l40s:1 --mem=96G --time=04:00:00 \
  --export=ALL,HF_HUB_OFFLINE=1,TRANSFORMERS_OFFLINE=1 \
  scripts/physical/run_aiconfigurator_vllm_forward_calibration.sbatch \
  --hardware-profile l40s --tp-size 1 --pp-size 1
```

A100 must be launched only after querying the assigned GPU's exact SKU,
memory, interconnect, and topology. If it is PCIe or has less memory than the
AIConfigurator `a100_sxm` profile, use a distinct profile ID and collect a new
database; do not relabel it as SXM. A TP=2 feasibility candidate is:

```bash
sbatch --job-name=moonkv-aic-a100-tp2 \
  --partition=short --nodes=1 --ntasks=1 --cpus-per-task=24 \
  --gres=gpu:a100:2 --mem=160G --time=04:00:00 \
  --export=ALL,HF_HUB_OFFLINE=1,TRANSFORMERS_OFFLINE=1 \
  scripts/physical/run_aiconfigurator_vllm_forward_calibration.sbatch \
  --hardware-profile detected-a100-exact-sku --tp-size 2 --pp-size 1
```

The future sbatch wrapper must create a job-specific temporary directory under
verified-writable `/tmp`, record the resolved node/GPU mapping, run the hash and
co-residency preflight, propagate a nonzero harness exit code, check for leaked
processes, and publish artifacts only after every audit passes. It must never
release, cancel, requeue, or otherwise mutate separately managed Slurm jobs.

## Required promotion artifacts

E3 promotion requires all of the following, none of which exists yet:

1. raw forward JSONL and source/model/environment hashes;
2. immutable train/held-out split manifest;
3. phase/shape-aware residual report with predeclared thresholds;
4. materialized vLLM database bundle manifest and bundle fingerprint;
5. canonical `moonkvsim.aiconfigurator-profile-selection.v1` record validated
   by `schemas/predictor-profile-selection.schema.json` and the runtime E3 gate.

Passing this component gate permits claims only for the measured profile and
shape range. It is not E4 end-to-end simulator validation or paper evidence.
