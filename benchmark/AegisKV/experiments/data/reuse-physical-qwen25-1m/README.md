## Current: sparse four-path figure (1517208)

共享文件系统四路径完整实测已完成。作业 **1517208** 在同一次 2×A100-PCIe-40GB 分配测量 Qwen2.5-7B-Instruct-1M、TP2、BF16、batch1。DRAM 和 Shared FS 都不与计算重叠。Shared FS 为实际 DPC 文件系统，直接读取真实历史 KV，再串行 H2D 和 1-token EXTEND；不是 SSD 介质测量。Linux 文件页在读前/后均未驻留，但 DPC/服务端缓存不受控。

| 总上下文 | HBM (s) | DRAM，无重叠 (s) | Shared FS，无重叠 (s) | Full Prefill (s) |
|---|---:|---:|---:|---:|
| 8192 | 0.090570 | 0.101757 | 0.183352 | 0.661433 |
| 65536 | 0.550348 | 0.680444 | 1.201179 | 20.125282 |
| 262144 | 0.893231 | 1.259789 | 3.451808 | 96.329280 |
| 1010000 | 1.305004 | 2.663166 | 10.156143 | 571.212672 |

HBM/DRAM 各三次取中位数和 min–max；Shared FS/Full Prefill 各一次，共 32 次正式计时，一个固定合成文本流。所有恢复、全文件哈希和串行时序校验通过；末尾 KV 文件已删除且作业已退出。原三路径 1517055 和早期失败结果保留，不与本次样本混合。

协议：[SHAREDFS_PROTOCOL.md](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/SHAREDFS_PROTOCOL.md)。原始数据和校验：[1517208](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208)。成本面板为 Figure 1(c)，更新 Markdown、LaTeX 和 canonical main.pdf。

累计实际使用 18227 GPU·秒（5.0631 GPU·小时），当前台账上限 5.5 GPU·小时。

## Historical: sparse three-path figure (1517055)

8K--1.01M physical measurements completed with the same sparse-generated KV.
At 1.01M: Full Prefill 565.93 s; HBM 1.266 s; DRAM without overlap 2.517 s.
The user requested serial DRAM only. Plot published-three-paths.csv.
Earlier overlap diagnostics remain in their original allocations;
the current v2 measurement script runs only three paths.
Protocol and selection decision: SPARSE_OVERLAP_PROTOCOL.md.
Raw records: blsc/results/1517055/. Source snapshot: sparse-archive/1517055/.
Old dense and 64-token results below are historical, not sparse measurements.

# Qwen2.5-7B-Instruct-1M：Prefill KV 填充实测

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

## 历史：原生 1-token 完整矩阵

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

## 历史：64-token 恢复协议与结果

状态（2026-09-20）：**实测完成，论文恢复成本图已更新。** 作业 1516025 在 agent-64 的两张 A100-PCIE-40GB 上完成 8K、64K、256K、1,010,000 四个上下文的三路径配对，全部正式点通过 KV、hidden state、decode 和后续 greedy token 校验。配置为 TP2、BF16、SGLang 0.5.10rc0 原生 DCA（关闭稀疏加速），一个固定输入，每路径一次正式计时。参考构造用作 Recompute 预热，HBM/DRAM 分别预热；没有误差线或独立 workload 统计推断。

累计实际用量 **6,647 GPU·秒（1.846 GPU·小时）**，包含卡型查询、失败、加载、校验及所有测量，低于授权的 7,200 GPU·秒。实验名下已无运行或等待的 GPU 作业。集群拒绝将最后作业从 45 分钟延长至 46 分钟，记录保留；该申请未生效，作业时限保持 45 分钟。

1516002 的五个 8K–128K 上下文各有三次计时，作为先期检查独立保留。最终图只使用 1516025 的同次分配。8K/64K 重叠点与先期中位数相差约 0.06%–1.27%，仅作跨运行诊断，不汇总为重复样本或置信区间。

| 总上下文 | HBM reuse (s) | DRAM reuse (s) | Recompute (s) |
|---|---:|---:|---:|
| 8K | 0.289 | 0.300 | 1.037 |
| 64K | 1.136 | 1.244 | 10.681 |
| 256K | 4.251 | 4.633 | 91.974 |
| 1,010,000 | 15.895 | 17.373 | 1088.527 |

数据：[JSON](blsc/results/1516025/measured.json)、[CSV](blsc/results/1516025/measured.csv)、[原始逐次记录](blsc/results/1516025/trials.jsonl)。这些是固定分块下的 worker 微基准，不是完整服务故障实验。

