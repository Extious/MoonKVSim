#### 3.5.3 Online admission, direct revaluation, and eviction：容量不足时直接比较当前方案

**采用直接价值重估。** 请求到来、封闭块产生、配置的 checkpoint 间隔、工具切换、重要画像变化和容量压力触发决策。每次使用同一个版本化快照，包含 DAG、需求摘要、committed copies、队列、lease 和容量账本；仅在依赖版本不变时复用估值。当前控制器不再维护租金水位、历史 credit 或 renewal。Tool 等待本身不会删除历史；正常复用价值始终参与评价。

这是当前算法选择，不代表已经验证全局最优或运行效率。Evaluation 保留租金作为比较过的替代策略：简化模型中，租金没有减少替换价值比较次数，累计代价反而更高。这一结果不能替代新控制器的完整 DAG、CPU 与端到端验证。

**先构造合法来者和可安全移除的对象。** 来者可以是提升到 DRAM 的合法块组，也可以是推进完整 checkpoint 所需的封闭块及其依赖。安全集合 Q 排除正在被物理读 lease 使用、有未完成复制依赖、或没有合法后继状态的对象。活跃请求的逻辑所有权不永久锁住具体物理位置。共享对象按实际副本计一次容量，所有 owner 的影响一起进入方案估值。

对每个来者，在私有快照中构造受害者方案。按稳定对象 ID 和持久游标，在受影响存储层轮转扫描有界数量的安全对象；对每个可执行移除动作，直接计算当前新增代价／该层可释放字节。每轮追加损失密度最小者，平局比较搬迁字节、再比较对象 ID；追加之后按已变化的临时方案重新估值后续受害者，直到空间足够或工作预算耗尽。下次从游标后继续，避免每次只检查相同前缀。有限扫描会漏掉更好的方案，不声称最优。

DRAM 降级若需要额外 storage 空间，按同一规则先构造下层 relief；storage 的最后副本删除必须有有效 fallback。所有下层受害者、copy 依赖、fallback 改变都属于同一个方案。临时移除方案也必须能在实际空间与预留约束内调度；复制来者要等受害者真正释放空间。无法在工作预算内构造可执行方案时，跳过该候选。损失／字节用于构造受害者集合，最终判断使用完整 DAG 的方案代价，不能把独立块收益相加。

![直接重估完整替换方案](figures/preview/placement-competition.png)

**本图解释直接重估，而不是历史扣租。** 构造的等大小、可加成本例子中，提升 x 节省 6 秒；降级 y 或 z 分别增加 2 或 5 秒；任一方案的迁移代价为 1 秒。因此两种完整方案的 ΔJ 分别为 −3 和 0 秒。有 read lease 的对象即使代价更低，也不进入安全受害者集合。若不确定性与滞回门槛合计小于 3 秒，第一种方案可进入资源预留；它不意味着空间已经释放。实际共同故障使用完整 DAG，不能套用示意图中的可加假设。

**每次选择一个完整方案。** 在已评估方案中选择 ΔJ 最小者，平局选择搬迁字节更少者，再按稳定对象 ID。可选迁移要求预测改善超过配置的不确定性余量和迁移滞回门槛；没有经过校准时，这只是启发式保护，不是统计置信上界。拒绝不改变放置和真实容量；接受前重新核对版本，并为立即可执行的动作预留目标和 transfer workspace，按依赖排队执行。已有迁移完成或失败后重新读取快照，不能继续使用旧状态下的计划。

容量强制收缩时没有来者。按当前损失规则逐步构造可执行 relief，达到目标前可以接受正代价；storage 先检查无 owner 或已被完整替代的对象。仍需删除活跃 checkpoint 最后副本时，先发布不依赖被删对象的完整旧 manifest 或 prompt＋存活 token log 回退，等待旧读者排空后才删除。没有安全方案时暂停新准入，保持当前 frontier，并在后续事件继续搜索。

正文 Algorithm 1 的流程为：

```text
on review event:
    snapshot versions, copies, queues and byte ledgers
    refresh causal demand and affected placement values
    if capacity must shrink:
        construct a safe current-loss relief plan
    else:
        form bounded legal sparse/layer candidates
        for each candidate within the work budget:
            construct victims by current loss per released byte
            include lower-tier victims and fallback changes
            skip infeasible plans
            evaluate the complete plan through the workflow DAG
        choose the lowest-cost plan that clears both margins
    if no plan qualifies: retain placement; pause admission on pressure
    recheck versions; retry from a fresh snapshot on mismatch
    reserve executable space and enqueue dependent transitions
on completion/failure:
    reconcile actual state and trigger a new review
```

画像缺失或过期时暂停可选提升，必要容量回收使用相同安全协议下的有界 LRU。候选构造、受害者比较、I/O 画像和完整 DAG 遍历都计入工作预算。报告实际决策开销、预算限制造成的损失以及最终 WCT，不能将旧简化模型的 scalar checks 称为完整控制器的 CPU 测量。

