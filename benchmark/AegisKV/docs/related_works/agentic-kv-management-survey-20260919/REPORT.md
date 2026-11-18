# 稀疏注意力预取与无故障多智能体 KV 管理

调研日期：2026-09-19。范围：在上一份 [KV prefetch 调研](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/related_works/kv-prefetch-survey-20260919/REPORT.md) 基础上，核对预取的预测对象、提前量和粒度，并扩展到无故障 Agent 工作流的缓存生命周期。文献表收录 29 项工作；阅读深度、版本、在线来源和本地 PDF 指纹见同目录 `LITERATURE.csv`、`SOURCES.json`。没有运行论文实现或新增实验。部分工作是预印本；下文系统设计建议是分析推论，不是已实现或已测得的 AegisKV 行为。

## 1. 主要结论

1. 多数稀疏预取方法预测的是“即将访问哪些历史 KV”，并不预测下一个生成 token 的文字内容。判断“是否逐 token”必须分别回答：多久决策一次、提前哪段计算、实际搬多少数据。
2. 直到 attention 需要 KV 时才发起读取，属于按需读取；在此之前利用其他计算提前搬运，才获得预取提前量。选择索引已经确定也不排斥预取，例如跨 Query block 或跨层流水。
3. 无故障多智能体 KV 管理已有直接相关研究。它们关注工具等待期间的驻留、再次访问时间、前缀复用、GPU 批处理空间、工作流进度与预取开销，不能仅用 SGLang/vLLM 的框架名称代表这一研究线。
4. AegisKV 应明确正常缓存策略，再在相同正常策略上增加故障保护。“Slack 大，不需要额外故障副本”不能推出“正常跨轮缓存也不保留”。
5. 固定角色前缀、持续增长的会话历史、跨 Agent 的部分相同文本、某层的稀疏热块，是不同的管理对象。它们不能共用未经区分的 K、命中率和复用假设。

## 2. 稀疏预取到底预测什么

### 2.1 三个独立维度

| 维度 | 应回答的问题 | 常见情况 |
|---|---|---|
| 决策频率 | 多久重新选择一次？ | 每个 decode step、每层；prefill 则随 Query/Query block 的计算推进 |
| 提前量 | 为哪次尚未发生的访问准备？ | 当前层选择尚未结束；当前 token 的下一层；下一个 decode step |
| 搬运粒度 | 一次准备哪些 KV 数据？ | 历史 token 的 KV 向量、若干 KV block/page，或聚合后的传输批次 |

例如，生成第 100 个输出 token 时，第 10 层可以为第 11 层准备一批历史位置的 KV；这些历史位置可能分散在很长的上下文中。“每生成一个 token 都更新一次预测”并不意味着“只传一个 token 的 KV”，也不意味着“每个历史 token 发起一次独立 DMA”。

还要区分三种预算或计数：注意力选择器的访问预算、预取器的候选预算，以及用户定义的 **K：一个请求在 Peer HBM 某一层实际驻留的 block 数量**。三者可能相关，但不是同一变量。预测命中也不等于及时命中：数据必须在实际使用前到达，才能消除等待。

### 2.2 代表方法逐项比较

