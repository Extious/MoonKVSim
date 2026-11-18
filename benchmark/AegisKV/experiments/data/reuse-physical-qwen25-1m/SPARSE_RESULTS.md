> Historical three-path record. The current published figure adds the measured Shared FS path from allocation 1517208. See [SHAREDFS_RESULTS.md](SHAREDFS_RESULTS.md) and [SHAREDFS_PROTOCOL.md](SHAREDFS_PROTOCOL.md). The historical measurements below remain unchanged.

# Sparse Prefill: measured results, 2026-09-20

状态（2026-09-20）：**稀疏三路径完整实测已完成并更新论文。** 用户最新要求 DRAM 仅使用无 Overlap 路径。作业 **1517055** 在同一次 2×A100-PCIE-40GB 分配上完成 8K–1.01M，Slurm 为 COMPLETED；使用 Qwen2.5-7B-Instruct-1M、TP2、BF16、batch1，C=M+1。图中没有重叠 DRAM 曲线。

| 总上下文 | HBM reuse (s) | DRAM reuse，无重叠 (s) | Full Prefill (s) |
|---|---:|---:|---:|
| 8,192 | 0.087696 | 0.098522 | 0.664835 |
| 65,536 | 0.542814 | 0.649302 | 19.768273 |
| 262,144 | 0.848706 | 1.183545 | 95.996849 |
| 1,010,000 | 1.265548 | 2.516522 | 565.933926 |

HBM 相对串行 DRAM 在 1.01M 降低延迟 **49.71%**。三条路径都采用同一 MInference vertical/slash 配置与 DCA；请求长度超过 32K 时包括最后单 token 在内都使用稀疏 EXTEND。8K 使用 grouped dense DCA。Full Prefill 以至多 8K 分块生成相同历史，再执行同一末尾 token；HBM 和 DRAM 复用这份历史 KV。DRAM 在计时内搬运全部 M-token KV，复制同步后才计算。终点均为模型主体完成且全部 C-token KV 就绪，不含 lm_head。

**验证与样本。** 28 次正式计时、8 次复用预热均成功。HBM/DRAM 各三次正式计时，中位数与 min–max；Full Prefill 各长度一次；只有一个固定重复文本流。两 rank 各七组算子检查包含 1M／8K-query 最大形状，与原始稀疏算子的最大差值均为 0。64K 完整模型参考的 hidden 和新 KV 差值为 0；各长度检查新 KV、hidden、greedy token，以及复用后的完整历史 KV 逐字节一致性。256K／1.01M 不另跑完整 Prefill 预热，算子预检和短前向预热已披露。这些检查不构成长上下文任务质量评估。

**实现与失败保留。** 直接共享 GQA K/V，去掉重复展开副本；前缀每组最多两个 query heads，单 query 合并全部 heads；稀疏索引生成后及时释放分数张量及视图，使用 expandable CUDA allocator segments。1517028 在原始算子参考校验时 OOM，1517033 在 1M Full Prefill 的稀疏选择器处 OOM；均保留失败及部分结果。1516928、1517015 和 1517033 的 overlap 结果只作历史诊断。当前图全部来自 1517055，没有拼接短测或失败运行的数据。

**与旧 dense 结果的关系。** 此前 1516685 的 64K／256K／1.01M Full Prefill 为 7.49／58.76／655.41 s，本次为 19.77／96.00／565.93 s。因此这套分块稀疏实现并非在所有长度都更快。两组来自不同分配和实现配置，不能当作同次配对消融或宣称普适加速；当前图只回答同一稀疏配置下的 KV 复用比较。

累计实际用量 **15882 GPU·秒（4.4117 GPU·小时）**，低于最新总上限 **5.5 GPU·小时**；本轮新增使用 1.0306 GPU·小时，剩余总额度 1.0883 GPU·小时。所有本实验作业均已退出。

[协议与最新选取要求](SPARSE_OVERLAP_PROTOCOL.md)、[三路径 CSV](blsc/results/1517055/published-three-paths.csv)、[完整原始记录](blsc/results/1517055/trials.jsonl)、[发布校验](blsc/results/1517055/publication-validation.json)。当前成本面板为 Figure 1(c)，Markdown、LaTeX、图注和 `paper/main.pdf` 已同步。
