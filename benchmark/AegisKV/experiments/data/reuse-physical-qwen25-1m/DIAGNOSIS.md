# Qwen2.5-7B-Instruct-1M：HBM/DRAM 恢复曲线接近的原因

2026-09-20。原完整模型测量为作业 **1516025**；本次算子诊断为 **1516090**。

源码、实际 CUDA launch trace 和同输入算子对照确认了原生 DCA 尾部算子的低并行度瓶颈：SGLang 当前关闭稀疏加速的 DCA Prefill 路径逐个 query head 执行，并沿用 `num_splits=1`。在 batch=1、64-token 尾部上，每次关键 Attention kernel 仅启动一个线程块。这个共同计算瓶颈是原完整模型 HBM/DRAM 相对差距较小的强证据解释；尚未完成优化前后完整模型的 HBM/DRAM 配对重测，不能宣称已量化其对两条曲线的全部影响。诊断对照仍保留 DCA 算法，不能把实现瓶颈泛化为 DCA 算法必然慢或必然削弱 HBM 收益。重复 KV gather 是单层 profile 中的次要开销。本次证据不支持把约 16 秒的耗时主要归因于没有 NVLink。

### HBM/DRAM 差距的因果边界

当前计时比较的是“历史 KV 已驻留 GPU 后完成尾部计算”和“先从 pinned DRAM 搬回相同 GPU KV 缓冲区，再完成同一尾部计算”。DRAM 路径的 Attention 也从 GPU HBM 读 KV；这不是 Attention 直接读取两种存储介质的带宽对比。当前传输与计算不重叠，因而忽略运行波动时，HBM 相对降幅约为 `T_H2D / (T_H2D + T_shared_tail)`。实现低效放大的是共有计算项及分母；它不消除省下的搬运工作。

已确认：单层原生实现存在瓶颈，保留 DCA 的合并-head 对照可显著降低该层耗时。强支持的解释：原模型约 15.9 秒的共有尾部时间掩盖了约 1.48 秒的两路径绝对差值。尚未验证：优化后的完整模型 HBM/DRAM 延迟、收益比例和通信占比，以及 Peer-HBM 备份系统的端到端收益。此前“已定位主因”的简写应按这些边界理解，不能等同于已完成完整模型反事实消融。

## 测量边界与来源

- 原模型：BF16、TP=2、28 层，每 rank 14 query heads / 2 KV heads，历史 KV 已知、尾部 64 tokens；HBM 表示已驻留在接管 TP 组，不含 Peer GPU 到接管 GPU 的搬运。
- 诊断：两张 A100-PCIE-40GB，PHB 连接、无 NVLink；节点 agent-7，原测节点 agent-64。相同 GPU 型号和拓扑类别，不是原节点逐算子重放。
- 诊断使用随机 BF16 Q/K/V，形状与实际模型每层一致；不加载权重，不构造完整模型历史，不代表优化后的模型延迟或模型质量测试。
- 诊断直接调用原生 DCA Attention 路径，源码 SHA256 与原运行记录严格匹配：`86fc86a8b2544a22294a3449c39bab689760239326ddbb8be4a95c3d577f18b7`。
- 8K、64K、1,010,000 三个长度，每个 variant 一次预热、三次计时；CUPTI profile 另行采集，不计入这三个样本。
- 诊断程序：[diagnose_attention.py](diagnose_attention.py)。原始数据、Chrome traces、operator 汇总：[blsc/results/1516090/](blsc/results/1516090/)。机器可读提取结果：[diagnosis-summary.json](blsc/results/1516090/diagnosis-summary.json)。

## 直接证据

1. [DCA 源码](blsc/kernel-source-inspection/dual_chunk_flashattention_backend.py) 第 788 行按 query head 循环，第 811 行逐 head 调用内层 DCA；第 1407 行附近调用 `flash_attn_varlen_func`，没有覆盖 `num_splits`。
2. 从实际安装环境取回的 [flash_attn.py](blsc/kernel-source-inspection/flash_attn.py) 中，`flash_attn_varlen_func` 的默认 `num_splits=1`。来源与哈希保存于 [runtime-flash-attn-source.json](blsc/kernel-source-inspection/runtime-flash-attn-source.json)。
3. 1,010,000 tokens 下 DCA 有 intra、succ、inter 三部分，每 rank 的 14 heads 因而产生 **42 次** Attention kernel。CUPTI trace 显示这 42 次 launch 的 grid **全部为 `[1,1,1]`**。GPU 有 **108 个 SM**；每个此类 kernel 只能使用其中一个 SM。GPU utilization 显示 busy 不等于所有 SM 都充分工作。
4. 同一层的 1M profile 中，Attention kernels 合计 **529.832 ms**，占所有 CUDA kernel 时间 **94.30%**；84 次 KV gather 合计 **30.683 ms**，占 **5.46%**。这里的分母是该 profile 的 CUDA kernel 时间和 **561.861 ms**，不是原完整模型恢复时间，也不把 CPU 与 CUDA 的重叠区间重复相加。

