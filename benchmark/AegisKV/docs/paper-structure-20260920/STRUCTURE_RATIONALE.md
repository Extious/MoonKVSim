# AegisKV 章节重构依据

日期：2026-09-20。对应文件：[paper_draft.md](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/paper_draft.md)。本记录说明结构如何来自用户对话和文献；正文提纲仍只保留 Background and Motivation、System Design 两章。

## 1. 采用哪些对话决定

本轮重新读取了三个被引用任务的近期消息：

- [分析 AegisKV 算法 (4)](thread://01a0b2d5-abfe-7173-87b5-7a12a88215b7?hostId=remote-ssh-discovered%3Agpu10)：用户要求分层解释请求之间与请求内部的优先级。
- [分析 AegisKV 算法 (5)](thread://01a0b2d6-502c-7421-ae99-a7d0b62835dd?hostId=remote-ssh-discovered%3Agpu10)：故障接管、存活控制状态与并发 retry 的背景。
- [分析 AegisKV 算法 (6)](thread://01a0b2d6-d55b-7612-8ba7-69297cad890e?hostId=remote-ssh-discovered%3Agpu10)：完整副本、安全回收、按需加载的背景。

这些任务保留了更早的章节编号和 L/容量分工。模块职责以本任务后续的用户指令为准；旧回答不能覆盖后续修正。

| 对话中的决定或问题 | 在新提纲中如何体现 |
| --- | --- |
| “主要是多个独立请求调用同一角色以及同一个 Agent 连续调用工具” | 2.1 从两类 KV 生命周期起笔；角色共享与 Agent 私有增长历史分开 |
| “我们解决的主要是 Failure 场景” | 2.2 建立故障恢复状态；3.6 闭合到实际故障接管，不扩成一般缓存调度论文 |
| 请求级、请求内部优先级要分层讲 | 3.3 与 3.4 分开，前者请求额外保护，后者决定层与块 |
| “KV Manager 改为 KV Master” | 全文采用 KV Master；功能命名不改回 Planner |
| 恢复目标与 Peer DP 到达时确定 | 3.1 先绑定目标，3.6 故障时重新核查并使用 |
| “L 作为每个请求单独调整，Adapter 只是调整 Peer HBM 的空间大小” | 3.4 管理请求 L，3.5 管理窗口容量；不再沿用全窗口统一 L |
| “先将 Z 固定为系统配置” | 3.2、3.3 明确 Z 固定；没有 Failure rate → Z → L 的强制控制链 |
| K 是每请求每层实际驻留的 block 数，目标数也可能固定 | 3.4 区分目标配额、原生 top-k、实际提交 K 和块身份替换 |
| 新请求不能抢占运行请求受保护副本；Adapter 可为容量收缩回传 DRAM | 3.3 明确拒绝新 Peer 增量，3.5 明确迁移权限、有效副本与 I/O 引用 |
| 高 Slack Agent 的反复重算也会影响其他请求 | 2.4、3.3 将健康运行的复用与系统代价纳入；不把高 Slack 当成删除缓存的依据 |
| 希望分离容错但不想绑定某篇普通缓存论文 | 3.1 定义接口，3.2 复用兼容副本；具体正常策略是实现与实验条件 |
| 当前要求重新设计章节，而不是解释 main.tex | 移除独立 Insights 章节；合并 Tracker 到请求决策；恢复绑定与故障执行分时介绍；重新安排图的次序 |

逻辑分工与物理共享是当前讨论下本轮采用的设计方案，不是已经实现和验证的通用接口。新提纲保留这一证据边界。

## 2. 文献如何影响结构

本轮核对的是与章节组织直接相关的原论文/作者/会议页面。以下是写作借鉴和机制边界，不是完整文献排名，也不声称必须重现每套系统。

| 文献 | 本轮阅读范围 | 用于结构设计的依据 |
| --- | --- | --- |
| [TokenCake v4](https://arxiv.org/html/2510.18586v4) | 背景、概览、时间/空间调度组织 | 先讲 Agent 行为，再解释资源冲突；正常管理已有较完整设计 |
| [Continuum v6](https://arxiv.org/html/2511.02230v6) | 背景、动机、TTL/调度组织 | 工具交接后的缓存寿命、等待与排队是正常路径问题 |
| [InferCept v2](https://arxiv.org/html/2402.01869v2) | 导论及系统机制组织 | 先解释局部操作代价，再解释跨请求分配；需计入资源外部影响 |
| [KVFlow v1](https://arxiv.org/html/2507.07400v1) | 背景、图与前缀管理方法组织 | 已有工作使用未来访问信息；AegisKV 需明确故障恢复价值 |
| [DéjàVu](https://proceedings.mlr.press/v235/strati24a.html) | 正式发表摘要 | 流式 KV 复制已有先例；引用它建立容错基础 |
| [GhostServe v1 / MLSys 2026](https://arxiv.org/html/2605.00831v1) | 背景、动机、方法组织 | 先解释保护成本，再组织保护机制；编码是该工作的具体手段 |
| [LUMEN v1](https://arxiv.org/html/2606.17787v1) | 背景、动机、设计 4.1–4.4 | 先分解故障代价，再围绕状态和控制点展开；放置与路由协调已有研究 |
| [RaidServe](https://mast.stanford.edu/pubs/raidserve/) | 作者项目摘要 | 将 TP 拓扑适应与本方案的兼容目标恢复分开 |
| [Mooncake](https://www.usenix.org/conference/fast25/presentation/qin) | 会议页面 | 为已有分层 KV 存储提供背景 |
| [ECHO](https://www.usenix.org/conference/osdi26/presentation/liu-guangda) | 会议页面 | 原生稀疏加载和预取已有研究，需区分恢复特定的放置问题 |
| [SYMPHONY](https://www.usenix.org/conference/nsdi26/presentation/agarwal) | 会议页面 | 结构/优先级相关 KV 管理与引擎协同已有工作，不能独立充当新颖性 |

据此，本轮采用的组织方式是：**应用状态 → 故障代价 → 工作流影响 → 受约束的保护选择；接口 → checkpoint → 请求级分配 → 请求内放置 → 容量退让 → 故障执行。** 这是对文献和对话的综合设计判断，不是从某篇论文照搬的目录。

## 3. 为什么改变旧稿

- 先讲 KV 生命周期，避免读者把 Agent 和引擎请求当成同一个对象。
- 先讲故障后能恢复哪些状态，再讲哪些请求需要更快恢复，避免 Slack 脱离已有副本与恢复路径。
- 将共享副本和增量 checkpoint 放在优先级之前，明确后面到底在分配什么。
- 用两节分别承担请求级、请求内核心决策，使 KV Master 不再是一个混合全部策略的大节。
- Tracker 的算法是请求级输入生成，预测图只作可选支持。
- Recovery Manager 的预绑定在概览中交代，故障后执行放在末节，按时间闭合设计。
- 不强制所有现有图进入主文：发布时间图不支持当前主要论点；最大分支差值 ECDF 只作辅助观察。

## 4. 图像与缺口

现有 PDF/PNG 内容不改，Markdown 主体引用 8 张预览，其中预测相关性图为可选；稀疏发布图只保留素材链接。

| 图像 | 新用途 |
| --- | --- |
| recovery-cost | 2.2 恢复路径，先于 Slack 讨论 |
| workflow、recovery-exposure | 2.3 依赖语义与保护排序的主要例子 |
| workflow-gaps | 2.3 的辅助观测，可移补充材料 |
| system-overview | 3.1 模块、接口与恢复约定，保持单栏 |
| agent-prediction | 3.3 采用已有预测能力的可选素材 |
| retry-kv-prediction | 3.4 块候选信号 |
| recovery-pipeline | 3.4 Peer 驻留减少什么等待；3.6 回引运行机制 |
| sparse-models | 不分配推荐主文段落 |

建议补图 A（生命周期与故障前沿）、C（共享对象与增量保护）优先采用语义示意。B（故障时刻 Slack/恢复成本）、D（请求状态与 L/K 轨迹）需要明确分析或模拟条件后再画。本轮没有生成新图、启动模拟或实测。

## 5. 验证范围

检查新目录、每幅内嵌图的出现位置和用途说明、本地链接、模型/图号归属，以及固定 Z、请求独立 L、实际提交 K、容量收缩权限等最新决策。对归档前所有其他 `paper/` 文件进行哈希比较；本轮不修改四个 LaTeX 文件、原 PDF 或已有 PNG。
