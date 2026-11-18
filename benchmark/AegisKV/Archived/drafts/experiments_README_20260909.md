# AegisKV experiments

当前论文入口：[Paper_Draft.md](Paper_Draft.md)。按 **Motivation 3 图 + System Overview 1 图 + Evaluation** 组织；Evaluation 用逐 Workflow 配对、真实抢占轨迹和恢复来源解释当前结果，并补充并发与固定外部故障频率扫描。

初稿含 13 张现有图及 P1–P8 八组未执行图稿规格（10 张独立候选），每项明确横纵坐标、对照、条件性理论趋势与可能反转的情形。[论文审查与已落实修改](PAPER_DRAFT_REVIEW.md) 记录正式文献版本、叙述改进及仍需实验补齐的证据；候选不计作结果图。

正文不再使用全部异质 Workflow 的原始 WCT P95 论证故障收益。并发比较采用同配置、同 ID 的 WCT 差值；故障比较新增 180 s 固定追加事件的 K2−K1 配对，保留实际受害身份与完整 160 个 Workflow 的释放/完成时刻变化。原始分位数仍保存在补充点表。

[实验设计与状态](EVALUATION_DESIGN.md) · [图稿/来源/实际尺寸检查](PAPER_FIGURE_REVIEW.md) · [事件诊断](../../../output/aegiskv-revision-20260909/EVALUATION_DIAGNOSIS.md) · [历史图像](Old_Figures.md)。

算法 2/3 保持 source-v3 冻结，原生收益仍未验证。并发只改活跃 Workflow 上限；故障率使用单独派生的外部时钟协议，不修改 live 算法。扩展图只读取完整审计后的点表。正式单故障隔离、DP/TP/Model、其他 baseline 与消融仍待执行；前版 [protocol.json](evaluation-design/protocol.json) 的拟议重复/阈值不作为本轮已完成实验。