| 工作及本轮依据 | 预测信号 | 提前到哪里 | 选择/搬运对象及边界 |
|---|---|---|---|
| [Quest，ICML 2024](https://arxiv.org/abs/2406.10774)；本轮核对摘要，前次已调研 | 当前 Query 与每页 Key 的 min/max 摘要 | 当前 Query 的 page 选择 | 选择历史 KV pages；单独这一机制属于按需稀疏检索，不是下一 token 的预测 |
| [InfiniGen，OSDI 2024](https://www.usenix.org/conference/osdi24/presentation/lee)；方法正文 | 较早一层输入、下一层部分 Query 权重及部分 Key 进行轻量 rehearsal | 同一 decode step 的下一层 | 预测重要历史 KV entries；不应表述为严格保持原始稠密注意力 |
| [FreeKV，v5](https://arxiv.org/html/2505.13109v5)；§3–4 | 当前 Query 选出的 pages，利用相邻解码步 Query 相似性 | 下一个 decode step 的同一层 | 预取历史 pages；Query 变化较大时纠正。其近无损精度结论不等于逐步精确一致 |
| [SpeCache，ICML 2025](https://proceedings.mlr.press/v267/jie25a.html)；方法正文 | GPU 低比特 KV 上的推测 Query/attention | 下一个 decode step | CPU 高精度 KV 子集；确实含推测 token 的执行，也有额外计算和低比特副本成本 |
| [ECHO，OSDI 2026](https://www.usenix.org/conference/osdi26/presentation/liu-guangda)；§5 | 历史统计估计选择阈值，结合当前 Query 已算出的 indexer 分数 | 当前选择过程尚未结束；prefill 中跨 Query block 流水 | 提前读取候选历史 KV，最终精确选择后补齐缺失；保持原生稀疏选择语义 |
| [SolidAttention，FAST 2026](https://www.usenix.org/conference/fast26/presentation/zheng)；§4–5 | 上一步同层选中的 blocks，加固定保留部分 | 当前步该层执行前 | SSD→GPU 的 block 预取，实际选择到来后处理错误和缺失；不是逐 token 发一次 SSD I/O |
| [HiSparse，v1](https://arxiv.org/html/2608.07009v1)；§3.4–3.5、§4.6 | 特定模型中后续层共享 anchor layer 的选择索引 | 共享索引的后续层 | 此条件下可精确提前取 KV；通用的跨层猜测在其实验中没有明显端到端收益 |

**ECHO 的 prefill 需要特别解释。** Query block 是调度和流水化单位，不自动意味着其中所有 Query 共用同一 KV 集合。可以在下一 Query block 进行打分时，为前一 block 搬运已确定或高置信的 KV。应分别记录每个 Query 的语义选择和内核实际聚合的搬运集合。[ECHO](https://www.usenix.org/conference/osdi26/presentation/liu-guangda)

**预取效果有边界。** HiSparse 的反例说明，预测出的热点可能本来已命中 GPU 缓存，真正剩下的 miss 更难预测。因此评估需要统计“新增的、及时到达的 miss 覆盖”，而不能只统计预测集合与访问集合的重合率。[HiSparse](https://arxiv.org/html/2608.07009v1)

**对 AegisKV 的推论：** 这些论文证明了可利用的相关性和实现方式，不能直接证明某个在正常 decode 时得到的热集适合稍后故障重放。故障后的尾部 replay、下一轮新增工具结果、不同层/Query，都可能改变访问集合。Peer 驻留的预测对象应是“预计恢复阶段实际需要的块”，并保留 DRAM 补取路径；64-token block 与 checkpoint 间隔 Z 仍是独立配置。

## 3. 无故障 Agent KV 管理：先区分复用对象

| 对象 | 典型复用 | 管理关注点 |
|---|---|---|
| 固定角色、工具描述或共享系统前缀 | 同一角色多次调用、多个请求共享相同开头 | 共享前缀身份、下一次被哪个 Agent 使用、驻留和路由 |
| 某个 Agent 的完整跨轮历史 | 工具返回后，原历史作为下一轮 prompt 的前缀 | 工具等待时长、历史增长、TTL、offload/prefetch、重排队成本 |
| 不同上下文中相同的文档或其他 Agent 输出 | 文本部分重叠，但前面的内容、位置或模型不同 | 不能默认 KV 相同；近似复用需要额外方法及质量检查 |
| 当前请求每层的稀疏工作集 | 当前或随后 Query 只访问历史的一部分 | 原生选择器、热块变化、及时补取、缓存容量与带宽 |

因此，“多轮请求”不自动意味着“上一轮完整 KV 可复用”。需核对下一轮的实际 token 序列、前缀关系、模型与缓存格式。反过来，一次 LLM 调用结束，也不意味着缓存对象失去后续价值。

## 4. 与 AegisKV 最直接相关的无故障研究

### 4.1 工具等待期间：保留、卸载，还是重算

**[InferCept，ICML 2024](https://arxiv.org/html/2402.01869)** 将工具等外部调用产生的停顿视为缓存决策时机，在 GPU 保留、swap、discard/recompute 之间选择，并通过分层、分批传输控制对执行的影响。它显式考虑缓存占用及重算对其他请求造成的资源代价。因此用户提出的“本 Agent 有足够 Slack，但反复重算挤占其他请求”属于已有正常服务研究中的核心问题。

**[Continuum，v6](https://arxiv.org/html/2511.02230v6)** 为工具调用后的 KV 设置 TTL。保留收益不只包括省去重载/重算，也包括避免下一轮重新排队；代价是等待工具期间占用 GPU。它使用工具完成时间的分布，并结合程序级调度。TTL 是有压力时可调整的正常缓存保留策略，不应当作不可撤销的故障保护承诺。

**[TokenCake，v4](https://arxiv.org/html/2510.18586v4)** 联合管理工具等待和 GPU 空间：工具耗时预测、GPU/CPU 压力、等待请求及回迁需求共同决定 offload/upload；空间调度为重要 Agent 保留容量。其 CPU block pool 与 hash 索引也用于复用已卸载前缀。它支持“同一物理 DRAM 对象服务正常复用”的实现思路，但其正常缓存机制本身不等于 AegisKV 的故障副本承诺。

### 4.2 哪个 Agent 会先回来：已知图和在线学习

**[KVFlow，v1](https://arxiv.org/html/2507.07400v1)** 用 AgentStepGraph 的 steps-to-execution 表示距离下一次执行还有多远，据此保留前缀、淘汰较远状态并预取后续 Agent。一个重要适用边界是：论文优先淘汰动态后缀、保护 Agent 的固定前缀。若下一轮会完整继承上一轮对话历史，动态后缀也有高复用价值，这一规则不能直接照搬。

**[CacheScout，v1](https://arxiv.org/html/2608.14624v1)** 从执行历史学习 Agent 转移关系，结合前缀近期使用、再次访问距离和重建成本管理缓存，适合调用路径不预先固定的情形。其主动预热通过普通推理接口、短输出请求实现；缓存缺失时会做 prefill。因此它的 prefetch 可能是后台计算，而不只是 DRAM→HBM 复制，需要预测置信度和限流。

**[Pythia，v2](https://arxiv.org/html/2604.25899v2)** 利用工作流路径和 prompt 组合提示，把预计会复用的状态保留到较慢层，并提前为未来调用准备已有前缀；已有缓存可以搬运，缺失的已知前缀也可在有空闲计算时预热。尚未产生的工具返回内容不能提前精确计算。这里“预测调用”与“预测 Query 访问哪些块”是两个层次。

### 4.3 保留 KV 还会改变谁能进入 GPU

**[TOPAS，v1](https://arxiv.org/html/2608.25523v1)** 联合选择驻留的前缀集合和进入执行的请求，并考虑工作流剩余路径、未来复用和搬运/抢占代价。它揭示一个关键冲突：多保留缓存可以提高局部命中，却压缩 batch 容量并延迟下游工作。因而不能仅以命中率优化整个多智能体系统。

**[ThunderAgent，v3](https://arxiv.org/abs/2602.13692)** 以跨越 reasoning/tool 阶段的 program 为调度单位，依据上下文增长和内存压力暂停、恢复程序，避免所有程序共同耗尽 KV 容量。**[Agentix，NSDI 2026](https://www.usenix.org/conference/nsdi26/presentation/luo)** 也将程序调度与前缀局部性结合，在短请求分散负载和长程序保留局部性之间取舍。两者说明，单独替换 eviction policy 不能解决路由和准入导致的全部问题。

**[Nalar](https://arxiv.org/abs/2601.05109)** 提供工作流依赖、未来上下文及逻辑状态生命周期的显式表达，并衔接保留、迁移和卸载。其价值在于把可用的应用信息交给服务层；不宜把整个框架简化成一种确定的最优淘汰公式。

## 5. 邻近方向及不能混淆的边界

| 工作 | 对本问题的补充 | 使用边界 |
|---|---|---|
| [Pensieve](https://arxiv.org/html/2312.05516) | 多轮状态跨 GPU/CPU 保存；按重算成本、空闲时长做 chunk 淘汰，支持缺失部分重算 | §4.3 实验采用 32-token chunks，优先丢较早的低重算代价片段；不能概括成所有系统都应淘汰后缀 |
| [CachedAttention，ATC 2024](https://www.usenix.org/conference/atc24/presentation/gao-bin-cost) | 分层加载、异步保存及调度相关的预加载，降低跨轮恢复状态开销 | 正常轮次切换，不是 GPU 故障恢复；本轮以官方摘要核对范围 |
| [SYMPHONY，NSDI 2026](https://www.usenix.org/conference/nsdi26/presentation/agarwal) | 根据应用提示分阶段准备状态；优先较早的模型层，以较慢层副本支撑可回收 GPU 缓存 | “前几层先放 HBM”本身已有正常服务相关工作，不能单独作为 AegisKV 新颖性 |
| [Preble，ICML 2025](https://arxiv.org/html/2407.00023) | 分布式前缀目录和缓存感知路由；结合新计算、等待与淘汰代价 | 命中最多的 GPU 不一定是完成最快的 GPU |
| [Strata，OSDI 2026](https://www.usenix.org/conference/osdi26/presentation/xie-zhiqiang) | 多层缓存、读写策略、并发加载协调、加载与计算的调度 | 加速数据路径与预测 Agent 的访问是不同贡献 |
| [Bidaw，FAST 2026](https://www.usenix.org/conference/fast26/presentation/hu-shipeng) | 结合计算负载与存储队列管理 KV | 本轮检查摘要与架构范围，未复核其完整优化推导 |
| [KVCache Cache in the Wild，ATC 2025](https://www.usenix.org/conference/atc25/presentation/wang-jiahao) | 真实服务中缓存复用与可预测性的差异 | 不能从一般云端 trace 直接推导某个 Agent DAG 的复用率 |
| [KVCOMM，NeurIPS 2025，Ye 等](https://arxiv.org/html/2510.12872v1) | 同样内容在不同上下文中的 KV，用 anchor/offset 近似调整 | 不等同于精确 prefix cache；不要与另一篇 Shi 等的 KVComm 混淆 |
| [DroidSpeak，NSDI 2026](https://www.usenix.org/conference/nsdi26/presentation/liu-yuhan) | 微调模型变体之间部分复用、部分层重算 | 跨模型质量与复用条件需要专门验证 |
| [CacheSlide，FAST 2026](https://www.usenix.org/conference/fast26/presentation/liu-yang) | 处理缓存片段位置变化，含位置及 attention 修正 | 不是只改缓存 hash 即可得到的零代价精确命中 |
| [AgentKV，v1](https://arxiv.org/html/2609.14872v1) | 为 think/act/tool 等阶段保存代表 Query，联合评分，跨轮保留压缩状态 | 属于有质量取舍的 KV 压缩，不是单纯无损预取；提示阶段变化会破坏近期 Query 的代表性 |
| [When KV Cache Reuse Fails…，ACL 2026](https://aclanthology.org/2026.acl-long.327/) | 跨部分上下文复用可能削弱 judge 的跨候选交互，最终准确率稳定也不代表判决一致 | 不能将此结果扩展成“精确同前缀复用有问题”；本轮核对官方摘要和问题范围 |

## 6. 对当前 AegisKV 设计的具体含义

本节是文献综合后的设计建议，不是对仓库运行时实现的确认。

### 6.1 先保证正常服务路径完整

应先回答“没有 failure，工具返回后怎样继续”。一个可研究的正常路径是：

1. **LLM 调用结束、进入工具等待：** 释放本次执行引用；根据再次使用时间、上下文重建成本和资源压力，保留 HBM、保留/写入 DRAM，或允许淘汰。执行引用为零只是可淘汰条件，不是立即删除命令。
2. **工具仍在执行：** 更新预计返回时间；HBM 的保留必须与前台 batch 空间竞争，DRAM 保留也受总容量约束。不能无限延长所有 Agent 的保护。
3. **接近下一次调用：** 确认未来会用到的前缀及副本位置。预算允许时预取；只有缺失且预期值得时才进行计算预热。搬运、重算和排队是不同成本。
4. **下一轮到达：** 用兼容的有效前缀启动，缺失部分加载或重算。路由同时考虑缓存局部性和等待；正常请求的工具间隔应在全局调度中体现。

“值得保留”的判断至少包含：再次访问概率、预计等待时间、省下的重算/读取/排队成本、占用这些字节导致的前台等待、以及搬出再搬回的成本。Slack 可提供工作流紧迫性信息，但不是这些量的替代品。

一个假设例子：Agent A 的工具还要运行 2 秒，历史重算要占 4 秒 GPU，即使它有 20 秒 Slack，直接删除所有缓存也可能让稍后重算挤占其他 Agent。相反，无限保留 A 的 HBM 又可能阻止当前请求进入。因此应比较保留、DRAM 回迁和重算的系统成本，而不是由 Slack 大小直接决定正常缓存是否存在。

### 6.2 正常复用与故障保护共享对象，但保留承诺不同

建议让一个兼容的 DRAM KV 对象具有多种用途：正常 prefix cache、活跃传输/读取引用，以及故障保护所需的保留承诺。相同模型、前缀/位置语义、KV 格式和版本且位于所需故障域之外时，同一份有效副本可以同时服务两者。已有副本被提升为保护对象通常不需要重写相同数据；尚未完成的重复写入也可合并。

但是，共用副本不等于没有保护成本：原来可被正常缓存策略淘汰的对象，被承诺保留后会挤占其他缓存。应分别统计物理字节与受保护字节，并共享 DRAM allocator、对象目录和传输预算。无需先假定物理 DRAM 必须硬切成固定“正常区/备份区”；可以使用保护预算或配额约束保留成本。这是综合建议，TokenCake 的共享 CPU block pool 不能替代故障域与提交状态设计。

正常缓存中的 TTL pin、当前计算的访问锁、故障保护租约也不能合并成一个布尔值。普通淘汰、Adapter 缩容和 owner 更新热集，对它们的处理权限不同；物理正在读写的块仍必须等待操作完成。Peer 降级时，已有有效 DRAM 副本可直接复用；没有副本且还需要保障时，要完成 DRAM 提交再释放原驻留。

### 6.3 保持既定职责，避免让 K 承担所有管理含义

- **正常缓存路径**负责跨轮复用、常规保留/卸载/预热，可采用已有策略作为可替换底座。
- **KV Master**在此基础上判断是否需要额外故障保障，选择保护前沿、层数 L 与 Peer 热块集合；K 继续表示每层实际驻留块数。选择 Recompute 表示没有额外恢复保证，不代表禁止正常缓存命中。
- **Recovery Manager**仍绑定恢复位置及 Peer rank；正常 prefix routing 的收益不能自动当作该恢复位置上的命中。
- **Adapter**仍只调窗口级 Peer HBM 空间；Z 仍是系统配置。正常前台内存与传输压力是其反馈来源之一。

关键的新颖性边界：Agent-aware 保留、DAG 紧迫性、预测预取、优先加载较早层都已有工作。AegisKV 应论证的是在明确故障模型下如何获得额外的恢复/WCT 收益，以及为这些保障付出了多少正常执行成本；不能把底座正常缓存带来的收益全部归因于故障保护。

## 7. 下一步应怎样验证（仅实验设计，本轮未执行）

### 7.1 四类必要工作负载

| 工作负载 | 要隔离的问题 |
|---|---|
| 固定角色前缀、重复切换 Agent | 图距离或转移预测能否优于 LRU |
| 同 Agent 完整历史持续增长、穿插工具调用 | 保留/卸载决策能否减少全系统重算；不能用只有角色前缀重复的 trace 替代 |
| 并行分支及 fan-in/judge | 缓存驻留与关键路径、批处理容量的冲突；如使用近似复用，要另测判决质量 |
| 动态分支、工具耗时波动、取消 | 错误预热、延迟到达、无用保留的成本 |

### 7.2 对照和指标

正常路径至少对比容量匹配的 LRU/常规 offload、工具感知 TTL/offload、图或在线访问预测；用联合准入/驻留方法检查“高命中但 WCT 更差”的可能性。具体重实现哪些策略应按接口及工作负载适配性决定，不把所有论文的完整系统收益当作一个缓存算法的收益。

AegisKV 核心对照应固定同一正常缓存策略、模型、工作流和资源，再比较“关闭/开启额外故障保护”。无故障时报告 WCT 分布、TTFT/排队、重算 GPU 时间、HBM/DRAM 占用、读写及无用预取字节、批处理/准入影响；有故障时另报告恢复及 WCT 的增量。

命中率需分 local HBM、DRAM、Peer，并同时报告 request-hit 与 token/byte-hit。预取还应报告真正覆盖 miss 的及时命中、晚到和误取；否则热块预测正确但没有新增收益也可能被误判为有效。故障前后的访问轨迹需要按请求/层/Query 对齐，不能用合成热点频次替代原生模型证据。

## 8. 阅读建议

当前设计最值得优先对照的是 **TokenCake → Continuum → KVFlow/CacheScout → TOPAS**：依次对应工具期间的分层管理、保留时间、未来访问预测及缓存与准入的联合影响。稀疏预取优先对照 **ECHO → FreeKV → HiSparse**，分别理解当前选择过程流水、跨步预测以及预测收益的反例。其余工作用于补齐分布式路由、跨上下文语义和数据路径边界。
