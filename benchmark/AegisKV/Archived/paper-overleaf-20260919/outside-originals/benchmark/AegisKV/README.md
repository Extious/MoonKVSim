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
| `paper/draft/` | 中文论文草稿，按章节拆分为多个文件（阅读顺序见其 [README](paper/draft/README.md)） |
| `paper/figures/` | 正文图 1–9 的 pdf / svg / png，`MANIFEST.json`（图源路径、哈希与模型参数），`system-overview.drawio`；Motivation 四图：图 1–2 为 CC/Weka 轨迹的分支差与暴露示例，图 3 为稀疏注意力模型发布调研（只画稀疏模型，出处见 MANIFEST，2026-09-17 起），图 4 为 A100 版重算代价（MiniCPM4-8B 实测 8K–128K + Qwen3-8B / Qwen3-30B-A3B 的 AIConfigurator 估计）；图 6（§3.3）为三模型版集中度（MiniCPM4-8B、NOSA-1B、NOSA-3B） |
| `paper/acmart.cls`、`ACM-Reference-Format.bst`、`references.bib`、`build.sh` | LaTeX 模板与构建脚本；`main.tex` 尚待从中文草稿移植（旧 revision 3 稿在 `Archived/latex-revision3-20260907/`） |
| `experiments/data/motivation-real-cc/` | CC / Weka 124 个真实多智能体工作流的分支重建（图 1、图 2 的数据） |
| `experiments/native-sparse/` | 原生稀疏注意力模型的实机测量；说明见 [experiments/README.md](experiments/README.md) |
| `experiments/scripts/paper/` | `render_draft_20260915.py`（图 1–4、6–9）、`build_draft_overview.py`（图 5） |
| `docs/related_works/` | 相关工作 PDF、索引 `RELATED_WORKS.md`、请求内备份文献调研 |
| `Archived/` | 与当前设计不同、但有参考价值的历史材料；清单与归档原因见其 [README](Archived/README.md) |

## 重新生成图

```bash
cd /home/comp/zhanzhao/MoonKVSim
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_draft_20260915.py   # 图 1–4、6–9 → paper/figures/
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_draft_overview.py    # 图 5（需要 drawio CLI）
```

Slurm 采集与测量脚本位于 `experiments/native-sparse/20260915/*.sbatch`，均从仓库根目录提交；
脚本中的路径已指向本目录下的新位置。