已修复 ARM64 wheel 缺少 A100 内核的问题：固定官方源码补编译 FA，实测 GPU 预检通过；显式使用官方 FlashInfer SiLU。1515991 成功分配 1,010,032-token KV pool，但在 8K 的普通整块与 M/64 分块校验失败，全部负结果保留。1516002 固定 M/64 请求边界，空缓存重算也先重建 M，再执行相同尾部；首轮得到零误差。不同分块的诊断保留于 `partition-diagnostic.jsonl`，不视为通过等价校验，不入图。该区别是测量条件，不能将结果称为不限定分块的最优恢复延迟。

已按授权删除 Qwen3-32B；其他模型保留。官方 1M 权重与配置完成 SHA-256 核验。当前快照见 `execution-status.json` 和 `blsc/latest-status.json`，二进制/构建来源见 `blsc/setup/`。旧 AIConfigurator 数据及图导出独立归档，物理图仅使用检查通过的数据。

## 当前修复与输出保护

- `blsc/build_sm80.py` 使用固定 SGLang/sgl-attn/CUTLASS 源码；启用 SM80，并仅编译本模型需要的 BF16、128 维注意力头。未修改注意力数值源代码。构建记录保留源码归档哈希和 CMake 变更。
- ARM64 通用库也没有 SM80；完整重编包含大量无关 MoE/量化内核。因此，适配器显式为 28 层 SiLU 选择 `flashinfer.activation.silu_and_mul`，保留 SGLang 原生 DCA，所有路径共享该实现。归一化采用已安装 SGLang 默认选择的 FlashInfer。不能将此运行称为原 wheel 的默认完整配置。
- `blsc/gpu_kernel_check.py` 在权重加载前检查小规模 GQA、分页 decode、SiLU、RMSNorm；这些是兼容性/正确性预检，不进入延迟图。
- `sg_backend.py` 在未计时的参考 prefill、tail、decode 中检查通用算子调用，拒绝进入缺少 SM80 的 CUDA 算子；保留各 rank 的审计文件。
- 固定页 host 缓冲区按最大计划历史分配一次，各上下文复用前缀视图；计时仍只包含实际历史字节的 H2D。避免不同长度的 pinned allocator 缓存累积导致 1M 主机内存超限。
- 每个上下文完成全部配对、预热和计时检查后写入 `context-<C>-COMPLETE.json`。整个作业未完成时，`aggregate.py --completed-contexts-only` 只能提取这些完整上下文，并记录遗漏长度和原始文件哈希。默认仍拒绝不完整作业；不能因为某条路径先完成就单独画出该点。
- 科研绘图入口为 `experiments/scripts/paper/render_reuse_physical.py`。仅接受完整配对且验证通过的物理结果。

## 固定协议

- 官方权重 `Qwen/Qwen2.5-7B-Instruct-1M`，revision `e28526f7bb80e2a9c8af03b831a9af3812f18fba`；真实完整权重、BF16、batch 1。
- 首先使用远端现有 SGLang 0.5.10rc0 / Torch 2.9.1 的原生 `DualChunkFlashAttentionBackend`，保留运行时源码 hash 和 Git revision。使用模型官方 DCA 配置，关闭可选稀疏加速；不能将此实现标为 MInference 稀疏路径。此前尝试的独立 vLLM 0.10.2 环境因下载缓慢已暂停，代码分支保留为备用，不能把不同后端结果合并成同一曲线。
- BLSC 当前计划使用同节点 TP2、PP1、8K prefill 分块。已抽查两节点为 A100-PCIE-40GB；实际型号、显存、驱动和拓扑仍以每次分配内记录为准。一次曲线使用固定 TP 组和同次分配，不拼接不同设备或分配；pilot 单独归档。
- 总上下文 `C=M+64`：最终绘图为 8K、64K、256K、1,010,000。K=1024，最后一项为模型精确上限。
- HBM：完整历史已驻留接管 TP 组；DRAM：相同完整历史来自 pinned host DRAM，实际 H2D 完成后计算尾部，无传算重叠；Recompute：空缓存开始，按不超过 8K 的分块重建历史 M，再执行同一段 64-token 尾部。三路径固定 M/64 恢复边界及终点。另一个合并尾部的分块方案未通过状态等价校验，不能混入此曲线。
- 模型权重、输入 token IDs 和缓存容量预先准备；计时包含请求状态绑定、原生 attention 元数据准备、必要 H2D 及 forward。终点为全部 64-token 尾部 KV 完成，CUDA 同步；排除词表投影、故障检测、排队和故障前备份。多卡取各 rank 同步后 elapsed 的最大值。
- DCA 的长度缩放依赖完整 prompt 长度。构造历史时也在 `SequenceData` 中保留完整 C，保证三条路径使用相同缩放；不能先按 M 的缩放生成备份，再与 C 的重算比较。
- 预设五种合成重复文本/代码流，原目标为每条路径预热1次、计时5次；当前累计2 GPU·小时约束下最终采用四长度、单输入、单次计时矩阵，实际输入数、重复数和长度以每次 metadata 为准，交错路径顺序。这是延迟微基准，五种输入不是五份独立 agent workload。每输入取重复中位数，再跨输入取中位数；保留原始计时范围。
- 首次 Recompute 校验固定边界的空缓存重建与参考状态；最短上下文另做一次未计时的普通分块诊断并保留结果。逐次比较尾部全部层 KV、尾部 hidden states、decode-mode 最后已知 token 的 hidden states 和后续 greedy token。decode 检查重放第 C 个 token，不执行超过官方上限的位置；词表投影在计时外。保留误差和失败，正确性失败的数据不入图。
- 不将 worker 微基准延迟称为完整服务故障恢复时间；完整 HBM 驻留也不等同于有限 Peer 容量。

