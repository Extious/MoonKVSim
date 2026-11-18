# 网页 ChatGPT 原始评审（工具返回的前 20,000 字符）

来源：https://chatgpt.com/c/6aae1081-a1a4-83ec-90a8-2db8c1a398dd

注意：完整评审保留在网页；以下由 read_thread 读取，接口在 20,000 字符处截断。引用标记为网页内部标记，请以原网页查看来源。

# AegisKV 稿件评审

**总体判断：选题有 EuroSys 价值，但当前动机证据和算法闭环尚不足以支撑有说服力的接收论证，建议对核心设计进行大修。** 这里的判断针对已提供的摘要、§2 和 §3，不是把这份节选当作完整投稿打分，也不意味着尚未提供的实现或实验一定不存在。

我已逐页阅读这份 9 页 PDF，包括两处编号公式、算法 1–3、图 1–5 和全部参考文献。图表放大后可以辨认；图 4 在最终排版尺寸下存在明显的字号问题。以下会区分：**稿件直接支持的事实、可由所述机制推出的问题、尚未明确的实现契约，以及完整投稿必须补充的验证**。我没有运行作者代码，也没有独立复现图中的数据。

EuroSys 2027 官方 CFP 要求有意义的问题、令人信服的解决方案，以及能展示收益、局限和相对既有工作优势的严格评估；新颖性、清晰性和正确性也都是明确标准。以下据此评审。:chatgpt-content-reference{index="0"}

---

## 一、核心贡献、当前证据与总体判断

### 1. 核心贡献应当如何概括

AegisKV 最有潜力的贡献不是“把 KV 备份到多层存储”，而是：

> **以预测的工作流延迟容忍度衡量故障保护价值，在有限资源下联合决定请求的恢复层级、Peer-HBM 中的保护深度和热块集合，再通过保持原生注意力语义的按需恢复完成接管。**

具体包括：Tracker 使用剩余执行时间预测与 CPM 计算 slack；Recovery Manager 预先绑定接管目标；KV Master 选择 R/D/P 层级和逐请求层深；Adapter 控制目标端 Peer 容量。这个职责划分在当前稿件中是明确的。:chatgpt-content-reference{index="1"} :chatgpt-content-reference{index="2"}

**真正需要证明的系统贡献，是这些组件组合后，在真实故障、预测误差、有限容量和争用同时存在时，仍能改善工作流完成时间，而不是单独展示每个组件看起来合理。**

### 2. 当前材料实际上提供了什么证据

| 材料 | 证据性质 | 可以支持的结论与不能支持的结论 |
|---|---|---|
| 图 1(a)(b) | 真实 trace 的描述性分析，但经过筛选，并以时间关系推断 fan-in | 支持保留样本中存在分支时长差异；不直接支持真实依赖 slack 的分布或总体故障收益。:chatgpt-content-reference{index="3"} |
| 图 1(c) | trace 时间线加静态重算成本的独立反事实 | 支持“重算成本排序可能不同于 WCT 损失排序”的条件化例子；不是物理故障重放。:chatgpt-content-reference{index="4"} |
| 图 2 | AIConfigurator HYBRID 静态估计，含外推与带宽假设 | 支持所建模型中的恢复成本量级；不证明实际部署、竞争带宽或有限热块备份的收益。:chatgpt-content-reference{index="5"} :chatgpt-content-reference{index="6"} |
| 图 3(a)(b) | 文献结果与选择性模型发布案例 | 前者不是 AegisKV 的 GBDT 运行时误差；后者不是部署占比，也不是后端可恢复性验证。:chatgpt-content-reference{index="7"} |
| 图 3(c) | 每模型三段 PG19 capture 的访问集合分析 | 支持这些输入与配置下的 distinct-KV 覆盖情况；不是 agent 故障恢复实验。:chatgpt-content-reference{index="8"} |
| 图 4 | 系统架构设计 | 说明组件及接口意图，不证明实现已经完成。:chatgpt-content-reference{index="9"} |
| 图 5 | 使用一个实测每层计算参数、假定传输参数的恢复流水线模型 | 不是四种完整恢复实现的实测比较，也不验证在线层深选择。:chatgpt-content-reference{index="10"} |

这份稿件的大部分正文对上述边界交代得相当诚实。**主要不一致是摘要末句已经声称实验显著降低 WCT、正常开销可忽略，而当前可见证据没有支撑这句话。**:chatgpt-content-reference{index="11"}

### 3. 最强的三点

1. **优化目标选得正确，而且具有可解释性。** 图 1 的关键价值是说明“避免最多重算”不等于“避免最多工作流延迟”。即使不把该例子推广到总体，这也是值得研究的资源分配问题。:chatgpt-content-reference{index="12"}

2. **对恢复对象和证据边界的处理比常见概念稿更谨慎。** 稿件区分了稀疏选择比例、跨 query/head 的需求并集、物理保护块和实际覆盖率，也明确要求 selector state 与缺失块按需恢复，而不是偷偷引入额外注意力近似。:chatgpt-content-reference{index="13"} :chatgpt-content-reference{index="14"}

