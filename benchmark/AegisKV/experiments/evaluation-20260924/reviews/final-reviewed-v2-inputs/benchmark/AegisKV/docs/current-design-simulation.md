# 当前 AegisKV 设计的 MoonKVSim 实现

以 2026-09-24 当前 [system_design.tex](../paper/system_design.tex) 及
[AGENTS.md 最后一次 KV Master 修订](../AGENTS.md) 为准，版本为
`checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`，默认
`Config.slack_mode="dag"`，支持显式 `"zero"` 对照。对应源码在
[current/](../../../python/moonkvsim/aegiskv/current/)。旧的租金、三层互斥所有权及
`mooncake_prompt_v1` 实验路径保留，不作为此版本实现。
这里交付的是可执行、未校准的元数据离散事件模型，不是完整生产部署。
逐项代码与测试证据见 [DESIGN_IMPLEMENTATION_COVERAGE.md](DESIGN_IMPLEMENTATION_COVERAGE.md)。

## 实现与设计的对应关系

| 设计 | 实现 | 已执行的语义 |
|---|---|---|
| Tracker | `current/tracker.py`, `predictor.py` | 固定 Agent-task DAG；一次调用一次异步预测；按预测提交时刻扣减 elapsed；残余 DAG 的 EF/LF；guard；任一必要预测缺失、过期或无效时整个工作流零 Slack |
| Router | `current/runtime.py` | 每 DP 的负载与精确 token-prefix 本地性；Peer 必须位于另一主机故障域；执行位置变化时重新验证 Peer；故障后重试到 Peer；接管者再选独立 Peer |
| Agent 选择 | `_rebalance_inner` | `E=max(T_reconstruct-slack,0)>lambda`；按 E 降序将完整检查点接纳到有限 Peer DRAM；每个物理主机只有一个容量账本 |
| 检查点 | `_checkpoint`, `Checkpoint` | 256-token 增量；各层、全部 TP 分片到齐才发布连续 frontier；PENDING 分配也计费；复制中的尾部不冒充已提交状态 |
| HBM 选择 | `policy.top_blocks`, `_sync_hot` | per-query 跨 head 去重；检查点边界衰减，提交后按冻结计数迟滞更新前 L 层各 Top-K；按 `G=[T_D-s]+-[T_H-s]+` 准入、低 G 优先回收；读租约可推迟释放，Peer 本地复制新进入块，保留完整 DRAM 底本 |
| 恢复 | `_restore`, `_layer_step`, `_require` | HBM 原地接管；按层预取；actual miss 优先、可保留已传字节抢占预取；hit 计算与 miss 传输重叠；已接受输出只重建、不重复提交 |
| Adapter | `policy.Adapter`, `_control` | 每 rank 的 ceiling 与 AIMD；有未接纳需求且连续稳定窗口后才增长；内存压力下缩小；按实际占用执行前台准入 |
| 安全与资源 | MoonKVSim `GlobalDES`, `FlowDESController`, `CapacityLedger`, `ResourceTransaction` | 全局 ns 时钟；共享 NIC/fabric/DRAM/H2D/D2H 的 max-min fair 流；原子字节分配；读引用延迟释放；故障使旧复制失效 |

恢复先在完整因果历史中选择 KV，再区分 checkpoint 与本地产生的 tail/self KV。
本地块参与 hit-compute 比例，但不从旧 checkpoint 召回；外部 selector 在正常与恢复
路径收到相同因果范围。故障时，排队中的后续调用也会持有有效历史检查点的读租约，
在 Peer 上恢复。其记录进入 `history_restores`，不混入 active co-victim 的 `recoveries`。
未发布检查点不能恢复，丢失 GPU 的 counters/snapshots 不再使用。

这里实现了可训练的上下文回归器：文本特征哈希加数值历史特征，对数剩余时长回归，
可导出 JSON 后通过 `--predictor` 加载。预测器只接收提交时可见的输入，不接触未来调用
或故障点；运行器拒绝训练工作流与评估工作流重叠。它没有在真实 Agent 任务上校准。
默认机制矩阵使用显式的时长先验预测器，不能据此声称论文所需的预测精度已经验证。
正式 FanOutQA 分组使用训练集角色/输出先验与当前 prompt 的 profile 成本，
guard 也是模拟训练数据的派生量；没有验证真实部署中的预测误差或控制器 CPU 开销。

