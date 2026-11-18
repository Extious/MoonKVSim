### 3.5 KV Master: Workflow-aware Tiered Placement

本节按 **请求紧迫性与块需求 → 跨请求信用 → 固定配额 Peer → 在线执行** 展开。先解释一个请求为何重视某块，再讨论跨请求复用；下层用租金保留长期价值，Peer 用简单的请求级准入提供快恢。

#### 3.5.1 Slack- and Access-aware KV Priority

**同一个 KV 位置，对不同请求的意义不同；同一个请求，对不同 KV 的需求也不同。** 前者用请求的恢复紧迫性表示，后者用逐层块的访问概率表示，两者相乘形成排序信号。

令 R 为当前放置下的预测恢复延迟，包含实际 owner 的读取、H2D、尾部 replay 与队列；s 为 Tracker 发布的 guarded Slack：

\[
u_r=\frac{[R_r-s_r]^+}{\max(R_r,\varepsilon)},\qquad
P_{r,l,b}=u_r\widehat p_{r,l,b}.
\]

当 R>0 且 s=0 时紧迫性为 1；Slack 足以覆盖 R 时，该恢复紧迫性为 0。它是排序权重，**不是精确可加的 WCT 收益**。无效 Slack 使用零 Slack；普通复用价值在下一节单独加入，不因 s 较大而消失。

**请求内部先不讨论跨请求 reuse。** Dense attention 中，同一层所有因果可见的历史块都会被后续 Query 读取，访问因子均为 1；不能因为前面的块出生更早、累计次数更多，就赋予更高未来价值。这不意味着不同大小、层或传输路径的对象成本相同。

Sparse attention 使用最近一段已完成 Query：

\[
\widehat p_{r,l,b}=\frac{\text{选择了该块的 Query 数}}{\text{该块已存在且因果可见的 Query 数}}.
\]

一个 Query 跨 heads 对物理块去重。分母在 selector 剪枝之前定义，不能只数已进入候选集合的 Query。40/200=0.2 与 15/30=0.5 的例子说明，原始次数会颠倒排序。新块采用校准的 layer prior 平滑，防止 1/1 立即成为最热块；必需 selector/辅助状态按依赖保留，不依赖低频统计。这里的近期概率是未来需求估计，不保证未来或 replay 一定命中。

![Slack 与单位容量保护收益的关系](figures/preview/retention-value.png)

**Figure 7：Slack 不是完整的收益排序。** A 用 2 单位容量将恢复 4→2 s，Slack=0，节省 1 s/unit；B 用 1 单位容量将恢复 18→8 s，Slack=6，节省 10 s/unit。这个构造例支持下层考虑代价/字节，也揭示后文仅按 Slack 准入 Peer 的简化边界；不能将其用作贪心策略最优的证据。

#### 3.5.2 Renewable Credit with Lazy Updates

**再把单请求优先级延伸到跨请求复用。** 不同 Agent 对同一物理对象贡献不同份额，信用相加、容量只算一次；同一 Agent 的新一轮实际使用刷新自身份额，不累计多个相同价值。Agent 身份包含 workflow instance，不能把所有同角色请求算成同一个使用者。

下层 pool j 的当前 grant 为：

\[
g_{a,x,j}=v^{\mathrm{reuse}}_{a,x,j}+\lambda_f c_{a,x,j}P_{a,x}.
\]

普通复用项由因果历史估计的 next-use 概率乘以所避免的服务开销得到，独立于 Slack；故障项使用同一决策 horizon 的风险权重 λ_f，以及从当前层移除对象后增加的服务工作 c。DRAM 对应额外 storage 读取，storage 最后副本对应重建。依赖组成本按字节分摊，不能给每块重复授予整个请求成本。多个 Agent 的信用合计表达竞争需求，不等于多个分支共同失败时的精确 WCT 之和；join 仍取最大值。

一次打分无法反映新的使用者，每次 checkpoint 又重新授信会保留陈旧状态。因此参考 Landlord/GreedyDual-Size，将当前 grant g 与已付租金 d 分开：

\[
C_{x,j}=\sum_a[g_{a,x,j}-d_{a,x,j}]^+,\qquad
H_{x,j}=\rho_j+C_{x,j}/b_x.
\]

ρ 是各 pool 独立的容量压力时钟，增加 δ 时扣 min(C,bδ)，按正余额比例分摊到 Agent 份额，不按墙上时间收费。所有已提交 resident 都计租，包括带物理 lease 的对象；可否删除是另一个条件。真实 reuse/恢复使用只续租当前 Agent，以 object＋request/use ID 去重；attention 观察只更新需求统计，价值变化、checkpoint 增长和迁移保留已付租金。Tool wait 可以保留仍有效的复用兴趣，过期兴趣移除。这个结构明确使用 recency、需求和 Slack，并不宣称严格包含所有 LRU/LFU 策略。

