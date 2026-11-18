# DCA 公共计算路径优化

用户要求：优化公共计算瓶颈，并用真实测量更新 HBM/DRAM 比较图。保留原生实现的全部数据；图中收益由重新测量决定，不以单层加速倍数缩放原曲线。

## 实现

`dca_grouped.py` 对特定源码 SHA-256 的 backend 实例启用独立子类，不修改已安装 SGLang 文件：

1. 将原来每 rank 14 个 query head 的串行调用合并，由 FlashAttention 处理 14 Q / 2 KV heads 的 GQA。
2. 保留原生 DCA 的位置变换、长度缩放、intra/succ/inter 分区和结果合并，仍关闭可选稀疏近似。
3. 将 FlashAttention 的 LSE 按真实 `[heads, queries]` 布局转成 DCA 合并需要的 `[1, heads, queries]`；不沿用只在单 head 下有效的 reshape。
4. 当前通过验证的配置对所有 query 固定 `num_splits=1`、`pack_gqa=False`。最初自动 split 的候选未通过真实模型校验，记录保留于下文。不把原来 64-query profile 的 grid 当成新实现 1-query 的实测。

优化同时用于 HBM、DRAM 和空缓存 Prefill。总上下文仍为 C=M+1，复用路径仅计算一个新 token，DRAM 仍为 pinned H2D 后再计算、无传算重叠。真实 forward 完成且所有 KV 可用为计时终点，不含 lm_head。硬件、权重、BF16、TP2、batch1 不变。

## 验证与测量

`sg_optimized_backend.py` 在计时外对随机输入覆盖短/长 query、部分页及 DCA 有效分块边界 253952、507904 两侧；包含 1M 单 query。逐 rank 对比原生与优化输出，保存最大绝对误差和相对 L2 误差。

`measure_prefill_optimized.py` 使用真实权重：

- 8K/64K 先做原生完整 Prefill，对比优化完整 Prefill 的全部层新 token KV 和 hidden。
- 每个长度在同一历史 KV 上做原生/优化的完整模型 1-token Prefill 对照，校验全部层新 token KV、hidden 和 greedy token。
- HBM/DRAM 正式计时仍各三次，空缓存 Prefill 一次；配对检查沿用新协议，并增加独立优化校验文件的哈希。
- 长上下文的每个历史位置未逐一重算原生完整参考；算子边界检查和同前缀 1-token 比较不能被宣称为任意输入的严格等价证明或模型质量评估。

启动文件 `launch_prefill_optimized.py`、`blsc/run_prefill_optimized.sbatch` 和 `blsc/submit_prefill_optimized.py`。先在原累计3 GPU·小时额度内做硬时限2分钟的8K/64K验证，使用其实测耗时估算完整矩阵的需求。当前初始余额842 GPU·秒；不擅自增加累计额度。

## 发布要求

只有完整上下文和数值校验通过的数据进入图。优化实现及参数写入 metadata、图注和正文；旧原生曲线留存供对照。完整成本图继续位于当前 Figure 1(c)，保留其他任务的稿件编排。修改 Markdown、LaTeX、图注与 main.pdf，并查看实际最终尺寸导出。

## 第一次验证：保留负结果

作业1516661，94秒×2卡=188 GPU·秒。随机张量的8种DCA形状均通过算子容差检查；1M单query原生单层约563ms、优化约2.95ms。但真实8K模型原生/优化完整Prefill对比的hidden最大差值1.0、KV最大差值0.25，未通过原定rtol=.01/atol=.02，不能进入图像。作业亦在预终止信号附近结束；日志、错误和源码快照保存在results及optimization-archive/1516661-autosplit。

第二候选关闭自动split和GQA packing，固定num_splits=1、pack_gqa=False，仍合并heads并修正LSE。两个参数同时变化，不能从这两次运行中单独归因哪一个参数造成了第一候选的差异。

## 第二次验证：真实模型通过

作业 **1516669**，同次分配的两张 A100-PCIE-40GB，125 秒、250 GPU·秒。每个 rank 的八种随机算子形状输出最大绝对误差均为 **0**；1M 单 query 的单层中位数原生约 **563 ms**、优化约 **40 ms**。这是单层诊断，不用于缩放模型曲线。

8K/64K 的原生完整 Prefill 与优化完整 Prefill，以及同历史前缀的完整模型 1-token 前向，各层新 token KV 和最终 hidden 最大差值均为 **0**；greedy token 一致。HBM/DRAM 与空缓存参考的配对验证也全部为零差值。

| 总上下文 | HBM reuse (s) | DRAM reuse (s) | Full prefill (s) | HBM 相对 DRAM 降低延迟 |
|---|---:|---:|---:|---:|
| 8,192 | 0.07469 | 0.08459 | 0.64491 | 11.69% |
| 65,536 | 0.09815 | 0.17637 | 6.68143 | 44.35% |

每个 reuse 点为三次中位数，Full prefill 每长度一次；这些是 pilot 的两个长度，不是完整 8K–1M 矩阵。8K/64K 在正式优化计时前还执行了原生完整 Prefill 参考，因此不能称只做了短 kernel warmup。完整矩阵脚本已明确记录这一差异；256K/1.01M 不重复原生完整 Prefill。

包含早期资源检查在内，当前累计 **10396 GPU·秒（2.8878 GPU·小时）**，原 3 GPU·小时额度剩 **404 GPU·秒**。所有实验作业已结束。用户回复“确认追加”，已将累计上限增至 **12600 GPU·秒（3.5 GPU·小时）**。完整四长度作业 **1516685** 已提交：2 GPU、15 分钟硬时限，另预留每卡60秒终止余量，总预留1920 GPU·秒，最坏累计12316 GPU·秒。

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
