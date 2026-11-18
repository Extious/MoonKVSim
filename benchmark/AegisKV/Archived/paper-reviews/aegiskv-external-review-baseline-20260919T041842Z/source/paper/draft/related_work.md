## 6 Related Work

**GPU 故障与训练侧的快速恢复。** 大规模集群的运维报告（Llama 3、MegaScale、Acme 的集群特征研究）一致指出 GPU 与 HBM 故障是非计划中断的主要来源。Gemini、CheckFreq、Oobleck、Bamboo、ReCycle 等利用内存检查点或冗余计算缩短训练故障的恢复时间。训练的状态是全局同步的，而服务的状态是每请求独立、生命周期短、价值随工作流位置变化的，这使得优先级放置成为核心问题。

**KV cache 系统。** PagedAttention/vLLM 把 KV 以块为单位管理；Mooncake、LMCache 等把 KV 提升为跨节点共享的一等对象，并用 DRAM/SSD 池支持前缀复用。AegisKV 复用这类块级密封与复制机制，但决定"复制什么、复制到哪"的依据是故障恢复对 WCT 的影响，而不是复用命中率。

**LLM 服务的容错与迁移。** DéjàVu 把 KV 流式复制到 CPU 以容忍 fail-stop；Llumnix、ServerlessLLM 通过请求迁移或快照缩短中断。AegisKV 的区别是结合 workflow 级 Slack 与请求内稀疏热度，为有限的备份介质分配两级保护优先级；它不要求替换引擎的并发恢复调度器。

**多智能体与工作流调度。** Parrot、Autellix 等把应用级依赖信息暴露给服务系统以优化端到端时延。AegisKV 使用关键路径法的总时差衡量请求能吸收的恢复延迟，将应用信息用于备份放置，而不是设计新的请求执行顺序。

**稀疏注意力与 KV 卸载。** NSA、InfLLM-v2/MiniCPM4、NOSA、DSA 等原生稀疏注意力通过可训练的块选择降低长上下文注意力的代价；Quest、DuoAttention、MInference 等在推理时选择部分 KV；NOSA、InfiniGen 等进一步利用选择的局部性做 KV 卸载与预取。AegisKV 不改变这些方法的选择器，只把它们已经产生的块选择信息用作备份优先级与恢复装载顺序，并处理它们都无法回避的"重放需要的是并集"这一事实。

<!-- TODO: 核对全部引用的出处、年份与会议：Llama 3 herd of models（2024，54 天 419 次非计划中断、GPU 相关 58.7%）、MegaScale（NSDI 2024）、Acme 集群特征（NSDI 2024）；关键路径法与 total float；MiniCPM4 / InfLLM-v2、NOSA、NSA、DSA；Mooncake（FAST 2025）、DéjàVu（ICML 2024）、GhostServe（MLSys 2026，§2.1 提及）、LUMEN（arXiv 2026，§2.1 提及）、Llumnix（OSDI 2023）、Parrot（OSDI 2024）、Autellix；图 3 十个发布点的模型卡 / 技术报告（URL 见 MANIFEST sources）。 -->