3. **已有若干正确的系统接口意识。** 例如 Peer 副本必须位于实际接管目标；策略触发不等于副本提交；虚拟 preview 不等于物理预留；保护优先级不等于强制串行重试。这些区分值得保留。:chatgpt-content-reference{index="15"} :chatgpt-content-reference{index="16"} :chatgpt-content-reference{index="17"}

### 4. 最可能导致拒稿的五个原因

如果完整投稿沿用当前论证而未补齐，最危险的五点是：

1. **核心收益仍停留在“存在性例子＋静态模型＋小样本访问分析”，但摘要已作端到端性能承诺。**
2. **恢复正确性依赖多个未具体化的 runtime contracts**，特别是 token 持久性、跨层/分片的可恢复前沿，以及稀疏 replay 的语义一致性。
3. **容量控制没有形成有界闭环**：活跃请求的旧 Peer 引用不能撤销，DRAM 又缺少明确的容量与失败处理机制。
4. **逐请求局部评分与工作流在同一 worker 故障下的联合损失之间存在结构性差距**，在线 slack、固定接管目标和争用成本也未连成可靠决策链。
5. **相对既有系统的增量尚未被准确隔离**：workflow-aware KV、关键路径/任务完成时间调度、预取、稀疏 offload，以及负载感知故障恢复，都已有直接相关研究。

---

## 二、相关工作核验：需要怎样收紧创新性论证

以下来源已经核验。列为 arXiv 的工作按预印本讨论，不将其表述为已被某会议接收。

| 工作 | 已有机制及与本稿的关系 | AegisKV 必须解释的增量 |
|---|---|---|
| **DéjàVu: KV-cache Streaming for Fast, Fault-tolerant Generative LLM Serving**，ICML 2024 | 已研究 KV streaming 与容错服务。:chatgpt-content-reference{index="18"} | 不能把异步复制或流式 KV 恢复本身作为主要新颖点；应突出工作流故障影响驱动的保护分配。 |
| **GhostServe: A Lightweight Checkpointing System in the Shadow for Fault-Tolerant LLM Serving**，MLSys 2026 | 使用纠删码保护 KV。其 §8 明确说明不提供完整 GPU runtime 容错，静态通信拓扑下不能直接动态替换故障 GPU。:chatgpt-content-reference{index="19"} | 比较必须对齐故障模型和恢复终点，不能把内存状态重建时间直接与跨 DP 接管时间比较。 |
| **LUMEN: Coordinated Failure Recovery for Distributed LLM Serving**，arXiv:2606.17787 | 研究负载感知 checkpoint 放置、局部性感知恢复与故障后的重平衡。:chatgpt-content-reference{index="20"} | 为什么到达时预绑定目标、但不预留接管资源，优于或能够补充故障时重平衡？ |
| **KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows**，arXiv:2507.07400 | 使用 Agent Step Graph 指导缓存淘汰，并进行 CPU–GPU KV 预取。:chatgpt-content-reference{index="21"} | “工作流信息指导 KV 放置/预取”已经存在；新增部分应是故障价值、恢复语义和保护资源约束。 |
| **TOPAS: Workflow-Aware Prefix-State Scheduling for Multi-Agent LLM Serving**，arXiv:2608.25523 | 联合 prefix residency 与请求调度，以任务剩余最长服务路径和迁移/抢占成本衡量决策。:chatgpt-content-reference{index="22"} | 必须区分正常服务中的任务进度优化，与故障联合影响下的备份分配；不能仅用“面向 WCT”概括新颖性。 |
| **NOSA: Native and Offloadable Sparse Attention**，arXiv:2510.13602v2，及其 NOSI 系统 | 已把稀疏选择、访问局部性和 CPU–GPU 数据移动作为共同设计对象。:chatgpt-content-reference{index="23"} | 热块预取与稀疏 offload 不是新的独立概念；应展示它们用于故障恢复时新增的状态、时序和保护价值问题。 |

这不意味着 AegisKV 没有创新。**目前更准确的定位是一个尚待证明的系统联合设计，而不是多个单独新机制的集合。** 完整稿应通过受控比较回答：使用相同恢复后端和相同资源，加入工作流故障价值后，究竟改变了什么决策、为什么有效。

---

## 三、按严重性排列的 18 个修改问题

### A01｜P0｜摘要的实验结论超出了当前证据

**定位：** p.1 摘要末句；p.8 §3.6 “Scope and validation”。  
**性质：** 关键证据与表述不匹配，不是“因为节选没附实验就判定未实现”。**负责范围：跨章节。**

**问题与机制：** 摘要写明 “Experiments show … substantially reduces … negligible overhead”，但 §3.6 明确把端到端 slack 准确性、并发恢复、前台干扰、层深和容量控制列为尚需验证。图 5 的局部实测参数也不能转化为 AegisKV 的端到端实测结论。:chatgpt-content-reference{index="24"} :chatgpt-content-reference{index="25"}

**可执行修改：** 当前版本先把摘要末句改为设计目标或现有分析的结论。为各图统一添加证据类型标签：trace analysis、literature result、static estimate、modeled pipeline、system measurement。

**通过标准：** 每一项性能承诺均能对应到同一系统、明确配置、明确基线的测量；“negligible”必须有预先定义的开销指标和边界，不能用“复制限制为链路的 20%”替代。