当前图像生成与审查：

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_revision_scaling.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_revision_story.py
python3 benchmark/AegisKV/experiments/scripts/paper/render_agent_lease_markdown.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/audit_revision_story.py --prepare-visuals
```

完成实际 PNG、PDF 及插入页面核对后运行 `audit_revision_story.py`。构建不启动模拟；缺少完整点表时不会生成伪造曲线。逐图源与可选 LaTeX 同行组合见图稿审查。

## Earlier Mooncake-aligned 8B study (2026-09-06)

The configuration-driven entry below is retained for the September 6 study.
The current algorithm revision has its own frozen `run_agent_lease_mechanisms.py`
entry and `configuration` binding; the older one-second AIMD settings below do
not describe the current 50 ms Guarded AIMD experiment.

The living `configs/engine.json` now selects `mooncake_prompt_v1`: every sealed
4,096-token prompt chunk is a candidate; request-specific salts isolate KV;
rendezvous routing fixes source/standby identity; local backup recovery copies
into separate primary buffers; completed requests drain and free protection.
The HBM quota is alpha times registered capacity, with one-second AIMD windows.
The library retains `legacy_v3` as its explicit compatibility mode for older
callers and historical results. The legacy routing/alias description below
does **not** apply to the current configured mode.

The revised paper and its 170-run paired protocol are in
[`../paper/simulation-8b`](../docs/paper/REVISION_OVERVIEW.md). See its
[`MOONCAKE_ALIGNMENT.md`](../docs/paper/MOONCAKE_ALIGNMENT.md) for exact
source mappings and the prompt-only, ideal-CPM, uncalibrated timing boundary.
The September 1/5 contracts and campaigns below remain historical evidence;
they do not identify the corrected runtime's results. The revised campaign
uses a separate immutable source/content manifest, without committing the
user's mixed workspace changes.

## Existing configuration and historical contracts

This tree is the AegisKV paper experiment workspace. The three living JSON
inputs are under `configs/`; `requests.md` records the dataset audit:

The completion gates for the ongoing formal Algorithm 2/3 and Qwen3-32B work
are frozen in [`FULL_ALGORITHM_SIMULATION_CONTRACT.md`](FULL_ALGORITHM_SIMULATION_CONTRACT.md).
The defect-by-defect implementation status is recorded in
[`SIMULATION_AUDIT_2026-09-01.md`](SIMULATION_AUDIT_2026-09-01.md).
Until every gate in that document passes, the existing paper sweeps remain
development E2 results and must not be relabeled as complete Algorithm 2/3
evidence merely because a figure has a desirable trend. Results produced before
the exact-token scheduler/HBM-authority, policy-granularity, and Store-lookup
repairs are stale diagnostics only; they are not current measurements or valid
inputs to a refreshed paper figure.

- `configs/requests.json` — selected public FanOutQA `dev` dataset,
  complete-question replay, closed-loop `workflow_concurrency`, and context
  guards. It binds the evidence-backed Qwen3-8B workload, manifest, and their
  content hashes for exactly 160 complete workflows.
- `configs/failure.json` — compact first-release `GPU_FAILURE` input: inject two
  ordered failures in one fresh workload cell by default. Each variant selects
  naturally routed focus spans near the shared 33%/67% workload targets and
  injects on the hosting GPU at 60% of that span's compute progress. The
  failed GPU or equivalent replacement capacity becomes reusable after two
  minutes of global virtual time. Injection and detection share one virtual timestamp;
  fixed fail-stop semantics and the parameter rationale live in
  `configs/failure/README.md`, while reroute remains an engine control.
- `configs/engine.json` — minimal modeled hardware input: Qwen3-8B, DP=8,
  8x A100-40GB on one node, a colocated 1 TB Mooncake DRAM Pool, and one
  PCIe-only effective rate of 25 GB/s. It declares no RDMA or Host staging.

`scripts/` runs those configs through the MoonKVSim AegisKV library. New
publications install the three JSON files into `results/<group>/configs/` in
the same atomic rename as the matrix and bind their hashes in `manifest.json`.

`results/` holds one directory per generated development group plus
`results/figures/` for plotting scripts and paper-facing SVGs. Presence in this
directory does not imply that a run passed the formal or paper-ready gates.
`workloads/` still contains the
historical 117-span Weka pilot subset; the living `requests.json` no longer
references it.

The living workload selection is FanOutQA rather than ODR. Its public,
human-authored decomposition and `depends_on` fields define the causal DAG;
revision-pinned Wikipedia evidence supplies branch content. The derived
Qwen3-8B adapter freezes 1,304 model requests and a gzip snapshot of every
exact Wikipedia revision used during ranked-prefix selection. The earlier ODR
normalizer remains test-covered reference code but is not selected by
`requests.json`.

The frozen workload is valid for the configured 131,072-token model limit, but
it must not be described as observed 128K-context coverage. Its per-request
prompt-token distribution has median 16,437, P95 55,272, and maximum 86,198;
the frozen manifest records `128k: 0`. The paper-sweep launcher publishes this
coverage fact and rejects any claim that the current workload contains an
observed 128K request. No truncation, padding, cross-workflow concatenation, or
synthetic extension is used to manufacture a longer context.

## Legacy v3 behavior (retained for old artifacts)

Cache-aware DP routing follows Mooncake's ownership split: the simulated
Conductor unions normal inference HBM KV and AegisKV Peer-HBM protection KV on
each DP rank, deduplicates their token coverage, and reports the longest
continuous local prefix plus the Store-tier prefix. The external router combines
that index result with Store-to-HBM restore time, the per-rank compute calendar,
and remaining model time. Mooncake Store itself does not select the initial DP
rank. Initial Store cache reads advance the
global virtual clock using the selected transport's path bandwidth, but do not
yet contend as shared fluid flows; failure-recovery transfers do use the shared
weighted max-min flow model. This is a routing-complete initial model, not a
claim of complete Mooncake data-plane fidelity.

Policy chunks never cross cache-identity scope boundaries. In particular, the
shared FanOutQA system template occupies one source-hash block (up to 64 tokens)
and is retained as a globally keyed chunk even though the configured maximum
policy chunk is 1,024 tokens; workflow-private blocks remain keyed by workflow.
This prevents a short shared prompt from being accidentally merged into private
request content and silently losing normal-HBM reuse.

Failure rerouting revalidates and atomically adopts only a target-local
**inactive** normal-HBM continuous prefix before reclaim.  This is symmetric
opportunistic cache reuse for Mooncake and AegisKV, not committed AegisKV
protection evidence.  Its bytes move directly from
`INACTIVE_REUSABLE_KV` to `RECOVERY_DEST_RESERVED` with zero network service.
Active-primary observations remain excluded because the simulator does not yet
model immutable page pins/reference counts.  Committed Peer-HBM recovery is
restricted to the request's Router-designated target rather than taking the
longest prefix from an arbitrary healthy Peer pool.

## Existing experiment tooling

The config directories attached to pre-layout releases are reconstructed
historical snapshots. Their values are checked against the result rows, but
their hashes are not retroactively part of the original manifests; the offline
auditor reports those as `reconstructed_unbound`. New releases must report
`manifest_bound`.

Run the current lock from the repository root (clean worktree required):

```bash
uv run python benchmark/AegisKV/experiments/scripts/run_aegiskv_e2_matrix.py \
  --suite core \
  --output-dir /tmp/aegiskv-e2-core