## 运行

在仓库根目录执行单次无故障模拟：

```bash
.venv/bin/python -m moonkvsim.aegiskv.current run \
  --out /tmp/aegiskv-current-f0 --policy aegiskv --seed 7 --workflows 3
```

在同一 Agent 的第二次调用、总 token 逻辑进度 80% 处注入故障：

```bash
.venv/bin/python -m moonkvsim.aegiskv.current run \
  --out /tmp/aegiskv-current-f1 --policy aegiskv --seed 7 --workflows 3 \
  --failure-agent wf00/slow --failure-invocation 1 --failure-progress 0.8 --journal
```

策略参数为 `none`、`dram`、`aegiskv`，另有 `all_dram` 和 `static_hbm` 控制。
`dram` 保持同一 Agent 选择规则、DRAM 检查点和逐层恢复，仅关闭 HBM；`all_dram`
忽略 λ/Slack 筛选，但仍受实际 DRAM 容量约束。故障默认使整个 TP worker 失效；
`--failure-scope host` 还使该主机上的其他 DP worker 和 DRAM 一并失效。
只有一个主机故障域存活时可继续执行，但不能建立跨主机的新备份。

`all_dram` 仍按 E 排序，不能当作零 Slack 对照。要移除 DAG Slack，保留
`--policy aegiskv` 并在配置 JSON 中设置 `"slack_mode": "zero"`；预测提交/返回
仍运行，只有决策使用的 Slack 被置零。这同时影响 DRAM 的 E 与 HBM 的 G，
不是保持 HBM Slack 不变的纯 O1 消融。`static_hbm` 固定初始配额、不执行 AIMD 增长，
但仍受前台内存安全回收约束，并非永不回收的固定驻留集。

完整机制矩阵：

```bash
.venv/bin/python -m moonkvsim.aegiskv.current campaign \
  --out /tmp/aegiskv-current-campaign
```

矩阵固定 9 个场景、78 个运行：dense 与构造稀疏场景各 3 个工作负载种子，其余场景
各 1 个种子；每种组合比较 3 种策略及 F0/F1。每个种子有 3 个固定 DAG 工作流，
每个工作流是 root → {slow, fast} → join，共 4 个 Agent、6 次调用。每个 DAG 只执行一遍。
种子改变实际工作量和 token 序列，不把相同时间线重复包装成独立实验。

早期 78 次线性成本机制回归见 [FINDINGS.md](../experiments/evaluation-20260924/mechanism-campaign/FINDINGS.md)
及 [AUDIT.json](../experiments/evaluation-20260924/mechanism-campaign/AUDIT.json)。
输入、原生访问诊断及主 Evaluation 的状态见
[本次协议](../experiments/evaluation-20260924/PROTOCOL.md)。
旧 [REPORT.md](../experiments/current-design-20260923/REPORT.md) 是 20260923 设计的历史证据。
首个不完整尝试发现并暴露了执行迁移后的 Peer 故障域检查问题，原始输出保留在
`experiments/current-design-20260923-initial-router-failure/`，不混入成功矩阵。

## 实验分组与冻结版本

五组替代实验共 483 个固定条件，使用本文顶部的同一实现版本，并保持 v1 的输入、
故障身份、模型 profile 与 priors。原始版本保留，不将替代运行计为额外统计重复。
五组共 483 个修正版条件均已完成并审计；精确状态以每组审计和完成标记为准。

