**原生稀疏小模型与多轮 Agent 恢复的可行性**

研究对象是一条请求内部的 KV 放置：少量状态在 Peer HBM，其余历史状态在 DRAM。恢复执行遵循模型原有的 attention 规则，不通过删除 dense attention 项换取速度，也不使用后段重算更贵的解释。请求级 Slack 与租金算法不在本分析范围内。

本轮核对得到三个判断。原生动态稀疏注意力已有公开的小模型和实现，可以开展机制实验；跨轮请求的历史访问统计只能用于预测，不能替代恢复时的真实选择；备份新鲜度需要证明 Peer 更早推进了一致恢复点，而共享分支不是推理引擎默认产生的工作负载。

**1. 可用小模型与运行模式**

NSA 是一个特定方法的名称，原生稀疏注意力则是一类架构。采用 NOSA、InfLLM-V2 或 HiLS 的模型并不是原始 NSA 的同一实现，但其训练包含相应稀疏机制，可以用于研究不增加推理期近似的 KV 放置。实验中的等价性应针对同一个已训练模型及固定的 attention 配置定义，不能宣称这些模型与原 dense 模型逐位等价。

| 模型 | 规模 | 公开证据与机制 | 对实验的定位 |
|---|---:|---|---|
| NOSA-1B | 1B | 官方发布模型与代码；模型文件目录包含 pytorch_model.bin；NOSA 为可训练、面向 offload 的稀疏机制 | 优先做访问轨迹、状态大小和故障恢复机制验证 |
| NOSA-3B | 3B | 官方模型卡和作者仓库明确列为已发布 | 在更大模型上复核 1B 结论；不能仅凭规模假定 Agent 能力 |
| MiniCPM4.1-8B | 8B | 使用可训练的 InfLLM-V2；官方提供 dense/sparse 两种运行模式 | 更适合进一步评估对话、推理工作负载，需锁定真实 sparse 后端 |
| HiLS-Attention-7B | 约 7B | 从 OLMo3 风格骨干持续训练，端到端学习 chunk 选择；公开 checkpoint 与代码 | 可作另一种分块原生稀疏机制的复核；是 base 模型，集成要求更高 |

NOSA 作者仓库公开列出 1B、3B、8B 模型，提供 NOSI 推理实现及相关评测入口。这里核对的是发布与代码证据，没有下载模型或完成本地推理验证。[^1]

MiniCPM4.1 的官方模型卡明确写出：其提供的 vLLM/SGLang 路线当前使用 dense 模式，稀疏路线使用 Transformers 配合 InfLLM-V2 实现或 CPM.cu。其示例还有 dense_len 阈值，短输入可能运行 dense attention。因此，“模型成功启动”并不证明当前执行路径是稀疏。应记录具体 revision、配置、后端和真实选择索引，而不能依赖 Hugging Face 自动生成的部署命令。[^2]

HiLS 官方模型卡则明确要求通过项目代码注册自定义机制，不能直接用标准 AutoModel 加载，并把 SGLang 支持列为 roadmap。其 base 模型身份也限制了直接把它当成熟工具调用 Agent 的合理性。[^3]

最小实验应优先选择 NOSA-1B，使用作者实现确认稀疏执行与 offload 行为，再尝试较大模型。NOSA 已针对局部性与 offload 联合设计，是重要的近邻工作；论文不能把“热点保留在 HBM、冷数据放在 DRAM”本身作为新的贡献。

**2. 一个 Agent 的多轮请求：先区分值复用和访问变化**

假设 R1 使用历史 P1 并产生输出 Y1；R2 的输入为 P1、Y1 与新增工具结果/用户消息 U2 的拼接。在固定模型、位置编码和执行规则下，真正保持相同 token 前缀的部分可以复用 KV。相同 Agent ID、相同自然语言主题都不能替代 token 前缀匹配。对话压缩、历史重排、模板修改或模型配置变化，需要重新确定有效前缀；已有的 prefix-cache 机制也以实际前缀标识为依据。[^4]

旧 token 的 K/V 值可复用，不代表新的 query 仍然访问相同的块。访问集合是 query、layer、KV head/group 及原生选择规则的函数，而不是每个 token 的永久标签。

