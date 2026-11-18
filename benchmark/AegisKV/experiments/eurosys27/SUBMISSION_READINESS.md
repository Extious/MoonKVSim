# EuroSys 2027：研究稿状态与实证门槛

更新：2026-09-23。当前是 **Evaluation 独立成章的完整研究稿**，不是已通过物理系统验证或满足投稿页数的稿件。本轮新增物理运行数为 **0**；重绘已有实测/trace/model 不增加样本数。

## 当前交付

- 六个根 TeX：`main.tex`、`abstract.tex`、`background.tex`、`motivation_and_challenge.tex`、`system_design.tex`、`evaluation.tex`。入口 `paper/main.tex`，规范输出 `paper/main.pdf`，中文 `paper/paper_draft.md`。
- Evaluation 为 8 个论文小节，6 张正文图，1 张补充 native-horizon 图。主图 PDF 在 `paper/figures/evaluation/`，中文预览在 `paper/figures/preview/evaluation/`；source、CSV、raw logs 和 review 在 `paper/` 外。
- 当前方法为 fixed-L/K/Z、exclusive Peer/DRAM/storage ownership、zero-slack Peer、lower-tier per-Agent lazy credit、total-Peer AIMD。旧 no-Peer、joint-WCT-search、完整下层复制和 Peer rent 不属于本轮主策略。
- 文献研究核对了六篇原文 Evaluation 与图，包括 EuroSys 2025 HCache/CacheBlend、OSDI 2024 Parrot、FAST 2025 Mooncake，以及固定 arXiv 版本 LUMEN/TOPAS；借鉴实验方法不等于复现其系统。
- `EXPERIMENT_MATRIX.md`、`PROTOCOL.md`、`campaign-plan.json` 定义当前实验设计。完整现行系统 cells 都是计划；硬件、runner、模型/输入版本与参数尚待冻结。

## 已有证据范围

| 证据 | 已有内容 | 不支持的结论 |
|---|---|---|
| Physical KV path | job 1517208，Qwen2.5-7B-Instruct-1M，TP2/BF16/batch1，2×A100 PCIe 40 GB；4 contexts/4 paths，同一输入流 | 未测当前 Peer policy、异步 overlap、并发恢复或 worker-failure WCT；DPC shared filesystem 不是 cold SSD |
| Held-out prediction | 1,443 completed-Subagent snapshots、170 workflows、5 workflow-disjoint folds，完整 error tail | whole-Agent 标签、弱改善和跨零区间不能验证 residual-segment Slack，未验证 temporal generalization |
| Native sparse captures | 3 documents/model，同预算 frequency/recency/oracle，native hashes 与 horizon sweep | 不是当前 normalized ranker、新 holdout、physical hit rate 或恢复收益；辅助状态需计费 |
| Historical allocation | 36 deterministic Peer-disabled 配置，17 改善、19 持平 | 不证明现行 fixed-slot/lazy-credit end-to-end speedup |
| Historical rent | 原始租金 506.39 高于 direct 462.96；修复 466.76 仍落后 | 抽象 cost/scalar checks 不是 WCT/CPU，不验证多 Agent sharing 或 exclusive protocol |
| Historical trace queue | 21,738 cleaned LANL starts / 22 systems 驱动假定 FIFO spare pool；mean 改善而 p95/p99 变差 | 非真实 agent DAG，不按 repair durations 改变 serving capacity，不是 availability 或 physical campaign |

LANL redistribution 的 23,739 rows 与原来源 23,741 差异仍未解决；Reflex/ByteDance alerts 在各 job 内平移且缺 down/up，不能拼成全局故障日历。使用 InfiniteHBD 等 trace 也需保留原 node/training-cluster 语义。真实故障时间只是输入证据，不自动验证 serving 映射。

## 当前系统主张尚需的证据

