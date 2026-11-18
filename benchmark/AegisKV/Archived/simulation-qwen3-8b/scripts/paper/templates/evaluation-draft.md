## Evaluation

### 实验方法与研究问题

评估围绕两个问题展开：第一，在相同负载与资源下，保护机制是否使正常服务出现可感知退化；第二，在同一个可控故障作用于同一个 Workflow 时，保护副本能否缩短完整完成时间，以及这一收益来自哪里。扩展实验分别研究故障频率与并发的影响，随后再评估模型与并行规模、其他基线以及算法消融。

我们比较 Mooncake、DRAM-only AegisKV 和完整 AegisKV。DRAM-only 使用 AegisKV 的 DRAM 准入并关闭 Peer HBM，用于分离 DRAM 策略与 Peer 的作用。三者应采用相同服务引擎、模型、物理资源、恢复路径与调度配置。原生实验需要完整系统实现；下面沿用的 source-v3 数据是未标定模拟中的策略对照，不能称为完整 Mooncake 和 AegisKV 的原生部署测量。

默认配置为 Qwen3-8B BF16、DP=8、TP=1、PP=1，8×40 GiB、1 TB DRAM Store、25 GB/s 共享路径，KV chunk 为 4096 tokens。输入包含 160 个 FanOutQA-derived Workflow，每个完整 DAG 执行两轮精确重访，共 2608 个请求；最大活跃 Workflow 数为 16。该重访构造用于施加可控复用压力，不代表生产重访频率。F0 表示无故障，F1 表示一次预定故障。一次运行处理整套输入；逐 Workflow 图的点代表同一个逻辑对象，运行重复仅用于估计不确定性。

WCT 从 Workflow 准入计到 DAG 完成。后续外部到达实验另报准入前等待和从 release 到完成的响应时间，防止并发上限掩盖排队成本。三系统按同一个 Workflow ID 配对，统一使用冻结的 Mooncake F0 排序。我们同时报告绝对秒、相对开销与尾部，避免较长 Workflow 的固有差异遮盖策略效应。

正常服务采用事前定义的非劣判据。当前草案将 WCT 均值及 P95 的服务退化边界暂定为 2%，以配对完整测量块形成的单侧区间判定；该目标尚待正式采集前冻结。TTFT、逐 token TBT、goodput 与完成率共同报告。CPU、显存及网络开销另行计量：异步操作即使不延长 WCT，也仍可能消耗额外资源。未发现显著差异不能作为零开销的证据。

本轮尚未执行上述新协议。以下七张图以冻结历史数据检验新画法和统计口径，保留正、负与零结果；它们不构成算法 2 后续修改版本的验证。实验清单、缺少的采集字段与重复方案见 [实验设计](EVALUATION_DESIGN.md)。

### 正常执行的服务代价

图 {{ref:eval-healthy-workflow}} 将每个 Workflow 的 WCT 除以同一对象的 Mooncake WCT，再减一，直接展示差异曲线。零表示基准服务时间，负值表示更快；不再用不同 Workflow 的原始时长高低判断系统收益。

{{fig:eval-healthy-workflow}}

{{healthy_table}}

历史模拟中，AegisKV 的平均 WCT 为 {{aegis_mean}} s，相对 Mooncake 增加 {{mean_overhead}}%；这不是“无额外服务开销”的结果。该配置每个系统只有一次用于当前曲线的执行，不能据此构造跨部署置信区间或完成非劣判断。原始绝对 WCT 和其余服务分布保留在补充材料中。

### DRAM、HBM 与控制面的代价来自哪里

图 {{ref:eval-healthy-reuse}} 进一步对齐同一组 Workflow 的 DRAM token 命中率。该图使用百分点差值；总体命中率则按 prompt token 加权。历史结果中，完整 AegisKV 相对 Mooncake 下降 {{hit_drop}} 个百分点，表明正常复用需要与保护价值共同权衡。

{{fig:eval-healthy-reuse}}

图 {{ref:eval-healthy-resources}} 将前台等待、控制计算和传输逐项相对同指标 Mooncake 归一化。各行具有不同计量对象，不能相加成总开销。历史模拟中的 HBM 分配等待与调度队列未随 Peer 一同增加，但 Python 参考控制 CPU 和模拟 CPU 服务需求明显增加；正常 GET 变少也伴随命中率下降，不能单独解释为带宽效率改善。

{{fig:eval-healthy-resources}}

{{resource_table}}