| 逻辑时刻 | 可观察的状态 | 可以采取的动作 | 尚不能知道的事情 |
|---|---|---|---|
| R1 prefill | 已处理 query 的真实选择索引、块位置 | 建立按层/组的访问记录 | R1 后续 decode 或 R2 会选择哪些块 |
| R1 decode | 最近若干步的选择变化与实际 miss | 更新 Peer 集合，启动复制 | 更晚步骤是否会突然访问远端历史 |
| R1 结束、工具执行 | 已有历史的统计与已提交备份 | 保留候选，按一致性规则管理副本 | 尚未返回的工具结果带来的 query |
| R2 新增输入 prefill | 新消息实际 query 的选择集合 | 用 R2 观测替换或更新 R1 统计 | R2 未来生成过程的所有访问 |
| 某个逻辑位置发生故障 | 只能使用故障前已完成提交的状态 | 选择恢复 GPU，恢复游标、索引和必要状态 | 不能使用故障后 oracle 选择作为在线策略 |
| 恢复首个待处理 token | 各层 query 随前向计算逐层出现 | Peer 命中直接使用或加载；真实 miss 从 DRAM 召回 | 后续层 query 在计算之前通常仍未产生 |
| 恢复后继续生成 | 新的真实访问与缓存驻留情况 | 按需继续加载；更新初始预测 | 故障前的固定集合是否仍有长期覆盖率 |

因此，不能把“每轮开始时统计一次访问频率”当成足够完整的策略。Prefill 与 decode 的 query 分布不同；原始计数还受到每段被多少 query 看见的影响。对原生稀疏机制，宜直接记录真实的块选择，不应额外计算完整 attention 矩阵作为免费统计。

**3. 局部性证据能支持到什么程度**

NOSA 对 InfLLM-V2 的分析在 16K 输入、每步选择 4K tokens 的配置下，观察到大多数层相邻步骤的选中集合重合率不低于 0.8，但同时发现这种局部性仍不足以消除 PCIe 传输瓶颈。NOSA 因此在训练机制中加入更强的局部性约束。该结果支持相邻 decode 步的预测价值，也直接说明高命中率不保证传输开销已经很小。[^5]

这不能直接推及跨轮 Agent 请求。用一个简单的集合例子说明：即使相邻两步始终有 90% 重合，每步也可能更换不同的 10%；经过多步后，最早保留的固定集合可能大量过时。若每步集合大小均为 k、相邻重合率至少为 gamma，则仅根据这一条件，H 步后与初始集合的重合下界最多只能保证 max(0, 1-H(1-gamma))。这是集合变化的保守推导，不是实际命中率预测。

需要分开测试两个场景：

- 当前轮 decode 中途故障：有同一轮故障前的近期选择，预测条件相对好。
- 下一轮加入新消息后开始执行，或新增输入 prefill 中途故障：旧轮统计可能过时，多个新 query 的选择并集可能很大。

故障不会自行改变相同逻辑位置的模型语义。真正变化的是恢复目标的缓存状态，以及是否需要跨越新增消息和执行阶段。把正常缓存逐渐积累的命中率直接解释成故障冷启动命中率，会遗漏这些条件。

**4. 首个恢复 token 的执行时间线**

下面描述一个带索引器或块选择器的原生动态稀疏实现，按层边界简化。不同架构的算子细节需要依其实现调整。

| 顺序 | 执行动作 | Peer 能帮助什么 | 仍可能阻塞的原因 |
|---|---|---|---|
| 0 | 准备恢复 GPU、模型、token 游标与状态映射 | 若恢复 GPU 本身持有备份，可直接复用其本地状态 | 权重、元数据和调度准备仍有开销 |
| 1 | 加载本层需要的索引、压缩表示或其他选择状态；提前搬入候选 Peer KV | 较早建立初始缓存 | 只备份热门原始 KV，可能还无法运行选择器 |
| 2 | 用当前隐藏状态计算 query，并执行模型原本的选择 | 已到达的 Peer KV 可成为命中 | 查询/索引计算本身仍必须执行 |
| 3 | 检查本层真实选中的块 | 减少需要从 DRAM 召回的块 | 选中但尚未就绪的块必须读取；错误预测不能直接跳过 |
| 4 | 必需数据就绪后执行本层 attention 与其他算子 | 消除部分数据等待 | 前一层依赖、计算时间以及剩余 miss |
| 5 | 重复所有层，经过输出头和采样 | 首个新输出可能提前 | 第一层恢复完成不意味着输出已可提交 |