| 分组 | 固定范围 | 当前证据入口 |
|---|---|---|
| `formal-core-v2-corrected` | 180 run 完成并审计：Qwen3-8B TP1 / 32B TP4、62 个完整 heldout workflows、3 loads、5 variants | [AUDIT](../experiments/evaluation-20260924/formal-core-v2-corrected/AUDIT.json)、[恢复完成日志](../experiments/evaluation-20260924/reviews/primary-resume.log) |
| `structural-campaign-v2-main` | 135 run 完成并审计：5 构造场景 × 3 seeds × 3 variants × F0/prefill/decode | [AUDIT](../experiments/evaluation-20260924/structural-campaign-v2-main/TRACE_MECHANISM_AUDIT.json)、[结果与负例](../experiments/evaluation-20260924/structural-campaign-v2-main/PAPER_NUMBERS_V2.md) |
| `sensitivity-campaign-v2-corrected` | 126 run 完成并审计：4 个完整 heldout workflows、按输入长度固定的单故障 | [AUDIT](../experiments/evaluation-20260924/sensitivity-campaign-v2-corrected/AUDIT.json)、[辅助数值](../experiments/evaluation-20260924/reviews/PAPER_NUMBERS_V2.md) |
| `capacity-slack-ablation-v2-corrected` | 32 run 完成并审计：DRAM 2/4/8/256 GiB × 4 variants × F0/F1，保留 WCT null | [独立审计](../experiments/evaluation-20260924/capacity-slack-ablation-v2-corrected/INDEPENDENT_VARIANT_AUDIT.json) |
| `slack-mechanism-posthoc-v2-corrected` | 10 run 完成并独立审计：单个构造 fork--join，紧/宽预算，手工先验；另两例 observer 透明性验证 | [审计](../experiments/evaluation-20260924/reviews/POSTHOC_SLACK_V2_INDEPENDENT_REVIEW.md) |
| `native-topk-warm` | 3 模型 × 每模型 3 PG19 文档的 native selector 捕获；不执行恢复路径、不产生 WCT | [README](../experiments/evaluation-20260924/native-topk-warm/README.md)、[审计](../experiments/evaluation-20260924/native-topk-warm/AUDIT.json) |

历史 `formal-core-v1` 为 180 run，`structural-campaign-v1` 为全部 143 run
（135 主矩阵加 8 个规模控制），均已完成原版本账本审计。v1 数值不代表新恢复语义。
历史 sensitivity/capacity/posthoc 的 timing metadata 追加勘误保留原 seal；
v2 prepare 已写入实际 GridDurationProfile/DMA 配置。
`native-topk/` 是冷启动和旧 tie 规则，不能与当前 warm 图表混用。

输入审计见 [inputs/README.md](../experiments/evaluation-20260924/inputs/README.md)：
160 个 FanOutQA 源工作流各保留一次；先按完整工作流的模型 native context 筛选，
再用固定 workflow-ID hash 分 train/eval。Prompt 构造、tokenizer 等价核对、被排除
长上下文 IDs 都留有审计。结构化工作负载不是第二套自然 Agent trace；Weka
episode 与 ODR 可用性审计也不作为原生固定 DAG 主实验。

### 冻结输入复跑与结果审计

正式 profile 组的冻结快照需从自身代码复跑。下面先做只读 seal/import 检查，再在新目录
仅复跑首个计划点；省略 `--limit 1` 才是整个原计划。辅助 import 若旧快照未携带，
replay helper 单独记录补充来源，不能覆盖冻结 core 模块。

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_frozen_profile_campaign.py \
  --campaign benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v2-corrected --verify-only
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_frozen_profile_campaign.py \
  --campaign benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v2-corrected \
  --out /tmp/aegiskv-formal-replay --workers 1 --limit 1
```

完整新敏感性实验使用新目录准备并冻结当前源码，因而是新版本实验，不能冒充旧组逐字节
复现。其 `run`/`summarize` 自动 re-exec 到该目录的冻结 runner：

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_sensitivity_campaign.py \
  prepare --out /tmp/aegiskv-sensitivity-new
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_sensitivity_campaign.py \
  run --out /tmp/aegiskv-sensitivity-new --workers 4
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_sensitivity_campaign.py \
  summarize --out /tmp/aegiskv-sensitivity-new
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/audit_capacity_slack_ablation.py \
  --out benchmark/AegisKV/experiments/evaluation-20260924/capacity-slack-ablation-v2-corrected
```

最后一个命令只重算已有 32-run 结果的独立分析产物，不启动模拟。