---

### A02｜P0｜“独立提交”缺少可恢复状态的具体一致性定义

**定位：** p.5 §3.4 的 commit frontier / runtime contracts；p.6 §3.5 sealing；p.7 “Commit and recover by actual readiness”。  
**性质：** 正确性说明不足；不是已经证明实现会读坏数据。**负责范围：算法。**

**问题与机制：** Peer 与 DRAM 独立提交是合理的，但目前没有定义如何从非均匀的层、分片和辅助状态覆盖中，计算一个合法恢复点。某些低层已提交到较新位置，不意味着高层、TP shard、selector state 也可在该位置恢复。另外，“已知尾部不重新采样”要求这些 token 在源失效后确实可得，不能只存在于故障 worker 的内存。:chatgpt-content-reference{index="26"} :chatgpt-content-reference{index="27"} :chatgpt-content-reference{index="28"}

**可执行修改：** 补一个恢复状态机和最小不变量：对象版本/布局标识、提交发布点、可恢复前沿、token 日志及确认顺序、source fencing epoch、重试去重。可采用一致前缀，也可支持非均匀覆盖，但后者必须说明依赖闭包和补算规则。工具副作用的去重可以交给 runtime，但需要写出接口边界。

**通过标准：** 在每个复制、提交、发布、确认步骤前后注入源故障；已确认 token 不丢失，不读取未提交对象，不混用不兼容状态，恢复位置可由存活元数据唯一确定。

---

### A03｜P0｜稀疏 replay 的“同一逻辑 KV”需要比“权重兼容”更强的契约

**定位：** p.5 图 3(c)；p.6 需求并集 \(U_l(n)\)；p.7 “Placement changes neither selector outputs …”。  
**性质：** 正确性关键假设未闭合。**负责范围：算法。**

**问题与机制：** 已生成的 64-token 尾部批量 replay，未必与原先逐 token decode 使用相同的原生稀疏选择过程；block pooling、Prefill gate、窗口边界、压缩状态或专用 decode 分支都可能影响选择。这里不是断言这些模型必然不一致，而是：**缺块后按需 fetch 只能保证取得选中的数据，不能自动保证选择过程等价。** 稿件使用实验性 Seer Prefill gate，且关闭了 final-block dense override，更应明确参考执行语义。:chatgpt-content-reference{index="29"} :chatgpt-content-reference{index="30"}

**可执行修改：** 按支持后端列出必要状态：KV、selector/indexer、压缩分支、窗口状态、位置编码状态及 shard 布局；明确批量 replay 与原 decode 是否等价，不等价时采用何种恢复执行方式并重测成本。

**通过标准：** 对同一已知 token 前缀，比较原生无故障执行与恢复执行的选择集合、必要辅助状态和 KV 数值误差；跨多个尾长、块边界和故障点验证。无需承诺未来随机采样 bitwise identical，但不能仅以最终任务准确率接近替代恢复语义检查。

---

### A04｜P0｜不可撤销的活跃引用，使“缩容”不能保证前台及时拿回内存

**定位：** p.7 §3.6；p.8 算法 3、第 7–9 行及 “Referenced copies drain as requests finish”。  
**性质：** 可由现有设计直接推出的容量/活性问题。**负责范围：跨章节。**

**问题与机制：** 降低 \(B_p\) 或 \(L_r\) 都不撤销活跃请求的旧引用；热集合变化还可能继续保留旧副本。因此目标缩小不等于可用空间增加，回收时间受最长剩余请求控制。物理空间检查避免了越界分配，却不能保证 R4 所要求的前台优先或可控正常开销。:chatgpt-content-reference{index="31"} :chatgpt-content-reference{index="32"}

**可执行修改：** 必须二选一：将“保留偏好引用”与短期读写 pin 分离，在可靠 DRAM backing 存在时允许安全撤销 Peer 保留；或者明确采用不可抢占预留，并给前台硬保留和最坏回收等待边界，收窄“弹性让位”目标。

**通过标准：** 在长请求和突发前台负载下测量目标预算、实际驻留、不可回收字节和 admission stall；证明前台资源恢复具有声明的边界，而不只是最终请求结束后能够回收。

---

### A05｜P0｜DRAM 回退被当作总能成功，但算法没有 DRAM 容量闭环

**定位：** p.6 R/D/P 层级；p.7 算法 2 第 6 行；p.8 有效 DRAM backing 的回收条件。  
**性质：** 资源可行性说明不足；有限 DRAM 下会成为设计漏洞。**负责范围：算法。**

**问题与机制：** 算法把所有 D/P 请求的 sealed state 加入 \(D_s\)，但没有 DRAM 预算、准入、保留周期或失败分支。Peer 申请失败则回退 DRAM，Peer 回收又要求有效 DRAM backing：若 DRAM 不足或复制长期积压，这两项都不成立。:chatgpt-content-reference{index="33"} :chatgpt-content-reference{index="34"} :chatgpt-content-reference{index="35"}

**可执行修改：** 为 DRAM 添加容量账本、共享对象引用、预留与准入规则，定义无可用 DRAM 副本时如何降级到重算。若设计确实假定 DRAM 足够大，必须明确这一适用前提并给出容量需求，而不能继续泛称解决有限多层备份资源问题。

