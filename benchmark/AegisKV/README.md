# AegisKV

AegisKV 论文、实验协议、图像与证据均在本目录；模拟器代码位于仓库级
`python/moonkvsim/aegiskv/`。当前论文设计以 [system_design.tex](paper/system_design.tex)
和 [AGENTS.md](AGENTS.md) 的最新修订为准，旧模拟器与分析模型并不自动代表当前控制器。

当前设计按 Agent 的 guarded Slack 与完整重建代价选择受保护历史，在 Peer DRAM
保存完整的 256-token 粒度检查点，并将前 L 层各 Top-K KV 块额外保存到 Peer HBM。
Adapter 按前台占用调整每 rank 的 HBM 配额。该版本没有租金/credit 或共享存储层。

最新模拟入口为 `.venv/bin/python -m moonkvsim.aegiskv.current`，当前版本为
`checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1`，包含 EOS 冷恢复清理修复，
以及默认 `slack_mode="dag"`、显式 `"zero"` 对照。见
[实现与复现说明](docs/current-design-simulation.md) 和
[设计—代码—测试覆盖表](docs/DESIGN_IMPLEMENTATION_COVERAGE.md)。
这是每 DP 单 active invocation 的 FCFS 元数据 DES，没有 continuous batching；
AIConfigurator HYBRID 成本表仍未做端到端实机校准。FanOutQA 保留原始人工分解 DAG，
但 prompts 是构造的；结构化场景和已有原生 selector 捕获的 CPU 诊断分别报告，
不能拼成原生稀疏模型的端到端运行结果。

[实验分组与冻结版本](docs/current-design-simulation.md#实验分组与冻结版本) 链接各组
状态与审计：敏感性、容量/零 Slack 对照、结构化主矩阵已经完成；正式主矩阵及结构化
规模扩展另有完成门槛。运行中的精确计数以链接的状态文件为准。
旧 formal/structural 冻结源保留修复前版本，新组使用各自快照，不追溯覆盖 manifest。

## 目录

| 路径 | 内容 |
|---|---|
| [paper/](paper/) | 唯一 Overleaf 源目录；`main.tex` 及其实际引入的章节、参考文献、模板和图像 |
| [docs/current-design-simulation.md](docs/current-design-simulation.md) | 当前模拟实现、资源/故障语义与可复现命令 |
| [experiments/evaluation-20260924/](experiments/evaluation-20260924/) | 当前分组协议、来源快照、运行状态、配对结果、原生访问诊断及审计 |
| [experiments/current-design-20260923/](experiments/current-design-20260923/) | 旧设计首轮机制快照和配对结果；保留历史来源 |
| [experiments/eurosys27/](experiments/eurosys27/README.md) | 保留的论文实验计划、协议和历史分析；不自动代表当前设计 |
| [experiments/scripts/eurosys27/](experiments/scripts/eurosys27/) | 历史分析与绘图脚本 |
| [experiments/native-sparse/](experiments/native-sparse/) | 既有原生稀疏路径采集与测量 |
| [experiments/schemas/](experiments/schemas/README.md) | AegisKV 专用 JSON schema；由仓库级校验模块加载 |
| [experiments/analysis/](experiments/analysis/) | 从根目录 `output/analysis/` 迁入的分析资料 |
| [docs/related_works/](docs/related_works/) | 相关论文全文与索引 |
| [exports/notion/](exports/notion/) | Notion 导出资料及发布脚本 |
| [exports/reference-pages/](exports/reference-pages/) | 参考论文页和说明图的导出 |
| [Archived/paper-reviews/](Archived/paper-reviews/) | 从根目录 `output/pdf/` 迁入的历史论文构建和审查资料 |
| [Archived/](Archived/) | 不同历史版本的设计、稿件和图；保留来源与局限 |

仓库级 `python/moonkvsim/aegiskv/` 和 `tests/aegiskv/` 保留包与测试结构；
不迁入论文资产目录。2026-10-04 的迁移、删除和保留状态见
[项目整理记录](exports/project-cleanup-20261004/README.md)。

## 编译与图像复现

下载整个 `paper/` 上传 Overleaf，入口为 `main.tex`，使用 pdfLaTeX。
章节以 `main.tex` 的实际 `\\input` 为准；当前已包含 Evaluation，旧三章说明不再适用。

```bash
cd /home/comp/zhanzhao/MoonKVSim
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

构建中间文件位于 `exports/latex-build/`，阅读版为 [paper/main.pdf](paper/main.pdf)。
可编辑源、原始数据、SVG 和审查记录留在 `paper/` 外；不生成额外投稿 ZIP。

旧 Evaluation 的实验计划及物理路径测量保留在实验目录。新的模拟结果与这些既有
数据分别记录来源和证据等级，不直接升级成论文级端到端实测结论。