## 可复现文件

- `measure.py`：配对恢复实测、KV 状态检查和逐次 JSONL。
- `sg_backend.py`、`launch_sglang.py`：现有 SGLang 的原生 DCA、显式 ForwardBatch 和实际 KV pool，不修改框架源代码。
- `run_sglang.sbatch`：Slurm 启动，默认完整矩阵；可通过环境变量缩小预检规模。`run.sbatch` 为尚未运行的 vLLM 备用入口。
- `env.sbatch`、`preflight.py`、`job_environment.sh`：独立且逐次复查的 GPU/框架预检、同型号设备检查和任务专属临时目录。
- `aggregate.py`：默认仅接受完整运行；显式 `--completed-contexts-only` 可提取已提交的完整上下文，输出 JSON/CSV 并标记遗漏长度。
- `submit_when_ready.py`：等待就绪并提交两级 Slurm 作业的一次性启动器，拒绝重复提交；不修改论文。
- `model-weight-manifest.json`：官方固定 revision 的四个权重分片名称、大小、SHA-256。
- 当前远端任务目录：`/home/bingxing2/home/scx8q31/aegiskv_reuse_qwen25_1m_20260919/`；旧 HK 目录仅作归档。
- 结果按 Slurm job ID 归档；`metadata.json` 固定配置，`trials.jsonl` 保留成功/失败及预热值，`COMPLETE` 仅在全部要求通过后写入。

官方参考：[模型配置](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-1M/blob/e28526f7bb80e2a9c8af03b831a9af3812f18fba/config.json)、[长上下文部署说明](https://qwenlm.github.io/blog/qwen2.5-1m/)、[vLLM 原生 DCA 后端](https://github.com/vllm-project/vllm/blob/v0.10.2/vllm/attention/backends/dual_chunk_flash_attn.py)。

## 图与论文更新入口

当前排版中恢复成本图是 **Figure 1(c)**（本任务早期称 Figure 2），资产名仍为 `paper/figures/recovery-cost.pdf`。原四模型静态数据和导出保存在 `../reuse-aiconfigurator-max-context-h100/`；工作流反事实图继续使用自己的静态条件，不改标为物理实验。

结果同步后，完整运行使用：

```bash
python3 benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/aggregate.py \
  benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1516025
python3 benchmark/AegisKV/experiments/scripts/paper/render_reuse_physical.py \
  benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1516025/measured.json \
  --output benchmark/AegisKV/exports/reuse-physical/recovery-cost
```

若整个作业因预算或错误结束但已存在完整上下文，聚合必须显式添加 `--completed-contexts-only`，并保留 `run_complete=false` 与遗漏长度。绘图程序验证原始文件哈希、模型、精度、固定尾部边界和三路径配对；单次计时不显示误差线。当前原生尺寸为 2.24×2.25 英寸，适配三联图中的实际宽度。

正式导出复制到论文资产后，同步 `paper/background_and_motivation.tex` 和 `paper/paper_draft.md` 的条件、范围与数字，再运行 `render_draft_figures.py` 和 `build_paper.sh`。编译 PDF 位于 `paper/main.pdf`。图源、清单和按实际正文宽度的渲染核对位于 `exports/reuse-physical/`；最终 PDF 按当前约定发布到 `paper/main.pdf`，其余中间文件仍放在 `exports/`。
