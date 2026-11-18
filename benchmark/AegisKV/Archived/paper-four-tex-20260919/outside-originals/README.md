# AegisKV

AegisKV 论文项目的全部内容都在本目录内；目录之外是 MoonKVSim 模拟器本体（包括
`python/moonkvsim/aegiskv/` 中的 AegisKV 策略实现、`tests/aegiskv/`、`schemas/aegiskv-*.schema.json`）。

当前设计（2026-09-15 起）：Slack 优先的三层放置（recompute / DRAM-only / Peer + DRAM），
请求内部按 `(layer ↑, hotness ↓)` 选块进入 Peer HBM，故障后按层预取、按选择器实际需求补取；
请求可并行 retry，不存在请求级串行恢复队列。此前的串行队列、agent-lease、容量租金等设计的
文档、图与结果一律归入 `Archived/`，不再作为当前结论的证据。

## 目录

| 路径 | 内容 |
|---|---|
| [paper/](paper/README.md) | 可独立上传 Overleaf 的英文 LaTeX 工程：入口 `main.tex`，摘要与第 2–3 节；含 13 个章节文件、合并后的参考文献、ACM 模板及构建配置 |
| `paper/figures/` | 当前 Figure 1–5 所需的 9 个矢量 PDF，按图号和子图命名；数据、图注及插入尺寸沿用整理前版本 |
| [exports/](exports/README.md) | 上传包 `aegiskv-overleaf.zip`、编译结果 `aegiskv.pdf`、构建中间件与检查记录；不混入论文源目录 |
| [Archived/paper-overleaf-20260919/](Archived/paper-overleaf-20260919/README.md) | 整理前完整 `paper/` 快照，包含中文草稿、可编辑图源、数据/来源说明、候选和旧构建结果；`FILE_MAP.csv` 记录路径与原始哈希 |
| `experiments/data/motivation-real-cc/` | CC / Weka 124 个真实多智能体工作流的分支重建（图 1、图 2 的数据） |
| `experiments/native-sparse/` | 原生稀疏注意力模型的实机测量；说明见 [experiments/README.md](experiments/README.md) |
| `experiments/scripts/paper/` | 绘图/来源脚本；`package_overleaf.py` 按当前 LaTeX 依赖生成上传包。旧绘图脚本的历史输出路径不作为当前发布入口 |
| `docs/related_works/` | 相关工作 PDF、索引 `RELATED_WORKS.md`、请求内备份文献调研 |
| `Archived/` | 与当前设计不同、但有参考价值的历史材料；清单与归档原因见其 [README](Archived/README.md) |

## 编译与打包当前论文

```bash
cd /home/comp/zhanzhao/MoonKVSim
sh benchmark/AegisKV/paper/build.sh
python benchmark/AegisKV/experiments/scripts/paper/package_overleaf.py
```

在 Overleaf 上传 ZIP 后选择 `main.tex` 和 pdfLaTeX。当前英文工程是部分稿件，
Introduction、Implementation、Evaluation、Related Work、Conclusion 的中文草稿保留在
[归档草稿目录](Archived/paper-overleaf-20260919/paper/draft/README.md)，未自动并入英文正文。

需要修改图时，从归档中的 Draw.io/SVG、来源说明或对应实验脚本开始，按
[图像映射](Archived/paper-overleaf-20260919/FIGURE_MAP.json) 将选定 PDF 更新到
`paper/figures/`。保持源目录仅含编译输入；PNG 预览、候选及审阅记录放在源目录之外。

Slurm 采集与测量脚本位于 `experiments/native-sparse/20260915/*.sbatch`，均从仓库根目录提交；
脚本中的路径已指向本目录下的新位置。
