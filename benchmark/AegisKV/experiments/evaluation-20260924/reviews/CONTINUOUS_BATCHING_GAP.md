# 当前设计接入 continuous batching 的可行性边界

日期：2026-09-24。只读可行性 memo；没有实现CB、改动现有矩阵或启动新实验。当前论文/正式结果仍是 FCFS、每DP一个active invocation。此前合并的 summary-only CPU日志优化不改变这一模型。

**结论：可复用调度、页所有权和step/failure桥接接口，但需要一个新的共享批次执行边界与batch-aware timing provider。将多个当前 `_step` 同时推进，或者给batch取单请求时长的max/sum，不能补齐目前的CB证据缺口。** 最小正确接入涉及请求生命周期、checkpoint可见性、恢复阻塞和输出计数，不能仅替换队列容器。新实现应另行冻结、验证和评估，旧结果不重标为CB。

仓库为 `/home/comp/zhanzhao/MoonKVSim`；下文Python模块路径省略共同前缀 `python/moonkvsim/`，测试路径相对仓库。`CONTINUOUS_BATCHING_INPUT_HASHES.json` 固定本次读到的文件身份。

## 已有、实际可复用的接口

| 组件与证据位置 | 可复用内容 | 接入限制 |
|---|---|---|
| `integration/vllm/scheduler.py:278–350,851–1154` | `ContinuousBatchScheduler`：FCFS running/waiting集合、step总token预算、最大resident请求数、chunked prefill、KV压力preempt/recompute、`SchedulerOutput`逐请求before/after进度与block IDs | 这是源码锁定的tensor-free vLLM V1镜像；文件24–35行声明commit和有限CPU语义证据，不是在本实验中执行真实vLLM/GPU |
| `predictor/vllm_adapter.py:68–160` | `AdaptedSchedulerStep`、`AdaptedPhaseBatch`；每phase保留request IDs、每请求extend和past-KV向量、完整fingerprint | mixed prefill/decode只提供形状，不自带时长合成规则；shape中无KV传输工作 |
| `aegiskv/scheduler_step_bridge.py:542–592,752–842` | `AegisSchedulerStepBridge.start_step()/complete_step()`、participants、phase shapes、residency before/after、provider evidence、单target不可重叠step | `schedule()`先改planned computed状态，完成后才提交输出；当前checkpoint逻辑必须读已完成frontier，不能读已schedule但未执行的进度 |
| 同文件`681–710,844–955` | `admit_restored_request`、明确`retire_request`、`failure_state_snapshot`、`fence_for_gpu_failure`；保留last-completed进度和in-flight参与者 | restore API的证明对象是连续、已在HBM的block-aligned prefix；不能把仅前L层的HBM Top-K或metadata当作完整可用prefix |
| `aegiskv/continuous_batch_des.py:476–559,1181–1324` | `AegisContinuousBatchDESDriver`提供release→step-ready→forward-complete→retire循环；`on_step_started/completed`、`on_before/after_admit`、abort与blocked-capacity回调；一次GPU forward可含多请求 | 当前constructor在519–524行硬要求`ObservedIdealTraceDurationProvider`，其request注册/时长分摊仍依赖observed request totals，不能直接塞入当前`GridDurationProfile` |
| `integration/vllm/scheduler.py:54–141`及`hbm_block_ledger.py` | `BlockLifecycleObserver`：allocate/release、recovery reserve/commit/abort、logical/physical audit；`HbmStageRankBinding`可绑定明确PP/TP rank layout | 必须与当前容量账本形成同一物理owner，不能让scheduler和`_reserve_primary`各扣一次同一KV |
| `aegiskv/experiment_hbm_authority.py:1–12,71–139` | `ExperimentHBMAuthority`示范logical16-token pages→physical64-token chunks，preview物理transaction成功后才发布logical ownership；支持共享backing/recovery reservation | 这是旧experiment账户模型的adapter，不是当前per-rank primary/checkpoint账户的直接替代；需要明确适配，不能借用旧SlackLandlord来替换当前E/G策略 |

源码锁定镜像与CPU differential可作为调度语义起点。`integration/vllm/differential.py:1–10`明确其不执行模型、不建立duration/physical parity。当前Aegis的metadata、per-query counts、E/G、TP checkpoint commit和逐层miss/hit overlap均仍需单独接入及验证。

另有两个直接的适配点：bridge 566–570行只接受两个既有HBM observer concrete class，不能把任何实现Protocol的新observer直接传入；`SchedulerExecutionBinding`（142–176行）只有一个`gpu_id`及failure-domain/layout身份，TP target到全部rank资源的映射/失效barrier必须由新边界明确提供，不能仅凭TP4 timing profile推断该映射已实现。

