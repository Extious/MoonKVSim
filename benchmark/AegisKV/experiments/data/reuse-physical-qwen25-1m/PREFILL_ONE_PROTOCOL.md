# Prefill KV 填充与 HBM/H2D 带宽：新协议

用户于 2026-09-20 明确将原 64-token 故障恢复指标改为 Prefill 填充 KV 的时间。旧 `measure.py`、1516025 数据及其失败记录保留；不能重标成 1-token 测量，也不能把旧延迟除以 64。当前论文成本资产为 Figure 1(c) 的 `recovery-cost.pdf`，另一任务的编排保持不变。

## 模型测量

固定 Qwen2.5-7B-Instruct-1M 官方权重及原 revision、BF16、batch 1、SGLang 0.5.10rc0、原生 DCA（关闭可选稀疏加速），同一次分配中的 2×A100-PCIE-40GB、TP2。保留原适配器与运行时源码哈希，不把诊断中的分组 head 实现冒充生产模型测量。

总上下文 `C ∈ {8192, 65536, 262144, 1010000}`，历史 `M=C−1`。三个路径最终均得到全部 C 个 token 的 KV：

| 路径 | 计时开始时已有状态 | 计时工作 |
|---|---|---|
| HBM reuse | M 个 token 的全部层 KV 已在 GPU | 1-token Prefill/EXTEND |
| DRAM reuse | 相同 M 个 token 的 KV 位于 pinned host DRAM | 实际 H2D，完成后执行同一个 1-token Prefill/EXTEND |
| Recompute / empty-cache Prefill | KV 为空，输入和权重已准备 | 以不超过 8K 的块 Prefill 历史 M，随后独立执行同一个 1-token EXTEND |

计时终点为模型主体 forward 返回后 CUDA 同步：全部 KV 已填充，不含词表投影/采样。此终点包括最后一层 attention/MLP，**不是在最后一次 KV 写入处打点的最短时间**。没有故障检测、排队、接管、尾部重建场景；模型加载和缓存准备均不计入三路径延迟。

1-token 路径仍为 `ForwardMode.EXTEND`，不能因 token 数为 1 就换成 DECODE。DECODE 仅在计时外用于状态验证。1-token attention 仍需访问历史 KV；不能用纯带宽比预测整个模型的加速比。

M 通常不是 16-token 页的整数倍。新脚本将连续页展开为 token 视图，精确复制 `[0:M)`，只校验新 token `[M:C)`，避免丢失历史末页。所有路径的 DCA 长度参数均保留完整 C。固定 M/1 边界，不声称任意 chunk 划分具有严格数值等价。

为节省付费时间，每个上下文只执行一次计时的完整空缓存 Prefill，作为参考；HBM/DRAM 分别预热一次、计时三次并交错顺序。使用一个固定重复文本输入；三次计时不是三个独立工作负载。正式计时前执行短 Prefill/EXTEND 内核预热和审计，DECODE 仅在完整 C-token KV 已填充后于计时外审计，但没有重复整个长上下文作预热，因此首次形状相关准备可能包含在完整 Prefill 时间内，须保留这个限制。

HBM/DRAM 的全部层新 token KV、hidden、DECODE hidden 和 greedy token 必须与完整 Prefill 参考一致（rtol=0.01，atol=0.02；报告实际最大绝对误差）。所有路径通过后才提交 context 完成标记及聚合结果。每上下文的 Recompute 只有一次，不绘制其误差线；reuse 可绘制三次计时的 min–max，不称置信区间。

文件：`measure_prefill_one.py`、`launch_prefill_one.py`、`blsc/run_prefill_one.sbatch`、`blsc/submit_prefill_one.py`。绘图脚本 `experiments/scripts/paper/render_reuse_physical.py` 对两种协议分别检查，1-token 使用纵轴 **Prefill latency (s)**，不会接受把旧记录只改标签的做法。

## 初始常量数据带宽测量（历史对照）

作业 1516138，agent-16，单张 NVIDIA A100-PCIE-40GB，2026-09-20。测量源 `measure_bandwidth.py`，原始数据 `blsc/results/1516138/bandwidth.json`，设备/拓扑/CPU 绑定信息保留于同目录。

HBM 采用实际流式读取及每块 FP32 校验和，避免编译器消除读操作；不是将 D2D 复制的读写双倍字节误当读取带宽。H2D 使用 pinned host 连续 BF16 buffer、实际异步复制及 CUDA event 同步。分子均只计输入 payload 一次，GB=10^9 bytes。缓冲区均大于 A100 的 40 MB L2。每项预热 2 次、9 个计时样本取中位数；HBM 每样本 5 次读取均摊，H2D 每样本 1 次复制。校验和写入额外字节单独记录。

| 数据量 | HBM 读 GB/s | pinned H2D GB/s | HBM/H2D |
|---|---:|---:|---:|
| 64 MiB | 952.56 | 19.01 | 50.11× |
| 256 MiB | 1055.33 | 19.06 | 55.37× |
| 1 GiB | 1478.95 | 24.03 | 61.54× |