## 消融对照

诊断对照把 14 个 query heads 一起送入同一个内层 DCA 函数，由 FlashAttention 处理 GQA；保留三段 DCA 运算，未改为普通全局 Attention。为了使多 head 的 DCA 合并正确，诊断子类还恢复了正确的 LSE `[heads, queries]` 布局：上游 reshape 在原来单 head 情况下有效，直接套到多 head 会改变 LSE 排列。因此不能只删除外层循环就视为可用补丁。

1,010,000 tokens，单层算子结果：

| 指标 | 原生逐 head | 合并 heads 的诊断对照 |
|---|---:|---:|
| Rank 0，三次计时中位数 | 566.171 ms | 39.637 ms |
| Rank 1，三次计时中位数 | 567.153 ms | 39.834 ms |
| Rank 0，Attention kernel 次数 | 42 | 3 |
| Rank 0，Attention kernel grid | `[1,1,1]` | `[4,2,1]` |
| Rank 0，Attention CUDA 时间 | 529.832 ms | 37.678 ms |
| Rank 0，KV gather 次数 | 84 | 6 |
| Rank 0，KV gather CUDA 时间 | 30.683 ms | 1.534 ms |

单层算子约加速 **14.3 倍**。两个 ranks 在全部三个长度的输出 `max_abs=0`、`relative_l2=0`。这是所测随机张量的 Attention 输出一致，不是完整模型 KV/hidden/decode 的回归验证；没有把此加速倍数用于修改论文曲线。

将原生单层 566.171 ms 乘以模型 28 层约为 **15.853 s**，与原模型 HBM 路径 **15.895 s** 同量级且接近。这只是基于层数的量级核对，不是对原模型 15.895 s 作精确分解。64K 样本存在抖动，全部保留；主要归因使用稳定的 1M 对照和真实 kernel trace。

## 排除与次要因素

- 两 rank 对 **448 KiB** 张量各执行 **56 次 all-reduce** 的独立诊断，中位数约 **7.23 ms**。它不测模型中的 rank 等待、不证明 TP=2 最优，但该拓扑上的这种通信量本身无法解释 16 秒级耗时。不能将它报告成原模型的实测 NCCL 占比。
- 两 rank 同时恢复一层 1M K/V，各传 **1,034,240,000 bytes**，中位数约 **43.06 / 43.07 ms**。这是单层 pinned-host H2D 测量；主机缓冲区复用、NUMA 分配与原完整模型不同，不应直接替代原模型 H2D 总时间。
- 原模型的 HBM=15.895 s、DRAM=17.373 s，差值 **1.478 s**。共同 Attention 开销很大，因而省掉 H2D 只占总延迟约 8.5%。这个差值来自两个独立计时样本，不能当成独立测得的纯 copy 时间。
- KV gather 的冗余确实存在，但 profile 表明它不是最大的耗时来源；CPU/Python 同步也不是这份 1M 算子 profile 的主要解释。

## 对论文与后续修复的含义

原图是该实现配置的真实结果，但强烈受尾部 Attention 实现限制。它可说明复用比当前完整重算便宜，不能用来断言 HBM 相对 DRAM 普遍只有约 8% 的收益。

后续修复应先合并 GQA heads、修正多 head LSE 布局，并检查 split-KV / 自动 split 配置是否适合短 query 和长 KV。合并后的 grid 仍只有 8 个线程块，因此此次诊断也不代表充分优化。必须用真实模型的 KV、hidden 和 next-token 检查验证新路径，再按相同 M/64 终点重新测量三条曲线；不能把本报告的单层时间直接作为论文的新数据。

本次任务只定位原因，保留原始测量和论文图像，不改写已测数据。

## 上游版本核对（2026-09-20）

本次运行是 `sglang 0.5.10rc0`，不是当前最新版本。GitHub 官方 API 报告最新稳定版为 **v0.5.20**，发布时间 **2026-09-18 22:41:33 UTC**（香港时间 9 月 19 日）。