正式原生实验还需要逐 GPU 的前台与备份 HBM 峰值、分配失败/抢占、逐路径链路利用率、进程 CPU 分解与真实逐 token TBT。此前双 L40S 的组件微基准发现，512-token、batch 1 条件下 Peer 输入使 forward 中位时长增加约 32.2%；组件结果说明复制干扰需要测量，不能直接代替三系统端到端成本。相关原始图保留于 [补充材料](Old_Figures.md#agent-lease-supplements)。

### 固定单故障下的同一 Workflow 比较

固定绝对墙钟时刻并不保证三个系统的 Workflow 已执行到相同位置。主实验因而使用预定语义边界：冻结焦点 Workflow/span、输入/输出 token、source GPU、恢复目标和不可用时长，在同一 decode token 的 kernel 边界注入。受控条件下，故障 GPU 在干预区间只持有同一焦点请求的易失 primary；其他前台任务使用相同的剩余资源。各策略自然形成的已提交副本允许不同，不能等待 AegisKV 的复制完成后才注入故障。

对于每个 Workflow，分别计算绝对 F1 WCT、相对自身 F0 的增量，以及使用共同 Mooncake F0 分母的归一化增量。绝对 F1 回答最终是否更快；F1−F0 则检查故障代价是否下降。近零或负的故障增量不作为倍数收益的分母。

图 {{ref:eval-failure-wct}} 与图 {{ref:eval-failure-increment}} 使用历史数据中三个事前选定的焦点实例 C1–C3 说明这两个终点。每个实例只比较同一个 Workflow，避免大量未直接受损 Workflow 稀释差异。历史触发按同一请求的总 token 进度 60% 解析，并非固定新协议的 decode 边界；其余受影响对象尚未固定。因此这里的点仍是旧协议诊断。

{{row:eval-failure-wct,eval-failure-increment}}

{{focal_table}}

三例的结果并不一致：C1 的 AegisKV 焦点 Workflow 更慢；C2 更快却具有负的 F1−F0；C3 也没有绝对 WCT 优势。负增量反映闭环调度与争用发生变化，不能解释为故障有益。历史全部 Workflow 的平均 F1 WCT 在三处注入中也均未优于 Mooncake。新的固定受害者协议需要重跑后，才可检验收益是否稳定传递到完整 Workflow。

### 从可恢复副本到 Workflow 终点

恢复分析沿同一焦点请求追踪故障检测、重路由、前缀装入、后缀重算、队列等待、恢复解码、分支完成及 DAG 汇合。图 {{ref:eval-failure-recovery}} 先用现有日志中可加的两个聚合阶段展示这条原因链的前半段；柱终点为恢复解码，尚不是 Workflow 完成。正式图需要补齐后段事件，重叠操作以时间区间表达，不把并行阶段相加为 WCT。

{{fig:eval-failure-recovery}}

图 {{ref:eval-failure-kv}} 对照相同实例的恢复来源与重算 token。三例均未从 Peer 恢复 token，因此较短的局部恢复不能归因于 Peer HBM。只有当已提交的保护前缀实际减少重算或装入时间，并且节省未被其他分支或排队吸收时，才可能解释完整 Workflow 的收益。

{{fig:eval-failure-kv}}

这组结果保留了当前证据的限制：局部恢复时间、保护字节数和完整 Workflow 收益不能相互替代。故障实验既要报告直接受害者，也要报告预定背景 cohort、完成率及系统 makespan，防止将成本转移给其他 Workflow。

### 故障频率扩展

【R1 / R2 结果待补】固定模型、DP=8 与并发上限 16，在一小时测量窗内分别注入 0、1、2、4、8 次预定故障，每次不可用 120 s。横轴明确为每 cluster-hour 注入次数；三系统重放相同外部到达与故障轨迹，报告实际故障次数和 unavailable GPU-seconds。两张独立图分别展示 SLO goodput 与 Workflow 响应时间 P95，旁列完成/删失比例。多故障结果需实际重跑，不能由一次故障曲线线性混合。

### Workflow 并发扩展

【C1 / C2 结果待补】固定模型、物理资源与一次预定故障，扫描最大活跃 Workflow 数 4、8、16、32、64。三系统在每个相同 C 下配对，主图分别展示 F1 goodput 和尾部响应时间，F0 作配对服务表。HBM、CPU 与链路观测用于解释容量拐点；Workflow 并发与单步 request batch size 分开报告。R1/R2/C1/C2 的空布局只放在 [实验设计](EVALUATION_DESIGN.md#仅供设计检查的扩展空布局)，不当作结果图插入正文。

### 模型与并行规模

【留空：DP size、Model 与 TP。】

### 与其他故障恢复基线比较

【留空：先匹配故障域、并行方式和资源预算，再比较 Related Works 中可复现的基线。】

### 算法消融

【留空：算法 2 与算法 3 分别消融，待算法 2 冻结。】