1 GiB 对应时间为 0.726 ms 和 44.676 ms。这是同一卡上两种操作的实测 payload 带宽，不是 DCA attention 带宽或 TP2 总带宽；不同数据量/时钟/NUMA 条件不可混为恒定设备速率。模型延迟必须由实际 forward 得到。

厂商标称对照（非实测）：[A100 40GB PCIe 产品说明](https://www.nvidia.cn/content/dam/en-zz/Solutions/Data-Center/a100/pdf/A100-PCIE-Prduct-Brief.pdf) 给出 HBM 峰值 1555 GB/s；[NVIDIA 架构说明](https://developer.nvidia.com/blog/nvidia-hopper-architecture-in-depth/) 明确 A100 PCIe Gen4 的 64 GB/s 为双向总和，单向为 32 GB/s，不能把 64 GB/s 用作 H2D 单向峰值。

## 预算与发布

原累计上限为 **2 GPU·小时**；用户随后明确追加 **1 GPU·小时**，当前累计上限为 **3 GPU·小时**。带宽作业只使用 18 GPU·秒；作业结束后累计 6809、剩余 391 GPU·秒。8K pilot 申请 2 GPU×2 分钟并预留每卡 60 秒终止余量，共 360 GPU·秒；通过原账本锁检查才提交，不自动重试。

完整四长度作业准备为 **2 GPU×30 分钟**，另预留每卡 60 秒终止余量，总预留 3720 GPU·秒。原数据中 1M 的完整 Prefill 单次约 1089 秒；新方案避免额外复制一次全长参考计算，以降低收费。预计本次完整矩阵可在 30 分钟时限内完成，但不保证新的 1-token 路径性能或首次形状开销。

若追加 **1 GPU·小时**，累计上限为 3 GPU·小时，可以覆盖此硬时限及终止余量。用户已明确授权，账本上限已改为 10800 GPU·秒，授权原文和时间保留。首次完整矩阵 **1516146** 在 64K 的短前缀 DECODE 预热中失败（orig_seq_lens=C，而实际页表只有 8193 tokens），55 秒×2 卡=110 GPU·秒；原始错误保留。修复为只在完整 C-token KV 填满后做 DECODE 校验，已提交 **1516148**，预留后累计最坏用量 10789 GPU·秒；pilot 与完整矩阵不能拼接为同次测量。

完整数据验证后，替换成本图并同步 Markdown、LaTeX 图注及 `paper/main.pdf`。建议图注核心口径："Measured Prefill latency on 2×A100 40GB (TP2, BF16): HBM and DRAM reuse a C−1-token prefix and execute one new token in EXTEND mode; empty-cache Prefill fills all C tokens with the same final one-token boundary. DRAM includes pinned H2D without overlap. Timing ends after the model-body forward, before vocabulary projection."

## 8K pilot 结果（已完成）

作业 **1516142**，agent-7 的同节点 2×A100-PCIE-40GB，运行 75 秒、实际 150 GPU·秒。`C=8192, M=8191`，三条路径使用相同输入和 M/1 边界。HBM 三次中位数 **283.782 ms**（283.625–284.630），DRAM **294.087 ms**（294.054–294.668），完整空缓存 Prefill 单次 **1028.195 ms**。全部新 token KV、hidden、DECODE hidden 对比最大绝对误差为 **0**；greedy token 相同。

原始文件：`blsc/results/1516142/measured.json`、`trials.jsonl`、`validation.jsonl`。pilot 只验证 8K，不能代替 1M；它不会与旧 64-token 长度矩阵拼接。当前总账为 **6959 GPU·秒 = 1.9331 GPU·小时**，原额度剩 **241 GPU·秒**，全部作业结束。追加 1 GPU·小时后可用 3841 秒，覆盖完整矩阵预留的 3720 秒。

此结果仍显示 HBM/DRAM Prefill 延迟相近，不能将原现象只归因于 64-token 设置。带宽微基准测到的是设备读能力，模型路径尚有 DCA 实现、权重读取、算子发射和 TP 通信等共同开销；没有用带宽推算替换模型实测。

## 最终完整矩阵与随机带宽复测

状态（2026-09-20）：**1-token Prefill 完整矩阵已完成并用于更新论文成本图。** 作业 1516148 同次分配、2×A100-PCIE-40GB、TP2、BF16、SGLang 原生 DCA，C=M+1；HBM/DRAM 仅做一个新 token 的 EXTEND，Full prefill 从空 KV 填充全部 C。四长度共 28 次正式计时，全部新 token KV、hidden 和 DECODE hidden 最大绝对误差为 0，greedy token 一致。HBM/DRAM 各三次取中位数；Full prefill 每长度一次。完整上下文预热限制见协议。

| 总上下文 | HBM reuse (s) | DRAM reuse (s) | Full prefill (s) |
|---|---:|---:|---:|
| 8,192 | 0.287 | 0.296 | 1.036 |
| 65,536 | 1.110 | 1.189 | 10.586 |
| 262,144 | 4.238 | 4.550 | 91.733 |
| 1,010,000 | 15.785 | 16.989 | 1089.444 |

随机 BF16 的单卡 1 GiB 带宽复测 1516171：**HBM 1079.20 GB/s，pinned H2D 23.98 GB/s，相差45.00倍**。此前常量数据 1516138 独立保留，不用其61.54倍作为主结果。纯带宽不等于模型加速比。

累计计费 **9958 GPU·秒（2.7661 GPU·小时）**，含所有加载、失败、pilot及带宽复测，低于最新授权 **3 GPU·小时**；所有实验作业已结束，剩842 GPU·秒。

[新协议](PREFILL_ONE_PROTOCOL.md)、[完整矩阵 JSON](blsc/results/1516148/measured.json)、[CSV](blsc/results/1516148/measured.csv)、[原始计时](blsc/results/1516148/trials.jsonl)、[发布前校验](blsc/results/1516148/publication-validation.json)、[随机数据带宽](blsc/results/1516171/bandwidth.json)。旧64-token实验及全部失败记录保留于下文，不作为当前口径。

随机复测采用 seed=17 的 BF16 正态数据；HBM 读取仍输出每块 FP32 校验和，并与 CPU 参考相对误差 1e-5、绝对误差 1e-3 检查。六组条件全部通过。1 GiB HBM/H2D 时间分别为 0.995/44.775 ms。不同作业的节点、时钟与数据模式未逐项控制，因此不将与常量版本的差异单独归因于压缩；当前论文明确采用随机数据结果。

## 2026-09-20：优化后的完整矩阵与发布

状态（2026-09-20）：**优化后的 1-token Prefill 完整矩阵已完成，成本图已切换为本次完整实测。** 作业 **1516685** 同一次分配的 2×A100-PCIE-40GB、TP2、BF16、batch1，测量8K、64K、256K、1,010,000，总上下文C=M+1。三条路径统一使用SGLang 0.5.10rc0的显式分组head DCA，修正多head LSE布局，固定num_splits=1、pack_gqa=False，关闭稀疏加速。未修改已安装框架，源码哈希与快照已归档。

| 总上下文 | HBM reuse (s) | DRAM reuse (s) | Full prefill (s) | HBM 相对 DRAM 降低延迟 |
|---|---:|---:|---:|---:|
| 8,192 | 0.08535 | 0.09690 | 0.75896 | 11.92% |
| 65,536 | 0.10138 | 0.19175 | 7.48964 | 47.13% |
| 262,144 | 0.32260 | 0.67825 | 58.76442 | 52.44% |
| 1,010,000 | 1.13897 | 2.51615 | 655.41018 | 54.73% |

HBM/DRAM各三次正式计时取中位数、误差线为min–max；Full prefill每长度一次，一个固定重复文本流。DRAM实际传输M个token的KV后再做相同1-token EXTEND，无传算重叠；计时终点为同步后的模型主体forward完成、全部C个token的KV可用，不含lm_head。完整HBM驻留不是有限Peer策略。

所有28次正式计时及配对校验通过。原生完整模型参考覆盖8K/64K，同历史KV上的原生/优化1-token比较覆盖全部长度；这些检查中KV和hidden最大绝对差值为 **0**，greedy token一致。每rank的八种随机算子形状覆盖DCA分块边界及1M单query。长历史每个位置没有另做原生完整重建，也未评估长上下文模型质量。

预热如实区分：短kernel和算子检查先行；8K/64K额外有原生完整Prefill预运行；256K/1.01M没有重复完整上下文预热，完整Prefill可能含首次形状相关开销。不可将计时重复当成独立workload或将范围当置信区间。

原生1-token矩阵1516148、旧64-token矩阵1516025、首个未通过真实模型校验的自动split候选1516661，以及通过验证的短pilot1516669均独立保留。原生/优化比较来自不同分配，未混合为同次重复样本。独立随机BF16带宽1516171仍为HBM1079.20GB/s、pinned H2D23.98GB/s，它不是整个Prefill的加速比。

最终累计实际用量 **12172 GPU·秒（3.3811 GPU·小时）**，包括资源检查、加载、失败、pilot和全部测量，低于用户确认的 **3.5 GPU·小时**；剩余 **428 GPU·秒**，该实验无运行或等待作业。1516685初始硬时限15分钟；在既有总预算内尝试延至17分钟被Slurm拒绝，时限未改变。

调度退出与数据完成分别记录：Slurm的批处理预终止警告出现在1M预热期间，worker继续完成全部正式计时及校验，并于10:03:58 UTC写入原始`COMPLETE`；延后的batch TERM trap在10:04:03 UTC退出，Slurm最终为FAILED/124。未重标调度状态，未伪造完成标记；全部28次正式记录、四个context标记、原始完整标记及哈希均通过独立审计，见`termination-audit.json`。无额外GPU重跑。

[优化说明与失败记录](./OPTIMIZATION.md)、[完整矩阵](./blsc/results/1516685/measured.json)、[CSV](./blsc/results/1516685/measured.csv)、[逐次计时](./blsc/results/1516685/trials.jsonl)、[发布校验](./blsc/results/1516685/publication-validation.json)、[与原生实现的独立运行对照](./blsc/results/1516685/native-comparison.json)。
