# Design conformance 定点复核

结论：找到 **1 个 coverage 未明确写出的实质恢复域偏差**，同时影响 sparse 需求身份和 dense 的 hit/compute 比例。其他所查发布、metadata gate、逐层优先级和副本完整性未发现新增偏差。未修改 live source、论文或冻结实验；只准备 `reviews/demand-domain-draft/` 中的补丁/测试草案。源码与各运行 summary 哈希见该目录 `EVIDENCE.json`。

## P1：恢复选择提前截断为 checkpoint 域，且漏计本地 tail hit

设计要求 tail 稀疏选择“as usual”，元数据到达后按当前层的正常因果可见域选块，缺失的 checkpoint 块再从 DRAM 召回（`paper/system_design.tex:368–382`）。当前 `runtime.py:1175–1185` 调用 `_demand(..., cp.frontier // block_tokens)`，在选择之前把 `history_blocks` 截为 checkpoint 块数；而正常计数的 `_forward_done:1259–1265` 在当前完整因果域选择。`policy.demand:83–92` 与 `evaluation_scenarios.SyntheticPhaseDemand:65–77` 都用 visible 数量参与选块本身，故这不是“完整选择后忽略已重建块”。

实际调用现有 `policy.demand` 的无模拟算术反例：block=64、CP frontier=512（8 块）、query=600、layer=1、synthetic_selected_blocks=4。当前恢复调用选 **{2,3,4,5,6}**；完整因果可见域为 10 块，正常选 **{0,3,4,5,6}**。两组都全部落在 checkpoint 中，因此恢复凭空改变了旧 KV 的需求/miss 身份。当前 provider 的跨 head 去重和未来块下标验证，不能消除这个域截断。

Dense 也有影响。CP=512、HBM/resident checkpoint 块={0,1,2,3} 时：

| 当前恢复 query（零基） | 因果可见块 | 本地 tail/self 块 | 当前 hit 比例 | 同一块级模型下完整选择的 hit 比例 |
|---:|---:|---|---:|---:|
| 512（第一条恢复 query） | 0..8 | 8 | 4/8 | 5/9 |
| 600 | 0..9 | 8、9 | 4/8 | 6/10 |

`query // block_tokens + 1` 是现有正常 selector 明确包含当前 query/self KV 的因果规则。第一条恢复 query 也应能选当前 tail block；该 KV 由当前层 forward 本地产生，不是未恢复的 DRAM 对象。后续恢复 query 的先前 tail KV 同样本地产生。代码目前只统计 CP selected references，漏掉这些 hit，可能减少可与 miss 传输重叠的 compute，改变 first-new-token/WCT。不能声称 dense 无影响，也不能在未重跑时量化误差。这里仍使用原块引用比例代理模型，不意味着精确 token/attention-FLOP 权重。

最小修复：保留现有 checkpoint metadata gate；在 `_demand` **统一**计算 `visible=min(blocks, query // block_tokens + 1)`，内置/外部 provider 均只接收 visible；recovery 与 normal 同样传 `ceil(end/block_tokens)`，由统一入口保证每个 query 的域一致。先完成选择，再拆分 `b < cp.frontier/block_tokens` 的 checkpoint 需求与本地 tail。仅前者进入 `_require` 和 DRAM miss 队列；后者直接计入 hit references，分母计入全部 selected references。tail selector metadata 视为当前本地 forward 产生，不能从旧 checkpoint 加载；将来接真实模型需显式提供对应引擎对象。禁止简单扩大 `_require` 到全部块，否则会把根本不存在于 DRAM 的 tail 块误召回。

该入口统一还有一个接口意义：旧 `_forward_done` 虽检查外部 provider 返回下标不能超过 query 的因果范围，却先把整个 batched forward 的 `ceil(end/block)` 传给 provider。若 provider 直接用这个 raw 参数而不自行裁剪，同一 query 的选择仍会受 forward 分区影响。不能只修 recovery 的调用参数。内置 selector 和当前 constructed-phase provider 都自行取 min，故其正常路径没有这项额外参数差异；将来外部 native provider 必须获得统一的因果参数契约。

已准备 `runtime-demand-domain.patch` 与 `test_recovery_demand_domain_draft.py`，**尚未应用、未执行测试/模拟**。草案覆盖：第一条/后续 dense query、上述 sparse 身份反例、外部 provider 选 self KV 合法且不触发召回、仍拒绝未来 KV，以及一个横跨四块的 forward 中每个 query 的 normal/recovery provider 参数完全一致且不泄露后续块数量。现有 overlap 测试 `test_current_algorithm_20260924.py:167–194` 的 3/4×200ms=150ms 断言本身固化旧域；同一例子加入本地 self KV 后应是 4/5×200ms=160ms，miss 仍被隐藏，完成时间仍 200ms。草案也给出该断言的对应改动。正式应用后需再跑已有 metadata/流抢占/租约/EOS/TP 检查，不应以更新旧数值断言代替新的域测试。

## 冻结证据影响范围

以下冻结 runtime 都含同一截断表达式。数量仅表示读取时已存在的 summary 及其中 checkpoint>0 的恢复，不表示每次一定产生可见 WCT 差异：

| 分组 | 读取到的运行数 | checkpoint 恢复数 | 路径 |
|---|---:|---:|---|
| formal-core-v1 | 180 | 120 | dense |
| sensitivity-campaign-v1 | 126 | 38 | dense |
| capacity-slack-ablation-v1 | 32 | 12 | dense |
| slack-mechanism-posthoc-v1 | 10 | 3 | dense |
| structural-campaign-v1（当时 141 个 summary） | 114 dense + 27 synthetic | 63 dense + 12 synthetic | dense / constructed-causal-phase-demand-v1 |

