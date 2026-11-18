# AegisKV GPU failure：注入、故障率与恢复时间

> 调研日期：2026-08-31。本文只讨论 MoonKVSim 第一版支持的
> `GPU_FAILURE`：目标 GPU fail-stop，计算与拷贝引擎立即不可用，GPU
> 上全部 HBM/KV 状态丢失；故障域之外已经 `COMMITTED` 的 Peer HBM 或
> Mooncake Store DRAM 副本仍可用于恢复。不把 fail-slow、NIC、主机、SSD/NVMe
> 或静默错误混入这一故障类型。经过固定的 GPU 恢复时间后，该 GPU 以空 HBM、
> 已重新装载模型权重和固定运行时的状态重新可用；丢失的 KV 不会复活。

## 结论

`failure.json` 只保留五个纸面可解释的输入：schema、故障类型、单次运行故障数、
条件化注入进度和固定 GPU 容量恢复时间。GPU 型号/数量、网络和 reroute 延迟属于 `engine.json`；
HBM 全损失、Store DRAM 跨故障域存活以及“注入即检测”是当前 `GPU_FAILURE` 的
固定语义，不在每份配置中重复声明。

实验必须分成两个协议，不能用一个不真实的高故障率兼任二者：

1. **条件化单次运行多故障**：每个 failure cell 只运行一次完整 workload，并在同一
   GlobalDES 虚拟时间线上注入 `failure_count` 次故障。第 `i` 次故障的目标 workload
   位置为 `i/(failure_count+1)`；每个实验 variant 在包含已有前序故障的自身 oracle
   中选择该位置附近、自然路由且安全的 focus span/GPU，再在该请求的固定计算进度
   注入。所有 variant 共享 workload 目标百分比与选点算法，但不强行 pin 到同一个
   物理请求/GPU，从而不改变各系统本来的路由决策。这是当前
   E2 matrix 已实现的协议；它测量的是“给定故障次数条件下”的恢复代价，不是工业
   发生概率。
2. **故障率实验**：如后续需要按工业故障率外推，应使用独立的 rate-analysis
   协议、真实时间跨度、多 seed 和长期 workload。v5 的条件化 `failure.json`
   不再携带 MTTF；当前 matrix 生成的是确定性均匀分布的多故障事件，因此不得把条件化结果
   描述成长期随机故障实验。

本文的主要“恢复时间”是**从故障发生到该 GPU（或等价替换容量）重新可调度**的
时间，因此使用固定输入 `gpu_recovery_time_minutes`。它表示自动 reset/restart、
健康检查或等价替换容量重新就绪的总时间，但不表示原 HBM 内容恢复。

请求恢复延迟是另一个指标，仍由模拟输出：

\[
T_{recovery}=T_{detect}+T_{reroute}+T_{restore}+T_{recompute/replay}+T_{resume}.
\]

其中恢复传输时间由可用的最长连续 `COMMITTED` 前缀、源层级、字节数、链路与
拷贝引擎争用决定；重算时间由未覆盖 token 和模型计算日历决定。固定 GPU
恢复时间是容量恢复 MTTR；上式描述的是应用请求恢复延迟，二者必须分别报告。

## 1. 文献中的故障怎样注入