## 输入、输出和复现

`--config config.json` 接收 `current/model.py:Config` 的字段，可只覆盖所需值。
`hosts` 列表的第 i 项为 DP worker i 所属的物理主机；TP rank 数由 `tp` 指定。
HBM 字节数指扣除权重和固定分配后的可分配池。默认形状是通用 32 层、DP=4、TP=2，
不是经校准的某个商业 GPU/模型配置。L、K、带宽、服务预留和 λ 均写入每次的 config。

`--workload workload.json` 接收 Agent 列表，每个 Agent 包含 `workflow`、`name`、
`predecessors`、`calls`、`prior_ns`、`role`、`release_ns`；每次调用包含明确的
`prompt`/`output` token ID 列表、`model`、`layout` 和可选 `text`。
新字段 `output_limit_tokens` 指预先声明的输出上限，主 KV 按 prompt+该上限预留；
必须不小于回放输出长度。省略时保留旧机制的完整输出长度预留，summary 用
`oracle_reservation_count` 明确报告；正式主实验要求该计数为零。
输出序列是模拟器的执行输入，不提供给 Tracker 预测器。后续调用只有与已保留历史的
token 前缀、model、layout 全部匹配才复用。CLI 输出的 `workload.json` 可直接读回。
`summary.output_tokens_exact` 检查固定 token 回放的 emitted token 数量与去重，
不验证数值 attention/KV 或模型生成输出的 identity equivalence。
真实 trace 必须先验证 Agent-task DAG 和 token 前缀，再转换为该格式；不能从时间相关性
补造依赖，也不能将现有调用级 DAG 不经核对就称作固定 Agent-task DAG。

每次运行保存：

- `MANIFEST.json` 与 `source_snapshot/`：代码、设计文本及测试文件的 SHA-256 和快照。
- `workload.json` 或 campaign 的压缩工作负载：实际使用的 token 与依赖。
- `config.json`、`failure.json`、`summary.json`：配置、故障及每次请求/恢复/工作流结果。
- `events.jsonl.gz`：策略抽样、提交、检查点、配额及故障事件。
- `flows.jsonl.gz`：启用详细日志时保存共享链路逐区间分配速率和传输字节。
- `journal.jsonl.gz`：指定 `--journal` 时的底层全局事件/资源事务日志。
- campaign 配对 CSV/统计 JSON：保留同 ID 的 F0/F1 和负值；不同 runner 的文件名、
  样本单位及统计字段以各自协议为准，不对单次固定故障生成 population CI。

输出目录必须不存在，防止覆盖已有证据。运行失败时保留 `FAILED.json` 和事件。

## 已验证内容与边界

针对性测试覆盖 Agent CPM、预测过期/乱序回调、一次调用一次预测、训练集泄漏检查、
AIMD 信号与 ceiling、native-count Top-K 排序、TP 提交屏障、完整 DRAM 底本、
精确前缀复用、故障域变化、共享主机容量、带宽竞争、回放输出去重、稀疏 miss 补取、
终态释放及确定性事件重放。测试命令：

```bash
.venv/bin/pytest tests/aegiskv/test_current*.py -q
.venv/bin/pytest tests/aegiskv/test_evaluation_profile.py \
  tests/aegiskv/test_evaluation_profile_metadata.py -q
.venv/bin/ruff check python/moonkvsim/aegiskv/current
```

这是未校准的 CPU 元数据 DES，没有运行 GPU、CUDA、vLLM 或 Mooncake 服务。
前台是每 DP 一个 FCFS 执行队列，不具备旧 vLLM adapter 的连续批处理。默认时长为
线性 token 模型；`--duration-profile` 可接入 `evaluation_profile.GridDurationProfile`
的具名模型/TP/形状表。当前 Qwen3 表来自 AIConfigurator HYBRID 算子估计，未经过
端到端校准。`compute_dma_slowdown` 可指定事件起点存在同 rank DMA 时的额外计算比例，
它是显式敏感性模型，默认零。F0 相同不能称为实机零开销。
模型 whole-forward 时长在恢复时按层均分；hit/miss 计算按被访问块比例拆分，
并没有数值 attention、softmax/LSE merge 或真实通信 kernel。预测的 `T_D/T_H`
是无竞争的 profile surrogate；实际恢复在 DES 中竞争共享链路，估计不是未来 miss oracle。

