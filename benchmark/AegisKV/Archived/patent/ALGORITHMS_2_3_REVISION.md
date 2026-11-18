# AegisKV 算法 2、算法 3 修订技术交底（Revision 3）

日期：2026-09-06。本文是本次修订的技术定义，替代原交底中 **SlackLandlord 逐块 credit 准入、永久封闭落后 tier、HBMQuotaAIMD 配额选择** 的对应段落。原 DOCX、条款转录和哈希保留为历史输入，不能当成新算法的实现证明。

**实现范围：** 已提供可执行的串行事件参考实现 `prefix_frontier.py`、`foreground_budget.py` 和 `revision_runtime.py`，以及边界/有界枚举测试。参考执行器明确执行组准入、复制确认、可见状态切换、回收确认、共享前缀和前台配额协议；它不执行 CUDA 数据复制。现有 Mooncake C++/vLLM 集成、MoonKVSim `mooncake_prompt_v1` 大规模 DES 路径和 170 次历史实验仍是旧算法。本文没有把新算法包装成已经完成实机验证的版本。

## 1. 对三个问题的直接判断

### 1.1 后插入的尾块不一定拥有最高阈值

旧规则是 `H(c) = L_at_commit + A(c)/bytes(c)`，credit 与该阈值还不是同一个量。后插入只意味着插入时租金不低；**不意味着单位字节收益更高**。例如，同样 1 单位大小，前块 `L=0, A=10, H=10`，后块 `L=1, A=1, H=2`。Slack 更新、不同大小的尾块、加载启动开销和恢复路径变化还会改变边际损失。因此，“尾块达到驱逐条件时前块必然都达到”的结论需要额外的单调性条件，现有算法没有这些条件。

但问题指出了一个实际的设计负担：旧算法保存大量历史 credit，却必须遵守前缀依赖、动态重算损失和共享物理容量，经典文件缓存分析不能直接适用。修订版**删除所有逐块历史 credit 和 rent**。保留对象元数据和前缀关系；按当前状态计算合法删除闭包的收益损失，不再保存隐藏前驱的历史分数。

即便某个静态例子满足阈值单调，删除尾块后也必须重新计算“再缩短前缀”的损失，不能一次性推断整条请求都没有保留价值。

### 1.2 正在生成的请求可以暂停保护，但不能永久停止

当前请求的续写组若没有比释放相应空间的损失更高的收益，本 tier 可以返回 `PAUSED`。这只暂停备份，前台推理继续。后续触发重评估的事件包括：新块完成、其他请求完成/释放、Slack 或恢复成本改变、复用引用加入/离开、额度增加、传输许可恢复、目标或路由改变。

“现在尾部最低”不能推出“以后所有块都不应备份”。未来组可能跨过加载启动成本，也可能出现空闲容量或更重要的复用请求。拒绝状态不设置永久封闭位；下一次从**当前已提交连续前缀的第一个缺口**重新构造组，不跳过缺口。只能补主副本仍可读且已完成的 KV；源已驱逐/失效时，等待合法重算产生，不假装缺失块存在。

在固定成本、固定竞争集合、无新增空间，且任意允许续写组的收益上界都不超过其驱逐损失的条件下，继续暂停是正确的局部决策。这个条件随事件重新判断，不跨未来负载无条件沿用。

### 1.3 多轮复用必须分离逻辑消费者与物理副本

不是每一轮都为同一前缀重新生成一份保护对象，也不是把上一轮的 credit 转给下一轮。修订版用内容寻址前缀树管理物理对象，用稳定的 `(workflow, agent, round, request)` 标识管理消费者。一个实际调用只能注册一个消费者；同一消费者重试是幂等更新。不同轮次是不同消费者，旧轮完成后不继续累加活跃恢复收益。

同一目标、同一 tier 中已有兼容的 COMMITTED 前缀时，新消费者关联它即可：不重复复制、不重复计费，立即按所有活跃消费者重算损失。共享页面被删除时，必须一次性计算所有受影响消费者的前缀缩短；释放一个逻辑引用不等于释放页面。不同目标或 tier 的副本仍各自计费；仅有相同文本但没有相容可读副本时，仍需正常准入和复制。

## 2. 状态、身份和作用域

