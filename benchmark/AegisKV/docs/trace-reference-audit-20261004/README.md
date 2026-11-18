# 真实 trace 来源核验（2026-10-04）

用户进一步澄清：“常见”需要实际执行 trace 作为依据。选择顺序改为先核查公开运行轨迹，再确定场景、逐轮请求和 Agent 依赖图。此前采购/营销图及 35 个请求模板保留为候选设计，不能作为真实轨迹或典型性证据。本次没有查看旧实验结果、运行模型、接入实验调度器或修改论文。

## 本次结论

已找到可以参考的真实运行资料，但目前核查范围中还没有一个来源被验证同时满足：固定 Agent 任务 DAG、多处并行与局部汇合、每个 Agent 内部连续多轮、完整累积历史、无工具或实测工具短。不要先画符合算法的图，再称其为常见。

“真实用户使用记录”和“真实模型执行基准任务”应分别描述。公开运行的存在可以支持 observed application/workflow patterns；不能单凭一个示例或有偏基准推断总体使用频率。

## 优先参考的来源

| 来源 | 实际提供什么 | 本次已核查/保存 | 对当前论文的限制 |
| --- | --- | --- | --- |
| [NVIDIA Agentic Serving](https://nvidia.github.io/TensorRT-LLM/latest/blogs/tech_blog/blog27_Evaluating_Agentic_Serving_with_Trace_Replay_and_Job_Level_Metrics.html)，[trace replay](https://github.com/NVIDIA/TensorRT-LLM/tree/main/examples/scaffolding/trace_replay) | 作者报告真实模型、工具、任务上的 730 次运行：Coder 500、Open Deep Research 100、IterResearch 100、Tree-of-Thought 30。紧凑格式记录 conversation、message index、工具 duration、parallel start/end 和 branch path | 下载 Coder 的 `matplotlib__matplotlib-23412.trace.json`，核查并行事件格式和研究 Agent 入口；已检查的 `trace_example/` 只发布这一 Coder 示例，未拿到完整 730 个文件或 ODR 原始轨迹 | Coder 示例没有多 Agent 分支。文中 ODR 示例 `deep-research-bench-59` 有四个并行研究分支，作者报告 512 s、98% generation-bound，但这是单个示例；它不能证明所有工具都短、复杂一般 DAG、预先固定全部任务或每个 Agent 完整历史。紧凑文件去掉 prompt 正文，仅保留结构/长度 |
| [MAST/MAD 数据集](https://huggingface.co/datasets/mcemri/MAST-Data)，[原始日志目录](https://github.com/multi-agent-systems-failure-taxonomy/MAST/tree/main/traces) | 数据卡为 1,642 个多 Agent 运行轨迹，七种系统、八种基准；包含任务、角色、对话/日志及失败标注 | 保存 ChatDev 的 2048 原始任务、完整日志、阶段配置，以及一个 MetaGPT 编程通信日志；没有下载约 202 MB 全量集 | ChatDev 样本的程序员与审查员跨阶段交替，不能直接变成一个节点一次完成的 Agent 任务 DAG；日志时间不是逐请求服务端耗时。不能由角色名重复或 `with_memory` 配置推断完整兼容历史 |
| [SyFI TraceLab](https://github.com/uw-syfi/TraceLab)，[v0.0.2 发布](https://github.com/uw-syfi/TraceLab/releases/tag/v0.0.2) | 用户真实 Claude Code/Codex 使用记录；公开字段含每轮 token、缓存计数、事件时间和工具 wall/internal 时间 | 核查发布资产/schema，流式保存 gzip 的前 100 行：四个 session、128 个工具记录，均为 Claude。只用于字段核验，不能用于总体分布推断；没有下载全量或验证全量 SHA256 | 样本和公开 schema 没有 prompt 正文、显式 Agent ID/parent/task DAG 字段；不能由并发时间重叠推断依赖。短调用中位数不能代替完整 workflow 的工具等待占比或长尾 |
| [Agent Scaling](https://github.com/ybkim95/agent-scaling)，[公开 PlanCraft 运行日志](https://github.com/ybkim95/agent-scaling/blob/main/example_traces/plancraft-test/multi-agent-centralized/run_trace.txt) | 有 PROMPT/回复及编排记录的多 Agent 基准运行示例 | 保存 PlanCraft 原始日志、配置和当前 worker 实现；样本显示三个 worker 开始工作 | Minecraft 合成任务不宜用作熟悉业务主场景。系统显式配置最少迭代次数，跨编排轮重新注入指导，当前代码取最近历史；旧日志的模块路径也与当前源码不同。需核查缓存状态，日志时间不能自动当成真实 API 执行耗时 |

NVIDIA 现成资料最接近“真实任务、并行 Agent、模型时间主导”的组合，适合作为研究型应用的首个审查入口；MAST 最适合阅读真实任务与交互；SyFI 适合补充真实时间/token/工具特征。它们目前都不能独立证明此前采购/营销 DAG，也不能独立关闭全部 workload 条件。

## 一个已经读到的具体 trace

ChatDev 任务是开发标准 4×4 的 2048 游戏，支持方向键、同值合并、随机新块、结束检测及分数显示。样本日志记录了需求分析、语言选择、代码生成、代码审查与修改、环境说明和用户手册。

日志有 14 个 `OpenAI_Usage_Info Receive` 记录，以及 14 个带角色/阶段的模型回复标题。程序员五次、审查员三次，其余为产品、CEO、CTO 角色。这里是日志记录计数，不是独立复核的服务端请求数。

实际片段：23:35:17 审查员给出 CodeReviewComment → 23:35:27 程序员给出 CodeReviewModification → 23:35:28 审查员再次给出 CodeReviewComment → 23:35:38 程序员再次修改。它能说明真实交互如何发生，同时直接显示：程序员不同轮之间需要另一角色反馈，不能称为内部连续执行的独立 Agent 任务。

原文可直接查看 [任务](sources/MAST_2048.prompt)、[完整日志](sources/MAST_2048.log)、[阶段配置](sources/MAST_ChatChainConfig.json)。上述时间是日志时间，不解释为生成起止时间或 GPU 执行时间。

## 排除容易混淆的资料

- [juliensimon/agent-traces-market-research](https://huggingface.co/datasets/juliensimon/agent-traces-market-research) 在数据卡明确标记为 synthetic：先构造流程和时间，再用 LLM 丰富内容。不能作为观测到的真实 workflow 分布。
- `GeoffreyWang1117/AgentTrace` 的已检查 `data/real_traces/customer_39885f33_real_trace.json` 虽放在 real_traces 目录，配套 `CustomerServiceWorkflow` 明确为模拟，分类/响应是本地规则，没有 LLM 请求。不能把这一客服样本当成真实客服模型 trace；这个判断只适用于核查的样本和实现，不推广到该仓库所有数据。
- MARBLE 的当前公开 `logs/` 仅有空 `__init__.py`，不能因为代码支持 graph 协作就声称已提供运行 trace。基准、框架、观测数据分别列证据。

## 新场景的入选方式

先从有原始来源和版本的完整运行中审查，保留完整 workflow ID 和全部请求，不拼接不同任务、不复制调用、不填充历史、不删掉长工具调用后仍称原始 trace。

1. 从原始任务和代码确认 Agent 任务粒度及真实职责，记录已执行的逐轮 messages；明确哪些内容无法公开获得。
2. 核对每个 Agent 的 system 与累积输入 token 前缀，包括摘要、重写、窗口裁剪、思考内容剥离。多个 invocation 不自动等于累积 KV。
3. 核对相邻调用之间是否只等待本 Agent 的结果，区分外部 Agent 等待、工具、用户等待、编排开销和服务端排队。
4. 用显式 fork/join、前驱产物引用或框架执行事件确认任务依赖及实际并行。不要仅按时间推边，或把异步函数/图拓扑当成观测并行。
5. 检查是否存在一般 DAG 的局部汇合和共享前驱，以及是否与论文的预先已知任务 DAG 相容。若图来自运行后展开，明确这是另一种语义。
6. 对完整工作流测量工具次数、时长、长尾及对关键路径的等待；阈值应在看恢复收益之前确定，并报告筛选后的覆盖范围与排除原因。
7. 原始实例通过这些条件后，再提取两张场景依赖图及实际逐轮请求。重跑所选真实应用生成新的完整 trace，并冻结模型/tokenizer/代码/任务集，再执行新实验。

公开紧凑 trace 可以参考依赖与长度，但不能据此还原真实 prompt。若实验需要原内容、token 前缀或原生稀疏注意力访问，必须采集或获授权取得真实 messages/token；不能用随机 token 替换后仍声称保留原访问行为。

## 本地资料与复核范围

- [下载来源与 SHA256](download-manifest.json)：所有下载均为公开资料；raw 上游 Python 只保存作阅读，没有执行。
- [样本字段核验](SAMPLE_AUDIT.json)、[核验脚本](inspect_samples.py)。这不是 workload 或性能实验。
- [NVIDIA 紧凑 Coder trace](sources/NVIDIA_coder_example.trace.json)、[SyFI 前 100 行样本](sources/TraceLab_v002_first100.jsonl)、[PlanCraft 完整日志](sources/agent-scaling_plancraft_run_trace.txt)。

版本记录：MAST `a70542e541b2104ef8fcd785778179e173fb8d70`；NVIDIA `fc0876cfd6c5d661f186707857a4e5bfeb12bc6f`；TraceLab `11b8b14c6005808ab272b3431487066832582414`，数据发布 v0.0.2；Agent Scaling `6f3bfb78a6481c1098d182680f39b0f904b292a2`。上游 main 文件另有下载内容 SHA256；没有把当前源码自动当成历史 trace 的生成版本。
