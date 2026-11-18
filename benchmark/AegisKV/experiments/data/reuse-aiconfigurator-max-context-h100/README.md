# Figure 2：每个模型的最大上下文

当前 Figure 2 数据。按 2026-09-18 用户要求，各模型曲线分别延伸到其上下文上限。全部为 CPU 上的 AIConfigurator 静态估计，未下载权重或执行 GPU 实验。上一版 8K–128K 历史矩阵完整保留在 `../reuse-aiconfigurator-architecture-h100/`；本版另立数据源，不改其冻结脚本或来源哈希。

## 模型、上限与来源

| 模型 | 注意力 / FFN | TP / EP | 最大总上下文 C | 上限依据 |
|---|---|---:|---:|---|
| Qwen3-14B | GQA / 稠密 | 1 / — | 131,072 | 官方 YaRN 4× 扩展，原生 32K |
| Llama-3.1-70B | GQA / 稠密 | 4 / — | 131,072 | 官方模型卡与冻结配置 |
| Qwen3-235B-A22B-Instruct-2507 | 全注意力 GQA 成本模型 / MoE | 16 / 16 | 1,010,000 | 官方扩展配置，原生 256K；大于 256K 仅作全注意力成本外推 |
| DeepSeek-V3.2 | DSA / MoE | 32 / 32 | 163,840 | 官方 config.json 的 max_position_embeddings（160K） |

官方文件逐字保存在 `official/`，`official/PROVENANCE.json` 记录 HF revision、下载 URL 和 SHA-256。Qwen 2507 revision 为 `ac9c66cc9b46af7306746a9250f23d47083d689e`；Qwen14 为 `40c069824f4251a91eefaf281ebe4c544efd3e18`；DeepSeek 为 `a7e62ac04ecb2c0a54d736dc46601c5606cf10a6`。Llama 沿用固定 AIConfigurator 内置快照。

`configs/PROVENANCE.json` 列出用于成本查询的派生配置及明确覆盖：Qwen14 加 YaRN、最大长度改 131072；Qwen2507 按其 1M 文件记录最大长度 1010000，但不把 DCA 或稀疏内核配置冒充成 SDK 已实现的成本模型。SDK 未消费 DCA 设置，Qwen >256K 的延迟只能称全注意力计算形状外推，不能称官方 1M 稀疏部署延迟。官方模型卡同时报告 Full Attention 和 Sparse Attention 的长文本质量结果，但本次没有复现任何质量实验。

上限指本图采用的官方模型/配置边界，不等于原生训练长度、API 服务长度或我们验证过的模型质量。DeepSeek 160K 是开源配置上限。

## 同条件恢复协议

- H100-SXM 80 GiB，vLLM 0.19.0，AIConfigurator 0.9.0 HYBRID / commit `4b9d9dc51e02b5e9d4acc3688f3edf41693834c6`。BF16 主权重/GEMM/MoE/KV，batch1，PP1，attention DP1；DeepSeek 索引器保持 FP8 key + FP32 scale。不同模型 GPU 数不同，只比较同一模型内部的三条路径。
- 横轴改为总长度 `C=M+64`；M 是历史，最后 64 tokens 是已知待重建尾部。因此终点不会出现“最大历史再加64”导致的上下文超限。SDK 内存估计另预留一个输出 token，未模拟该输出的生成时间。
- HBM：完整历史及必要辅助状态已在接管 GPU 组，每 rank 查询 `isl=C,prefix=C-64`。DRAM：每 rank 同时恢复完整历史状态，耗时 `bytes / 64e9`，然后执行相同尾部。64 GB/s 是假设，主机带宽不共享，无传算重叠。
- Recompute：从空缓存按至多 8192 tokens 的连续块重建。第 j 块查询 `isl=end_j,prefix=start_j`，使用此前重建的 KV；所有块及缓存尾部均去除 SDK 可能加入的 logits GEMM，因为词表投影不重建 KV。Qwen MoE 的 SDK 列表原本没有此项；其他模型通过显式扣除保持一致。所有其他算子（含通信）保留。总延迟为块延迟和，峰值内存为所有块的最大值；没有额外调度/CPU 开销或跨请求资源竞争。
- 每 rank 历史状态字节沿用核对后的公式：GQA 按头分片与复制；DSA 包括在 TP rank 间复制的 MLA latent、RoPE key 与索引器状态。与 SDK 单 token 状态量相等。没有假设只搬运 sparse top-k。
- 采样总长度为 8K、16K、32K、64K、128K，以及各模型范围内的 256K、512K、768K 和精确上限；去重后共 25 个形状、75 个路径值、201 个唯一 SDK 查询。K=1024，图的 M 后缀为十进制百万。所有路径无物理重复计时或置信区间。

## 各模型终点

| 模型 | C | HBM (ms) | DRAM (ms) | Recompute (s) | Recompute 峰值 (GiB/卡) |
|---|---:|---:|---:|---:|---:|
| Qwen3-14B | 131,072 | 21.691 | 357.071 | 14.730 | 51.867 |
| Llama-3.1-70B | 131,072 | 24.109 | 191.799 | 15.221 | 47.361 |
| Qwen3-235B-A22B-Instruct-2507 | 1,010,000 | 70.162 | 829.634 | 219.951 | 77.817 |
| DeepSeek-V3.2 | 163,840 | 52.340 | 252.771 | 26.422 | 59.213 |

全部 25 个形状通过静态容量检查，最大估计 77.817 GiB/卡；不等于实机部署成功。前一轮整段 prefill 的容量失败保留在 `output/pdf/aegiskv-motivation-long-context-20260918/`，原 TP8 失败仍在旧架构数据目录。分块后的不同结果源于明确改变了执行协议，未隐藏或改写失败数据。

## 外推与证据边界

- DSA 内核表的总长度仅到32768，32K以上的点依赖外推；所有 cached-prefix 查询依赖 SDK 的解析前缀修正，既包括 HBM 尾部，也包括 Recompute 后续块。`silicon` 标签仅表示基础表来源，不是所画形状或请求级恢复实测。
- Qwen2507 >256K 为标准全注意力成本外推，不包含 DCA 的位置处理、稀疏选择或专用内核加速。官方 `config_1m.json` 被保留用于核对版本与最大长度，但没有虚称完整 DCA 已由 AIConfigurator 建模。
- 未执行原生稀疏恢复正确性、长文本精度、H2D有效带宽或软件接管测量。检测、排队、模型加载、故障前复制和竞争均不计。完整历史 HBM 为对照，不是 AegisKV 有限 Peer 热块策略。
- Figure1 仍使用冻结 A100/Qwen14 反事实，图像、数据及数值保持原样。

## 复现

```sh
HF_HUB_OFFLINE=1 /home/comp/zhanzhao/aiconfigurator/.venv/bin/python benchmark/AegisKV/experiments/data/reuse-aiconfigurator-max-context-h100/estimate_reuse.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py --only figure2
sh benchmark/AegisKV/paper/build-motivation.sh
sh benchmark/AegisKV/paper/build.sh
```

`estimates.json` 保存每个原始查询、来源标签、内存分解、分块列表、被排除的词表投影 和来源哈希；CSV 保存75个延迟值及每行形状。`partial-results.json` 是运行中保存的诊断副本。最终图和论文页面核对记录在 `output/pdf/aegiskv-motivation-max-context-20260918/`。
