## 2　背景

本节介绍基于 DAG 的 Agent 工作流如何映射到 LLM 服务系统，以及服务 worker 故障后系统如何恢复 Agent 的 KV 状态。

### 2.1　基于 DAG 的 Agent 工作流服务

多 Agent 应用通过协调具有不同职责的 Agent 完成用户任务。Agent 可以生成中间结果、调用外部工具、委派子任务，并使用其他 Agent 产生的输出。这些依赖构成有向无环图（DAG）：每个节点代表一次 Agent 调用，每条边代表数据依赖或控制依赖。

**Workflow** runtime 维护 DAG，并在依赖满足后释放相应调用。Fork 允许多个调用并行执行，join 则要求下游调用等待所有必要前驱完成{{cite:lin2024parrot}}。

一个 **Agent** 可以在同一工作流中被多次调用。每个 turn 的输入可以包含 Agent 专属指令、此前的模型输出、工具结果，以及其他 Agent 传来的输出。这些输入形成不断演化的 Agent 历史，由工作流 runtime 保留。

[图 1](#fig-serving-model)展示 Agent 调用到 LLM 服务系统的映射。就绪调用作为推理请求提交，并在模型 workers 之间调度。一个 **worker** 包含一个模型副本，或一个跨张量并行（TP）组的分布式副本{{cite:shoeybi2019megatron}}，可以同时服务来自多个工作流的 Agent。

请求处理包括 prefill 和 decoding。Prefill 处理输入 tokens，并为每个 Transformer 层生成 KV cache；decoding 则为新生成的 tokens 追加 KV。当同一 Agent 的后续调用复用相同历史前缀时，对应 KV 允许 worker 只处理新增输入，而不必重新 prefill 完整历史{{cite:gao2024cachedattention}}{{cite:zheng2024sglang}}。因此，活跃 Agent 会在迭代的 turns 中积累 KV 历史。

KV cache 按模型并行配置分布{{cite:kwon2023vllm}}。在 TP 下，每个 rank 保存自己的 KV 分片，以及注意力实现所需的元数据。因此，复用 KV 需要模型版本、并行配置、数值格式和 KV 布局兼容。

<a id="fig-serving-model"></a>

![图 1：基于 DAG 的 Agent 工作流服务](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/serving_model.png)

**图 1：** 基于 DAG 的 Agent 工作流服务。节点代表 Agent 调用，A1/A2 和 D1/D2 分别是同一协调 Agent 的连续 turns。Runtime 在 worker 故障域之外保留已接受历史和工具结果。不同工作流的就绪请求共享 workers；图中每个 worker 是一个 TP2 模型副本，各 rank 保存对应的 KV 分片。虚线箭头返回输出。后续 turn 可以复用仍可用的匹配前缀。本图是概念示意，不表示实测工作负载、host 拓扑或固定分配策略。

### 2.2　Worker 故障与 KV 恢复

本文考虑使模型 worker 不可用的 fail-stop 故障，worker 可以是一个模型副本或一个 TP 组。故障可能来自加速器、服务进程、主机或通信{{cite:cao2026lumen}}{{cite:jayakody2026ghostserve}}。受保护的故障域取决于部署，可以对应进程、分布式模型副本或整台主机。恢复副本只有在相应故障域失效后仍然可达，才能提供保护。例如，主机本地 DRAM 或 SSD 可能在进程故障后仍然可用，但不能保护主机故障。

一个 worker 可以保存多个 Agent 和工作流的 KV。因此，一次 worker 故障可能同时中断同一工作流的多个分支，以及来自其他工作流的 Agent。本文将同一次 worker 故障导致 KV 不可用的全部调用视为**一个故障事件**。

本文假设工作流 DAG、已接受 tokens 和已完成工具结果保存在故障 worker 之外。因此，受影响调用可以重新提交给兼容的幸存副本，使用相同的模型版本、并行配置、数值格式和 KV 布局。本文聚焦模型 worker 故障，因为它会移除大量 worker 本地 KV 状态，但工作流仍可从持久化输入恢复。工作流 runtime 或持久化 token 存储的故障与本文问题正交，可以通过常规复制机制处理。与这些控制状态和持久化状态不同，KV cache 随 Agent 历史增长，使完整复制成本高昂，由此产生本文研究的资源分配问题。本文假设至少一个声明的恢复域仍然可用。

如果没有幸存 KV 副本，替代副本必须 prefill 每个受影响 Agent 保留的历史，然后才能恢复生成{{cite:strati2024dejavu}}。另一条路径是恢复与某个已接受 token 前缀对应的完整 KV checkpoint，再重放该前缀之后已接受的 tokens{{cite:strati2024dejavu}}{{cite:cao2026lumen}}。完整 checkpoint 包含所有模型层、所有模型并行分片所需的历史 KV tensors 和注意力元数据。部分 KV 副本可以加速恢复，但不能独立提供完整恢复覆盖。

