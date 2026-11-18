# Agent 剩余时间预测：语言模型微调之外的路线

补充调研日期：2026-09-20。用户明确工作流 DAG 的节点是 Agent；节点内部有多轮 LLM 请求与工具调用，需要逐 step 更新该 Agent 当前任务的剩余执行时间。本文件是文献核对与方案比较，没有新增训练、模拟或物理实验，没有修改论文正文。

前一轮把主要讨论集中在 Heddle 和 AgentDecarbonizer，范围过窄。相关方法至少包括状态统计、历史前缀检索、随机过程、存活时间分析、轻量回归、语义编码加回归、监督微调，以及生成式估时。无需微调语言模型不等于无需历史数据；统计估计、分布拟合和回归训练也需要数据与验证。

## 已核对的方法与证据边界

| 工作 | 方法与真正目标 | 是否需要语言模型微调/生成式估时 | 如何用于 AegisKV |
| --- | --- | --- | --- |
| van der Aalst 等，2011，[Time prediction based on process mining](https://doi.org/10.1016/j.is.2010.09.001)；[作者机构记录](https://research.tue.nl/en/publications/time-prediction-based-on-process-mining/) | 从事件日志构造带时间标注的状态转移系统，将运行中的事件前缀对应到状态，预测整个实例完成前的剩余时间 | 不需要；需要历史日志和状态抽象 | 把一个流程实例映射为一个 Agent 的任务实例；输入是内部 step 前缀。状态抽象不改变外层 Agent DAG。原论文不是 LLM Agent 实验 |
| Rogge-Solti 与 Weske，2015，[Prediction of business process durations using non-Markovian stochastic Petri nets](https://doi.org/10.1016/j.is.2015.04.004) | 对活动建耗时分布，在当前状态估计整体剩余时间和超时风险；考虑自上次事件以来已等待的时间 | 不需要；需要结构与耗时分布估计 | 适合建模重试循环、工具等待和阶段分支。没有新事件时，“仍未结束”也提供信息。原结果来自金融/物流流程，迁移到 Agent 需要验证 |
| Vandenabeele 等，2022，[Enhancing Stochastic Petri Net-based Remaining Time Prediction using k-Nearest Neighbors](https://ceur-ws.org/Vol-3167/paper1.pdf) | 根据活动和时间特征找到相似历史前缀，用相应完整轨迹构造随机 Petri 网并模拟剩余时间 | 不需要；需要历史轨迹、检索、过程发现和模拟 | 支持“同一角色执行进度不同，应匹配不同历史”的路线；原方法并非仅对邻居剩余时间求平均，在线模拟开销也需评估 |
| 2020，[Investigating Social Contextual Factors in Remaining-Time Predictive Process Monitoring—A Survival Analysis Approach](https://www.mdpi.com/1999-4893/13/11/267) | 用带协变量的 Weibull 存活模型处理进行中的流程与删失信息，预测剩余时间 | 不需要；需要拟合统计模型 | 可比较在当前状态及仍未完成条件下的完成时间分布。该论文不是 LLM Agent 结果；超时/取消是否可当作普通删失，需要另外判断 |
| [Magnus，ICWS 2024](https://arxiv.org/html/2406.04785) | 预训练 LaBSE 提取语义，压缩后用随机森林预测单请求输出长度；另用 kNN 预测批次服务时间 | 这条路线的回归器是随机森林和 kNN，不能记成 GBDT 或微调生成式 LLM | 可借鉴“语义表示与传统回归分开”和历史相似样本估时；原目标不是整个动态 Agent 的剩余时间 |
| [Maestro，2026](https://arxiv.org/html/2606.12950)；[本地论文](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/Maestro: Workload-Aware Cross-Cluster Scheduling for LLM-Based Multi-Agent Systems.pdf>) | MiniLM 滑窗编码、结构化特征和 GBDT/LightGBM，先预测工具调用意图，再回归阶段输出长度，结合模型画像换算推理成本 | 文中关键的专用学习器是分类/回归模型；不能因使用编码器就称其为生成式提示估时 | 与“语义向量加轻量回归”非常相关。迁移时需将标签改为整个 Agent 的剩余秒数；论文的阶段长度 MAE 不是 Agent 时间 MAE |
| [Maze / MaLearn](https://maze-doc.readthedocs.io/en/latest/malearn.html)；[本地论文](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/Maze.pdf) | GBDT 将任务输入特征映射为 DAG 节点耗时，完成后反馈、后台更新 | 不需要语言模型微调；需要树模型训练 | 单节点是原系统的标签粒度，GBDT 本身可以直接回归 Agent 剩余时间。是否有效取决于状态/语义信息和训练数据 |
| [CacheScout，2026](https://arxiv.org/html/2608.14624)；[本地论文](</home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/2026/Learning Agent Execution for KV-Cache Management in Agentic Serving.pdf>) | 在线统计 Agent 间转移次数，形成一阶转移概率，预测下一个 Agent 并辅助 KV 复用 | 不需要离线神经训练或 LLM 提示估时；需要在线观测 | 说明在线计数也能提供有用执行信号。其 76–86% top-1 是下一 Agent 身份预测，不能当剩余时间精度；内部状态加耗时的扩展属于我们的设计 |

对于 Magnus 和 Maestro，读取了原论文方法部分，而不是只采用被引用论文对其方法的简写。Magnus 为 LaBSE + 随机森林，其批次估时器为 kNN；Maestro 为 MiniLM 语义特征 + LightGBM。仅凭“M 开头、回归预测”无法唯一确定 Maze，此前按这个线索直接锁定 Maze 不够严谨。

## 对当前问题最直接的两条候选路线

**路线 A：按状态匹配历史 Agent 前缀，直接查询剩余时间。**

在每个 step 记录当前角色/模板、最近工具序列及状态、成功/失败反馈、完成轮次、经过时间、已观察 token 和当前服务速度。从已完成的其他工作流中，寻找进度和状态相近的 Agent 前缀，读取这些前缀当时到 Agent 完成的真实剩余时间，形成经验分布。这是从流程监控与近邻方法得到的工程候选，不宣称是上述 Petri 网论文的完整复现。

例如，“修改后第一次测试失败”和“全部测试通过、开始整理结果”应属于不同状态；把所有 Subagent 混合后取一个中位数会丢失这一信息。可先用工具状态和数值特征检索，文本仅用冻结编码器作为可选补充。匹配不到足够样本时退回角色/任务族历史，并扩大不确定性，不制造确定性。

这一路线直接读取后续总耗时标签，因此不用显式预测未来有几轮。困难在于历史覆盖、相似度是否与剩余时间相关、动态新任务泛化，以及负载/工具环境变化；没有理由预先保证其比 GBDT 更准。

**路线 B：对整个 Agent 直接做轻量残余时间回归。**

使用同一套逐 step 状态，将训练标签设为 Agent 完成时刻减去当前观测时刻。先训练结构化特征 GBDT/随机森林，再比较加入冻结文本编码是否改善跨工作流效果。GBDT 预测范围取决于标签，不被 Maze 的任务粒度限制。改变标签仍需要重新训练和独立验证，不能转用 Maze/Maestro 的模型权重或精度。

两条路线都只更新预测输入/输出即可逐 step 运行，不要求每个 step 都更新模型参数。它们不改变外层 DAG 的 Agent 粒度，也不把 Agent 内部所有工具调用提升成工作流节点。

## 其他路线何时有价值

- **状态转移加耗时分布**：当角色流程存在可重复的搜索、修改、测试和重试模式时，可以建立带结束状态的随机过程，计算未来到结束的累计耗时分布。若采用半马尔可夫近似，需要覆盖状态停留时长和终止概率；不能默认未来轮数已知，或假定所有停留时间无记忆。它是内部预测模型，不是重新定义工作流 DAG。
- **存活时间模型**：长尾明显且有未完成轨迹时，关注“已经运行到现在且仍未完成”的条件。统计模型仍有分布、删失和漂移假设，不能因为不用神经网络就省略校准。
- **Heddle 式监督微调**：若前缀检索和轻量回归无法利用复杂反馈，且有足够语义轨迹，可作为更高成本候选。
- **AgentDecarbonizer 式提示估时**：缺少训练轨迹时可作冷启动参考，但其保守总时长实验不足以证明逐 step Slack 数值可靠。

## 推荐的比较顺序与验证

先比较角色/进度条件分布、前缀近邻、结构化 GBDT、语义增强 GBDT，再决定是否投入语言模型微调。无需因方法不用 LLM 微调就先假定准确度更高或上线成本可忽略；Petri 网过程发现与模拟尤其需要测量开销。

现有早期 GBDT 诊断只在每个 Agent 一个时点预测，且缺少语义和明确工具完成事件，它不能排除上述动态状态方法。新增实验应保持完整工作流与时间隔离，近邻库也不能包含同一测试 Agent 的其他前缀或来自未来的数据；同一 Agent 多快照不能计为独立任务。评估仍以剩余秒数误差、Slack 过估计、有限保护预算下的故障 WCT 和预测成本为准。

本补充没有发现一个能直接据其报告精度保证 AegisKV 逐 step 剩余时间预测效果的现成方案。流程监控论文提供的是更匹配的预测任务与替代方法，Agent 服务论文提供的是可复用的特征、统计和回归机制；二者应分别引用，不跨任务迁移精度。
