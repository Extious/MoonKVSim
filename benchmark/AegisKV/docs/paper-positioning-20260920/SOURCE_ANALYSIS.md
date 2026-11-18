# 从专利与验收材料重新确定 Background and Motivation

对应提纲：[paper_draft.md](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/paper_draft.md)。本记录对应本轮三节 Background；上一轮 `paper-structure-20260920/STRUCTURE_RATIONALE.md` 的四节 Background 已被此稿替代。System Design 的六节组织和最新算法约定保留，仅更新一处跨章引用。

## 1. 读取了哪些材料

| 材料 | 本轮采用的位置 | 提取出的定位信息 |
| --- | --- | --- |
| [MoonKVSim 专利终稿](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/patent/AegisKV专利交底书-final-version.docx) | OOXML 段落 P067–P079、P087 | 工作流完成取决于依赖；KV 是可重建的已计算状态；保护与前台共享资源；局部缓存价值不足以描述工作流恢复价值 |
| [MoonKVSim 实例批注版](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/patent/AegisKV专利交底书-实例一二批注版.docx) | 相同背景段落 | 背景与终稿相同，没有把算法批注当作论文当前机制 |
| [SGLSim 早期专利](/home/comp/zhanzhao/sglsim/AegisKV/doc/patent/AegisKV专利交底书.docx) | P058–P078 | 多轮增长、底层故障、工作流延迟与无差别备份成本组成最初的问题链 |
| [SGLSim 独立分层专利](/home/comp/zhanzhao/sglsim/AegisKV/doc/patent/AegisKV专利交底书-独立分层最终版.docx) | P067–P079、P087 | 保留工作流恢复价值与前台资源冲突；这一版的背景与 MoonKVSim 终稿相同 |
| [二阶段验收演示](</home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/source_materials/acceptance/AegisKV 二阶段验收.pptx>) | 第 2–6 页，文字内容 | 明确从请求级延迟转到 WCT；相同 KV 损失在不同工作流位置影响不同；正常服务开销是约束 |
| [专利申请说明演示](/home/comp/zhanzhao/sglsim/AegisKV/doc/Archived/2026-08-06-pre-kvcache-centric/source_materials/patent/AegisKV专利申请说明.pptx) | 第 2–6 页，文字内容 | “关键路径到关键 KV”的研究意图，以及恢复收益与保护成本的联合考虑 |
| [SGLSim 验收设计](/home/comp/zhanzhao/sglsim/AegisKV/doc/acceptance/main.tex:80) | 80–141、441–479 行 | 目标是故障造成的 WCT 增量与正常路径开销；初步模拟、设计要求和正式统计证据明确分开 |
| [MoonKVSim 计划](/home/comp/zhanzhao/MoonKVSim/MOONKVSIM_PLAN.md:66) | 科学目标、12.4 baseline recovery、旧验收条款 | 相同资源下比较 WCT；已有 Store 副本可参与恢复；不能通过剥夺基线缓存夸大保护收益 |

源文件与摘录的 SHA-256、读取范围见 [sources.json](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/paper-positioning-20260920/sources.json)。DOCX 段落编号按 `word/document.xml` 中全部 `w:p` 顺序计数，包含表格；PPT 只做了文字提取，没有审阅旧版排版或重新认证图中实验。相同背景的多个版本属于同一设计沿革，不能作为多个独立证据。

## 2. 对论文定位的修正

最稳定的问题定义是：**面向 Agent 工作流完成时间的 LLM 推理容错，通过选择性 KV 保护减少故障影响，并控制保护对正常服务的代价。**

这一定位包含三个层次：

1. **服务目标在应用层。** 用户等待完整任务结束，工作流依赖决定某次恢复延迟能否被吸收。WCT 是主要效果指标，请求时延、恢复命中与重算量用于解释机制。
2. **故障与操作对象在推理层。** 本轮继续采用 GPU fail-stop、兼容 DP 接管的范围；操作的是可恢复 KV 及其驻留，不处理 LLM 输出错误或外部工具副作用。
3. **选择受到共享资源约束。** 保护越充分未必越有利，HBM、DRAM、传输和恢复执行都影响健康服务。要比较恢复实际省下的等待和保护增加的负担。

