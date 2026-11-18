# 论文说明与历史记录

当前论文入口是 [paper/main.tex](../../paper/main.tex) 和 [paper/main.pdf](../../paper/main.pdf)。
正文图像与章节分别集中于 `paper/figures/` 和 `paper/sections/`。

**现有稿件是算法 2/3 revision 3 修订稿。** [完整技术定义](../patent/ALGORITHMS_2_3_REVISION.md)
及 [本次变更与验证](ALGORITHM_REVISION_V3.md) 说明该稿件版本。
下列旧版对齐/打包 PASS 记录保留历史作用域；170 次实验和实机 pilot 不评价新算法。

2026-09-13/14 的研究方向已进一步收敛为固定 Retry DP、Peer HBM/DRAM 共同覆盖下的请求内 KV 放置。
下列 Motivation 与方法规格是理论设计进展，尚未替换正文或完成运行时接入。

| 文档 | 用途 |
|---|---|
| [SGLANG_SPARSE_FIGURES_20260914.md](SGLANG_SPARSE_FIGURES_20260914.md) | 本机 DSA/HiSparse 源码图与 Top-k 参考输出，明确构造输入和 Retry Prefill 接口边界 |
| [REQUEST_KV_POLICY_SPEC_20260914.md](REQUEST_KV_POLICY_SPEC_20260914.md) | 分层优先级与 Slack 容量上限的条件推导、共同故障 WCT、租金接口及当前代码审计 |
| [KV_MOTIVATION_AND_PRIORITY_20260913.md](KV_MOTIVATION_AND_PRIORITY_20260913.md) | 固定恢复状态下的四张理论图、层深决策与原生稀疏证据边界 |
| [INTRA_REQUEST_KV_PLACEMENT_THEORY_20260913.md](INTRA_REQUEST_KV_PLACEMENT_THEORY_20260913.md) | 前层放置与请求内物理需求的详细理论分析 |
| [ALGORITHM_REVISION_V3.md](ALGORITHM_REVISION_V3.md) | 新旧算法变化、参考实现验证、未完成的实机接入与校准 |
| [REPRODUCE.md](REPRODUCE.md) | 实验、图像、论文与交付包的复现命令 |
| [REVISION_OVERVIEW.md](REVISION_OVERVIEW.md) | 当前稿件、图像及已接受实验的说明 |
| [MOONCAKE_ALIGNMENT.md](MOONCAKE_ALIGNMENT.md) | Mooncake 实现与模拟的对应关系及边界 |
| [ALGORITHM_2_3_REVIEW.md](ALGORITHM_2_3_REVIEW.md) | 算法 2/3 的漏洞、native 反例与修改优先级 |
| [三方详细对比](../../../../docs/development/mooncake-aegiskv-three-way-design-implementation.md) | 算法、架构、API、状态和故障恢复对照 |
| [FIGURE_REVISION.md](FIGURE_REVISION.md) | 三联 Motivation 与十幅图的修订记录 |
| [RELATED_FIGURE_REVIEW.md](RELATED_FIGURE_REVIEW.md) | 相关论文的图像组织依据 |
| [SUBMISSION_READINESS.md](SUBMISSION_READINESS.md) | 研究与投稿证据的现有边界 |
| [BUILD_STATUS.md](BUILD_STATUS.md) | 构建及版面检查说明 |
| [REORGANIZATION.md](REORGANIZATION.md) | 本次路径迁移与校验记录 |
| [archive/legacy-paper/](archive/legacy-paper/) | 原 `paper/` 旧稿的完整快照 |
| [archive/simulation-8b-unused/](archive/simulation-8b-unused/) | 修订稿未引用的旧章节与图像 |

`*_AUDIT.md`、`AUDITFIX.md`、`REVISION_PLAN.md` 与 `FIGURE_METHODS.md` 保留其历史用途，
不作为另一套活动论文入口。旧快照中的原始路径和指纹是历史记录。