**通过标准：** 有限 DRAM、复制积压和请求完成/工具交接组合下，内存占用有界；每次恢复都能依据实际提交覆盖选择合法路径，不依赖尚未完成的 DRAM 副本。

---

### A06｜P0｜逐请求超 slack 损失不能直接代表同一次 worker 故障的工作流价值

**定位：** p.6 深度评分段；p.7 算法 2 的 slack 顺序与 Score。  
**性质：** 决策目标的结构性近似问题，作者虽已声明 heuristic，但影响仍需证明。**负责范围：算法。**

**问题与机制：** 考虑一个最简单的反例：同一 worker 上两条等长关键分支同时失效，二者分别需要 10 秒恢复，且恢复时间互不影响。预算只能完全保护其中一条。逐请求评分可把保护它视为避免 10 秒损失，但工作流仍等待另一条，WCT 不变；备份却有正常开销。问题不是要求全局最优，而是当前局部收益可能连真实边际收益的方向都判断错误。稿件明确说明评分不是 workflow-makespan sum，因此更需要揭示这个差距。:chatgpt-content-reference{index="36"}

**可执行修改：** 至少以“源 worker 故障事件”联合采样受影响请求，计算对各工作流完成时间的边际影响；若保留局部近似，应说明适用条件，并用小 DAG 的可行最优策略量化偏差。

**通过标准：** 覆盖并列关键路径、共同故障、共享 join 和跨工作流竞争；报告真实 \(\Delta WCT\) 与局部评分的偏差，以及对可行 oracle 的 regret，而不只报告平均速度提升。

---

### A07｜P0｜新颖性边界尚未与最接近的已有机制对齐

**定位：** p.1 §2.1 相关工作段；p.3 §2.4；p.4 §3.1。  
**性质：** 决定性的定位缺口，尚不能据此断言“没有创新”。**负责范围：跨章节。**

**问题与机制：** 当前主要区分 DéjàVu、GhostServe、LUMEN，但尚未处理 KVFlow、TOPAS、NOSA/NOSI 与本稿之间的直接重叠。把 GBDT、CPM、分层存储、热块和流水线组合起来并不自动构成足够强的创新论证。当前 §2.1 的三行对比承载不了这个任务。:chatgpt-content-reference{index="37"}

**可执行修改：** 按“优化对象、故障模型、可预测信息、保护对象、容量约束、恢复语义”制作机制对照，并明确哪些基础机制继承已有工作，哪些决策因故障和 WCT 目标而改变。相关来源见前述核验表。

**通过标准：** 在相同恢复后端和资源下，把工作流故障价值、热块/层深机制分别打开与关闭；结果能够隔离新增设计的价值，而不是主要来自更多 HBM、更强复制后端或更弱基线。

---

### A08｜P1｜Heddle 的相关性不能验证 GBDT 的 wall-clock slack，DAG 完整性也未操作化

**定位：** p.4 §3.3；p.5 图 3(a)、算法 1 第 2–5 行。  
**性质：** 关键预测与适用范围证据不足。**负责范围：跨章节。**

**问题与机制：** Heddle 的 Figure 13 确实研究 trajectory-length 预测，其预测器也不是本文这个 GBDT；该文结果不能证明运行时秒数的校准。即使预测始终是真实时间的两倍，Pearson 相关性仍可为 1：真实剩余时间为 100/90 秒的两分支，真实 slack 为 10 秒，预测却给出 20 秒；15 秒恢复便可能被错误地判为可完全吸收。:chatgpt-content-reference{index="38"}

此外，算法 1 的 CPM 递推和空前驱/后继边界写法没有明显基础错误；真正欠缺的是“DAG structure incomplete”如何判定，以及纯依赖图估计如何处理资源排队。整工作流 fallback 到零 slack 可能使算法在目标应用中频繁失去区分能力。:chatgpt-content-reference{index="39"} :chatgpt-content-reference{index="40"}

**可执行修改与通过标准：** 明确完整 DAG/在线增量 DAG 的契约；按 workflow、项目或时间切分训练测试，避免同一轨迹 snapshots 泄漏。报告秒级误差、正 slack 的错误判定、关键路径排序、零-slack fallback 占比和最终决策 regret；与简单历史均值、零 slack 和 oracle 对照。

---

### A09｜P1｜预绑定目标解决局部性，却没有解决故障时的接管可行性

**定位：** p.1 failure model；p.4 §3.4 的环形映射与“不预留 HBM”；p.5 readmission。  
**性质：** 接管策略与现实故障场景说明不足。**负责范围：算法。**

**问题与机制：** 一个 worker 故障会影响其多个在途请求，而不是图 1(c) 那种独立丢失一条分支的情形。预绑定目标可能在故障时已被前台占满；本地 Peer 副本消除了搬运，但排队和缺少恢复工作空间可能主导 WCT。还需要说明 Peer 副本转为本地活跃 KV 时如何更改所有权、核算空间，以及 TP 中一个 rank 故障时究竟失去哪个 DP 的服务能力。:chatgpt-content-reference{index="41"} :chatgpt-content-reference{index="42"} :chatgpt-content-reference{index="43"}

