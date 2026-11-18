# AegisKV EuroSys 2027 paper

> **当前 MoonKVSim 8B 修订论文（2026-09-06）**：
> [完整论文 PDF](simulation-8b/main.pdf)、[交付说明](simulation-8b/README.md)、
> [Mooncake 实现对齐](simulation-8b/MOONCAKE_ALIGNMENT.md)。
> 下文保留 9 月 1 日整理的旧论文来源说明与历史数值，不代表本次修订结果。


> **MoonKVSim 整理快照（2026-09-01）**
>
> 本目录是从 Mooncake canonical paper tree 整理出的当前活动论文快照，
> 仅保留 `main.tex` 实际使用的正文、算法、图件、模板和验证脚本，并附带
> 当前设计文档与已编译投稿 PDF。完整来源、哈希、证据边界、排除项和离线
> 再生成限制见 [`SOURCE_PROVENANCE.md`](SOURCE_PROVENANCE.md)。

The canonical source is the Mooncake paper tree recorded in
`SOURCE_PROVENANCE.md`; this directory is its curated MoonKVSim snapshot.
The manuscript describes the current
source-owned, independent-HBM/DRAM AegisKV design and keeps two empirical
lineages separate: frozen **legacy** SGLSim artifacts answer the workflow
completion-time (WCT) question, while frozen current-design SGLSim telemetry
describes pressure, effective alpha, tier occupancy, prefix reuse, intended
residency, copy amplification, and conditioned recovery coverage.  The latter
is mechanism evidence, not a WCT or Estimand-B result.  No legacy result is
evidence for the current implementation.

Within this self-contained snapshot, [`design/current_design.md`](design/current_design.md)
is the copied sole design authority.  Its SHA-256 must match the fingerprint
embedded in the system-design section and all three algorithm files.

## Active WCT paper snapshot (2026-08-26)

The active endpoint is workflow completion time, not Estimand B.  The paper
re-analyzes three frozen result sets without launching SGLSim, Mooncake,
vLLM, CUDA, a GPU job, or Slurm:

1. A direct DP8 fixed-alpha trial with 24 paired workflows, three soft
   failures, and no-backup/host-only/peer-GPU/legacy-AegisKV policies.
2. A Qwen3-8B logical-DP64, at-most-128K-context **model projection** for 160
   workflows.  It is not measured WCT.
3. A Qwen3-32B logical-PP heavy-failure smoke with 20 workflows at offered
   concurrency 8 and 16.  It is tagged offline-unvalidated and its historical
   pressure check is false.

The direct DP8 comparison is deliberately not a dominance result:

| Policy | Mean WCT (s) | p99 WCT (s) | Paired mean delta vs. no backup |
|---|---:|---:|---:|
| No backup | 91.695 | 113.733 | -- |
| HostBackup | 79.734 | 99.339 | -11.961 s |
| GPUReplica | 81.731 | 97.382 | -9.964 s |
| Legacy AegisKV | 87.756 | 104.269 | -3.939 s |

Legacy AegisKV improves mean WCT by 4.3% versus no backup but loses to both
simple backup controls in this trial.  The DP64 projection predicts an 11.8%
mean and 14.6% p99 reduction versus no backup.  The heavy-failure smoke shows
18.9% and 30.4% descriptive mean reductions at concurrency 8 and 16.

The defensible conclusion is narrow: the historical artifacts show that
preserving reusable KV can reduce recomputation delay.  They do not establish
the incremental WCT benefit of the current Slack-aware admission, independent
source-owned paths, or HBMQuotaAIMD.

## Current-design mechanism snapshot (2026-08-26)

Without launching a new experiment, the paper also binds frozen SGLSim lineage
`4a99c306e8f9`: 33 scenarios, 311 policy--scenario cells, 10 seeds, and 3,110
completed runs over 393 Weka workflows and 98,827 requests.  The matrix covers
Qwen3-8B TP1/PP1 and Qwen3-32B TP1/PP4, 16--128 simulated GPUs, concurrency
32--224, 1--40 GB/s transfer bandwidth, and failure hazards from 0 to 41.667
per 1,000 GPU-shard-hours.

The mechanism results now visible in the paper include:

- At concurrency 32/64/128/224, mean pressure rises from
  0.018/0.049/0.173/0.590 while mean effective alpha falls from
  0.868/0.665/0.280/0.129.
- At concurrency 128, scaling from 16 to 128 GPUs lowers mean pressure from
  0.860 to 0.077 and raises mean alpha from 0.012 to 0.492.  The 16-GPU case
  spends 27.3% of windows at alpha zero; the Qwen3-32B PP4 stress point spends
  27.6% there.
- 92.63% of requests contain workflow-local 64-token prefix reuse and 98.31%
  of input tokens are reusable under that accounting.  Reuse-stratified
  intended residency and conditioned restored-token coverage are reported in
  Evaluation rather than collapsed into a single average.
- The central point has 1.443x copy amplification.  Across 33 full-policy
  scenario aggregates (330 seed runs), no HBM-only admission or DRAM eviction
  appears; these are explicit matrix gaps, not successes.
- Fixed-K64 conditioned restored-token coverage is 0%, 87.09%, 90.92%, and
  93.28% at 1/10/20/40 GB/s.  It is descriptive conditioned-event telemetry,
  not online recovery probability, physical throughput, WCT, or Estimand B.

