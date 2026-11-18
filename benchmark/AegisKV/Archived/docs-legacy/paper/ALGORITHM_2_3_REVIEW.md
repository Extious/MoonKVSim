# 算法 2 / 算法 3 的设计与实现审查

2026-09-06。对象为当前正文的 SlackLandlord、HBMQuotaAIMD，Mooncake native Controller / Worker，以及论文实际使用的 MoonKVSim 运行器。本次只做审查和有界复现，没有修改算法、论文正文或既有实验结果。

判断：两个算法的核心职责划分成立，但当前版本还不足以支持“异步故障下协议完备、稳定控制、整体收益充分论证”的强结论。优先级应是回收与反馈协议的正确性，其次是准入目标和前缀决策，最后才是调参。

## 1. 结论与优先级

| 优先级 | 问题 | 证据等级 | 建议 |
|---|---|---|---|
| P0 | 配额回收先删除 Controller 元数据，物理删除失败后，后续窗口不重新返回旧 victims | native 有界复现 + Worker 路径检查；未做真实网络故障试验 | 为物理回收保留任务和 ACK，分离逻辑失效与物理释放 |
| P0 | 同一压力窗口重复调用会重复乘性缩减 | native 同时刻双调用已复现 | 每 target 使用 epoch/window ID；重复请求返回同一结果，旧窗口拒绝 |
| P0 | 恢复读保护在 native 与模拟间不等价 | 源码确认，跨进程竞态未执行验证 | 统一可回收判定与恢复 lease；明确取消、超时及重算 fallback |
| P1 | 零收益首块被拒绝，阻止到达整体有收益的连续前缀 | native 构造输入已复现 | 对少量连续块作成组准入，并维持全组提交前不可恢复 |
| P1 | 准入比较的是立即故障 harm，没有正常期干扰、复制完成机会和保护空窗的控制约束 | 源码与公式确认；尚无新策略效果试验 | 增加复制预算、pending 上限和完成时机约束；先避免引入未经校准的故障概率 |
| P1 | 压力信号可能测到自身回收耗时，且 CUDA free 不等同于引擎空闲 KV slots | 可选路径源码确认；实际影响待测 | 标记操作来源，分离前台分配失败与后台操作耗时，引入有效样本与滞回 |
| P1 | 只要连续无压力就增加配额，没有需求门槛、执行 ACK 和完整的时间尺度定义 | 算法确认；振荡幅度待测 | 按稳定持续时间和保护需求扩张，以实际可用容量约束生效配额 |
| P2 | Landlord/AIMD 的经典性质不能直接成为当前系统的证明 | 原论文模型与当前问题不同 | 补充不变量、局部性质、反例和有界状态检查，而非宣称继承全部保证 |

## 2. 本次真正执行的三个反例

使用未经修改的 Mooncake `aegiskv_controller.cpp` 与公开 header 编译小型 C++ 程序；不使用模拟策略替代 native 实现。

- [复现程序](../../experiments/results/algorithm-review-20260906/native-probe.cpp)
- [结果](../../experiments/results/algorithm-review-20260906/native-results.json)
- [编译命令、源码指纹与证据范围](../../experiments/results/algorithm-review-20260906/EVIDENCE.json)

### 2.1 单块贪心无法跨过零收益前缀

设完整重算 100 ms、Slack 为零、空闲 DRAM 足够。第一块的 tier recovery estimate 为 100 ms，故 gain=0，被 BYPASS。第二块若加入连续前缀可使 recovery estimate 降为 80 ms，但 ordinal=1 被拒绝：首块未提交，前缀不连续。将相同总大小作为 ordinal=0 的一个成组候选时，native 接受，gain=20 ms。

这不是说“零收益块都该缓存”。问题在于**逐块正收益与前缀依赖同时存在时，局部拒绝可能堵住有收益的组合**。加载 setup/warmup 可产生这一形状；native gate 的恢复估计确实包含这些项，并夹在 previous/full recompute 上界内。[gate.py](/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/src/aegiskv/vllm/gate.py:493)

建议在首块或被阻塞 frontier 上检查有上限的连续候选组，例如最多 2–4 块；按组总 bytes、整个前缀的 gain 与 joint victim loss 决策。组未全部提交前不能把它作为完整恢复前缀；还需明确超时、配额收缩和部分完成时的处理。group 大小是待评估参数，本次未证明其最佳值。

### 2.2 重复压力报告重复缩减配额

target 注册容量为 1000 B、初始 alpha=0.5、gamma=0.5。对同一 target、同一 `now_ms=1000` 连续调用两次压力窗口，配额分别变为 **250 B、125 B**。当前接口没有 window ID，也不拒绝同一时间的重复处理。[ControlWindow](/home/comp/zhanzhao/Mooncake/mooncake-store/src/aegiskv_controller.cpp:1738)