上一稿开篇过于强调“在某个正常缓存之上追加什么接口”，容易把系统组织问题变成论文的主要动机。本轮将它压缩到 2.3 的一个段落，并保留 3.1–3.2 的具体接口说明。这样仍承认普通副本的价值，也无需在 Background 先挑选 TokenCake 或另一完整系统作为算法前提。

“关键路径到关键 KV”可以保留为问题意识，但不能直接成为块级规则：关键请求的所有块不具有相同的恢复贡献，非关键请求的重算也可能争用资源。论文需要把请求的工作流影响、块的实际恢复需求和系统成本连接起来，再用实验检验。

## 3. 哪些旧内容不继承

| 旧材料内容 | 当前处理 |
| --- | --- |
| SlackLandlord、租金键、连续尾部淘汰、双比例反馈与相关公式 | 不用于改写当前算法 |
| 旧计划将专利列为最高设计契约、禁止 HBM→DRAM 降级 | 视为当时实施计划；当前用户明确要求只参考定位，后续已允许 Adapter 安全降级，不回滚 |
| 旧统一缓存管理方案 | 保留副本共享和物理资源不重复计费的合理要求；是否分开策略模块仍以当前设计为准 |
| 演示将 Mooncake 归为传统请求容错 | 不沿用该分类；普通 KV 保存与复用不自动构成故障保护保证 |
| “尚无多智能体推理容错”等整体空白判断 | 不写入论文；用可检验的目标与机制差异定位 |
| 393 个工作流、321 次 fan-out、2.2×/8.6× 时长比 | 历史统计，不替代当前 121 个工作流的最大时长差 ECDF，更不作为故障时刻 Slack 分布 |
| Demo WCT CDF、验收阈值、测试项 | 仅理解指标选择与证据要求，不作为当前算法的性能结论 |

文献分类还复核了 [TokenCake v4](https://arxiv.org/html/2510.18586v4)、[GhostServe v1](https://arxiv.org/html/2605.00831v1)和 [LUMEN v1](https://arxiv.org/html/2606.17787v1)。正常 Agent KV 管理、故障 KV 保护和恢复负载协调已有相应研究；本轮提出的是 AegisKV 的叙事与待验证主张，不声称完成了新颖性证明。

## 4. 三节 Background 怎样写

| 新节 | 论证任务 | 主图与作用 |
| --- | --- | --- |
| 2.1 Agentic Workflows and KV State | 定义用户任务、WCT、两种 KV 演化和请求/Agent 寿命 | `workflow` 建立汇合语义；建议补生命周期面板 |
| 2.2 From KV Loss to Workflow Delay | 串联“失去状态→恢复代价→依赖传播与资源竞争” | `recovery-cost` 解释状态保护；`recovery-exposure` 解释排序差异；`workflow-gaps` 仅作辅助 |
| 2.3 Balancing Recovery Benefit and Protection Cost | 说明选择性保护的必要性，明确与普通缓存关系及双侧目标 | 回引前图；后续补保护容量与健康服务代价 |

与上一稿相比，原来的故障状态节和工作流影响节合并，使读者沿同一因果链理解动机；checkpoint 的 M/N/Z、manifest、引用与版本等具体定义移回 System Design。当前 Background 不出现编号 Observation，也不展开预测器、L/K 或 Adapter 伪代码。

## 5. 图像与验证

本轮检查了四张 Background PNG 的实际导出，核对 A1/A2 的示例数值与图义。现有工作流图、恢复成本图、恢复暴露图为主要素材，分支差值 ECDF 为可选辅助。图片内容未修改，所有 25 个其他 `paper/` 文件保持哈希不变；保留四个 LaTeX 输入文件。

旧稿与旧检查报告保存在 [归档目录](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/paper-positioning-20260920)。当前检查记录为 [checks.json](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/exports/draft-preview/checks.json)。此次没有重新编译 LaTeX，没有绘制新图，也没有启动模拟或实测。
