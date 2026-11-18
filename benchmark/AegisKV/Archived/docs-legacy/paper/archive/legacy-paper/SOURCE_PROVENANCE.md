# AegisKV 当前活动论文快照来源说明

## 快照身份

- 整理日期：2026-09-01
- MoonKVSim 目标目录：
  `/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper`
- canonical paper source：
  `/home/comp/zhanzhao/Mooncake/aegiskv/paper`
- canonical design source：
  `/home/comp/zhanzhao/Mooncake/aegiskv/design/current_design.md`
- 初始迁移关系：Mooncake 中的论文树最初于 2026-08-16 从
  `/home/comp/zhanzhao/sglsim/AegisKV` 导入；SGLSim 仍是历史论文资源和
  冻结实验输入的来源，但不能覆盖当前 Mooncake canonical tree。
- `design/current_design.md` SHA-256：
  `0fdfd097a536ab73cd9f7eb12099eb6f5b9c068a061da30af57a8e6798caacac`
- canonical 已编译投稿 PDF SHA-256：
  `5ab501f2f8914af575375c27d612af9c8562fb0064f50da1ec7f490fe3884c68`

这是当前本地工作区的整理快照，不是 Git 锚定的 release。整理时
`/home/comp/zhanzhao/Mooncake/aegiskv` 源目录未被 Git 跟踪，因此上述
来源身份依赖绝对路径、文件内容和 SHA-256，而不是可检出的 commit/tag。

## 证据边界

论文严格保留两条互不替代的证据线：

1. **WCT 是 legacy frozen evidence。** 三组 WCT 资源来自早期 SGLSim
   原型：DP8 单次配对试验、DP64 模型 projection、以及 heavy-failure
   logical-PP stress smoke。它们说明避免 KV 重计算可能降低 WCT，但不验证
   当前 source-owned independent-tier 设计。
2. **current-design 仅为 mechanism telemetry。** 当前设计活动资源只支持
   alpha、pressure、occupancy、reuse、intended residency、copy
   amplification 与 conditioned restored-token coverage 等机制诊断。
   它们不是 current-design WCT，不是 physical serving/failover measurement，
   也不是可直接作为 paper-ready 性能结论的证据。

不得删除或弱化正文、manifest、README 中关于 legacy、projection、
smoke、simulated-only、non-physical 和 mechanism-only 的限定。

## 本快照包含

- `main.tex`、`references.bib`、源 README/MIGRATION、reviewer audit 和
  result integration plan。
- `main.tex` 实际 include 的 `sections/01` 到 `sections/08`，其中活动设计
  是 `03-system-design-v2.tex`，活动评估是 `05-evaluation.tex`。
- 三个算法资源：`slack-update.tex`、`slack-landlord.tex`、
  `guarded-aimd.tex`。
- 活动 Motivation、System Overview、legacy WCT 和 current-mechanism
  图件及其 manifest；同时保留图件 README。
- 构建与活动包验证脚本、ACM class/BST。
- canonical 已编译 PDF，位于
  `output/pdf/aegiskv-eurosys2027-submission.pdf`。
- canonical 设计副本，位于 `design/current_design.md`。

## 明确排除

本快照故意不包含：

- `quick_4090*`、物理 pilot、fleet/preflight、fallback、bootstrap、
  preliminary、superseded 和其他实验运行目录；
- 历史或被排除的 figure candidates，以及未被当前正文引用的旧设计图；
- `tmp/`、`__pycache__/`、LaTeX `aux/log/out/bbl/blg/fdb_latexmk/fls`
  等构建缓存；
- `sections/05-simulation-results.tex`、
  `simulation-results-manifest.json`、相关 tables/renderer/audit，即未被
  `main.tex` include 的历史 full-integration package；
- Mooncake paper tree 中的其他旧 section、旧 renderer 和测试脚本。

## 构建与验证

从本目录运行：

```sh
sh scripts/check_design_sync.sh
sh scripts/build.sh
```

`build.sh` 在 historical full-integration section 与 manifest 同时不存在时
跳过该包；若只出现其中一个则失败，以避免半包状态。

本机默认 TinyTeX 缺少 `xstring.sty`。验证时使用 canonical paper tree 已有的
只读 TeX 安装 bundle：

```sh
AEGISKV_TEXMFHOME=/home/comp/zhanzhao/Mooncake/aegiskv/paper/.texmf \
AEGISKV_TEXMFCONFIG=/home/comp/zhanzhao/Mooncake/aegiskv/paper/.texmf-config \
AEGISKV_TEXMFVAR=/home/comp/zhanzhao/Mooncake/aegiskv/paper/.texmf-var \
sh scripts/build.sh
```

该约 48 MiB 目录是环境依赖，不是论文活动资源，因此没有复制到精简快照。

已复制包的验证不等于所有图件都能从快照内重新生成：

- `render_legacy_wct_submission.py --verify-package` 严格验证 manifest 绑定的
  本地图件输出，并报告外部冻结 SGLSim 输入的存在/哈希状态。其重新渲染仍依赖
  `/home/comp/zhanzhao/sglsim/AegisKV/Archived/2026-08-06-pre-kvcache-centric`。
- `prepare_current_mechanism_supplement.py --verify-package` 严格验证 manifest
  绑定的本地图件输出和冻结指标记录，并报告外部 campaign 输入状态。其重新
  聚合/准备仍依赖
  `/home/comp/zhanzhao/sglsim/AegisKV/experiments/sglsim_large_scale_v2/.../4a99c306e8f9`。
- `render_motivation_real_cc_submission.py` 保留 canonical provenance 路径；
  重新生成 Motivation 图仍依赖 Mooncake AegisKV tree 外层的冻结 CSV 和
  workflow Draw.io/PDF 输入。本快照包含最终 PDF/PNG/manifest，可离线使用
  和按哈希核对，但不伪装成完全自包含的再生成包。

若这些外部冻结输入不可访问或已发生哈希漂移，LaTeX 所需图件仍已包含；
当前两个 `--verify-package` 检查会真实报告 `missing` 或
`hash_mismatch` 及 `regeneration_ready=false`，但仍可确认快照内 manifest
绑定的输出没有损坏。它们不会跳过本地输出校验，也不会伪造数据。