| 工作 | 注入方式 | 能借鉴什么 | 不能直接照搬什么 |
|---|---|---|---|
| [DéjàVu](https://arxiv.org/abs/2403.01876) | OPT-66B、4-stage pipeline；在 token generation step 1200 注入一次 stage failure，另在 600/1200/1800 秒注入故障 | 在确定的逻辑进度或时间点注入，且让 baseline 与方案共享同一故障点 | 论文没有给出工业故障率，也没有公开一个可直接采用的 heartbeat timeout |
| [FailSafe](https://arxiv.org/abs/2511.14116) | 长期实验缩放 GCP availability trace；每个 failure event 随机禁用一块 GPU，recovery event 随机恢复一块；在线恢复实验在第 250 个请求后 100 ms 注入一块 GPU 故障 | 分开做 trace-driven 可用性实验和一次条件化恢复实验 | 这是预印本；64-GPU 实验由单台 8×H100 服务器仿真 8 个节点，且把 reconfiguration 固定为 10 s，并非测得的 GPU 修复时间 |
| [Llama 3](https://arxiv.org/abs/2407.21783) | 真实 16K H100 同步训练中由硬件/软件自然产生中断，NCCLX watchdog/heartbeat 自动超时和定位 | 工业系统以监测、超时、隔离故障 GPU/主机处理真实中断 | 这是训练作业中断，不是受控 KV-serving 故障注入 |

MoonKVSim 的第一版应采用**逻辑原子 fail-stop**，而不是模拟一个含糊的
`CUDA error`：

1. 在事件时间戳把目标 GPU 标记为不可用；
2. fence 其活动/排队计算和依赖该 GPU 的传输，取消未完成预留；
3. 目标 GPU 的 HBM ledger 全部转为不可用，不能从同一 HBM 继续读；
4. 不删除独立故障域中已经提交的 Peer/Store 副本；
5. 在同一虚拟时间戳执行检测事件并选择健康 DP rank，只从兼容且连续的已提交
   前缀恢复，其余部分重算或 silent replay；
6. 到达固定 `gpu_recovery_time_minutes` 后生成 `REPAIR_COMPLETE`：GPU 重新进入健康
   集合，模型权重与固定运行时占用重新建立，Peer/normal HBM KV 池为空。

这与“进程被 kill 但显存对象还可以被测试代码访问”的注入不同，后者不能证明
HBM 全损失语义。

## 2. 故障频率怎样参数化

### 2.1 推荐参数

如果后续建立独立的长期 rate-analysis，可以使用 per-GPU MTTF 描述故障发生
间隔。对长期、可替换 GPU 的 fleet，同一个量也常被称作单 GPU MTBF；只统计错误
事件的测量论文则常报告 MTBE。三者不能在文稿里无说明地互换，也不应塞回当前
条件化多故障配置。

`GPU-h`（GPU-hour）是累计设备暴露量：1 块 GPU 运行 1 小时等于 1 GPU-h，
100 块 GPU 运行 10 小时等于 1,000 GPU-h。假设单 GPU MTTF 为 100,000 h，表示
单块活跃 GPU 的平均故障间隔为 100,000 小时；它不是一次故障要修 100,000
小时。若有 (N) 块独立活跃 GPU，集群平均首次故障间隔约为 (100000/N) 小时。

可选的第一阶 rate model 可采用正常寿命期内、各活跃 GPU 独立且恒定 hazard 的
指数模型：

\[
\lambda_{gpu}=1/MTTF_{gpu},\qquad
\lambda_{cluster}=N_{active}/MTTF_{gpu},
\]

\[
P(\text{at least one failure in }T)
=1-\exp(-N_{active}T/MTTF_{gpu}).
\]

指数模型适合作为可复现的第一阶模型，不代表真实故障永远独立。设备老化、同批次
硬件、温度、固件、机架电源和运维事件都会造成非恒定或相关 hazard；有可信的
时间序列时，应增加 trace-replay 模式，而不是继续调小 MTTF 来拟合 burst。

### 2.2 工业量级

| 来源 | 公开观测 | 与本配置的关系 |
|---|---|---|
| [Story of Two GPUs, SC'25](https://arxiv.org/abs/2503.11901) | 1056 块 A100/H100、1170 万 GPU 小时；不可纠正 HBM 错误的 per-GPU MTBE：A100 为 283,271 h，H100 为 88,768 h | 最直接的现代 GPU/HBM 锚点；但 MTBE 是错误事件，不等于每次都发生“整块 HBM 永久丢失” |
| [Llama 3](https://arxiv.org/abs/2407.21783) | 54 天内 419 次 unexpected interruption，论文称 58.7% 为 GPU issues | 约 246 次 GPU 类作业中断，即 16K 作业约每 5.27 h 一次；若假设恒定 16,384 GPU 且每次由一个 GPU 触发，等效约 86,000 GPU-h/事件。该数值是本文推导，不是 Meta 直接报告的单 GPU MTBF |
| [Google TPUv4 resiliency](https://www.usenix.org/conference/nsdi24/presentation/zu) | 平均每天 0.08% 的 TPU machines、0.005% ICI links、0.04% OCS 发生故障 | 说明论文也常报告 component/day；0.08%/day 在恒定 hazard 下约等于 30,000 machine-h，但 TPU machine 不是单 GPU，不能直接当作 A100 MTTF |
| [504-GPU B200 operational report](https://arxiv.org/abs/2605.09370) | 55 天、504 GPU、10 个 XID-identified GPU failures | 粗略暴露量约 66,500 GPU-h/XID；样本只有 10 个且是技术报告，适合做压力档参考，不适合单独确定默认值 |
| [SuperBench](https://www.usenix.org/conference/atc24/presentation/xiong) | Azure 两年验证数十万 GPU；三个月约 2000 个 regression/failure incidents，GPU memory 是最大的 incident source | 证明主动筛检和灰故障很重要，但论文未给出可直接换算的单 GPU fail-stop MTBF |

没有一个跨代际、跨故障定义的“工业统一 GPU failure rate”。如果另做长期
rate-analysis，建议扫描：

- **默认**：`100000` GPU-h，取 H100 HBM 与 Meta 大规模 GPU 类中断的同一数量级；
- **压力档**：`50000` GPU-h；
- **乐观/A100-HBM 档**：`300000` GPU-h，接近 SC'25 的 A100 HBM MTBE。

因此长期分析应报告 `[50000, 100000, 300000]` 的 sensitivity，而不是只展示一个
对 AegisKV 有利的 rate。这些数值不属于当前 `failure.json`。

以默认 100,000 GPU-h 为例，独立 hazard 下：1024 块活跃 GPU 的平均首次故障
间隔约 97.7 h；16,384 块约 6.10 h。8 块 GPU 暴露 1 h 至少失败一次的概率只有
约 0.008%，这正是短实验不能靠真实 rate “等到一次故障”、而需要条件化注入的
原因。

若在独立分析中把两分钟固定恢复时间视为 MTTR，则单 GPU 的一阶稳态可用率为
$A=MTTF/(MTTF+MTTR)$。取 100,000 h MTTF 时约为 99.999967%；这只是指数故障加
固定恢复的解析结果，不是对真实 A100 fleet 可用率的测量。

## 3. GPU 重新可用时间与请求恢复时间

公开数据跨越三个完全不同的层次：

| 层次与来源 | 观测值 | 解释 |
|---|---|---|
| KV-serving 应用恢复，[FailSafe](https://arxiv.org/abs/2511.14116) | Llama-3.1-70B：recompute 22 s、host KV backup 530 ms、完整方案 120 ms、oracle 15 ms | 最接近 AegisKV 的恢复数据；包含 KV/权重恢复，来自单台 8×H100 原型和逻辑故障注入 |
| KV-serving 请求影响，[DéjàVu](https://arxiv.org/abs/2403.01876) | 单次故障使 baseline microbatch latency 变为无故障的 1.91×，DéjàVu 为 1.24× | 论文强调端到端请求影响，没有给出一个可移植的固定恢复毫秒数 |
| 大规模训练作业重启，[Acme/NSDI'24](https://www.usenix.org/conference/nsdi24/presentation/hu) | ECC restart 中位/均值 1.8/2.8 min；CUDA error 2.0/78.3 min；node failure 21.5/102.8 min | 包含调度、诊断、checkpoint 和人工长尾，不应作为 KV 恢复带宽常数 |
| GPU 节点维修，[Story of Two GPUs](https://arxiv.org/abs/2503.11901) | 失败节点平均 service time：A100 0.88 h、H100 2.2 h；个别 H100 DBE 事件 19 h，另一个 contained ECC 重启约 2 min | 这是物理容量恢复 MTTR；若请求能迁移到健康 GPU，它不在请求关键路径上 |
| 训练编排恢复，[504-GPU report](https://arxiv.org/abs/2605.09370) | 自动重试间隔中位 11 min（配置 10 min delay），成功 episode downtime 中位 1.9 h，人工为 3.3 h | 说明 retry policy 会主导运维恢复时间，不能把它误认为 GPU 数据面恢复时间 |

本实验选择 `gpu_recovery_time_minutes=2` 作为自动检测、reset/restart 或等价容量
替换的快速恢复默认值，并把它换算为 120,000,000,000 ns 安排在 GlobalDES 全局
虚拟时钟上。两分钟由 SC'25 contained ECC restart 约 2 min，以及 Acme 的 ECC/
CUDA restart 中位数 1.8/2.0 min 提供量级参考；它仍是本项目的建模假设，不是
AegisKV 实测。SC'25 的 A100 平均 service time 0.88 h 描述更完整的物理节点维修，
而 Acme node failure restart 中位数为 21.5 min，因此两分钟不应泛化为所有故障。

因此 AegisKV 的主要恢复图应同时给出：

- 注入/检测到 reroute、restore、recompute/replay、resume 的分段时间；当前检测段为 0；
- 恢复源层级、恢复字节/token、重算 token；
- 受影响请求的 recovery latency、TTFT/TBT（若模型支持）及整个 workload WCT；
- 无故障与同故障点 baseline 的 matched pair；
- 固定 GPU repair time 单列为容量可用性指标，不计入已经迁移请求的恢复延迟。

当前不研究故障检测算法，因此不配置 `detection_delay_ms`。`FAILURE_INJECT` 先按
事件优先级执行 GPU fail-stop、HBM 丢失和 fence，随后在**同一个 GlobalDES 虚拟
时间戳**执行 `FAILURE_DETECT`，即固定检测延迟为 0。注入和检测是每次故障的两个
因果事件；这不表示真实硬件能够零延迟检测。如果后续研究 heartbeat/watchdog，
应建立单独的 detection sensitivity 协议，而不是给主配置放一个无校准的 5 ms。

## 4. v5 配置契约

```json
{
  "schema": "moonkvsim.aegiskv.failure.v5",
  "type": "GPU_FAILURE",
  "failure_count": 2,
  "injection_progress_percent": 60,
  "gpu_recovery_time_minutes": 2
}
```

- `failure_count=2`：在同一个 fresh failure cell、同一份完整 workload、同一个
  GlobalDES 虚拟时钟中注入两次故障。脚本自动把目标位置设为约 33.3% 和 66.7%；
  `1/2/4/8` 分别映射为 `[50]`、`[33.3,66.7]`、`[20,40,60,80]`、
  `[11.1,22.2,33.3,44.4,55.6,66.7,77.8,88.9]`。百分比是目标位置；当
  workflow 数较少时，脚本按已完成
  workflow 比例选择最近的可行请求，因此实际参考比例可能离散。所有 focus span
  都必须属于同一个实验 context bucket，避免 failure-count sweep 混入不同上下文
  严重度。通用矩阵允许每个 variant 保持自然路由；论文成对比较则联合两个 profile
  冻结相同的 focus span、物理 GPU 和请求内计算进度。
- `injection_progress_percent=60`：每个 matched recovery cell 都在其 focus
  span 的整体计算虚拟时间进度 60% 处注入故障；它不是 decode-token 进度、失败
  概率或 workload 完成率。
- `gpu_recovery_time_minutes=2`：故障发生到 GPU/等价替换容量重新可调度的固定
  **虚拟时间**；恢复后的 HBM 为空。
- schema 固定 `GPU_FAILURE` 的 fail-stop/HBM-loss，以及
  仅允许故障域外 `COMMITTED` 副本恢复；注入与检测在同一虚拟时间戳。未知字段
  fail-closed。

未保留的字段不是被忽略，而是被移到唯一 owner 或固定为契约：

| 原字段 | 处理 |
|---|---|
| `enabled`、`allowed_types`、`semantics`、`effects` | v5 schema/运行时固定；scenario 决定是否注入 |
| 嵌套 `repair` | 压缩为一个 `gpu_recovery_time_minutes` 固定参数 |
| `per_gpu_mttf_hours` | 移出条件化多故障配置；如需要，归独立 rate-analysis 协议 |
| `detection_delay_ms` | 移除；当前固定为同一虚拟时间戳直接检测 |
| `target.topology`、`target.gpu_sku` | `engine.json` 唯一拥有 |
| `reroute_delay_ns` | `engine.control.reroute_ns` 唯一拥有 |
| `selection_scope`、`frequency.scenarios` 和说明文字 | matched-pair 实验协议拥有 |

## 5. 证据边界

当前配置和结果仍是 E2 modeled/preliminary：没有物理 CUDA/NCCL/RDMA 故障恢复
校准，也没有完成 rate-driven 随机多故障 matrix。SC'25、Meta、Google 等数据只
用于给 rate sweep 定数量级；FailSafe/DejaVu 数字只用于恢复结果 sanity check。
任何模拟结果都不能据此升级成工业可用性或 paper-ready 实测结论。
