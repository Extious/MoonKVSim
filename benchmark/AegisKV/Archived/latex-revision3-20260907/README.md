# AegisKV 论文

[阅读 PDF](main.pdf) · [LaTeX 主文件](main.tex) · [复现与交付说明](../docs/paper/README.md)

本目录保留原有 8B LaTeX 修订稿，直接子目录仅有 `figures/` 和 `sections/`。

新的 [中文论文初稿](../experiments/Paper_Draft.md) 参考其论证结构，使用 source-v3 图像与实验结果，包含 Motivation、System Design 和 Evaluation 三部分。下述 LaTeX/PDF 仍保留原版本，并未随中文初稿重新生成。

```text
paper/
├── main.tex                  # 模板设置与章节引用
├── main.pdf                  # 当前论文 PDF
├── references.bib            # 参考文献
├── acmart.cls                # ACM 文档类
├── ACM-Reference-Format.bst   # BibTeX 样式
├── build.sh                  # 构建入口
├── README.md
├── figures/                  # 正文图像、可编辑源文件和 Motivation 子图
└── sections/                 # 摘要、引言、正文、算法和结果宏
```

`sections/abstract.tex`、`introduction.tex`、`motivation.tex`、`system-design.tex`、
`implementation.tex`、`experimental-method.tex`、`results.tex`、`physical-pilot.tex`、
`limitations.tex`、`related-work.tex`、`conclusion.tex` 按正文顺序组织。
三个算法为 `algorithm-*.tex`；`result-values.tex` 保存由统计数据生成的结果宏。

从仓库任意工作目录运行构建脚本，或在本目录执行：

```bash
sh build.sh
```

需要 `latexmk` 和完整的 LaTeX 环境。脚本将 `.aux`、`.log`、`.bbl` 等中间文件写入
[`experiments/results/paper/build/`](../experiments/results/paper/build/)，再更新本目录 `main.pdf`。
当前为算法 2/3 revision 3 修订稿，共 14 页（12 页正文、2 页参考文献），含 10 幅正文图和 3 个算法。

辅助资料的位置：

| 内容 | 位置 |
|---|---|
| 论文说明、复现步骤、对齐与审计记录 | [docs/paper/](../docs/paper/README.md) |
| 绘图、结果生成、校验和打包脚本 | [experiments/scripts/paper/](../experiments/scripts/paper/README.md) |
| 图像数据、构建产物、版面检查和交付包 | [experiments/results/paper/](../experiments/results/paper/README.md) |
| 旧论文完整快照与未使用的历史素材 | [docs/paper/archive/](../docs/paper/archive/) |

算法、架构图和证据解释已更新；旧实验继续明确归属于旧策略。新算法只有可执行参考验证，尚无新的 native/完整 DES 运行与实机干扰认证。研究证据的边界见
[投稿准备度说明](../docs/paper/SUBMISSION_READINESS.md)。

当前状态：[算法修订说明](../docs/paper/ALGORITHM_REVISION_V3.md)。这是研究修订稿，尚不能标为直接投稿终稿。