**Lazy refresh 分成三层。**

1. **统计层：** 每层维护 Query 计数，块的首次可见位置和窗口边界决定机会数，不逐 token 更新所有块分母；仅更新被原生 selector 选中的物理块。有限 Query buckets 随窗口到期删除旧计数，按 checkpoint 批量发布。Dense 不需要逐块 attention 计数。
2. **估值层：** Slack 变化只更新请求标量与版本；块在使用、准入/淘汰候选或轮转扫描时才读取最新概率和 Slack。先结算此前租金，再刷新 grant，已付部分保留。两次 materialization 之间已发布 grant 固定，保证全局压力时钟可懒结算。
3. **排序层：** 不能只刷新旧 heap 顶部，就声称找到了全局最小值。每轮在固定工作预算内刷新 q 个低 key 候选和 q 个轮转候选，再选择受害者；持续轮转最终覆盖未被访问的对象。这是近似选择，必须与 eager 全刷新比较，而非宣称任意动态值下排序完全精确。

复杂度随实际选择 ID、检查的候选和 Agent 份额增长；heap 操作为 O(log 对象数)，不声称整条流程 O(1)，也不需要导出完整 attention matrix。Figure 10 在本节的信用例子之外不承担性能证明。

#### 3.5.3 Greedy Peer Protection

**Peer 不收租金，固定 L/K/Z，只做请求级准入与热块替换。** 对每种兼容模型/layout，离线校准选定前 L 层、每层 K 块及 checkpoint 间隔 Z，正式测试前冻结。线上块身份可以变化，但不逐请求重新搜索 L/K。引擎物理 block size 与 Z 分开；64 tokens 是某些测量的单位，不是统一要求。

每个 Peer slot 的固定配额是最多 LK 块加单独预算的必需状态。短历史可能不足 K，共享对象只占一份物理空间，因此应写“固定配额”，不能说所有请求始终占同样的实际字节。

![固定 L/K 下的互斥三层 KV 分布](figures/preview/sparse-recovery.png)

**Figure 8：一个请求的对象在哪一层。** 示例固定 L=2、K=2，前两层各有两个 Peer 块，其他格子分布于 DRAM/storage；执行工作 KV 独立于受管三层。Layer 1 的 B0/B1/B2 分别走 Peer 命中、DRAM H2D、storage read＋H2D。虚线尾部尚未提交。稳定态每对象一个 owner，三层并集完整；热集替换及淘汰都要完成真实迁移，不能直接删除唯一 Peer 副本。

Peer 的顺序规则是：

- 使用 Tracker 截断后的 guarded s=0 作为候选条件，包括运行中 Slack 降到零的请求；不是对未处理浮点预测做相等测试。
- 已准入请求每层按概率选 K 块，平局按 recency、block ID；所有必需状态必须有覆盖，不因预测冷而丢失。
- 请求完成或进入 tool handoff 后，该 slot 可淘汰。新准入和 Adapter shrink 先回收这些 slot，再按当前 Slack 从大到小回收活跃 slot。
- 普通准入遇到同为零 Slack 的 incumbent 时保留已有请求，新请求等待 Peer，并继续使用下层保护；强制 shrink 的活跃平局按最久未发生 request use 处理。
- 活跃 slot 是策略上的保留偏好，不是不能撤销的逻辑锁；实际 read/copy lease 必须等释放。共享对象仍被保留 slot 使用时不释放，一个 sole owner 不能同时算作不同 DP 的本地命中。

**Overlap 用来解释离线选择，不再驱动逐请求在线 L 搜索。** M 是已提交历史，N 是之后的未提交尾部。三层中的历史避免重建，执行 N 又能遮盖后续层读取；Peer 额外减少的是暴露读取/H2D 等待。L/K 要在声明的 M/N、带宽和负载校准集合中选择，并在不同测试工作流上检查泛化，不能将一个示例的 L 称为普遍最优。

![显式包含 storage read 的三层恢复流水线](figures/preview/recovery-pipeline.png)