这证明的是接口不具备窗口幂等性；不意味着已观测到生产 RPC 重试造成该后果。RPC 返回丢失或未来加入重试时，这一契约缺口会变得重要。模拟 `HBMQuotaAIMD.update` 拒绝不递增时间，因此模拟所施加的调用约束更强，但单纯比较时间也不能完全取代窗口身份。[模拟更新](/home/comp/zhanzhao/MoonKVSim/python/moonkvsim/aegiskv/hbm_quota_aimd.py:166)

建议请求携带 `(target_id, controller_epoch, window_id, observation_time)`，由单一 target owner 发布；相同 ID 重试只重发原 publication/reclaim plan，不再次计数或缩减。缺失报告维持 UNKNOWN，不当作一个有效稳定窗口。当前 native 已正确跳过未上报的其他 target，这一点无需再修。

### 2.3 回收返回值丢失后，元数据已释放但不再重发 victims

先提交一个 400 B 的 HBM 保护块，然后把 500 B 配额缩至 250 B。Controller 返回一个 victim，并立即将其 allocated bytes 记为零。若该返回未被执行，下一无压力窗口返回 **0 个 victims**，仍报告 `quota_satisfied=true`。

本例通过故意不执行回收列表表达“返回丢失/物理删除失败”，没有运行真实 HBM。它证明 native Controller 自身没有在该路径保留待确认释放的物理债务。Worker 确实在 publication 之后调用 `free_local`；失败会抛错并记录日志，而本条 loop 没有保存一份未完成回收任务以重试。[Worker 执行路径](/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/src/aegiskv/vllm/aimd.py:178)

本地 allocator 仍有容量和暂停保护，所以不能把此例写成“已经发生 OOM/数据损坏”。准确问题是：Controller 和 Worker 的占用状态可能分离，恢复进展和后续清理缺少明确的收敛协议。

建议使用 `REVOKED/RECLAIMING → FREE_ACKED` 的物理释放阶段。REVOKED 后禁止新恢复读取，但 bytes 仍计入物理占用，直到目标确认释放；保留可重发、幂等的 reclaim ID 和逐 key 完成状态。Controller 应分别暴露目标配额、已提交保护、pending 复制、待释放占用和目标实际占用。超时后做 target inventory 对账；不能靠 alpha 后来增长掩盖未完成删除。

## 3. 算法 2 的目标还需要收紧

### 3.1 立即故障收益不是期望 workflow 收益

当前比较 $A_x>D_Y$，其中收益与损失都来自本层 fail-now harm。native `NetGain` 实际直接返回 `GrossGain`，不扣正常期复制干扰。[实现](/home/comp/zhanzhao/Mooncake/mooncake-store/src/aegiskv_controller.cpp:363)

该目标可以作为故障时保护质量的代理，但没有回答：副本是否来得及完成、还能存活多久、占用哪条共享传输路径、会否让另一关键分支变慢。已有 full 比 DRAM-only 多约 91.8% 健康期保护流量而 WCT 优势不显著，说明这些问题值得测试；该结果本身不能证明任何一个缺口就是原因。

建议先保留层间独立性，加入可直接执行的约束：每源/每链路保护流量预算、每请求和每 target 的 pending bytes 上限、预计完成时间早于候选有效期，以及收益差的最小容差。不要直接把“条件于一次故障节省的 ms”与“每次必付的复制 ms”机械相减；若要优化期望收益，需要先声明共同的故障/存活时间范围并校准权重。

### 3.2 保护空窗应被约束，而不只是被承认

先删 victims 再复制是明确的设计取舍，不违反 PENDING 不可恢复的约束。但准入时 $A_x>D_Y$ 只保证最终候选状态的局部比较，不能保证复制期间的保护更好。

普通替换可在严格容量预算内保留少量 staging 空间，或只允许预计完成时间足够短的替换；硬前台压力时仍可直接删除并接受重算。不要承诺所有替换都 copy-before-delete，因为满池时没有免费空间。评价应包含空窗持续时间、空窗内故障、复制取消和无效复制流量。

### 3.3 独立 tier 价值需要明确解释

两层各自用本层 harm 评价，能保留独立冗余，但不是请求实际最短恢复时间的联合边际收益最大化。HBM 和 DRAM 各自正收益并不证明同时写两份最划算。

应说明优化的是各层独立保护质量，并用带宽预算控制代价；若将来改为按故障域的联合风险优化，那是目标函数变更，必须保留独立 source copy/commit 的所有权语义，并重新做消融。不能将 DRAM 又改回 HBM 删除的前置条件。

## 4. 算法 3 的控制信号与生效协议

### 4.1 要区分真正的前台压力和自身工作带来的耗时