**可执行修改：** 给出真正的目标分配策略，而不只是“可分散到多个目标”；明确预留、负载上界或故障时重路由方案，并说明重路由后如何重新计算 Peer 价值。无需扩大到全主机故障，但应分别定义 worker crash 和 GPU progress failure 的检测与隔离。

**通过标准：** 同一源上多个请求同时重试、目标忙而其他 DP 空闲时，仍能正确恢复并量化排队损失；与负载感知重平衡比较，不能只测有空闲目标的环形接管。

---

### A10｜P1｜逐请求 layer readiness 如何落到连续 batching 和 TP collective 中尚不清楚

**定位：** p.5–6 独立重试段；p.7 “each layer waits for all required inputs”。  
**性质：** 执行机制不足，不是已经证明存在死锁。**负责范围：算法。**

**问题与机制：** “不按保护优先级串行重试”不等于“可以独立推进每个请求的层”。同一批次中某请求缺 KV，可能延迟整个 batch；不同请求处于不同层时，也需要明确的 batch 组织和 collective 顺序。现在 readiness、连续 batching 和共享 copy capacity 之间只有契约式描述。:chatgpt-content-reference{index="44"} :chatgpt-content-reference{index="45"}

**可执行修改：** 补充恢复队列到执行批次的状态图：哪些请求可入批，缺块时是否拆批，何时占用中间激活与恢复缓冲，demand copy 如何获得优先级，DMA 不可抢占如何处理。

**通过标准：** 在一请求发生长 miss、其他请求已 ready，以及多请求同时 miss 的情况下，测量 batch 级拖累、copy 排队、公平性和吞吐；证明不会因资源持有顺序产生死锁，并把不可避免的争用计入成本模型。

---

### A11｜P1｜层级规则可能选择被重算支配的 DRAM 路径，Score 也缺少可实现定义

**定位：** p.6 式 (1)、层级条件和评分描述；p.7 算法 2 第 11–12 行。  
**性质：** 一个条件性决策漏洞，加上算法定义不足。**负责范围：算法。**

**问题与机制：** 式 (1) 没保证 \(R_D<R_R\)。短历史或传输拥塞时可能 \(W_0>T_{rc}\)；此时低 slack 请求进入 P，拿不到 Peer 后仍保留更慢的 DRAM 路径。另一方面，Score 混合正常服务延迟与故障概率加权损失，但没有明确单位、受影响前台请求集合、风险 horizon、样本分布和旧 pin 的成本归属。:chatgpt-content-reference{index="46"} :chatgpt-content-reference{index="47"}

**可执行修改：** 先排除被其他可行路径支配的候选，或统一比较 R/D/P。把 Score 写成完整公式和可执行伪代码，定义风险模型、hysteresis 在零 slack/交叉边界时的行为，以及 profile 缺失时的决策。

**通过标准：** 在 \(R_D<R_R\)、\(R_D=R_R\)、\(R_D>R_R\)、故障风险接近零和容量突然变化的单元测试中，不选明显被支配的路径；给出小规模枚举对照和切换稳定性结果。

---

### A12｜P1｜trace 选择偏差不只来自作者的二次筛选，上游数据也有条件

**定位：** p.1–2 §2.2、图 1。  
**性质：** 动机外推范围不足；不是指控作者隐瞒挑例。**负责范围：动机。**

**问题与机制：** 作者已诚实说明最大 gap、推断 fan-in 和特意选择案例，但仍缺少总体结构。上游数据卡还规定最低请求数、并发子代理数量上限，并排除特定动态工作流记录缺陷的 sessions；`in` 来自 hash-block count，而非真实 tokenizer count，存在过计数风险。这些会影响代表性和恢复成本换算。:chatgpt-content-reference{index="48"}

从 393 sessions 到 121 workflows 后再取每 workflow 的最大 gap，会强调“至少存在一次大差异”，不能说明随机故障时刻通常有多少 slack。:chatgpt-content-reference{index="49"} :chatgpt-content-reference{index="50"}

**可执行修改与通过标准：** 发布逐级筛选计数、全部保留组分布、每 workflow 等权结果，以及按故障暴露时间抽样的结果；区分 duration gap 与实际 finish-time margin。用具有真实依赖记录的工作流验证 fan-in 推断，并对 hash 长度误差做敏感性分析。结论必须在这些口径下仍成立，或者明确收窄适用范围。

---

### A13｜P1｜图 2 说明“备份有用”，尚未说明“有限 Peer-HBM 值得付费”

**定位：** p.2–3 §2.3、图 2。  
**性质：** 从动机到具体机制的证据缺口。**负责范围：动机。**

**问题与机制：** 图 2 的 HBM 路径是假定完整历史已在实际接管 GPU，而 AegisKV 只放置有限热块；DRAM 路径又采用先完整加载、再计算的无重叠模型。真正强的替代方案应是层优先、transfer–compute overlap、按需加载的 DRAM 恢复。与重算相比的巨大收益不能直接论证 Peer 相对优化 DRAM 的增量。稿件自己已经指出 full-history HBM 只是参考。:chatgpt-content-reference{index="51"}

