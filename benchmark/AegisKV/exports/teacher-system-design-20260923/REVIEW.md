# 老师版 System Design：按 O1/O2/O3 重构

用户明确要求在老师版加入重写的 System Design，对应 Motivation 的三个 observation，并且不考虑 tool use、shared storage 和租金算法。本次新增的是按该指令编写的设计章，不将其声称为老师提供的原文，也没有恢复此前移出的其他章节。

## 主线与机制

| Motivation | 新设计的决策 | 具体机制 |
|---|---|---|
| O1：Agent 恢复价值不同 | 保护哪些 Agent、保留哪个完整检查点前沿 | GBDT 预测当前可见调用的剩余时长，CPM 给出带误差余量的 Slack；在同一故障事件、接管布局和队列规则下直接比较整个工作流完成时间；候选包含共同瓶颈分支的联合保护以及被替换对象。 |
| O2：KV 区域恢复价值不同 | 哪些层与块值得额外驻留 Peer | 原生选择单位上的可见机会归一化访问统计只筛选候选；有限缓冲、真实需求揭示顺序和传输/计算重叠模型评估暴露等待；候选变化后重算工作流收益。 |
| O3：复制容量随负载变化 | 每个 TP rank 可授权多少 Peer HBM | 物理容量上限、受约束 AIMD、稳定窗口、缩容时按当前损失回收副本；读者和复制租约结束后才释放物理空间。 |

正文先介绍两层结构，再依次展开 O1/O2/O3，最后用一个事件循环和检查点提交/故障恢复流程连接三者。

## 这次采用的状态关系

- DRAM 为每个获准保护的 Agent 保存完整检查点，Peer HBM 保存额外的部分副本；执行 KV 独立计费。Peer 逻辑区域始终属于完整 DRAM 检查点，不沿用旧三层稿的互斥归属关系。
- DRAM 有限：完整检查点或完整前沿不能获准时，保留较旧的已提交前沿，或者从存活的输入和 token log 重算。不引入磁盘溢出层。
- Peer 缩容只丢弃可安全释放的副本，DRAM 保持完整，因此没有 Peer 到 DRAM 的回写或级联下沉。所有真实副本、暂存和复制过程中的双份占用均计费。
- 新章节和新图没有工具等待、工具交接触发、共享存储、租金/Credit/Landlord 机制。老师 Background/Motivation 中的通用应用背景和历史微基准比较保持原文；它们不扩展新 Design 的执行或分层范围。
- 不沿用固定 L/K 准入规则。层和块集合来自有工作预算的候选选择，Z 仍是固定的块对齐检查周期；不声称全局最优。

## 交付与来源

- 正文：`paper_teacher/system_design.tex`；PDF：`paper_teacher/main.pdf`。
- 新 Figure 4 `teacher-system-overview` 保留已有三层架构布局、配色和对应 TP shard 的几何风格，替换为完整 DRAM 与 Peer 副本结构及 O1/O2/O3 职责。
- 新 Figure 5 `teacher-selective-recovery` 是构造的状态图：12 个逻辑区域全部在 DRAM，3 个额外 Peer 副本，共 15 份托管区域副本。L1 的 B0/B2 命中 Peer、B1 来自 DRAM；没有性能数值或实测收益声明。
- 可编辑源在 `sources/`，原生 Draw.io PNG/嵌入源 PDF 在 `figures/`，状态例在 `data/selective-state.json`。生成器 `experiments/scripts/paper/build_teacher_design.py`，原生导出 `render_teacher_design.sh`。导出使用本机官方 Draw.io 和 Xvfb；单栏 PDF 保持矢量文本。
- 引用只新增既有文献库中的 CPM 与 AIMD 条目；未搬回旧租金算法或实验章节。

## 核对

`build_teacher_paper.sh` 编译成功，最终 8 页，只有 Background、Motivation、System Design 三个正文节及参考文献。没有未定义引用/文献、重复标签或 overfull。算法上下留白保留 acmart 的常规 vspace 提示。

逐页检查了最终 PDF 的 1–8 页，另检查新图所在第 4、6 页灰度导出；两张原生 Draw.io PNG 也已打开。没有观察到裁切、文本碰撞或公式溢出。图 4/5 单栏宽度均约 84.68 mm，最小文字分别约 10.170/10.167 pt，无嵌入位图；灰度下层次、文字和虚实线可辨。算法的版本校验失败分支明确重排队，不能发布未获准状态。

`review/checks.json` 保存最终输入/PDF 哈希、章节、图号/页码和范围检查；`figure-metadata.json` 保存字号；`semantic-checks.json` 保存有限算术与结构核对。共同瓶颈例中两个单独保护的收益均为零，联合保护的收益为 8 个构造时间单位；暴露等待例区分隐藏等待 0 与暴露等待 4。它们仅核对公式和叙事，不是当前控制器实现测试或系统性能结果。

Background 字节不变；Motivation 只恢复老师原文指向 Design 的末句，原三张图片及禁用备选稿不变。规范主稿 `paper/` 的 44 个文件哈希与修改前完全一致。历史负面数据和旧设计未删除。

仍需验证的研究问题包括调用级剩余时间与 Slack 校准、原生需求的跨窗口预测、有限搜索的损失、共享恢复资源的实际竞争，以及完整系统故障注入和正常服务开销。新设计不把旧模型、旧租金诊断或单路径微基准当作已实现的系统收益。