物理块 `block_tokens=64`、检查点 `checkpoint_tokens=256`、正常计算块
`prefill_chunk_tokens=256` 独立配置。实际 forward 在 checkpoint 和故障边界切分。
`count_decay=0.9`、`topk_hysteresis=0.1`、selector/count 元数据大小均为可变模型假设，
每个 TP 分片的复制和容量都包含元数据。不是原生 GPU counter/kernel 的开销测量。
计数只在受保护或恢复期间累积，没有补算保护前/保护间隙的访问。每个 Z 边界衰减并
冻结快照，等待对应模拟复制提交后才更新前 L 层集合；后续层在恢复时排序。warm native
分析假定从 q0 持续计数且诊断检查点立即可用，只验证 selector 机制，不等价于这些
受保护状态和异步复制条件下的完整部署历史。runtime tie 规则优先较早 block ID。
Z=64 会把正常 prefill forward 也切至 64-token；故障 token 位于块内同样会改变
forward 分区，因此 F1−F0 包含服务形状和调度变化，不能全部叫复制/故障检测开销。

Python 接口还支持 `CurrentRuntime(..., duration_profile=..., demand_provider=...,
retain_detailed_logs=False)`；外部 demand 必须给出因果、去重的历史块索引。
`--summary-only` 关闭逐区间 flow/DES 日志以控制大规模内存；运行时 invariant 仍执行，
但不能对未保存的完整 flow intervals 声称做过独立字节/速率重算。

`synthetic_sparse` 是可检验 miss 路径的构造 selector，不能称作训练模型的原生选择。
恢复期间读取实际 demand，绝不把预测 Top-K 直接当成全部需要的 KV。故障是单次永久
worker/host 故障，取消/释放在模拟时钟中同步确认；真实驱动取消延迟和重复故障未校准。

256 是检查点发布粒度，**不是异步复制滞后的上限**。复制跟不上时，故障后重建量为
`durable_tokens - committed_frontier`，可超过 256；数据明确记录 `tail_exceeds_256`。
恢复后的首个新输出用单 token 事件计时，其余健康 Decode 使用固定 token 分组。
小样本分位数仅描述此次机制矩阵，不能替代真实 trace、原生稀疏模型和物理路径实验。

### 2026-09-24 EOS 恢复边界修复

这项修复首次引入于 `...-20260924-eosfix1`，当前版本还包含后续因果域与排队历史修复。
当最后一个输出已完成而冷 KV 仍在后台加载时，旧实现会遗漏完成唤醒。
现在在 EOS 同步取消剩余 prefetch、隔离旧 epoch 回调，然后释放读租约与目标空间，
不把内部传输清理延迟计入请求完成时间。恢复不完整的本地历史保守失效，后续同 Agent
调用不能把它误作完整前缀命中；这也意味着没有利用可能仍有效的部分前缀。
取消已经暂停并恢复的流时，只记本次恢复后实际传输的字节，避免重复计数。

复现、隔离原型、补丁和应用哈希保存在
`experiments/evaluation-20260924/reviews/EOS_RESTORE_REVIEW.md` 及相邻文件。
新旧版本的稠密对照时间相同；稀疏边界回归覆盖 EOS、同 Agent 后续调用、依赖 Agent、
排队请求、陈旧回调、终态释放和独立流量守恒。
`formal-core-v1`、`structural-campaign-v1` 保留原冻结版本，不能追溯改写其来源；
所有 v2 替代实验使用共同的新恢复实现。

较早文档核对的 79 项检查属于当时另一组测试范围。当前恢复修复门槛为 74 项
`test_current*.py` 回归；profile/metadata 另有 14 项检查，不能与较早的重叠测试累加。
冻结 replay 的 `--verify-only` 仅核验 seals/imports，不启动模拟；测试也不替代结果审计。
