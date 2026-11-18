# MoonKVSim 历史对话与项目状态

核对日期：2026-09-05。依据为本机历史索引、主对话的关键指令和回复、当前
Git 工作树，以及最新实验验收和论文产物。早期对话中的运行状态只代表当时。

## 可读取的记录

- Cursor：`/home/comp/zhanzhao/.cursor/projects/home-comp-zhanzhao-MoonKVSim/agent-transcripts/`。
  找到 119 个 JSONL 文件，其中 30 个在顶层对话目录、89 个在 `subagents/`。
  顶层也有委派审计记录，不能把这些数字称为 119 次人工聊天。
- Codex：本机数据库按精确 cwd 筛选得到 84 条任务记录，其中 5 个主任务、
  79 个子任务。原始 JSONL 位于 `/home/comp/zhanzhao/.codex/sessions/`；
  当前应用也能读取这些主任务的历史。
- 可见范围是本机实际保留且可访问的记录；没有据此断言 Cursor 云端或其他
  机器上的所有历史都可见。没有修改任何历史对话或会话数据库。

## Codex 主线

| 主任务名称 | 历史内容 | 现在如何理解 |
|---|---|---|
| MoonKVSim AegisKV 请求层 | 从 MOONKVSIM_PLAN 建立基础模拟器；整理 FanOutQA、并发 16、128K guard、至少 160 个独立任务，早期暂用 seed 0 | 当时 workload 尚未冻结；当前已冻结 160-task/1,304-call 输入，论文研究用五个 admission seeds，不能沿用早期“不可运行”状态 |
| MoonKVSim AegisKV 故障层 | 在一次完整 workload 中注入 N 次 GPU_FAILURE；自然路由选点，故障丢失该卡全部 HBM，120 秒后空 HBM 修复；修正恢复 admission | 已成为后续故障实验的语义基础。模拟的故障执行与真实硬件故障测量必须区分 |
| MoonKVSim AegisKV 引擎层 | 审核 engine 参数到运行时的绑定，并生成多节点拓扑图 | 多节点图和历史 80-GiB 配置不等于本次论文配置；当前研究是单节点 8×A100-40GiB、DP8/TP1/PP1 |
| 设计AegisKV对比实验图 | WCT CDF、AIMD、KV reuse 和故障/并发扩展实验；随后深入修复连续批处理、HBM、pin、传输、取消/commit 生命周期和统计审计 | 多轮旧结果因语义变化而过时；理想趋势是研究问题，不能成为保留或删除结果的门槛 |
| 总结历史对话与项目状况 | 先梳理 Cursor/Codex 历史，随后明确要求完成只含 8B 模拟的整篇论文和全部合理图像 | 本轮已完成五组验收、七图、完整正文和最终交付检查，详见下文 |

主任务 ID 分别为 `01a04e41-3a04-71b2-953a-918a9d7ca7ba`、
`01a053a9-8684-77d0-a8aa-70f3388d8b80`、
`01a053aa-fc17-7d80-b6a1-7b0b6bb8f259`、
`01a05551-1d99-7d21-a0b4-3a6988947e0a`、
`01a06fb3-0069-74e1-af0f-ef9bcd39310a`。

## Cursor 主线

- 8 月 30 日的 `3db9e9a8-9267-40fa-b7cb-3ed4ecbbbc4d`：读取 Codex
  进展、收窄到 Qwen3-8B/DP8/8×A100-40GB，并把实验收拢到
  `benchmark/AegisKV/experiments/{configs,scripts,workloads,results}`。
- `d7568931-a534-4b73-b3eb-efacc71f818a`：接续实验长任务；重点是
  Algorithm 2/3 的完整执行、无故障额外开销、恢复机制分解、路由及调度
  负载估计。对 32B/TP 的探索后来被搁置，研究重新聚焦 8B。
- `11fa02ad-18e5-4a21-898d-b244971bfe67`：汇总 Mooncake/sglsim 中的
  论文与文献资源，整理到本仓库；讨论故障频率、实验窗口与受控 F1
  注入的区别。历史估算和旧论文资源不作为当前实验的观测值。