| 状态/参数 | 精确定义 |
|---|---|
| 物理对象 `k` | 一个已完成、不可变的 KV 页组；有 bytes、shards、parent 和内容标识 |
| namespace | 租户共享域、模型及权重版本、adapter、KV ABI/dtype/layout、并行分片方式；非 token 输入也必须纳入身份 |
| content ID | 对 namespace、父块内容 ID、当前 token 序列及必要输入身份作稳定摘要；不能只用 token 文本或 ordinal |
| pool | 一个 tier 的一个物理目标；源故障域和目标故障域须满足保护要求 |
| `C_r` | 本 pool 已提交、允许恢复的新读取集合，关于 parent 前缀闭合 |
| `f_i(C_r)` | 消费者 i 在 `C_r` 内的最长兼容连续前缀长度 |
| `P_r` | 正在复制的组，尚不可恢复；参考执行器每 pool 最多一组 |
| `R_r` | 已撤销、正在取消/物理回收的对象；不能新读，但尚计入物理占用 |
| 恢复读 lease | 已预留恢复主 KV 后获取的有界源读取租约；正在读的源不能直接 free |
| 源复制 lease | 源 worker 保持已完成 KV 在复制完成/取消确认前可读；由数据面适配器执行 |
| 保留 lease | 已结束轮次的可淘汰前缀引用，权重为零，具有字节上限和 TTL；不保证下一轮命中 |
| `epoch` | 本 pool 的值/路由/消费者/可见性变化版本；提交时检查，不用墙钟替代版本 |
| `Q_r, S_r` | 实际授权保护额度及其中的临时复制储备；`S_r` 不是额度之外的额外空间 |
| `G_max` | 单次连续候选组上限；还受 `S_r`、路径预算、源可读范围和有效期限制 |

