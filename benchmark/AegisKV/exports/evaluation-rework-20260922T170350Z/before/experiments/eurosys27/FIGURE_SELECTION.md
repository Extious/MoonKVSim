# Evaluation 正文图像选择

正文保留 **8 张必要图**，17 个实验小节及完整执行矩阵均保留。选择依据是每张图是否承担独立核心论证，收益和不利结果都纳入。继续使用紧凑单栏画布和约 10.3 pt 字体。

## 正文核心图

| 顺序 | 图像 | 必须回答的问题与保留依据 |
|---|---|---|
| 1 | `eval-workflow-outcomes` | 一次故障后各策略的工作流延迟；36 个模型配置的主分布，同 ID 配对的 17 优/19 平另在正文报告 |
| 2 | `eval-branch-exposure` | 优先保留哪些分支、为什么；固定实例中恢复时间与故障时 join slack 的直接对照 |
| 3 | `eval-burst-interference` | 单次收益能否扩展到并发恢复；保留共享池拥塞下相对 LRU 变差的适用边界 |
| 4 | `eval-trace-penalty` | 记录故障日历下的条件恢复分布；平均收益与 p95/p99 回归并列，延迟仍标为模型 |
| 5 | `eval-value-ablation` | 价值项如何同时影响恢复和正常复用；六策略、两类成本、相同 12 场景及权重 |
| 6 | `eval-layer-factorial` | 层放置与流水线各自及交互的作用；等预算 2×2 消融，保持原生需求语义 |
| 7 | `eval-rental-cost` | 租用、续租与滞回是否值得额外复杂度；总成本包含 miss 与迁移，保留 rent 更差的结果 |
| 8 | `eval-capacity-frontier` | 收益如何随 DRAM 预算变化；区分联合正常/故障目标与非单调 fault-only penalty |

合并消融图逐值复制 `eval-ablation-fault.csv` 与 `eval-ablation-reuse.csv`。两类成本不是可相加的恢复阶段，不增加配置、实验次数或独立样本。原来的两个单指标视图继续保留。

## 补充与备用图

以下 26 个入口不占正文图位，对应实验仍必须按完整矩阵执行。

| 图像 | 移出正文的原因；保留内容 |
|---|---|
| `eval-paired-benefit` | 分布主图以外的配对视图；同 ID 差值必算，正文报告配对结果 |
| `eval-recovery-attribution` | 详细阶段分解；正文完整规定顺序干预和真实关键路径计时 |
| `eval-storage-traffic` | 字节数和 pool 占用可准确写入正文；资源成本仍必测 |
| `eval-background-backlog` | 条件流体诊断；直接受损、共享资源、隔离 cohort 和真实队列仍必测 |
| `eval-logical-fault-phase` | 辅助扫描；同 ID 的 20/50/80/95% 与各执行/迁移阶段保留 |
| `eval-checkpoint-lag` | 辅助扫描；Z、实际 committed frontier、写回争用和失败写入保留 |
| `eval-trace-outages` | 来源描述；清洗、修复语义、计数和原档限制仍在主文 |
| `eval-trace-bursts` | 聚簇诊断；分钟分辨率与完整故障簇映射仍规定 |
| `eval-modern-trace-labels` | 来源适用性审计；Reflex 缺乏可靠 down/up 的限制仍在主文 |
| `eval-trace-queue` | 主 trace 结果的内部归因；intrinsic delay、queue wait、资源占用分开报告 |
| `eval-trace-system-benefit` | 逐系统诊断；System 2 的负均值仍在主文，分系统/窗口统计必做 |
| `eval-trace-burst-control` | 方法对照；original/even spacing/分钟内展开及语义保留 |
| `eval-trace-time-stress` | 辅助压力扫描；1/10/100/1000 倍和原速区别保留 |
| `eval-ablation-fault` | 相同数值已纳入合并消融图；保留单指标备用视图 |
| `eval-ablation-reuse` | 相同数值已纳入合并消融图；正常复用回归仍可见 |
| `eval-common-fault` | 构造反例；isolated-sum、共同故障和候选族消融仍在矩阵 |
| `eval-layer-exposure` | 与四格图重叠；required compute=24 ms 和 exposed wait 分解仍在正文 |
| `eval-sparse-misses` | 辅助预测扫描；held-out demand、miss/unused bytes、reveal-to-ready 和完整性必测 |
| `eval-rental-churn` | 次数不是最终收益；108/106 次和其他变体结果仍在主文与原日志 |
| `eval-rental-revaluation` | 两策略同为 396 次，可在正文准确表达；实际 CPU、锁和重估成本仍必测 |
| `eval-storage-bottleneck` | 容量主图以外的资源扫描；读写/并发/NIC/H2D/缓存/后端失效仍必测 |
| `eval-prediction-robustness` | 辅助扫描；−25% 不利点仍在主文，完整 error/fallback/shift 矩阵保留 |
| `eval-healthy-io` | 通用 M/D/1 不能验证系统开销；真实 F0 WCT、TTFT、ITL、goodput 和保护成本必测 |
| `eval-rate-break-even` | 公式和阈值可直接交代；低故障率与健康成本摊销仍必评估 |
| `eval-safe-demotion` | 理想轨迹不能证明协议；交错、lease、epoch、提交和删除测试全部保留 |
| `eval-controller-scaling` | 未校准投影不能代表实现；DP/DAG/candidate 扫描和真实 CPU/尾延迟必测 |

## 位置、数据替换与后续选择

- `main-figures.json` 是有序正文清单；英文和中文正文使用同一组 8 张图。
- 原有 33 张图加一张合并图，共 34 个入口，分为 8 张正文和 26 张补充/备用。完整 PDF/SVG/PNG 位于 `../../exports/evaluation-expanded-20260921/figures/`。
- `--publish` 仅将 8 张正文图复制到 `paper/figures/` 和 `paper/figures/preview/`；图像目录从实验包显示补充图。
- CSV schema、来源校验和实测替换方式保持一致；新增合并图有留空结果值的模板。日常数据刷新不会恢复已移出的正文浮动图。
- 得到物理结果后按证据重要性重选。如果健康开销、预测失误或协议风险改变核心结论，就应获得正文空间。8 张是本次选择，不是永久配额。

完整设计见 [EXPERIMENT_MATRIX.md](EXPERIMENT_MATRIX.md)，全部预览见 [FIGURE_CATALOG.md](FIGURE_CATALOG.md)。本次保留所有实验和负向结论，仍不施加 12 页限制。
