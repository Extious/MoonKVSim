# Archived

这里保存历史材料，以及为精简论文工程而移出的写作和绘图材料。
2026-09-17 的旧设计/旧实验归档不能自动作为当前论文证据；2026-09-19 的
`paper-overleaf-20260919/` 则保存整理前的完整论文树，包含当前图源和来源说明。
**仅因不参与 LaTeX 编译而归档，不代表其内容已过时。** 各目录的用途以对应 README 为准。
原始快照不改写；历史外部链接可能仍指向迁移前路径，2026-09-19 的路径映射见 `FILE_MAP.csv`。

| 子目录 | 内容 | 来源 | 体积 |
|---|---|---|---|
| [paper-four-tex-20260919/](paper-four-tex-20260919/README.md) | 将论文合并为 4 个 `.tex`、去除图名编号前缀前的 29 文件快照；含新路径映射和退役 ZIP/打包工具。当前只下载 [paper/](../paper/) | `paper/`、`exports/`、打包脚本 | <1 MB（不含导航快照） |
| [paper-overleaf-20260919/](paper-overleaf-20260919/README.md) | Overleaf 整理前完整论文树；256 个原始文件均保留并核对哈希。含当前中文草稿、可编辑图源、数据来源、候选/旧稿和构建产物；当前精简英文入口为 [paper/main.tex](../paper/main.tex) | `paper/` | 27.3 MB |
| `drafts/` | 2026-09-16 版草稿原文快照（`Paper_Draft_20260916_monolith.md`，已拆分到 `paper/draft/`）；2026-09-09 三份 Before* 草稿快照；逐图审查、旧图索引（`PAPER_FIGURE_REVIEW*.md`、`Old_Figures.md`、`FIGURES.md`）；旧评估设计、故障/三系统协议、agent-lease 协议与实现、Qwen3-8B 图契约、模拟契约与审计（`FULL_ALGORITHM_SIMULATION_CONTRACT.md`、`SIMULATION_AUDIT_2026-09-01.md`）；旧 `experiments/README.md` | `experiments/` | <1 MB |
| `latex-revision3-20260907/` | 旧 LaTeX 稿 revision 3：`main.tex`、`sections/`、`figures/`（aligned-* 等）、`main.pdf`；`results-paper/` 为其数据与交付清单（`data/aligned-statistics.json`、`figure-manifest.json`、`figure-inputs/`、`delivery/MANIFEST.json`）。LaTeX 模板与 `references.bib` 仍在 `paper/` | `paper/`、`experiments/results/paper/` | 15 MB |
| `design-notes-20260913-14/` | 转向请求内放置前后的理论/规格笔记：`METHOD_DECISION_20260913.md`、`KV_MOTIVATION_AND_PRIORITY_20260913.md`、`INTRA_REQUEST_KV_PLACEMENT_THEORY_20260913.md`、`REQUEST_KV_POLICY_SPEC_20260914.md`（含已废弃的租金接口）、`KV_PLACEMENT_PAPER_FIGURE_GUIDE_20260914.md`、`NATIVE_SPARSE_TRACE_20260914.md`、`SGLANG_SPARSE_FIGURES_20260914.md`、`kv-policy-theory-20260914/` 分析输出 | `docs/paper/`、`output/analysis/` | <1 MB |
| `docs-legacy/` | 其余旧文档：`paper/`（Mooncake 对齐、revision 计划/状态、各类审计、`archive/` 中更早的稿件）、`drawio/`（Mooncake/AegisKV 实现架构图、算法 2/3 流程图、slacklandlord 图源）、`algorithm-2/`（算法 2 参考实现与验证）、旧 `docs/README.md`、旧顶层 `README.md` | `docs/`、`README.md` | 79 MB |
| `patent/` | 专利交底书（final、实例一二批注版）、算法 2–3 修订交底 v3、专利契约 YAML 与审计脚本、图与审阅记录。专利算法基于 agent-lease / 租金设计，与当前论文设计不同 | `docs/patent/` | 78 MB |
| `figures-legacy/` | 全部历史图系列（29 个目录）：`e2-initial-figures-20260831/`、`aegiskv-paper-sweeps-v2/v3`、`aegiskv-healthy-*-20260908`、`three-system-20260908`、`aegiskv-paper-story-20260908`、`aegiskv-agent-lease-20260908`、`aegiskv-evaluation/single-pass/revision-20260909`、`h2d-prefill-evidence-20260911`、`hbm-layer-benefit/recovery-layer-profile/kv-motivation-20260913`、`sglang-sparse/native-sparse-prefill/batched-layer-*/layerwise-prefix-benefit-20260914`、`aegiskv-draft-20260914`（前一日草稿图集）、`aegiskv-draft-20260915-retired/`（当前图集中撤出正文的 design-cascade、eval-*、motivation-needed-fraction；`paper/figures/MANIFEST.json` 的 `archived_figures` 仍记录其哈希）、`native-sparse-20260914-figures/`（NOSA-1B 首批探索图）、`aegiskv-draft-20260915-rtx4090-figure1/`（2026-09-17 之前的图 1：MiniCPM4-8B / NOSA-3B / NOSA-1B 在 RTX 4090 上的实测曲线与 128K 线性外推下界，含可从 `experiments/native-sparse/20260915/*-retained-kv-151751.json` 重绘的独立脚本；已被 A100 版图 1 取代） | `output/pdf/`、`output/native-sparse-20260914/figures/` | 170 MB |
| `simulation-qwen3-8b/` | 旧串行队列设计的 Qwen3-8B DP=8 模拟实验栈：`configs/`、`workloads/`、`evaluation-design/`、`baseline-tag-evidence.json`、`scripts/`（49 个运行/审计脚本 + `scripts/paper/` 63 个旧渲染脚本与模板）、`results/`（100 个有内容的结果目录、`figures/`、算法评审输出、`DATA_REMOVAL_20260913.md`）、`paper-simulation-8b/`（2026-09-05/06 发布矩阵与源码快照，2.0 GB）、`evaluation-redesign-20260909/`、`three-system-development/`、`audits/`（2026-09-01 模拟审计夹具与 09-13 存储清理审计，1.9 GB）、`figure-browser-scripts/`（Playwright 审图脚本）、`run-revision-publish.py` | `experiments/`、`output/`、`tmp/` | 4.2 GB |

## 2026-09-17 整理删除的内容（历史记录；2026-09-19 未删除原始文件）

- 所有 `__pycache__/`
- `experiments/results/` 下 2026-09-13 数据清理后遗留的 169 个空目录
- 旧 LaTeX 的构建中间件 `results/paper/build/`、审阅截图 `results/paper/review/`、`archive-build-before/`、`source-bundle-check/`，以及三份交付压缩包 `delivery/*.zip|*.tar.gz`（解压内容即 `latex-revision3-20260907/`）
- `tmp/pdfs/`（历次审图的 PDF/PNG 渲染，90 MB）、`tmp/figure-browser/` 的 `node_modules/` 与 Playwright 浏览器（289 MB）
- `tmp/figure4-expansion-validation/`（与 `paper/figures/motivation-sparse-concentration.*` 及 `experiments/native-sparse/20260915/*_models.csv` 内容相同的暂存副本）
- `tmp/*.json` 科研绘图技能的经验导出（原件在 `~/.codex/memories/`）
- `output/native-sparse-20260914/review/`（2026-09-14 探索图的审阅 PNG）