native 首先用 `torch.cuda.mem_get_info(0)` 的 free bytes 判断压力；可选 stall 路径取 target 的 allocation/reclaim 耗时最大值。[配置与采样](/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/src/aegiskv/vllm/connector.py:440)、[压力汇总](/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/src/aegiskv/vllm/aimd.py:112)

CUDA allocator 外部空闲量与 vLLM 已预分配池中的空闲 KV slots 不是同一指标。可选 reclaim 样本还可能包含 AIMD 自己触发的删除：本轮缩额造成较慢回收，下轮将该耗时又当成压力，继续缩额。这是可构造的反馈风险，不是已经测得的 pilot 现象；该 stall 配置本身也并非始终启用。

建议记录操作原因，将前台 allocation shortfall/stall 作为主要压力证据；后台 copy/reclaim 耗时作为控制器开销单列。有效 samples 用窗口统计和滞回，真实分配失败则触发即时保护。对样本丢失、重启和 epoch 改变单独处理，不能以零样本自动证明系统有持续扩张空间。

### 4.2 “没有压力”不足以证明应该扩张

当前 $K$ 个无压力窗口后加 $\delta$。它没有要求存在被配额拒绝且有正收益的 HBM 保护需求，也没有要求上次配额已经被目标确认。建议扩张同时要求：有效稳定持续时间、足够的主 KV headroom、有等待保护需求、上一窗口执行完成；硬压力则走立即暂停/回收路径。

实机 pilot 的窗口是 5 s，模拟是 1 s；$K=4$ 意味着等待 20 s 或 4 s。注册 $M$ 的实际含义也不同：pilot 为 2 GiB，模拟为 40 GiB。相同 $\delta=0.05$ 并不是相同的 bytes/s 调节速度。应把稳定持续时间、每秒增长字节上限和最大单次回收量写进配置与报告。

### 4.3 恢复读 lease 必须进入可回收条件

native Controller `IsPressureEvictable` 只检查 COMMITTED 与 excluded 集合，未查询 Worker 恢复 leases；Worker copy 临界区有本地锁。模拟从选择源到物化期间施加更强的 pin。[Controller](/home/comp/zhanzhao/Mooncake/mooncake-store/src/aegiskv_controller.cpp:297)

应把“被恢复读取的副本不能被普通替换撤销”写成跨模块协议。与此同时，不能让 lease 无限阻挡紧急主 KV 分配：需要有界 lease、显式恢复取消和 DRAM/重算 fallback，并避免先 pin 住全部备份、再等待无处可分配的主 KV 所导致的等待环。

## 5. 论文怎样变得更严谨

经典 Landlord 面向文件缓存和检索成本，当前算法加入了动态 Slack、前缀依赖、异步提交与多个独立层；经典 AIMD 分析面向特定拥塞反馈模型。两者的结论不能直接套到当前系统。这是基于问题假设差异的判断。[Young 原文入口](https://www.cs.ucr.edu/~neal/Young02Online)、[Chiu–Jain 原论文](https://pages.cs.wisc.edu/~suman/courses/740/papers/chiu89isdn.pdf)

更适合证明/检查的局部性质包括：

1. 已提交前缀连续、pending 不产生恢复收益、route/layout 不兼容则拒绝。
2. 所有尚未实际释放的 bytes 都有账本归属，物理回收失败后任务仍可追踪。
3. 同一控制窗口最多影响一次 alpha 与 stable-window 计数。
4. 在固定 Slack/恢复估计、候选与 victims 属于不同请求的单池快照中，成功准入的**假设已提交状态**比原状态降低 tier-local harm；不扩大为复制期间或整个 workflow 的保证。
5. 若持续存在有效 headroom、待保护需求且执行能完成，配额能在有界时间恢复；若短时间交替压力，给出可测的调整频率与回收开销上界。

需要的最小新实验：零收益首块/两块组合、ACK 延迟和丢失、重复/乱序控制窗口、复制过程中降额、回收部分失败、恢复 pin 与前台容量同时争用，以及含突发负载的不同控制周期对照。先用小输入对照 eager 全量重算与 lazy heap，再做工作负载级 WCT；无需先扩展大规模矩阵。

正文算法 2 的 `ResidencyOutcome(h,d)` 也应改成明确的“准入计划/当前 pending 状态”，最终 residency 从提交状态查询；当前 native 已区分 `AdmissionDecision` 与 `ChunkState`，伪代码应保持同样清晰。

建议实施顺序：先修窗口身份与物理回收 ACK/重试，再统一恢复 pin，随后引入有界前缀组准入和复制预算，最后调整压力信号、时间尺度与扩张条件。它们都属于后续修改建议，本次未把建议写成已经实现或已经带来性能收益。