内容键遵循已有前缀缓存关于父哈希及隔离域的设计原则；这里新增的技术描述集中于保护收益、共享删除闭包、异步替换与前台约束的结合，而非宣称“哈希复用”本身是新发明。[vLLM 官方前缀缓存设计](https://docs.vllm.ai/en/latest/design/prefix_caching/)、[SGLang 论文](https://arxiv.org/abs/2312.07104)。实际接口还必须校验来源、模型、全部分片和布局，不能把摘要相等当成收到数据的证明。

未完成的可变页不共享；发生前缀分叉或对部分页继续写时使用独立页/写时复制，保留已有不可变前缀。滑动窗口、混合注意力或非前缀充分恢复模型，必须另行定义依赖闭包；本算法的前缀证明限于前缀充分的注意力 KV 表示。

## 3. 算法 2：当前前缀价值与成组原子替换

### 3.1 优化目标

对 tier r 定义当前可计算的代理目标：

\[
\Phi_r(C,t)=\sum_{i\in\mathcal A(t)} w_i [T_i^r(f_i(C),t)-s_i(t)]_+ .
\]

- `A(t)` 是去重后的活跃调用集合；未知未来轮不提前计入。结束轮的缓存保留引用权重为零。
- `T_i^r` 含读取、剩余重算和未保护输出的重放成本，取可用恢复方法与完整重算的最小值，因而不会因可选前缀变长反而增加最优恢复成本。
- 同一 pool 内共享对象的物理 bytes 只计算一次；`Phi` 仍对不同真实活跃调用各计一次恢复代价。
- `w_i` 默认 1，若使用业务优先级应预先声明。没有引入未经校准的故障概率。
- `Phi` 是 **tier-local、条件于当前故障的加权调用 harm 代理**。它不是多个分支同时故障后的精确 DAG makespan，也不是故障概率加权的长期收益。CPM Slack 在这里仍然是预测信号。
- HBM 与 DRAM 各自评价和提交，以保留独立保护；跨 tier 的重复保护不能被描述为全局最优容量分配。两条源复制共享真正的源/链路资源预算。

### 3.2 候选组和共享删除闭包

对请求 i，从 `f_i(C)+1` 起枚举最多 `G_max` 个已经完成且源可读的连续终点，得到候选组 X。已有共享 COMMITTED 前缀直接作为起点；复制字节 `b(X)` 只包含新物理对象。有效期须满足：

\[
t+\widehat\tau_{copy}(X)<\min(t_{request\ expiry}-\tau_{residence},t_{permit\ expiry}).
\]

预计时间只是过滤器；实际 deadline 到达仍取消，不能用预计完成代替 ACK。实现需要超时事件，过期许可也必须停止后续 DMA batch。

删除根节点 k 时，合法对象集合是其在 `C` 中的全部已提交后代 `cl_C(k)`。它同时截断所有引用这些对象的消费者，保证不留下不能独立恢复的孤儿后缀。候选依赖的祖先和正在读取的对象不能进入删除闭包。

从暂定状态 `C'` 选取最小密度闭包：

\[
\rho(Z)=\frac{\Phi_r((C'\setminus Z)\cup X,t)-\Phi_r(C'\cup X,t)}{\sum_{k\in Z}bytes(k)}.
\]

每次暂删后重新枚举闭包与全部受影响消费者，直到最终已提交集合满足 `bytes((C\Y)∪X) <= max(0,Q-S)`。同一物理对象在 Y 中去重。最后直接计算：

\[
\Delta(X,Y)=\Phi_r(C,t)-\Phi_r((C\setminus Y)\cup X,t)>\eta.
\]

只有严格超过非负数值/最小收益余量 `eta` 才准入；无需把各块收益相加，也无需逐块收益为正。以最终 Phi 最小、其次复制 bytes 最少作确定性排序。`G_max` 和 staging 上限可能拒绝需要更大组合的正收益方案，这是资源有界近似的明确边界，不宣称最优或对所有前缀都无饥饿。

### 3.3 完整事件算法

```text
OnRelevantEvent(pool, request, now):
  update unique consumer, immutable prefix and current value snapshot
  if a compatible committed prefix exists: attach it with zero extra bytes
  if a copy is pending or physical reclaim remains unacknowledged: PAUSED
  enumerate available contiguous groups from the first missing object
  for each group:
    check source lease, tier placement, copy permits, lifetime and staging limits
    tentatively choose legal shared deletion closures by current loss / real bytes
    evaluate whole final-state harm once; keep only strict improvements
  if no feasible improvement: PAUSED; retry on a relevant state/budget event
  reserve new objects inside Q; leave old C recoverable; mark group COPYING
  submit independently from the source for each admitted tier

OnAllShardsAck(group):
  validate epoch, route, layout, deadline, leases, quota and current improvement
  if any check fails: abort group; retain old C; enqueue fenced group free
  else atomically publish (C minus Y) union X; mark Y RECLAIMING
  do not return physical bytes to the free ledger before per-object FreeACK

OnTimeout/Failure/Cancel(group):
  fence source and destination transfer handles; abort group visibility
  enqueue idempotent reclaim IDs; late transfer ACK cannot resurrect the group

OnFreeACK(object, allocation/reclaim generation):
  require all dependent reads/copies complete or cancellation ACKed
  remove exactly that generation from physical accounting
  ignore duplicate or obsolete ACK; retry remaining tasks

OnRoundEnd:
  remove active recovery value; optionally retain a zero-weight TTL reference
  last reference expiry makes unpinned objects reclaimable; shared users survive
```

TTL 保留不是无限常驻承诺：有活跃正收益请求竞争时，零权重保留对象优先成为低损失 victims。参考实现保留对象总量受 pool 额度约束；生产接入还可加租户保留上限。保留的元数据索引和幂等事务历史应按已终结 epoch 安全压缩；不能无限保存到主进程退出。

### 3.4 为什么普通替换不再制造原先的保护空窗

旧流程先删除 victims 再复制；修订版让新组先占用 **额度内预留的 staging**，旧前缀一直保留到组完成。提交时一次切换元数据，之后回收旧物理分配。物理占用满足：

\[
B_{physical}=B_{committed}+B_{copying}+B_{reclaiming}.
\]

普通准入前检查 `B_physical+b(X)<=Q`。结束后目标 steady 使用量不超过 `Q-S`；回收 ACK 未到时不启动下一组。满池而没有 staging、组太大或读 lease 阻挡时返回 PAUSED，不能声称“无额外内存地原子替换”。紧急前台收缩仍可以直接撤销未 pinned 的保护，并接受 DRAM/重算退路；这个事件不受普通替换不降保护的性质覆盖。

在同一 pool 锁/串行 owner 下，给定不变消费者快照和成功 ACK，提交前后 Phi 严格下降；这不是复制期间的全局工作流延迟保证，也不是经典 Landlord 的竞争比。参考实现使用 eager 重算来验证语义，未把“只暴露尾部”误写成共享树下的全局最小。生产优化需要保持与 eager oracle 等价，再引入树聚合和带版本索引。

## 4. 算法 3：前台约束下的可撤销 HBM 额度

### 4.1 控制目标从 alpha 改成可兑现的 bytes 和复制许可

不再用“连续 K 个无压力窗口就加 alpha”寻找最优点。对目标 p，在前台调度/分配事件之前建立互不重叠的内存预算：

\[
Q_{mem}=\min\{M_{registered}, Q_{policy}, L_{allocator},
[M_{physical}-M_{fixed}-M_{primary}-M_{next}-R_{burst}-R_{allocator}]_+\}.
\]

`M_fixed` 包含权重及不可回收 runtime 空间，不能与 `M_primary` 重复计数；后者包含已分配和已预留的主 KV。`M_next` 是本次将新增的前台预留量，不是总需求。`L_allocator` 是推理引擎实际可借给保护的页面额度；一个无法归还的预分配 KV arena 必须报告 0，不能直接用 CUDA free 替代。

`R_burst` 必须覆盖在**停止新批次 + 当前不可抢占批次结束 + 撤销/释放确认**最长时间 tau 内的额外主 KV 增长。可由调度器对 batch/token 上限、并发准入和每 token KV bytes 求上界；若只用历史分位数，那是经验风险储备，不是确定性上界。`R_allocator` 覆盖碎片/分配对齐和测量误差的已声明界。

新请求入队、prefill/decode step 预留、恢复主 KV 申请、worker 状态改变和超时 watchdog 都触发更新。周期采样用于刷新证据，不能代替前台分配前的同步检查。生效后 `alpha_p = Q_p / M_registered` 只是派生展示量。

### 4.2 内存安全不等于没有推理干扰

Peer-HBM 副本可能通过内存带宽、复制引擎、PCIe/NVLink、NIC、源端读和 CPU/allocator 锁影响 TTFT/TPOT，即便 GPU 空闲 bytes 很多。因此同时限制以下资源：

1. 目标 HBM bytes 和正常替换 staging，统一进入上述预算。
2. 每个源、目标和共享链路的 token bucket。HBM/DRAM 共用相同物理瓶颈 bucket，不能每条路径各算一次“空闲带宽”。
3. 不可抢占的单次 DMA batch bytes 及其最长持续时间。组可以较大，但数据面须拆成小 batch，每批重新检查许可。
4. 前台等待、复制取消、回收锁持有和释放 ACK 时延；不能把后台回收耗时误当成前台分配 stall 来二次惩罚。

若转移路径的源/目标/链路许可之一不存在，则不启动该批。给 DRAM 复制也必须检查源端和共享链路许可；DRAM 不能借“HBM 已关闭”绕过前台保护。

### 4.3 “几乎不影响”的可复现实验定义

默认目标为 `epsilon=1%`，可配置。对无故障、配对相同到达序列/请求内容/输出长度/缓存初态的重复实验定义：

\[
I_{TTFT}=\frac{p99(TTFT_{backup})}{p99(TTFT_{off})}-1,\quad
I_{TPOT}=\frac{p99(TPOT_{backup})}{p99(TPOT_{off})}-1.
\]

TPOT 先按请求计算稳定定义的每输出 token 时间，再求请求间 p99；另记录 token 间延迟分布，不能混用两者。无输出/首 token 特例需固定统计口径。吞吐/goodput 相对损失也不得超过 epsilon，以防通过少服务请求掩盖尾延迟。

**准入条件是三个开销的一侧置信上界均 <= epsilon**，而不是样本均值低于 1%。按独立负载重复/时间块做配对 bootstrap 或声明其他有效方法；不能把同一突发中的 token 当成独立样本。需预先固定置信度、多指标校正、尾部分位数样本量和校准/验证分割。多个候选配置的搜索与最终认证用独立重复，不能挑最好一次作为证据。

认证域绑定硬件、模型/并行、allocator、软件版本、负载区域、quota、复制速率和 batch 大小等联合配置。只有测过并经独立验证的区域支持扩大许可；不能从一个点未经验证外推整片区域。参考 `QoSCertificate` 保存域、上界、配额/速率/batch 限制、释放时限、有效期和证据定位；它是可信校准器的输入接口，非自动生成性能证明的函数。

这是**所测负载区域中的统计目标**，不是对任意未来 burst 的确定性 1% 上界。在线监测前台服务和队列可触发快速撤销，但在线运行没有同时可观测的无备份反事实，因此不能单靠当前 p99 自证 1%。无有效认证、域外负载、样本过期、前台违约或回收界失效时：停止新批次、Q 目标设为 0、有界取消并按 ACK 释放。生产默认没有认证则不借用 HBM；modeled 认证只有显式参考评估模式才允许。

### 4.4 配额决策与确认协议

设 `D` 为当前存活且有正收益的保护总需求（包含值得保留的现有保护、待准入内容及必要 staging，不能只统计新增请求）。在有效域内：

\[
Q^*=\min(Q_{mem},Q_{cert},D).
\]

- 收缩：任何前台事件发现 `Q*<Q`，立即发布较小的目标并暂停可能越界的新复制。采样失效或 QoS 违约时目标为 0。
- 扩张：连续有效稳定时间达到 `T_stable`、有需求、没有未确认回收、实际占用不超过已生效额度时，至多增加 `v_grow * delta_t` bytes，且不超过 `Q*`。采样断档/配置域变化重置稳定计时，不能积累“未观测的稳定 credit”。
- 幂等：报告携带 `(target, controller_epoch, sequence, sample_time, payload)`。相同 ID 相同内容重发同一决策；相同 ID 不同内容拒绝；旧 sequence/epoch 拒绝。参考实现重发最近结果，更旧重试需要查询当前状态，不重新执行。
- 释放：`RECLAIMING` 的 ID 保持可重发。丢失返回、重复 ACK 或部分失败不会使 bytes 提前返回。目标和物理账本不相符时先暂停/对账。
- 恢复：先预留恢复目标主 KV，再获取源读取 lease，避免“pin 住所有备份后等待空闲主 KV”的环。过期 lease 只触发取消请求，**不代表 DMA 已停止**；仍须读结束/取消 ACK。
- 启动前台：检查当前物理占用和全部前台预留满足预算；发布 alpha 不能作为分配成功的证据。未腾出的空间继续由 burst reserve 承担或等待确认，不允许复用未释放地址。
- 重启：新 epoch 从禁止保护开始，盘点 allocation/transfer/reclaim 状态、完成 fencing 后再发许可。控制面 HA 不属于目前参考执行器的实现证据。

AIMD 可保留为历史对照。它并非在所有系统都“不合适”；本问题需要处理不连续的前台内存需求、显式资源预留和可撤销复制，单纯的窗口反馈不能替代这些约束。原 AIMD 的网络反馈分析也不能直接证明 GPU 推理干扰界。[Chiu--Jain 原论文](https://pages.cs.wisc.edu/~suman/courses/740/papers/chiu89isdn.pdf)。

## 5. 可证明的性质与不能偷换的结论

| 性质 | 条件和证明要点 | 不涵盖什么 |
|---|---|---|
| 前缀闭合 | 候选从首缺口连续添加，删除是后代闭包，提交是单 owner 原子可见切换 | 不证明分布式锁或网络分区下线性一致性 |
| 共享计费准确 | 对象以物理键去重，逻辑用户只影响 Phi，回收 ACK 才减物理账 | 不验证实际 KV tensor 内容 |
| Pending 不可恢复 | 只对完整组所有分片 ACK 后发布 C | 不将部分成功字节算作保护 |
| 普通失败不丢旧保护 | staging 在 Q 内，旧 C 保留到成功切换 | 不覆盖硬前台撤销或真实目标失效 |
| 局部严格改善 | 同快照下只提交 `Phi(old)-Phi(new)>eta` 的组，提交时重评估 | 不证明全局最优、长期最优、竞争比或 WCT 提升 |
| 不提前释放 | allocated = committed + copying + reclaiming；陈旧 ACK 不能释放新 generation | 物理设备必须兑现 fencing/ACK 合约 |
| 前台预留不被备份侵占 | 全部内存项真实、互不重叠，allocator 原子预留，Rburst 覆盖回收期间增长 | 经验分位数储备不能证明任意突发安全 |
| 1% 目标 | 有足够统计效力的独立配对校准，认证仅用于有效区域 | 不是无条件确定性零干扰，也不是当前已有实机结论 |
| 有条件进展 | 有可行组、稳定价值/资源、读和复制可终止、ACK 最终交付且重试公平 | 一直过载、不断失效/更新、组超储备或无有效认证时不保证保护成功 |

单 pool 单 in-flight group 是参考实现为了可审计选择的串行化上界；正常请求照常并发生成。优化到多组并发需要每事务独立资源预留、冲突验证、重叠 victims 防重选以及有序可见性提交，不应在论文中先声明并行吞吐已解决。候选/闭包 eager 搜索开销随对象数、活跃调用数和候选上限增长；目前未证实生产规模控制器 CPU 开销可接受。

## 6. 本次可执行验证及接入边界

参考源码：

- [prefix_frontier.py](../../../../python/moonkvsim/aegiskv/prefix_frontier.py)：共享前缀、组准入、复制提交、回收/读 ACK、TTL。
- [foreground_budget.py](../../../../python/moonkvsim/aegiskv/foreground_budget.py)：内存预算、认证域、快速收缩/限速增长、幂等窗口、路径令牌。
- [revision_runtime.py](../../../../python/moonkvsim/aegiskv/revision_runtime.py)：连接两个独立 tier 与前台观测/传输预算的串行事件适配器。
- [测试](../../../../tests/aegiskv/test_prefix_frontier_revision.py)、[预算测试](../../../../tests/aegiskv/test_foreground_budget_revision.py)。

从项目根目录：

```bash
PYTHONPATH=python uv run python -m pytest -q \
  tests/aegiskv/test_prefix_frontier_revision.py \
  tests/aegiskv/test_foreground_budget_revision.py
```

覆盖：零收益首块与有收益组、缺口不可跳过、暂停后恢复、多轮共享及分叉、最后引用释放、TTL、复制失败保留旧状态、部分分片 ACK、迟到 ACK、回收重试及 ABA、路由/Slack/完成/读 pin 更新、配额收缩取消、过期 read 不等于可 free、burst 前台预留、采样缺失/过期、未知校准域、重复/乱序窗口、物理债务及共享带宽预算。另枚举小规模收益组合与内存需求，对提交后的目标函数和容量界作独立检查。

现有 Mooncake/完整 DES 接入仍需满足以下接口，不能因为参考测试通过就标成已经完成：

1. 推理 allocator 提供真实可借页额度和分配前同步 hook；单次 copy/reclaim 的取消和 ACK 有界。
2. Router/connector 使用共享内容身份、每 tier 独立可重试 frontier；实际完成页和源 lease 接入。
3. native Controller 替换 rent/heap 与立即释放账本，接入 staging、共享后代闭包及回收 generation。
4. 在 burst、steady high load、长 prefill、持续 decode、恢复与重用负载下校准 TTFT/TPOT/goodput；取得有效证据后才能启用 HBM 认证。
5. 重新冻结执行源码与匹配工作负载，生成新实验。170 次旧实验及 4090 pilot 不改写成新算法结果。

## 7. 建议写入专利技术方案的核心关系

技术交底以以下组合关系展开：利用工作流 Slack 为活跃调用构造 tier-local 恢复损失；根据共享物理前缀的后代删除闭包计算当前联合损失；从首缺口构造成组候选，在授权额度内预留复制储备并经完整确认后原子切换可恢复集合；利用前台资源预留、可验证回收界和负载域内干扰上界限制目标容量及源/目标/链路复制许可；由带 generation 的取消/释放确认实现保护内存向前台的可兑现归还。

优点应写成有条件且可检验的机制效果：避免按块独立评价遗漏有收益的前缀组合，防止共享引用重复计费，在普通复制失败时保留原可恢复前缀，防止未确认回收空间被重复分配，并使备份资源选择受明确前台约束。不要写“最优 alpha”“所有 burst 零开销”“一定降低工作流延迟”或“任何评审都无法质疑”。本文是技术说明与实现契约，没有作专利新颖性检索或授权结论。