**可执行修改：** 增加一组同资源、同恢复终点的“优化 DRAM vs 有限 Peer”比较；提供每 rank 字节数、共享 host/NIC 瓶颈、实测带宽及模型脚本。图 2 的 64 GB/s/rank 与图 5 的 6.25 GB/s 可以属于不同场景，但必须解释场景而非任意选择参数。

**通过标准：** Peer 的增量价值在测得的共享带宽与容量限制下仍能成立；大模型静态外推继续明确标注，不冒充其部署验证。

---

### A14｜P1｜热块预测的收益主要受模型和粒度制约，当前样本不足以决定线上策略

**定位：** p.4 Insight 3；p.5 图 3(c)；p.6 512-step 统计与式 (2)。  
**性质：** 可迁移性证据和边界行为不足。**负责范围：跨章节。**

**问题与机制：** Seer 的频率策略覆盖率 43.0% 已接近文中的 oracle 43.3%，表明其主要限制是需求并集和物理粒度，而不只是预测器不够好；MiniCPM 的频率优势也远小于 NOSA。不能据此统一推断 agent retries 都值得维护历史频率。短请求还可能没有 512 个 decode steps；短历史下 mandatory window/sink 也可能超过 \(\lceil hn\rceil\)。:chatgpt-content-reference{index="52"} :chatgpt-content-reference{index="53"} :chatgpt-content-reference{index="54"}

**可执行修改：** 增加真实 agent 文本、工具返回后的分布突变、不同尾长和冷启动；规定统计不足与 mandatory quota 超额时的策略。补模型、数据和 gate 的版本。已核验的 Seer 模型卡仅提供实验适配器的简要说明，不足以独立确认文中的 Prefill 配置及修改细节，这部分应标为待 artifact 核验。:chatgpt-content-reference{index="55"}

**通过标准：** 报告字节覆盖、暴露等待和 WCT 三者，而不只报告命中率；必须保留接近 dense-union 的负例，并展示不适合热块预测时如何回退。

---

### A15｜P1｜“前 \(L_r\) 层”限制和图 5 的恢复终点尚未支撑在线层深选择

**定位：** p.6 深度选择及 first-\(L_r\)；p.7 图 5。  
**性质：** 启发式依据与成本模型不足。**负责范围：算法。**

**问题与机制：** 在均匀层模型下，优先保护前几层具有流水线直觉；真实层的计算、状态大小、稀疏度与 miss 代价可能不均匀。图 5 又在 tail-KV 重建时结束，但图中部分 cold-KV 搬运延续到该终点之后；这部分恢复债务可能影响后续 decode 和其他请求。147 MiB 也缺少 \(h\)、每层对象及辅助状态的字节分解，无法直接与式 (2) 对账。:chatgpt-content-reference{index="56"} :chatgpt-content-reference{index="57"}

**可执行修改：** 明确这是受限候选空间而非一般最优放置；给出每层 profile、字节账本、实测 \(C\) 的硬件与方法，以及 tail-ready 后的搬运/计算开销。对非均匀层至少做一个按边际收益选层的对照。

**通过标准：** 在多个 context/tail 状态下，对比零深度、固定深度、最佳固定深度和在线选择；报告相对可行 oracle 的差距，并同时量测恢复后 token latency 与 WCT，不能只看首次 tail-ready。

---

### A16｜P1｜20% 链路限速不能推出正常开销可控，三个时间尺度可能形成复制积压

**定位：** p.6 checkpoint \(Z\)、512-step 统计窗口；p.7 copy 限速与 Adapter 窗口；p.8 validation。  
**性质：** 正常路径开销及控制稳定性证据不足。**负责范围：跨章节。**

**问题与机制：** prefill 完成时可突然产生大量复制；若新增备份字节持续超过复制服务能力，commit lag 会增长，实际尾部远超 \(Z\)。稿件已正确承认这一点，但没有说明何时限流、跳过 checkpoint、合并版本或调整准入。即使每条链路限速，HBM 带宽、源端读取、统计维护和容量占用仍可能损伤前台。:chatgpt-content-reference{index="58"} :chatgpt-content-reference{index="59"} :chatgpt-content-reference{index="60"}

**可执行修改：** 给出 \(Z\)、统计窗口、容量窗口及 hysteresis 的默认值和耦合规则；明确复制队列的有界策略。区分实验注入故障频率与评分使用的风险先验，给出保护收益抵消常态成本的 break-even 分析。

**通过标准：** 稳态和突发负载下报告 TTFT、TPOT、吞吐、控制开销、复制积压、commit lag、策略切换次数和实际 HBM 占用；在故障风险较低时允许结果显示“不值得启用 Peer”。

---

### A17｜P2｜图 4 明显不满足最终尺寸可读性，图 2 的路径编码依赖颜色

**定位：** p.5 图 4；p.3 图 2；p.7 图 5。  
**性质：** 实际排版与图形问题。**负责范围：跨章节。**

**问题与机制：** 从 PDF 中图 4 的文字对象检查，多个内部标签约为 **5–6 pt**，不是放大屏幕上能看清就算合格。图 2 的线型/marker 表示模型，但恢复路径主要依赖颜色，灰度下识别不稳健。CFP 要求所有文字、图与图注至少 10 pt、至少 12 pt leading，并要求灰度打印不放大可读。:chatgpt-content-reference{index="61"} :chatgpt-content-reference{index="62"}