- **v0.5.19**：直接下载该 tag 源码，非稀疏 DCA 路径第 818 行仍逐 query head 调用内层函数；其 FlashAttention 包装层第 244 行仍默认 `num_splits=1`，DCA 调用没有覆盖该参数。因此这个版本没有消除本次定位的两个实现因素。没有运行新版本的 GPU 性能测试。
- **v0.5.20**：已删除 Dual Chunk Flash Attention 后端。删除 PR [#32114](https://github.com/sgl-project/sglang/pull/32114) 于 **2026-09-10 07:12:02 UTC** 合并，merge commit 为 `c0b790cf7fe6dc1516c3ec1f23de9b37baca654a`；官方 [release notes](https://github.com/sgl-project/sglang/releases/tag/v0.5.20) 将删除列为 breaking change，对应 tag 的原 DCA 源码 URL 返回 404。这不是该路径的性能修复，现有实验配置不能直接原样迁移。
- 维护者在上述 PR 中给出的背景是：该后端是 Qwen 1M 模型家族的可选路径，底层 kernel 约一年没有功能变化。不能将此说明扩展成“SGLang 所有 Attention 后端都未维护”。
- v0.5.20 也停止发布 CUDA 12 系列 wheels/images；若另行升级，要重新检查本实验 A100、ARM64、驱动和 CUDA 兼容环境，不能视为原环境中无代价替换版本。

官方 API 原始响应、v0.5.19 源码及哈希保存在 [upstream-version-check/](blsc/kernel-source-inspection/upstream-version-check/)。搜索引擎缓存的 `main` DCA 源码仍可能显示删除前内容，当前判断以发布 tag、实时 API 和合并记录为准。本次核对未升级远端环境、未新增 GPU 用量。

## vLLM 源码对照（2026-09-20，仅源码审查）

直接核对了 vLLM **v0.9.2**、**v0.10.2** 及 QwenLM 的 **dev/dual-chunk-attn** 分支。三个实现的 DCA 非稀疏 Prefill 分支均存在逐 query head 切片、逐 head 调用 `_dual_chunk_flash_attn_prefill_func` 的循环，分别位于归档源码第 664、665、603 行。v0.10.2 还保留逐 head KV 收集和多 head 情况下需要额外检查的 LSE reshape。因此切换到这些 vLLM 实现不能自动消除已定位的逐 head 调度因素；不把 SGLang 的实测 kernel grid、16 秒延迟或 14.3 倍消融加速直接套到 vLLM，它们仍需针对具体 FlashAttention 版本做运行验证。

这些实现的稀疏分支将全部 heads 传入内层 DCA，与本实验关闭稀疏加速的分支不同。启用稀疏加速会改变实验配置和注意力近似，需要独立验证正确性、质量和恢复终点，不能声称无需验证就解决全部问题。

vLLM **v0.11.0** 的 [release notes](https://github.com/vllm-project/vllm/releases/tag/v0.11.0) 列出 V0 attention backends 清理（PR #25351）；该 tag 的旧 DCA 文件返回 404。当前发布版 **v0.29.0** 的内置 V1 backend registry 不包含 `DUAL_CHUNK_FLASH_ATTN`。因此最新版也不是可以原样替换当前 DCA 实验的路径。

下载源码、URL、SHA256 与检查时间保存在 [vllm-check/manifest.json](blsc/kernel-source-inspection/vllm-check/manifest.json)。这次对照没有安装 vLLM、没有 GPU 实验，也没有增加费用。

## 费用与结束状态

诊断作业 1516090 **COMPLETED**，Slurm 计费口径为 72 秒 × 2 GPU = **144 GPU·秒（0.04 GPU·小时）**。累计 **6791 GPU·秒 = 1.88639 GPU·小时**，仍在已授权 2 GPU·小时内，余量 409 GPU·秒；无该实验的运行中或排队作业。详见 [budget.json](blsc/budget.json)。

## 2026-09-20：改为1-token Prefill后的实测

| 总上下文 | HBM reuse (s) | DRAM reuse (s) | Full prefill (s) |
|---|---:|---:|---:|
| 8,192 | 0.287 | 0.296 | 1.036 |
| 65,536 | 1.110 | 1.189 | 10.586 |
| 262,144 | 4.238 | 4.550 | 91.733 |
| 1,010,000 | 15.785 | 16.989 | 1089.444 |

新矩阵为1516148，四长度同次TP2分配，C=M+1，全部配对检查通过。1M HBM/DRAM为15.785/16.989秒；少算63个新token没有消除公共路径的高开销，不能将原来的接近仅归因于64-token设置。独立随机BF16大buffer读取1516171测得HBM/H2D为1079.20/23.98 GB/s；这不能替代对真实attention内核的profiling。旧单层DCA诊断仍支持原实现的低并行度问题，但尚未运行修复DCA后的完整模型反事实。

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
