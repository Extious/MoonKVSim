# AegisKV 论文

[阅读 PDF](main.pdf) · [LaTeX 主文件](main.tex) · [复现与交付说明](../docs/paper/README.md)

本目录以当前 8B 修订稿为唯一入口，直接子目录仅有 `figures/` 和 `sections/`。

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
当前 PDF 为 13 页，含 10 幅正文图和 3 个算法。

辅助资料的位置：

| 内容 | 位置 |
|---|---|
| 论文说明、复现步骤、对齐与审计记录 | [docs/paper/](../docs/paper/README.md) |
| 绘图、结果生成、校验和打包脚本 | [experiments/scripts/paper/](../experiments/scripts/paper/README.md) |
| 图像数据、构建产物、版面检查和交付包 | [experiments/results/paper/](../experiments/results/paper/README.md) |
| 旧论文完整快照与未使用的历史素材 | [docs/paper/archive/](../docs/paper/archive/) |

统计和实验结论沿用修订稿；目录整理没有新增实验。研究证据的边界见
[投稿准备度说明](../docs/paper/SUBMISSION_READINESS.md)。