## 最小正确接入必须改变的边界

1. **每DP只有一个批次在飞，但该批次可含多个invocation。** 当前`current/runtime.py:162–165,906–918`的`busy: worker→one Agent`和单head admission需要替换为step participants与resident/waiting状态；普通任务、retry和KV暂不可用任务都进入同一调度器预算。保留现有DAG释放、Agent多调用顺序、causal predictor和policy controls。给request使用`(Agent, invocation, execution epoch)`身份，避免同Agent下一调用覆盖尚未结束的异步回调。

2. **区分scheduled、model-completed、Router-durable/output、checkpoint-committed frontiers。** 镜像scheduler在`_schedule_request`（1113–1154行）预先增加computed tokens；bridge failure snapshot（861–934行）用participant.before回滚尚未完成step。当前`_forward_done`才推进`durable`并收集query counts。新的checkpoint触发、衰减、Top-K冻结必须依附有效step-completion，禁止预先发布被故障取消的query/count/KV。一个batch内各请求跨越不同Z边界，不能依靠单全局256-token chunk推断所有请求的checkpoint。

3. **先解决输出/KV token约定差异。** 当前runtime把prefill完成与首个decode输出分开；旧CB实现的terminal prompt forward直接产生首个输出，随后只有`output_count−1`个decode forward（`continuous_batch_des.py:74–85`、bridge `complete_step`）。不能混用两套公式而产生额外/遗漏首token成本或错误的80%故障点。新边界应显式记录已materialize的KV/query位置与已提交输出位置，并给出与故障token、checkpoint/frontier的映射；旧冻结数据保持原约定。

4. **保留declared output reservation的非oracle边界。** 当前`Invocation.output_limit_tokens`与实际replay EOS长度分开。旧`ContinuousBatchRequestSpec.max_output_tokens`同时进入Request、duration归一化和终止判断，bridge 823–832行用它决定terminal。若填真实output长度，会把未来长度泄露给scheduler/容量；若填512/16384，则会错误地一直生成到cap。需要独立的declared cap和仅在forward completion揭示的EOS/replay-output接口。普通step只能看已提交prompt、已生成输出和cap；不能看未来call或实际终长。

5. **恢复必须与共享forward共同建模。** 当前`_layer_step`（1151起）是单请求逐层metadata→需求揭示→miss recall与hit compute重叠，且prefetch可被urgent miss抢占。旧CB bridge/driver只有整个forward开始/结束，没有batch内layer readiness。必须明确：若已选batch某participant下一层KV未就绪，是全batch等该层、还是在下一合法step边界暂不选该request；然后对实际participants计算共享layer/step成本。不能给恢复请求独立跑一套layer compute，同时普通batch也占用同一GPU计算。仅“full restore后再入batch”的起步模式可用于基础ownership测试，但省略了本设计的按需/逐层恢复，不能作为完整AegisKV CB评估。

6. **一个物理HBM authority处理所有owner。** 选择以现有current per-rank `CapacityLedger`为唯一容量事实源，logical scheduler page经observer映射到physical KV block；checkpoint HBM副本、recovering read leases、primary、pending DMA、weights/reserve共享同一rank预算。明确full declared reservation与按step增量KV allocation如何共存，预留额度与实际page不要重复计费。TP step、capacity admission和checkpoint publication均要满足全rank一致；同host失效仍删除该host DRAM。Foreground reclaim只能回收允许回收的replica，不能释放另一active participant或read lease的backing。

7. **统一事件owner和fault fencing。** `GlobalDES.register_handler`（41–43行）拒绝重复handler。Current runtime已注册`FORWARD_COMPLETE`/`FAILURE_INJECT`（217–227行），旧driver也注册同类事件（550–557行），不能直接并排实例化。应由一个执行owner持有batch completion/epoch，统一路由事件；故障取消整批in-flight参与者的未提交进度并分别重建所有active/queued/route-bound请求。故障发生在目标逻辑token时，需要定义如何对所有batch参与者一致确定切分/完成点，不能只切目标请求而让同一forward的其他请求无成本继续。

EOS后的可见完成、cold-copy取消、read lease释放、下一同Agent调用、以及延迟callback的epoch检查也必须迁移；不要恢复旧“等所有cold copy再报告EOS”的行为。必须增加真实admitted/step-start/step-end日志，从而后续区分queue、compute、miss wait与completion，避免沿用当前只有submit→finish的ordinary latency来充当queue时间。

## 现有batch-1 AIC grid为什么不够