- `33b578e5-e649-424b-a2d4-d82425d68817` 及其审计记录：继续多种子
  论文证据、失败反例、恢复源选择和严格审计。无故障结果一度受 AIMD
  事件来源、跨时间线 rent 单调性等检查阻塞；旧 v13 等结果保留为历史。
- 其他记录涉及 drawio/pdf skill 迁移、Cloud Agent/remote-control、
  codex-vscode-pair，以及专项只读诊断，属于开发工具和辅助审计。

## 当前项目与证据

MoonKVSim 是基于单一全局虚拟时钟的 CPU 元数据离散事件模拟器，包含
vLLM 风格调度、物理容量账本、Mooncake DRAM Store、GPU 故障与恢复，
以及 AegisKV 的策略与实验管线。它不执行真实模型前向或 CUDA 推理。

AegisKV 当前研究组合了 ideal residual-DAG CPM、Slack-Landlord 保留规则、
独立的 Peer-HBM/Store-DRAM admission 和 AIMD Peer 配额。备份由源端分别
准入；Peer 与 Store 可以覆盖同一前缀，覆盖率不能相加，也不是逐级 destage。

当前分支 `aegiskv` 跟踪 `origin/aegiskv`，HEAD 为 `b108867`
（2026-09-02，Fix AegisKV recovery and HBM accounting）。检查时有
47 条已跟踪修改和 212 条未跟踪状态项；未跟踪目录可能包含多个文件。
没有合并或提交这些混合工作。最终实验用独立冻结快照绑定执行代码，
而不是声称当前 dirty checkout 已整体冻结。

| 完成的研究 | 完整模拟运行数 | 独立验收 |
|---|---:|---|
| 无故障开销 | 10 | VALID |
| 主 F1 与各策略 F0 对照 | 20 | VALID |
| 七点故障/并发敏感性 | 70 | VALID |
| 四策略消融 | 40 | VALID |
| 三种服务时间模型 | 60 | VALID |

每次执行 160 个完整 workflow、1,304 个请求；五个 admission seeds 在研究间
重复使用，200 次执行不是 200 个独立统计样本。输入来自确定性派生的
FanOutQA，而非部署中采集的真实 agent 推理轨迹。最大 prompt+output 为
86,214 tokens，128K 桶为空；容量支持的声明不能替代观测到的 128K 结果。

最终有效证据位于 `output/paper-simulation-8b/20260905/runs-v3/`，
敏感性的审计修正版在 `runs-auditfix/`。该修正只改审计器和测试，运行时
语义及原逻辑故障计划保留；旧失败结果未混入最终数据。

## 主要结果和当前交付

- 主实验整体平均 WCT 差（AegisKV 减 Store-only）为 -0.048459 秒，
  95% 区间 [-0.239654, 0.142735] 秒；没有稳定整体收益的证据。
- 无故障保护提交字节增加约 66.3%；接近零的平均 makespan 变化不能解释为
  所有任务都无额外开销，也不包含部署控制器的真实 CPU 开销。
- full retention 相对 LRU 的选定 workflow 故障罚时改善为 7.377 秒，
  区间 [1.953, 12.800]；这是整套 retention 的条件性结果。
- 七点敏感性的 focus-mean 与 whole-mean 区间均跨零；三个时间模型也
  未确定优势。负面案例、孤立的正向比较及多重比较限制均写入正文。

当前完整论文为 `benchmark/AegisKV/paper/main.pdf`：
13 页、技术内容不超过 12 页、7 张已验收矢量图、完整摘要到结论、12 项
已核对主要文献。17 项交付一致性检查全部 PASS；所有页面完成视觉检查。
独立源码包可重新构建，13 页渲染像素与交付 PDF 一致。

完整逐项报告：`benchmark/AegisKV/docs/paper/COMPLETION_REPORT.md`。
重建方法：同目录 `REPRODUCE.md`。最终源码包和图像包位于日期输出根目录。

这是完成的、可供作者投稿审阅的模拟论文；没有进行外部投稿，也没有获得
真实硬件校准、部署性能优势或会议接收证据。仓库更广范围的旧 C++ oracle
环境和已有 lint 问题在完成报告中单独列明，没有将整个仓库宣称为全绿。
