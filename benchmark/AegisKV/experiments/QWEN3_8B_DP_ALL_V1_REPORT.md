# Qwen3-8B DP-only AegisKV GlobalDES report

## Evidence boundary

This is an **E2 modeled/preliminary** result produced by CPU-only metadata
simulation on one monotonic nanosecond `GlobalDES` clock. It is not calibrated,
paper-ready, or evidence of physical hardware performance. No model inference,
CUDA kernel, live GPU, network transfer, RDMA service, Slurm job, sleep, or
wall-clock timing measurement was executed.

This bundle is the current complete AegisKV matrix. It supersedes
`e2-initial-v1` for current-implementation analysis and replaces the split
between that legacy full matrix and the later `e2-fluid-core-v2` subset.

## Locked model and parallelism scope

Every protocol, provenance document, result row, variant parameter object, and
payload binds the same machine-audited deployment contract:

- model: `Qwen/Qwen3-8B` only;
- revision: `b968826d9c46dd6066d109eabc6255188de91218`;
- model-config SHA-256:
  `f7c4eadfbbf522470667b797a3c89be2524832d2d599797248dc304fff447c30`;
- tensor parallelism: fixed at TP=1, with no TP sensitivity;
- pipeline parallelism: fixed at PP=1, with no PP sensitivity;
- the only varied parallel dimension is DP, with DP in {2, 4, 8};
- primary-KV bytes use source-derived Qwen3-8B TP1/PP1 layouts; these are not
  physically calibrated KV-capacity measurements.

## Frozen implementation and matrix

- implementation commit: `690a8734ebef386b712e7f602d2a267632f17caf`;
- implementation tree: `c087e2e74cdac408d30356c904c9011f1e7bbf0b`;
- communication: sliced, work-conserving weighted max-min fluid contention;
- GPU HBM: a closed 80-GiB event-boundary ledger per simulated GPU;
- Store: independent source-owned DRAM placement and transfer lifecycle;
- failure type: `GPU_FAILURE` only;
- workload: 117 unmodified Weka trace spans from two workflows;
- context buckets: 8K, 32K, 64K, 96K, and 128K source hash-block shapes;
- suites: 7 core systems, 12 ablations, and 27 sensitivity variants;
- scenarios: `no_failure` and `gpu_failure`;
- seeds: 0, 1, and 2;
- repetitions: fresh A and B GlobalDES instances;
- result rows: 2,760;
- exact A/B pairs: 1,380;
- frozen failure schedules: 285.

Repeat A is the statistical observation. Repeat B is a byte-determinism replay,
not a second independent sample. Statistics use conservative two-sided 95%
Student-t intervals over the three seeds.

Publication identity:

- matrix manifest fingerprint:
  `676d77b124701b6b902fe317639e0f4563d317d885932abb4883fcff17933ad9`;
- matrix manifest SHA-256:
  `36b0a77b1d1ffa9dcd2b83a081d602e341691354d32b6c0bddbd18830e2a08ec`;
- results SHA-256:
  `7b788258b0cebd87a83c148b62995f2bbf0ce5fd5dc521e08f4cb22fb8be58c8`;
- statistics SHA-256:
  `cb498682c55d39cc3e773f2314e8b9568464a9a5fcf44f6e22b5dc210bd8e421`;
- representative-run SHA-256:
  `38d313227874181f8930538c2bfeaa2bc749184b757577e1ba600503ea5b5a3d`;
- figure manifest SHA-256:
  `4f18ab02940cc67e901ae26a56299a7b254308513e98c5a1c6826696ca64a5c9`.

## Preliminary core result

The following matched comparison uses full AegisKV and Vanilla Mooncake DRAM
under `GPU_FAILURE`. WCT is the whole-workload mean; the bucket identifies the
failure-focus cell. Negative WCT delta favors AegisKV.

