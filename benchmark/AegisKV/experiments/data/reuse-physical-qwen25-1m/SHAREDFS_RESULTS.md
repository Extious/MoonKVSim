# Shared-filesystem KV reuse results

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