**可执行修改：** 图 4 改为跨双栏或拆成控制面与数据面，删除重复 DP 内部细节；图 2 用分面或冗余线型区分路径；图 5 用纹理、直接标签与清晰终点替代仅靠颜色的小时间片。

**通过标准：** 按最终版面导出后检查嵌入字号，并进行 100% 比例灰度打印审阅。不要为给实验腾页数而继续缩小图中文字。

---

### A18｜P2｜术语和结构需要围绕接口组织，而非围绕机制名称堆叠

**定位：** p.1 workflow 定义；p.4 segment 定义；p.6–8 request 生命周期；算法 2 输入输出。  
**性质：** 表达与逻辑组织问题。**负责范围：跨章节。**

**问题与机制：** 文中 request、agent、branch、segment、workflow 和 DP/worker/TP group 分别在不同位置定义，读者很容易把分支 slack 当作单请求预算，把 policy depth 当作实际驻留上界。作者事实上已作了部分区分，但关键解释分散。算法 2 返回 \(H\)，Output 行却未列出它，也是可避免的不一致。:chatgpt-content-reference{index="63"} :chatgpt-content-reference{index="64"} :chatgpt-content-reference{index="65"}

**可执行修改：** 增加一张简短的“对象—所有者—生命周期—失效条件”表；按“故障与状态契约→组件接口→策略→恢复数据路径→资源控制”组织 §3。将图 3(b) 的 “adoption”改为 selected releases，考虑用后端恢复状态适用性表替代发布年表。

**通过标准：** 读者无需来回翻页，就能说明一个请求从到达、提交、失效、接管到完成过程中，各种 slack、frontier、depth、budget、reference 分别由谁维护。当前没有 §1 是本轮提供范围所致，不应作为结构缺陷。

---

## 四、跨组件自洽性：三个必须覆盖的具体场景

以下数值均为**审稿构造的测试条件，不是论文实验结果**。

### 场景一：预算已经缩小，但前台请求仍无法进入

目标 DP 的 KV pool 为 40 GiB，其中 20 GiB 为活跃长请求持有的 Peer 副本。前台需求随后增长到 30 GiB。Adapter 把 Peer 目标降到 10 GiB 或更低，KV Master 也降低 \(L_r\)，但旧引用仍然保留。

结果不是立即 OOM——物理准入检查可以避免越界——而是**前台无法取得所需容量，必须等待旧请求释放引用**。这说明 Master 的目标策略和 Adapter 的实际可回收空间不是同一控制量。当前稿件对“不会即时释放”已经诚实，但仍需要解决其对前台延迟上界的影响。对应 **A04、A16**。:chatgpt-content-reference{index="66"}

**需要记录的时序：** 预算下降、停止新预留、不可回收字节、前台 admission stall、首次物理释放和达到目标占用的时间。只有画出目标预算曲线是不够的。

### 场景二：Peer 是本地的，但接管目标成为最慢的资源

三个已加载相同模型的 DP 中，DP0 的请求预绑定到 DP1。故障发生时 DP1 有大量前台请求，DP2 相对空闲；DP0 上多个请求同时重试。

固定路由确实让 Peer 副本成为本地数据，却不能保证 DP1 有计算、恢复缓冲或完整活跃 KV 空间。等待 readmission 的时间可能大于省掉的传输等待，并且拖慢未故障工作流。改去 DP2 又意味着原 Peer 不能继续按“本地 HBM”估价。对应 **A09、A11**。:chatgpt-content-reference{index="67"} :chatgpt-content-reference{index="68"}

**需要的设计选择：** 明确什么时候等待本地 Peer、什么时候迁移、迁移后如何重新估价，以及谁负责刷新目录和保护策略。

### 场景三：Peer 更新领先于 DRAM，源在发布中间失效

设 DRAM 的可恢复前缀为 \(k\)，Peer 的若干低层块已复制到 \(k+64\)，但其他层、selector 状态或某个 shard 尚未达到该位置；源又已经产生了更长的输出。

此时不能仅取“最新副本位置”作为全局恢复前沿。正确做法可能是回到 \(k\)，或依据非均匀覆盖执行明确的补算；两者都需要可用 token 日志和一致的状态定义，而且真实 replay tail 可能显著长于策略预测。对应 **A02、A03、A11**。:chatgpt-content-reference{index="69"} :chatgpt-content-reference{index="70"}

**这不是对某个未见实现的 bug 指控。** 它说明独立提交、前沿估计和恢复成本三个组件之间，目前还缺一个可检查的共同契约。

---

## 五、最小但有说服力的评估矩阵

### 1. 最低配置与比较原则

无需为了匹配图 2 的每个大模型点都采购相应硬件。一个有说服力的最小原型可以先覆盖：

**一个 dense 后端、一个真正支持原生稀疏选择与状态恢复的后端；两个独立故障域中已加载同模型的 DP 用于实际接管，三个 DP 用于检验目标失衡与重路由。** 若完整稿主张 TP 支持，则还需覆盖 TP group 中的故障语义；否则明确把实测结论限定在已验证配置。

