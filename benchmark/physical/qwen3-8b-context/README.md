# Qwen3-8B context physical probe

Each numeric directory is one Slurm job published by
`scripts/physical/qwen3_8b_vllm_context_probe.sbatch`.  A consumable directory
must contain `PUBLICATION_COMPLETE.json`, must not contain
`PUBLICATION_INCOMPLETE`, and must pass `sha256sum --check SHA256SUMS`.

The probe uses the pinned offline Qwen3-8B snapshot and pinned 1Cat vLLM
environment.  It runs a native 8,192-token prompt, the same prompt under the
proposed static-YaRN factor-4 configuration, and exactly 131,071 prompt tokens
plus one generated token.  After each engine starts, it also reads the actual
worker `FullAttentionSpec` objects through vLLM's collective RPC and checks all
36 layer names, dimensions, dtype/quantization mode, and aggregate page bytes
against the matching checked-in `kv-layout.json`.  This is a runtime layout
differential, not a CUDA allocator measurement.  The overall result remains
physical functional evidence only:
wall-clock fields are telemetry, not calibration or performance evidence, and
the synthetic short prompt is not a quality evaluation.  The manifest labels
this as a `physical_functional_diagnostic` with an evidence ceiling of
`physical_functional_only`; it does not claim any E-level calibration or formal
experiment result.

Submit from the repository root:

```bash
sbatch scripts/physical/qwen3_8b_vllm_context_probe.sbatch
```

Job `142285` received an L40S allocation on 2026-08-30 but failed in wrapper
preflight before the probe Python process or model load. The submitted wrapper
incorrectly derived the repository root from Slurm's spooled
`BASH_SOURCE[0]`; the fail-closed record is
`142285-preflight-failure.json`. The wrapper now resolves and validates the
submission directory through `SLURM_SUBMIT_DIR`. This failed allocation is not
a physical functional result and must not be counted as a completed probe.

Replacement job `142288` passed source/model/runtime checks and identified its
assigned L40S, but the pre-launch NVML guard found a foreign Python process
holding 18,528,337,920 bytes on that GPU.  It therefore published a complete
audited `FAIL` bundle without loading the model or running any context case.
Job `142290` is a delayed retry pinned to `gpu20` no earlier than
2026-08-30 10:50 local, after the unaccounted incumbent's scheduled end.  It
retains the same process-isolation guard; its pending scheduler state is not a
physical result.

The probe never kills processes.  It checks only the single GPU exposed in its
own Slurm allocation and fails closed if another process is present there.  At
job start the wrapper copies and hashes the Python probe into staging, executes
that exact copy, and captures the actual Slurm-spooled wrapper with
`scontrol write batch_script`; a missing or mismatched capture fails closed.