## Active paper spine

- `main.tex`: anonymous EuroSys review entrypoint and two-lineage abstract.
- `sections/01-introduction.tex`: problem, contributions, and explicit legacy
  evidence boundary.
- `sections/02-background-motivation.tex`: public-trace motivation.
- `sections/03-system-design-v2.tex`: current design and Algorithms 1--3.
- `sections/04-implementation.tex`: current source contract and model.
- `sections/05-evaluation.tex`: legacy WCT methodology and three WCT figures,
  followed by current-design alpha/occupancy and reuse/recovery telemetry.
- `sections/06-discussion.tex`: lineage mismatch, statistics, simulator, and
  baseline limitations.
- `sections/07-related-work.tex` and `sections/08-conclusion.tex`.

`sections/05-simulation-results.tex` and `simulation-results-manifest.json`
remain frozen historical artifacts.  They are no longer included by the
manuscript.  The build still verifies that package when present so unrelated
corruption cannot pass silently.

The paper-only mechanism binder is
`scripts/prepare_current_mechanism_supplement.py`.  It verifies and copies only
the selected frozen reuse/recovery figure and emits
`figures/current-mechanism-supplement.manifest.json`.  The alpha/occupancy
figure remains hash-bound by `simulation-results-manifest.json`; the generated
historical Estimand-B result section and its performance figures remain
excluded from `main.tex`.

Current mechanism hashes:

- Supplement manifest:
  `d0160acabd6d590e92ef00ee4659629d7005f672917c59d9779b286ada2873c4`
- Alpha/occupancy figure:
  `8541e2b70803651c0d3422320a784e843fbf6a91fa361aeb7461abeafe471cee`
- Reuse/recovery figure:
  `e2673f8b4078c57671463d0c99229747eced39701f71d2ecf5c81447c48076c8`

## WCT figure provenance

Run the paper-only renderer from this directory:

```sh
python3 scripts/render_legacy_wct_submission.py
```

It reads only the frozen archive under
`/home/comp/zhanzhao/sglsim/AegisKV/Archived/2026-08-06-pre-kvcache-centric`
and emits:

- `figures/legacy-wct-policy-comparison.pdf`
- `figures/legacy-wct-dp64-projection.pdf`
- `figures/legacy-wct-heavyfail-stress.pdf`
- `figures/legacy-wct-submission.manifest.json`

The manifest records `new_experiment=false`, `sglsim_executed=false`,
`physical_runtime_executed=false`, and `current_design_validation=false`, and
binds all source and output files by SHA-256.

Current hashes:

- WCT manifest: `6270b14753ea3475c1ca3f752275556b1096b28033ee4dbf958dc88227e50aa2`
- DP8 WCT figure: `cd503e7b2a2d81091c13e707a02168f5ab407cdecec7aacff27cad9494b5fc10`
- DP64 projection figure: `e6592cd4590aec5ebb615dda8b74e04e14eb17434bda0c8fe2a6145a16f135ea`
- Heavy-failure figure: `8f2b3e35225f8345abc202505362ef60b9ff82be8e8199c37aade66bcee05bfa`

All three are vector PDFs with 10.0 pt minimum extracted text at source size.
The active Motivation and editable System Overview figures remain unchanged.

## Build and audit

Build from this directory:

```sh
sh scripts/build.sh
```

The TeX installation must provide the dependencies required by `acmart`
(including `xstring`).  On the machine used to curate this snapshot, a plain
TinyTeX invocation lacked `xstring.sty`; the successful verification build
used the existing canonical TeX bundle by setting `AEGISKV_TEXMFHOME`,
`AEGISKV_TEXMFCONFIG`, and `AEGISKV_TEXMFVAR`.  This environment bundle is a
TeX installation, not a paper artifact, and is not copied into the snapshot.

The build verifies the current-design fingerprint, legacy WCT package, and
mechanism supplement before forcing a fresh LaTeX build.  The historical
`sections/05-simulation-results.tex` plus
`simulation-results-manifest.json` package is intentionally absent from this
snapshot because `main.tex` does not include it; `build.sh` skips that
verification when both files are absent.  The technical-page ceiling defaults
to 99 for the unrestricted historical full-integration draft and can be
overridden with `AEGISKV_MAX_TECHNICAL_PAGES` when that package is present.

The active build has 12 technical pages followed by two reference pages;
References starts on page 13.  All 14 pages were rendered and visually
inspected.  The log has no overfull box, undefined citation/reference, fatal
LaTeX error, or undefined control sequence.

- Final PDF: `output/pdf/aegiskv-eurosys2027-submission.pdf`
- Final PDF SHA-256:
  `5ab501f2f8914af575375c27d612af9c8562fb0064f50da1ec7f490fe3884c68`

## Submission boundary

The paper is structurally complete, and the current-design telemetry supports
mechanism-level statements about alpha, pressure, occupancy, reuse, intended
residency, and conditioned recovery coverage.  It does not supply
current-design WCT or physical serving validation.  Before claiming
current-design performance, rerun a multi-seed, same-lineage WCT campaign with
current Algorithms 1--3, matched baselines, executed failover, and
contention-aware serving.  Do not remove the legacy/projection/smoke or
mechanism-only qualifiers from this snapshot.