uv run python benchmark/AegisKV/experiments/results/figures/generate_aegiskv_e2_figures.py \
  --results /tmp/aegiskv-e2-core/results.jsonl \
  --manifest /tmp/aegiskv-e2-core/manifest.json \
  --representative /tmp/aegiskv-e2-core/representative-run.json \
  --output-dir benchmark/AegisKV/experiments/results/figures/generated
```

All outputs remain E2 modeled/preliminary and not calibrated.

Algorithm 1 is evaluated in an explicit ideal-trace mode for these sweeps.  The
known per-agent `recorded_api_time_ns` values are used as exact node durations;
an exact forward/backward CPM pass over each frozen workflow DAG computes
`slack = max(0, LS - ES)`.  This path does not train or invoke a predictor and
does not use observed absolute finish timestamps or the selected failure
location.  The artifact records that provenance under
`metrics.policy_effects.algorithm1`. The exact CPM slack is observed when the
request becomes causally ready and decays on GlobalDES time. Protection credit
is evaluated at the actual chunk-seal `PUT_START`, and recovery ordering uses
the remaining slack at failure rather than granting the original slack again.

The AegisKV full variant now uses independent, source-owned formal
`SlackLandlord` instances for Peer HBM and Store DRAM. The two protection paths
reserve, transfer, commit, abort, and fail independently; Store is not a
target-owned writeback or destage of Peer HBM. Each path enforces one safe
suffix frontier per logical request, candidate-request victim exclusion, lazy
frontier refresh, strict per-victim `H_y < Theta`, and the exact joint
`A > D_Y` admission gate. A physical content alias can serve multiple logical
requests without collapsing their frontiers; alias-dependent requests
participate in exact victim-loss recomputation, while the candidate's already
shared physical content is excluded from its victim set. Destination reserve,
`PENDING`, transfer, `COMMITTED`, and `ABORTED` are journaled separately, and
only committed chunks are recovery eligible. A fail-closed artifact auditor
reconstructs these decisions from the event stream rather than trusting
capability labels alone.

Admission and frontier decisions are now made independently for every physical
candidate. A workflow-private candidate is never larger than the configured
1,024-token policy unit; the shared global system template may remain the
separate 64-token source block. After individual preview/apply, transfer service
may combine at most eight adjacent admitted/`PENDING` candidates into one
physical task. Completion still commits every policy unit in order, while an
abort removes the pending suffix in reverse order. With multiple Store
segments, only adjacent candidates mapped to the same segment are combined and
their original global order is preserved. Formal Store route and recovery
lookups use the same content-addressed protection chunks as formal writes;
Mooncake's ordinary Store lookup retains its original request-key semantics.

Peer-HBM AIMD records foreground-pressure observations immediately but latches
them until the next fixed per-target GlobalDES control window.  That window
performs at most one multiplicative decrease after coalescing the maximum
shortfall, resident-primary count, and reason set observed during the window.
Additive increase still requires `K` consecutive stable windows. The
slow-timescale interval is frozen for a run as the median ideal-CPM workflow
makespan (with a one-second floor), and each decision records
primary-headroom pressure, resident-primary request count, the action, and the
resulting alpha.
Headroom is `FREE + INACTIVE_REUSABLE_KV`, so ordinary inactive-cache eviction
does not create a false pressure signal; a shortfall or allocation/reclaim
stall is observed before Peer-HBM reclaim. A smaller quota immediately invokes
formal safe-tail contraction. Scale-plot alpha summaries are virtual-time-
weighted across DP ranks instead of event-count-weighted.

The exact-token experiment path now uses scheduler-step continuous batching and
a unique physical HBM authority backed by the experiment `CapacityLedger`.
Scheduler block pools remain logical 16-token pages. Before publishing a
scheduler allocation/free mutation, the authority atomically maps those pages
onto rounded 64-token source allocations, handles inactive-prefix zero-copy
activation, and audits resident logical bytes against physical `ACTIVE`
ownership after every step. AIMD pressure is derived from this resident/ledger
state. On failure, the scheduler is fenced before the experiment performs the
one-time physical `UNAVAILABLE` transition. Recovery may adopt only a verified
block-aligned external prefix, then recomputes the remaining prompt suffix,
silently replays already committed output positions, and commits external
output once; lost HBM is never reused or released twice.

This closes the exact-token modeled residency capability, not the calibration
or physical-execution gap. Scheduler-step durations still come from known
ideal-trace request durations plus an uncalibrated token-share and batch-
composition model. The source-hash fallback retains the legacy one-request
lane and must report `continuous_batch_residency_modeled=false`. Neither path is
evidence of measured A100 kernels, CUDA/NCCL execution, or PCIe/RDMA transfer
timing.

The requested 160-workflow paper sweep has a separate fail-closed launcher. It
uses exactly the frozen deterministic seed vector 0--4 per cell as the independent
sampling units, retains the exact paired Mooncake/AegisKV observations, and
requires every planned failure and repair to execute. It refuses formal output
while `continuous_batch_residency_modeled` is false or the compute scheduler is
not the scheduler-step bridge; this prevents queue-only concurrency sensitivity
from being mislabeled as validated batching pressure.
The causal plan oracle executes both frozen system profiles and selects
deterministic logical focus spans that remain unaffected and temporally feasible
for both at the shared workload-progress targets. Measured cells reuse those exact
span IDs while each system retains the physical GPU produced by its own natural
route. The launcher rejects a cell if any logical focus cannot be projected or
the two systems' focus lists diverge. The first focus
span uses the highest non-empty context bucket; later failures may select from
the whole workload so multi-failure cells remain feasible without pinning a
common physical route:

```bash
uv run python benchmark/AegisKV/experiments/scripts/run_aegiskv_paper_sweeps.py \
  --output-dir benchmark/AegisKV/experiments/results/e2-fanoutqa-paper-sweeps-v2 \
  --jobs 14 --seeds 0,1,2,3,4

uv run --extra paper python \
  benchmark/AegisKV/experiments/results/figures/generate_aegiskv_paper_sweeps.py \
  --results benchmark/AegisKV/experiments/results/e2-fanoutqa-paper-sweeps-v2/paper-sweeps.json \
  --output-dir benchmark/AegisKV/experiments/results/figures/paper-sweeps-v2 \
  --pdf-output-dir output/pdf/aegiskv-paper-sweeps-v2
```

The five-seed, 14-cell formal matrix contains 70 runs when complete. No such
post-repair 70-run matrix has been generated yet, so there is currently no
refreshed formal aggregate or paper-ready figure set. The frozen workload also
still has `128k: 0`; it must not be described as observed 128K coverage. All
outputs remain uncalibrated, non-physical E2 simulation until separate physical
validation is performed.