若备份 Peer 与恢复 GPU 不是同一设备，Peer KV 仍需要转移或远程访问，不能把命中时延直接设为零。若恢复目标就是保存该备份的 Peer，也要计入放置与恢复路由联合选择的约束。

ECHO 的执行顺序提供了相关先例：它维持 GPU 上的索引 K，预取候选 KV，最终对真正选中但未缓存的状态执行 guaranteed recall，之后才进行 attention。这是保持原生计算规则的关键。[^6]

按整层简化，可以把首个可提交输出时间写成：

    R(S) ≈ T_setup + T_forward + sum_l W_l(S)

其中 S 是故障前已提交到 Peer 的集合，T_forward 包含正常 query/选择/attention/FFN/输出头计算，W_l(S) 是该层尚未被并行计算或预取隐藏的数据等待。索引状态的缺失等待也必须纳入。该表达式是分析分解，不是忽略共享资源竞争后的实测性能预测。

Peer 的收益应比较相同原生模型的恢复策略：

    Delta R(S) = R_native_DRAM_only - R_native_Peer_plus_DRAM(S)

全 DRAM 基线也应只召回原生模型真正需要的段，并使用同等级的预取、分层执行和 I/O 优化。把这个基线改成“加载所有历史 KV 后才能开始”，会把稀疏模型或流水的固有收益错误归给 Peer。

还必须区分以下三种工作：读取 DRAM 中已经存在的历史 KV，不是重算；为下一轮新增消息做 prefill，是该轮本来就需要的计算；只有历史状态丢失、未提交、无效或恢复算法主动选择重算时，才会产生历史重计算。在完整一致备份的主场景里，不能默认所有非 Peer 段都要重新 prefill。

如果启动、索引或计算占据主要时间，Peer 即便提升命中率也可能没有明显端到端收益。NOSA 还表明实现本身会改变瓶颈：其普通 HF 路线的算子与启动开销可能掩盖 KV 搬运优化，作者因此提供 NOSI。[^5] 这要求机制验证与性能验证分别报告，不能用低效参考实现上的结果推断成熟引擎的收益。

**5. 备份新鲜度：应比较完成提交的时间**

“Peer 备份必须比 DRAM 备份更早产生可用状态”是新鲜度动机的核心要求；“每次 P2P memcpy 都比 D2H memcpy 快”则过强，也不是正确的测量对象。

对于新段 b，设 c_P(b) 和 c_D(b) 分别是其 Peer 和 DRAM 副本完成可用提交的时间。Peer 提供额外新鲜状态的窗口是：

    c_P(b) < failure_time < c_D(b)

而且 b 必须与其他必要 shard、layer、游标和元数据一起构成一个更近的一致恢复点。单个 shard 先到，并不等价于整个 token 已可恢复。

提交时间包括排队、打包、传输、同步以及确认。即使名义 P2P 带宽没有更高，独立通道或不同排队/批量策略仍可能使 Peer 更早提交；反过来，名义带宽很高也不保证小块增量更快。NVIDIA 文档说明 P2P 可以使用 PCIe 或 NVLink 等路径，并依赖设备互访能力；它不提供 P2P 对 D2H 的统一胜出保证。[^7]

应在相同前台干扰预算下比较“仅 DRAM”与“Peer+DRAM”策略的完整恢复游标、重放量与提交延迟分布，计入并行备份新增的竞争。如果 Peer 从不更早形成一致恢复点，单独的新鲜度动机就不成立。

这并不自动排除 Peer 的恢复读取价值。备份写入比较的是源 GPU 到 Peer 的 P2P 与源 GPU 到 DRAM 的 D2H；恢复读取比较的则是 Peer 到恢复 GPU 与 DRAM 到恢复 GPU 的 H2D。即使写入无新鲜度优势，后者仍可能更快，但它属于恢复读取加速，应独立证明。

**6. 多分支是否是默认推理行为**

不是。核对的 vLLM v0.28.0 SamplingParams 默认 n=1；SGLang 当前 sampling 参数文档同样默认 n=1。这意味着普通请求默认生成一条输出序列。并行采样、beam search 或应用层树搜索需要显式请求或应用编排，不能因为引擎有这些能力就假定工作负载会使用。[^8][^9]

