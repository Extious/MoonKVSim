# 论文目录整理记录

2026-09-06。当前 8B 修订稿已提升为 `benchmark/AegisKV/paper/` 的唯一论文入口。
该目录直接子文件夹只有 `figures/` 和 `sections/`；主文件、参考文献、ACM 模板、
构建脚本和最终 PDF 位于根目录。

| 整理前 | 整理后 |
|---|---|
| `paper/simulation-8b/main.tex`、`main.pdf`、`references.bib` | `paper/` 中同名文件 |
| 修订稿正文引用的图像与 Motivation 组件 | `paper/figures/` |
| 修订稿正文与算法 | `paper/sections/`，算法命名为 `algorithm-*.tex` |
| 原本内联在主文件中的摘要、引言 | `sections/abstract.tex`、`sections/introduction.tex` |
| `simulation-8b/scripts/` 和根目录 Python 辅助程序 | `experiments/scripts/paper/` |
| 结果文字模板 | `experiments/scripts/paper/templates/results-template.tex` |
| 修订稿中的说明、审计 Markdown | `docs/paper/` |
| 图像数据、交付包、预览与编译缓存 | `experiments/results/paper/` |
| 原 `paper/` 的旧稿、模板、脚本与来源说明 | `docs/paper/archive/legacy-paper/` |
| 修订稿未被引用的历史章节和图像 | `docs/paper/archive/simulation-8b-unused/` |

共迁移 219 个原有文件，迁移时逐一验证 SHA-256。完整迁移前备份和原位置、新位置、
原始指纹记录在 [REORGANIZATION.json](../../experiments/results/paper/REORGANIZATION.json)。
随后对活动脚本、文档链接和 LaTeX 引用进行了必要的路径调整；原始指纹记录没有被改写成调整后的指纹。

`sh benchmark/AegisKV/paper/build.sh` 成功生成 13 页 PDF，10 幅正文图和 3 个算法均保留。
整理前后 13 页在 1.5 倍渲染下逐像素一致，文本内容一致；检查记录见
[relocation-pixel-check.json](../../experiments/results/paper/review/relocation-pixel-check.json)。
LaTeX 中间文件写入 `experiments/results/paper/build/`，构建不会向 `paper/` 添加辅助目录。

冻结执行源码、工作负载、170 次模拟原始事件和统计数值未改变；路径整理不构成新实验。
来源、复制状态与完整原始事件检查仍由迁移后的 `verify_delivery.py` 执行。
交付清单和独立源码包构建记录位于
[delivery/](../../experiments/results/paper/delivery/)。

历史快照、原始导入清单和冻结生成器中保留的旧路径用于追溯当时来源。
它们不再是当前论文的入口。原统计生成器仍可使用 `--paper` 显式指定输出目录；
当前命令将输出写到 `experiments/results/paper/`，不会重建旧 `paper/simulation-8b/`。