| Bucket | Vanilla WCT (s) | AegisKV WCT (s) | Relative WCT delta | 95% WCT-delta interval (s) | Goodput delta | Recovery-local observation |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 8K | 6342.427 | 6329.289 | -0.207% | [-15.806, -10.469] | +0.305% | no restore/recompute difference |
| 32K | 6343.214 | 6312.913 | -0.478% | [-91.535, +30.933] | +0.432% | latency -17.4%; 2,731 more restored tokens |
| 64K | 6353.166 | 6320.923 | -0.508% | [-85.549, +21.064] | +0.409% | no restore/recompute difference |
| 96K | 6359.455 | 6328.143 | -0.492% | [-123.483, +60.861] | +0.450% | latency -4.0%; no restored-token difference |
| 128K | 6347.065 | 6323.906 | -0.365% | [-105.994, +59.676] | +0.438% | latency +16.1%; 28,672 fewer restored tokens |

Only the 8K WCT interval remains below zero. The other four WCT intervals and
all five goodput-difference intervals cross zero. The matrix therefore does
**not** support a blanket AegisKV performance-win claim.

Resource cost is material in the same failure cells:

- aggregate AegisKV Peer-HBM peak is 21.52--28.69 GiB across four DP ranks;
- both AegisKV and Vanilla fill the modeled 63.98-GiB Store pool;
- AegisKV network byte-time is 12.8%--73.0% higher than Vanilla;
- AegisKV copy-engine busy time is 63.6%--78.9% higher than Vanilla.

## DP-only sensitivity

The table below is a descriptive mean over 15 repeat-A failure cells (five
buckets by three seeds). Buckets are not claimed as additional independent
replicates, so this table has no confidence interval and is not a physical
scaling result.

| DP | Mean WCT (s) | Goodput (tokens/s) | Recovery-ready mean (s) | Restored tokens | Recomputed tokens | Peer-HBM peak (GiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 6364.813 | 5.779 | 31.127 | 24,644 | 33,805 | 9.98 |
| 4 | 6323.035 | 5.807 | 22.753 | 9,353 | 49,728 | 25.65 |
| 8 | 6308.472 | 5.816 | 23.953 | 13,995 | 45,124 | 52.93 |

Within this uncalibrated model, increasing DP reduces whole-workload WCT while
substantially increasing aggregate Peer-HBM use. Recovery is not monotonic:
DP=4 has lower modeled recovery-ready delay than DP=8, while DP=2 restores more
tokens. These trade-offs should be treated as hypotheses for model refinement,
not hardware scaling claims.

## Ablation diagnostic

Across the same 15 repeat-A failure cells, random eviction is 1.769% worse in
mean WCT than the full policy, LFU is 0.572% worse, and removing reuse value is
0.383% worse. Conversely, disabling anti-colocation is 0.136% better and LRU is
0.097% better in this modeled aggregate. These negative controls prevent a
claim that every current AegisKV mechanism is individually beneficial; the
anti-colocation and value-policy assumptions require further refinement.

## Preliminary figures and audit

The current figure bundle contains F1--F11 and F13--F15 (14 SVGs), each with a
hash-locked provenance sidecar and per-point result bindings. F12 simulator
accuracy is intentionally excluded because observed-versus-predicted evidence
would require physical calibration, which is outside this simulation-only
scope.

The strict offline auditor passes the complete matrix and figure bundle. It
recomputes statistics, checks the exact matrix cross-product, A/B payload and
journal equality, artifact hashes, GlobalDES/no-physical boundaries, SVG point
bindings, and the Qwen3-8B DP-only deployment contract.

```bash
uv run python scripts/audit_aegiskv_e2_artifacts.py \
  --matrix-dir benchmark/AegisKV/experiments/e2-qwen3-8b-dp-all-v1 \
  --figure-dir benchmark/AegisKV/experiments/figures/e2-qwen3-8b-dp-all-v1
```

Expected status: `PASS`, `result_count=2760`, `pair_count=1380`,
`required_svg_count=14`, `physical_execution=false`, and `slurm_used=false`.

Repository verification at publication: `760 passed, 1 skipped`; Ruff PASS;
mypy PASS for 94 source files; strict mypy PASS for the standalone auditor.

## Remaining claim boundaries

- all time, rate, and capacity parameters remain modeled and not calibrated;
- 128K means source-reported 64-token hash-block shape coverage, not target
  tokenizer-equivalent physical 128K inference evidence;
- the proposed 128K YaRN layout is source-derived and physically unvalidated;
- only three seeds are available, so intervals remain wide;
- no TP, PP, other-model, physical-network, or physical-inference result is in
  scope;
- F12 and paper-ready causal/performance claims remain unavailable.