自动 prefix caching 是另一个机制：多个已经存在的请求若具有相同 token 前缀，引擎可以复用 KV，并不会因此自动创建更多分支。批处理多个请求、张量并行以及连续多轮对话也不等于同一请求的多候选分支。

因此，单 Agent 的串行多轮请求应以跨轮前缀复用为基础，不能把共享分支的收益作为默认动机。只有实际任务运行 best-of-N、self-consistency 或树搜索时，才值得加入多分支实验；物理 KV 是否已共享、恢复时是否只需要加载一次，还要再核算。

**7. 决定是否继续这条论文路线的最小验证**

固定模型的稀疏选择预算、窗口与所有 attention 配置，只改变 Peer 容量和放置策略。模型每步允许访问多少 KV，与系统提前保护多少 KV，是不同参数；不能一起变化后把收益都归给保护策略。

先在 NOSA-1B 的真实稀疏实现中收集按 layer、head/group、物理块记录的访问、驻留和传输轨迹。用完整 token 历史构造多轮场景，并分别测试 decode 中断、加入新工具结果后的 suffix prefill，以及长输入 prefill 中断。只使用故障前信息构造在线集合。

比较五类放置：相同字节数的随机选择、原生固定块、上一轮统计、当前轮最近访问、故障后访问可见的离线 oracle。Oracle 只能作为参考。首先看 oracle 能否获得明显收益：若连理想选择都无法缩短首个恢复输出，继续改预测算法没有意义；若 oracle 有收益而在线方法没有，再研究热点变化与预测。

至少同时报告 Peer 实际字节占比、首个恢复输出时间、恢复后前若干步的累计等待、实际 DRAM miss 字节、额外历史重算量、索引/元数据恢复成本以及正常服务备份开销。读取量与逻辑命中率不能互相代替，重复使用已驻留块也不能重复计入节省的搬运。

目前具备模型与机制先例，但跨轮热度稳定性、低 Peer 字节预算的恢复覆盖率、真实端到端收益和当前硬件 P2P/D2H 提交优势均尚未本地验证。这些是实验要回答的问题。

**参考来源**

[^1]: [NOSA 作者仓库](https://github.com/thunlp/NOSA)、[NOSA-1B](https://huggingface.co/openbmb/NOSA-1B)、[1B 文件目录](https://huggingface.co/openbmb/NOSA-1B/tree/main)、[NOSA-3B](https://huggingface.co/openbmb/NOSA-3B)。核对公开模型、实现和发布说明；未运行权重。

[^2]: [MiniCPM4.1-8B 官方模型卡](https://huggingface.co/openbmb/MiniCPM4.1-8B)，Usage / Inference with Sparse Attention。后端说明与示例配置按本次访问版本记录。

[^3]: [HiLS-Attention-7B 官方模型卡](https://huggingface.co/tencent/HiLS-Attention-7B)，Model Description / How to Use / Training。

[^4]: [vLLM Automatic Prefix Caching 设计文档](https://docs.vllm.ai/en/latest/design/prefix_caching/)。用于说明实际前缀身份与缓存复用边界。

[^5]: Yuxiang Huang 等，[NOSA: Native and Offloadable Sparse Attention, v2](https://arxiv.org/html/2510.13602v2)，2026-01-29，§2.2、§3.1、§4、§5.5.3。使用相邻步骤局部性、通信瓶颈与运行时实现的机制证据；跨轮故障恢复为待验证扩展。

[^6]: Guangda Liu 等，[ECHO: Efficient KV Cache Offloading with Lossless Prefetching for Serving Native Sparse Attention LLMs](https://www.usenix.org/system/files/osdi26-liu-guangda.pdf)，OSDI 2026，§3。使用索引状态、预取及 guaranteed recall 的执行先例。

[^7]: [NVIDIA CUDA Programming Guide: Programming Systems with Multiple GPUs](https://docs.nvidia.com/cuda/cuda-programming-guide/03-advanced/multi-gpu-systems.html)，§3.4.2。用于 P2P 路径与设备互访条件，不作为当前集群带宽实测。

[^8]: [vLLM v0.28.0 SamplingParams](https://docs.vllm.ai/en/v0.28.0/api/vllm/sampling_params/)，n 默认值与多输出语义。

[^9]: [SGLang 官方 sampling 参数文档](https://github.com/sgl-project/sglang/blob/main/docs/docs/basic_usage/sampling_params.mdx)，n 默认值与多输出说明。