当前`evaluation_profile.py:38–120`只接受单invocation的`(start,end,stage)`，grid只有`(stage,context,extend)`；decode逐token相加。它没有batch size、每participant KV长度、混合phase组成、共享weight read、batched projection/attention/collective等输入维度。

同一批次的时长通常不能从孤立请求时长唯一确定。把sum当batch成本，会重复支付可共享工作；把max当成本，则未经证明地假定完全并行。批内一个短prefix和一个长prefix也不能只用平均/最大context替代完整向量而不新增明确假设。恢复热点命中后的compute与DMA共存，更需要全批次占用边界。

旧`ObservedIdealTraceDurationProvider`（116–238行）明确是prefill1/decode8权重、per-request observed total分摊，再max或max/sum混合的**未校准模型**；它的evidence设置`formal_use_allowed=False`。不能因为已有driver可跑就把它叫AIC批成本。另有`qwen3_32b_tp4_duration.py:549–722`的全batch解析roofline provider，考虑共享weight读、各phase动态bytes和TP collective，但同样未校准、另有128K扩展假设，与本轮AIC HYBRID/40,960上下文证据不相同；driver当前的concrete-provider检查也不直接接受它。

下一阶段应保留`SchedulerStepDurationProvider.predict_step_duration_ns(AdaptedSchedulerStep)`和其证据fingerprint接口，增加当前模型/TP的batch-aware provider。最少覆盖实际token预算与resident请求数范围、heterogeneous prefix/extend向量、pure prefill、pure decode、mixed steps；分层恢复若继续按均分whole-step成本建模，必须把该假设写入profile与manifest。校准/外推/OOD规则、数值来源及mixed-step合成规则都要显式，不能静默退回batch1。

## 必需的回归与新证据门槛

| 测试类别 | 必须检查的行为 | 已有可复用基础 |
|---|---|---|
| 正常共享step | 两个以上resident请求、prefill/decode mixed、总token预算、运行请求上限；同一GPU不重叠whole forwards；晚到任务只进后续合法step | `test_scheduler_step_bridge.py:166,231`；`test_continuous_batch_des.py:210` |
| 输出与causality | terminal-prefill首输出约定；declared512/cap与短实际EOS分开；prefix reuse、多调用、仅首新输出后的Router frontier；无未来output长度控制 | 当前reservation/EOS测试 + 新bridge completion接口测试 |
| 中途故障 | 多participant批次所有未提交query/计数回滚；Router已提交输出silent replay；普通queued和route-bound future admission不漏/不重复；同timestamp completion/failure严格顺序 | `test_scheduler_step_bridge.py:275`；`test_continuous_batch_des.py:659,702,939,1143` |
| Primary与recovery ownership | logical page↔64-token physical chunk↔TP rank守恒；容量不足rollback；已恢复prefix不会再扣一次；read lease阻止错误回收；等待容量有明确wake，结束零泄漏 | `test_experiment_hbm_authority.py`；`test_hbm_block_ledger.py`；bridge restored-prefix测试200行 |
| 逐层恢复与CB相互作用 | missing metadata先于demand；urgent miss先于prefetch；恢复请求阻塞对整个batch/其他请求的作用；传输共享限速且同GPUcompute不重复；EOS取消只清理所属epoch | 当前`test_current_algorithm_20260924.py`、`test_current_eos_restore.py`迁移到batch participants |
| Checkpoint/statistics | 每请求每query去重、Z处beta一次、checkpoint只发布已完成TP shards；不同step切分不偷偷改count语义；completed EOS早于cleanup可见且后续call安全 | 当前checkpoint/counter测试 + 不同batch partition对照 |
| 可复现profile和证据 | step形状fingerprint到profile行/模型；batch1明确约定后的退化对照；summary/full日志结果同；shared-step工作量/资源/输出守恒；所有新source/workload/profile哈希封存 | 既有adapter/evidence tests与本轮campaign auditor可扩展 |

上述旧测试在本memo中只作为已有接口证据，没有在此次只读任务中重新执行，也不能代替最新Aegis checkpoint/HBM/metadata协议与CB组合后的测试。

## 建议的决策顺序

先完成当前180/143矩阵和其EOS/source核查，按既定范围交付FCFS证据。最终评审若仍将CB作为阻塞项，先做一个独立的新执行后端：复用`ContinuousBatchScheduler + AegisSchedulerStepBridge`，保留current policy/flow/Tracker，把上述frontier、EOS/cap和唯一HBM authority接起来；不要整体切回旧experiment策略栈。只有batch-aware profile和混合恢复正确性门槛通过后，才冻结小型机制点，再决定新的主矩阵。该阶段需要新的实验身份，不从本轮完成时间差换算CB收益。
