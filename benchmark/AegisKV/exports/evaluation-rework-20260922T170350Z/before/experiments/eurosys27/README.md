# AegisKV 完整论文与扩展 Evaluation

当前英文稿为 `../../paper/main.tex`，PDF 为 `../../paper/main.pdf`，中文详稿为 `../../paper/paper_draft.md`。设计为共享 DRAM + SSD/共享存储，保留 rent、native sparse demand 与 layer overlap。**当前阶段不限制 12 页，以完整实验设计为先；正文图像只保留必要项。** Evaluation 保留全部 17 个小节，正文图由 33 张收敛为 **8 张单栏核心图**。最终页数、字号和检查结果见 `../../exports/evaluation-expanded-20260921/CHECKS-expanded.json` 与 `REVIEW.json`。

本次没有运行端到端 GPU 故障实验。原有 33 张图及其数据仍在实验包中；新增一张合并消融图精确复用两张原图的数据，合计 34 个绘图入口：8 张正文、26 张补充/备用。正文为 7 张解析/机制模型、1 张 trace-driven model；全部入口为 26 张解析/机制模型、3 张公开 trace 描述统计、5 张 trace-driven model。合并图不增加实验或独立样本数。单次模型收益与 queue-tail/rental 的负例都保留。

2026-09-21 紧凑美化版：图像保持 84.7 mm 单栏宽，原生高度为 48.3–61.0 mm，统一 Libertine 字体、10.3 pt 图中文字、柔和配色和紧凑图例。图例位于数据区上方，线型/marker/纹理辅助灰度辨识。逐系统图改为紧凑竖柱，保留全部 22 个系统和负值。调整发生在绘图源中，正文继续按 `columnwidth` 原比例插入。紧凑化阶段的旧图和数据一致性、排版检查记录保存在 `../../exports/evaluation-expanded-20260921/compact-figures-20260921/`；本次正文图筛选记录在 `../../exports/evaluation-expanded-20260921/core-figures-20260921/`，内容完整性要求仍然有效。

- `EXPERIMENT_MATRIX.md`：完整执行规格，单次 failure 分解、真实 trace 连续重放、12 项消融与四格交互、正常服务/正确性/鲁棒性/扩展性。
- `FIGURE_SELECTION.md`：8 张正文图的保留依据，以及其余图转为补充/备用的原因。
- `main-figures.json`：正文图的有序清单；`--publish` 仅将此清单中的图发布到 `paper/`。
- `FIGURE_CATALOG.md`：8 张正文图优先显示，随后列出 26 张补充/备用图的 caption、预览与 CSV。
- `figure-specs.json`：固定的单栏图像配置；数据变化不需要重新配置字体、画布或图例。
- `PROTOCOL.md`：公共物理实验契约及 E0–E9；新版矩阵补充并优先于旧版精简图选择。
- `THEORY.md`：原 static model 与新增 trace/FIFO、bounded layer、isolated rental 的假设。
- `DATA_CONTRACT.md`：raw logs、campaign pairing、绘图 schema、measured replacement。
- `SUBMISSION_READINESS.md`：已交付与尚缺实证，当前不做篇幅压缩。
- `RELATED_WORK.md`：近邻工作与主张边界。
- `measured-template/expanded/`：34 个空 CSV schema；`expanded-layout/` 保留系列、横坐标和分类、留空结果值，方便直接填实测。空白是未测，不能填 0。

从仓库根目录重建数据与图（不重新生成正文措辞）：

```bash
python3 benchmark/AegisKV/experiments/scripts/eurosys27/theory.py
python3 benchmark/AegisKV/experiments/scripts/eurosys27/expanded.py
python3 benchmark/AegisKV/experiments/scripts/eurosys27/plot_expanded.py --publish
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
python3 benchmark/AegisKV/experiments/scripts/eurosys27/check_artifact.py
python3 benchmark/AegisKV/experiments/scripts/eurosys27/check_expanded.py
```

生成数据位于 `../data/eurosys27/expanded/`，原始 trace 位于 `../data/eurosys27/trace-source/`。LANL 使用钉住 revision 的 redistribution：23,739 CSV rows 与官网 23,741 不一致，原 FTP 不可达，尚未核实原始 archive；清洗和模型只对该明确版本负责。ByteDance/Reflex 是 job-shifted alert/label dataset，缺失 fail-stop/repair 语义，因此不冒充现代 serving failure calendar。

将自己的 raw logs 按协议聚合为相同字段 CSV 后，用下面入口替换已有测量的图，其他图保持原证据标签：

```bash
python3 benchmark/AegisKV/experiments/scripts/eurosys27/prepare_measured_figures.py \
  --tables /absolute/path/to/aggregated-csv \
  --raw-manifest /absolute/path/to/raw-manifest.json \
  --out /absolute/path/to/measured-plot-input
python3 benchmark/AegisKV/experiments/scripts/eurosys27/plot_expanded.py \
  --data /absolute/path/to/measured-plot-input \
  --spec /absolute/path/to/measured-plot-input/figure-specs.json \
  --out /absolute/path/to/measured-figures
```

检查真实结果后给最后一条命令增加 `--publish`，再编译论文。同名图可直接覆盖，画布和坐标语义不变；物理数据仍需同步修订数字、解释与证据声明。`prepare_measured_figures.py` 负责provenance打包，不代替统计聚合，不把输入随意改标成 measured。

`expand_evaluation_text.py` 是本轮英文写作快照，只在有意重新整合 Evaluation 时调用；日常替换数据无需运行，以免覆盖作者后续文字修改。之前14页压缩稿保存在 `../../exports/evaluation-expanded-20260921/before/`。原十图 renderer 仍可复现历史版本；当前 Evaluation 使用 `plot_expanded.py`。paper 保持四个 root tex 与独立 Overleaf 编译，代码/原始数据/日志/可编辑图均在外部，不生成 ZIP。