所有核心比较应使用相同请求、故障时刻、故障源、模型配置、物理资源、DRAM 容量、HBM 配额及带宽限制。**无故障运行也是配对基准，不只是另一个吞吐柱状图。**

下面的标记含义是：

- **A：** 文稿、公式、图表或既有数据重析，无需新硬件。
- **B：** 必须新增运行或测量，可使用现有 CPU/GPU；不等于必须购买硬件。
- **C：** 必须先作重大设计决策，再验证。

### 2. 评估矩阵

| 要回答的问题 | 最小基线与消融 | 负载、故障及压力条件 | 核心指标与判定 | 类型 |
|---|---|---|---|---|
| **状态是否真的可恢复？** | 无故障原生执行；全量可靠 checkpoint；AegisKV | prefill/decode；块边界；复制/提交/发布中途失效；已有输出确认 | token 前缀不丢失、无未提交读取、选择与状态一致性、引用无泄漏、合法恢复前沿 | **C+B** |
| **工作流策略是否改善真正的 WCT？** | 重算；优化 DRAM；相同后端上的 slack-blind Peer；AegisKV | 已知依赖的 fork–join、嵌套工作流、串行负例；一个真实带依赖日志的 agent workload | 配对 \(\Delta WCT\)、受影响与未受影响工作流的分位数、吞吐、SLO 达标率 | **B** |
| **收益来自 workflow 信息还是数据路径？** | 至少做“slack 开/关 × 热块按需恢复开/关”；固定与自适应深度 | 固定资源、固定故障序列 | 各组件边际收益与交互；不能由更多备份字节解释 | **B** |
| **slack 预测是否值得使用？** | 零 slack、简单历史统计、GBDT、oracle；小 DAG 最优分配 | 按 workflow/时间切分；未知 DAG、时长漂移、工具延迟、资源争用 | 秒级误差、错误安全判定、fallback 占比、决策 regret、最终 WCT | **A+B**，预测训练/测试也属于新增实验 |
| **热块和层深是否有效？** | recency、frequency、oracle 热集；深度 0、固定值、最佳固定值、自适应 | 多 context/tail；短请求；工具返回后分布突变；接近 dense-union 的负例 | 字节覆盖→暴露等待→WCT 的对应关系；深度选择 regret；后续 TPOT | **B** |
| **同一 worker 的并发恢复是否击穿模型？** | 环形预绑定；负载感知分配/重路由；同数据路径 | 同源多个请求同时失效；目标忙而其他 DP 空闲；共享 host/NIC 限流 | readmission、copy 排队、batch 拖累、恢复公平性、未故障请求损失 | **C+B** |
| **缩容与 DRAM 回退是否有界？** | 固定 Peer 预算；现有不可撤销引用方案；选定的修订方案 | 长请求、热集合变化、DRAM 满、前台突增、复制积压 | 目标/实际/不可回收/在途字节，回收时间，准入停顿，队列是否有界 | **C+B** |
| **无故障时是否值得运行？** | 完全关闭保护；DRAM-only；完整 AegisKV | 稳态与突发到达；低到高负载；长 prefill 与短 decode 混合 | TTFT、TPOT、吞吐、CPU/控制开销、复制流量、commit lag、实际 HBM 税 | **B** |
| **动机和模型能否复核？** | 全部保留组与每 workflow 最大值；不同采样口径；静态估计与少量实测校准 | 筛选、带宽、尾长、共享瓶颈和 context 外推敏感性 | 可复现样本计数、置信区间、模型误差与排序错误 | **A+B** |

### 3. 基线不能弱化到只剩“全量串行 DRAM”

**必须具备的主基线**是：重算、带层优先与重叠的异步 DRAM 恢复、以及使用相同数据路径但不利用 slack 的 Peer 分配。仅与图 5(a) 的 token-block order 比较，会把数据布局改进与工作流价值混为一谈。

已有系统比较则应遵守边界：DéjàVu/LUMEN 的机制可作为匹配后的系统或策略基线；GhostServe 需要对齐其状态恢复与完整接管的差别；KVFlow/TOPAS 本身不是故障恢复系统，若借用其策略，应标为“在共同恢复后端上的适配策略”，而非声称原系统直接支持本实验故障模型。:chatgpt-content-reference{index="71"}

### 4. 可证伪性要求

评估应允许核心假设失败，而不是只设计能获益的条件：

- 当 slack 预测较差、DAG 不完整或所有请求都近似关键路径时，AegisKV 可能没有工作流收益。
- 当优化 DRAM 已能掩盖传输，或稀疏需求并集接近全量时，Peer 热块可能不值得占用 HBM。
- 当目标拥塞、引用长期不能回收、风险先验很低时，正常服务代价可能超过预期故障收益。

这些情况不必全部“战胜”，但必须报告边界和回退行为。样本应按工作流/故障运行计数，不把同一轨迹的大量 snapshots 当成独立样本；报告重复运行、种子和区间估计。完整稿应展示**为什么在预先声明的目标范围内值得使用**，而不是追求所有图都正向。

---

## 六、五个最有价值的英文改写或图表重构建议

##