**Figure 9：同一覆盖下区分读取、H2D、计算和暴露等待。** 32 层、32K 历史、64-token replay，共 1,024 MiB 独特历史；(a) 串行读取完整 KV 后执行，(b) 完整 KV 按层流水线，(c) 每层预取 336 块、按需补 64 块，(d) 相同稀疏需求，将前 7 层的 336 块移到 Peer。前三种 DRAM/storage 各 512 MiB；最后 Peer 147 MiB，DRAM/storage 各 438.5 MiB。Replay 沿用已存在 MiniCPM4-8B 的每层均值 2.870 ms；storage/H2D 3.125/6.25 GB/s 为假设，336/64 是构造需求，非原生预测实测。新层 demand 在上一层完成后才暴露。完成/等待分别为 266.3/174.5、177.4/85.5、186.9/95.1、171.9/80.1 ms。**(c) 比 (b) 更慢的结果保留：预测 miss 的临界路径与非抢占队列可能抵消少传字节的收益。** Peer 对相同稀疏需求减少约 15.0 ms 等待，但这不证明端到端收益或 L=7 最优。假设独立 I/O、足够 staging/workspace、无前台竞争，迁移已在故障前完成，cold KV 不影响所画 replay 终点。

#### 3.5.4 Online Three-Tier Management

Prefill 提交已封闭块；decode 每固定 Z tokens 复核；请求完成/tool handoff 提供最终短 snapshot。真实 use、Slack 变化、容量变化、传输完成/失败也驱动同一事件循环。新对象建立产生它的 Agent 的初始信用，已有未变前缀不因 checkpoint 增长重新授信。

**下层准入与淘汰。** 空闲空间可以准入零信用 state；有压力时刷新候选，试收足以让某个合法受害组信用归零的租金，incoming 同时支付这段试租。Incoming 归零则从该层延后，DRAM 不准入时可尝试直接到 storage。已提交对象归零只进入可淘汰状态，需要容量时才迁移。DRAM 被淘汰对象传往 storage，其 retention credit 独立估计相对重建的价值；storage 最后副本只能在所有受影响 manifest 已发布有效旧 checkpoint/输入日志 replay fallback 后删除。

**Peer 和下层连接。** 请求 slot 的迁入、迁出以及热块替换可触发 Peer→DRAM→storage 级联。必须先找到安全目的地并预留实际字节，无法完成时等待；不能把 quota 下降当成显存已经空出来。每个 lower pool 保留自身已付金额，离开时停计，往返不清零。

**Algorithm 2：Online three-tier management**

```text
ReconcileTransfers(e); PublishSignals(e)
RecordNewBlocksAndUses(e)
Q ← LowKeysAndRotation(q)
for x in Q while WorkLeft():
    SettleRent(x); RefreshGrantAndKey(x)
P_D ← LowerTierAdmission(e, Q)
P_H ← PeerSlots(s, B, L, K, e)
P ← PrepareCascade(P_D, P_H)
if P is empty:
    Defer(e); return
if not ReserveIfCurrent(P):
    Requeue(e); return
Submit(P)  // completion/failure emits a new event
```

Connector 复制、确认目的端、切换 owner，最后等待旧 readers 排空再释放源；暂存的双份都计容量。拒绝试算不改真实租金与 owner；成功的容量交接提交试算租金和 incoming 剩余信用。完整依赖覆盖后才推进 M，copy lag 可能导致 N>Z。受保护的 source failure 须保留所有 owner 可达，额外 sole-owner loss 则回退。可执行性检查不再冒充全局 WCT 最优搜索；动态值、依赖和有界刷新也不继承 Landlord 竞争比。

![共享 DRAM 对象的续租与价值更新](figures/preview/renewable-credit.png)

**Figure 10：为什么使用不等于价值更新。** 单位大小 DRAM 对象，A/B 初始份额 3/2，收租 2 后为 1.8/1.2。A 的 grant 更新到 4 时，保留已付 1.2，剩 2.8；A 真正发生新 use 后才续租到 4，B 仍 1.2。Lazy materialization 必须先结算旧租金再更新 grant。它是信用记账示意，不是性能结果，Peer 不在该租金时钟中。

**支撑设计的验证边界。** 访问概率需在未来 Query 上与原始次数比较，控制块年龄和预算；Lazy 需对照 eager refresh 的淘汰偏差、WCT 与 CPU；固定 L/K/Z 需隔离校准/测试，比较相同 slot 的 FCFS、Slack、恢复收益排序和可变深度参考；租金需在相同估值、候选机会与工作预算下，对照 direct revaluation、普通 GDS/Landlord 和去续租/去压力 aging/去共享份额。原 462.96/506.39 反例继续保留。已有 KVFlow 等工作已使用工作流关系，新颖性不能写成“首次使用 Agent 依赖”。这些是待验证的设计取舍，不因文字与图像修改而变成已完成实验。