profile-smoke-v1/v3 各 6 点、各 2 次 checkpoint 恢复也含旧表达式。其他早期 mechanism 产物未在本次定点复核中逐项审计。所有这些完成/哈希/账本审计仍证明**旧模型自身**一致，不能改标成修复模型结果；当前 EOS 边界排除证明也不是本选择域修复的等价证明。

Dense：旧 CP miss 身份不变，但本地 tail 参与的 compute 比例可能变。Built-in synthetic / constructed-phase：需求身份和 hit/miss 比例都可能变。外部 native-provider 接口：若返回完整 trace 中的本地 tail 块，旧上界还会把合法需求拒绝为“不可见”；因此将来不能直接宣称恢复原生 trace 等价。现有 native-topk/native-topk-warm 是独立选择/计数诊断，不执行该恢复 layer 路径，不能据此推断其原生恢复 WCT 已验证。policy=none 的完整重建、无失败 F0、未取得 checkpoint 的失败不走该受限选择分支。

## 其余核对：无新增问题，保留现有明确简化

- **未执行/排队 Agent 的 E/G。** `_rebalance_inner:617–628` 排除未提交、finished、recovering 与小于 Z 的状态；已有兼容历史但排队中的 Agent 仍以已 durable 历史算 E，并保留跨调用 replica，这与设计 `system_design.tex:498–502` 的 Agent 生命周期不矛盾。未看到设计要求这些 Agent 的 E/G 强制为零。runtime 立即提交后续调用，缺少显式 Tool/思考停顿属于已声明工作负载简化。G 的无竞争/非 native-miss surrogate 已见 coverage:26–39。
- **Checkpoint 与 DRAM/HBM 完整性。** `_checkpoint:442–516` 以冻结计数版本、所有层 Z-token KV 和全新 metadata 计费；`_start_copy:350–363` 等全部 TP rank ACK 后发布。HBM 对象只从已提交 checkpoint 挑选，`_sync_hot` 每对象仍等全部 shard 完成，未发布部分不进 `cp.hbm`。`_load_next:963–971` 校验全部 checkpoint KV 和每层 metadata 后才宣布 full restore。异步 lag 可超过 Z 已在 coverage 中声明，不是本次新增。
- **Metadata gate 与真实性。** `_layer_step:1246–1248` 在 reveal 前 `_require` 当前层 metadata；刚解锁的 reveal 先于 `_load_next` 后续预取。第一 L 层 metadata 在 HBM 则无需传输；否则和后层一样先召回。metadata 对象实际只有版本/字节与就绪标记，`policy.demand` 不读取 compressed-key 数值，provider API 也没有此对象参数；这是 coverage:33–36 已披露的非数值 selector 简化，不能称为真实 metadata 重建。上述 P1 是除此之外的可见域错误。
- **L 后层与 full recall。** `_restore:930–953` 前 L 使用 checkpoint 冻结的 hot_sets，后层按保存 counts 恢复时排序；所有层按序先 metadata+TopK，然后再排所有层剩余 cold KV。它不是后层一开始强制 full recall。实际 miss 经 `_require` 提升、保留已传字节并优先于后续预取；hits 与 miss 流并行，二者就绪后再做剩余比例 compute，事件次序符合设计。CPU 排序、GPU scatter-add、数值 softmax/LSE 和真实 metadata payload 均未建模，已在 coverage 中声明。

追加两个定点确认：**dense TopK 缺少热点区分证据**。`policy.demand` 的 dense 返回全部可见块，故更早块的累计访问不少于更晚块；统一 beta 衰减保留该顺序，`top_blocks` 的较早 block tie-break 使这些运行通常固定保留前 K 块。dense 恢复可评估驻留 K 块所减少的字节与等待，不能验证热点识别、native 访问集中度或漂移收益。这是 workload/证据范围限制，不是另一个应扩修的代码错误。

**Tracker fallback 未使用 oracle。** `tracker.py:95–134` 仅消费预测值、预测提交年龄及尚未开始 Agent 的 prior；任何 missing/expired/nonpositive 输入将整个残余 Workflow 的 Slack 置零。`runtime._submit:768–794` 提供当前 prompt、已完成调用时长/输出长度和已逝时间；异步旧版本不能覆盖新版本。没有读取后续 invocation 输出、未来完成事件或实际剩余时长作为 fallback。手工/训练 prior 的预测有效性尚未验证已在 coverage 中声明，与未来标签泄漏不是一回事。

## 追加：隔离验证已执行

主代理后续授权了隔离验证。`demand-domain-draft/PROTOTYPE_VALIDATION.md/json` 记录：旧实现新增域测试 5 失败/1 通过，旧 existing 回归60通过，修复源码的新域+existing回归66通过；所有导入都绑定隔离树路径和hash。另运行8个固定小Workflow和4个初始化单层微例，dense/sparse均发现可见 timing 变化。它们只使用特意较慢 H2D 的线性成本机制输入，不能外推正式矩阵修正量。此追加覆盖前文“尚未执行测试/模拟”的初检时点说明；原冻结运行、source和seal未被修改。

候选评审以 exit0 / success / input_drift=[] 完成后，按主代理授权合入 live；版本为 `checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1`，live66回归通过。旧/新hash与评审完成门槛见 `CAUSAL_DOMAIN_APPLICATION.json`。随后候选评审指出排队跨调用 history 的故障存活问题，主代理已授权另行核实与修复；在该项完成前暂不冻结新 campaign。