| Gate | 完成条件 |
|---|---|
| G0：实现与环境 | 当前 controller revision/设计映射、GPU/host/storage/fault-domain inventory、native model/kernel/layout support、可审计 raw logs |
| G1：状态正确性 | complete KV/TP/selector state、exclusive ownership、commit/redirect/drain、leases、epoch fencing、token acknowledgement、sole-owner fallback；16 类交错各 100 seeded cases 与小状态检查单独计数 |
| G2：校准与冻结 | 实测 storage/NIC/H2D/compute；workload prompts/tools/DAG/ID；disjoint train/calibration/test；L/K/Z；SLO/horizon/common load 与 tuning budget |
| G3：端到端故障 | 原始 arrival cohort、同策略 paired F0/F1、整个 source replica failure；H-LRU/Reuse/Recompute/AegisKV；absolute WCT、fault penalty、completion/restricted cost；10 campaigns 是起点而非统计功效保证 |
| G4：正常代价与机制 | 同绝对到达率 F0 WCT/TTFT/ITL/goodput；Peer working-HBM 机会成本、migration/commit lag；same-value direct/eager、共享份额、normalized demand、Peer/overlap 与 Router/queue interactions |
| G5：泛化与边界 | residual-segment labels/guard；held-out workloads/native demand；容量/带宽交叉点、dense、cold starts、级联、DP/TP/故障比例、controller scale |
| G6：数据和论文 | raw/source hashes、聚合脚本、逐点表、所有失败/timeout/负结果；图与文字同步；最终 PDF 的构建、字号、灰度、页数与匿名检查 |

主 decisive suite 是 **480 planned run slots / 60 paired campaigns / 6 blocks**；完整 minimum plan 含 **1,200 slots / 150 campaigns / 15 blocks / 68 cells**。80-slot pilot 是主矩阵子集，不另加数量。JSON 另列 extensions；counts 不是已完成样本或 GPU-hours。先做 readiness/correctness/pilot，再按真实执行代价安排后续资源。本轮未启动这些运行。

## 格式与检查记录

已于 2026-09-23 核对 [EuroSys 2027 官方 CFP](https://2027.eurosys.org/cfp.html)：技术正文最多 **12 页**，参考文献另计；补充材料独立且不保证被阅读。内容区域 178×229 mm，双栏间距至少 8 mm；所有文字包括图内/图注至少 10 pt、行距至少 12 pt；须灰度无放大可读并编号；匿名评审。用户当前允许先完成较长研究稿，因此不能将当前稿称为 submission-ready；最终上传前重新核实官方要求。

- 当前 standalone export/review：`exports/evaluation-rework-20260922T170350Z/figure-manifest.json` 与 `FIGURE_REVIEW.json`。它们记录七个导出的来源、数值、native geometry 和 color/grayscale 检查，不自动验证论文中的实际缩放。
- 本轮 checker：`experiments/scripts/eurosys27/check_evaluation.py`，只检查所实现的结构/数据契约，不替代 G0–G5。
- 规范构建：`sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh`。以最终 `paper/main.pdf` 的 hash、页数、渲染为准；旧 expanded review 仅适用于其历史 PDF。

最关键缺口仍是：在完整现行实现、可比资源与正常服务成本下，workflow urgency、native sparse placement 和 lower-tier credit 是否优于强对照。完整文稿、旧模型收益与图形排版不能关闭此缺口。本任务不提交论文。

最终集成核对：本轮 `paper/main.pdf` 为 20 页；Evaluation 图 13–18 位于第 13–15 页，实际插入最小字号约 10.30 pt。已查看实际彩色/灰度页面，构建无 undefined references 或 overfull boxes。完整最终 PDF 哈希、检查范围和限制见 [`FINAL_REVIEW.json`](../../exports/evaluation-rework-20260922T170350Z/FINAL_REVIEW.json)；图像合集见 [`evaluation-figures.pdf`](../../exports/evaluation-rework-20260922T170350Z/evaluation-figures.pdf)。
