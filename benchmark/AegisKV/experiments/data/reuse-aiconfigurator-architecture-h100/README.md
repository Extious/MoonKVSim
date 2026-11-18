# Figure 2：大规模、MoE 与稀疏注意力的恢复估计

本目录为当前 Figure 2 数据。使用固定 AIConfigurator 0.9.0 / commit `4b9d9dc51e02b5e9d4acc3688f3edf41693834c6` 的 CPU 静态估算，不下载权重或启动 GPU 实验。

| 模型 | 总参数 / 激活参数 | 注意力与 FFN | TP | EP | H100 数量 |
|---|---|---|---:|---:|---:|
| Qwen3-14B | 14B / 14B | 稠密 GQA / 稠密 | 1 | — | 1 |
| Llama-3.1-70B | 70B / 70B | 稠密 GQA / 稠密 | 4 | — | 4 |
| Qwen3-235B-A22B | 235B / 22B | 稠密 GQA / MoE | 16 | 16 | 16 |
| DeepSeek-V3.2 | 671B / 37B | DSA 稀疏注意力 / MoE | 32 | 32 | 32 |

MoE 是前馈专家结构，不等于稀疏注意力。结构来源见 [Qwen 模型卡](https://huggingface.co/Qwen/Qwen3-235B-A22B)、[DeepSeek 模型卡](https://huggingface.co/deepseek-ai/DeepSeek-V3.2) 及 [DeepSeek 参数说明](https://fe-static.deepseek.com/chat/transparency/deepseek-v3.2-model-card-0414-EN.pdf)。配置文件来自固定官方 Qwen14B revision 或上述 AIConfigurator commit 的内置快照，逐字复制；`configs/PROVENANCE.json` 区分来源并保存 SHA。

所有模型使用 H100-SXM 80 GiB、vLLM0.19.0、HYBRID、batch1、PP1、attention DP1，主权重/GEMM/MoE和KV按BF16。DeepSeek原检查点有FP8权重量化元数据，此处明确覆盖为BF16成本配置，并非在运行该检查点；其DSA索引器仍为原生FP8 key和FP32 scale。不同模型GPU数不同，**只能比较同一模型配置内的恢复路径，不能按图中绝对延迟作等资源排名**。

## 相同恢复终点与传输状态

固定历史 M=8K/16K/32K/64K/128K 和已知64-token尾部，权重已加载。终点为历史与尾部KV及必要辅助状态可供继续decode。

- HBM：所有接管rank已有完整历史状态，执行64-token尾部；不视为零时间。
- DRAM：各rank同时从本机DRAM恢复完整历史状态，在全部传输完成后执行同一尾部。每GPU64GB/s来自H100系统YAML假设，无共享主机瓶颈，无传输计算重叠；不是H2D实测。
- Recompute：空缓存前向M+64；DSA使用SDK的 `ContextDSAModule`，包含索引器与稀疏MLA，没有用稠密模型或简单top-k缩放冒充。所有GPU通信项保留。

GQA每rank每token字节：`2 * layers * ceil(KV_heads/TP) * head_dim * 2`。Qwen235B的TP大于KV头数，因此每rank至少保存一组KV头；不能错误地把总KV均除TP。DSA每rank字节：`layers * (kv_lora_rank*2 + rope_dim*2 + index_head_dim + ceil(index_head_dim/128)*4)`；这里MLA和索引器状态在TP rank间复制，没有除TP。两类公式均与SDK `get_kvcache_bytes_per_sequence(1)` 核对相等。

| 模型 | 历史状态/每rank/128K (GiB) | HBM (ms) | DRAM (ms) | Recompute (s) |
|---|---:|---:|---:|---:|
| Qwen3-14B | 20.000 | 22.208 | 357.752 | 14.084 |
| Llama-3.1-70B | 10.000 | 24.307 | 192.079 | 15.100 |
| Qwen3-235B-A22B | 5.875 | 56.362 | 154.928 | 12.279 |
| DeepSeek-V3.2 | 9.561 | 52.333 | 212.740 | 20.059 |

## 证据边界与保留的失败

- `estimates.json` 保存20个模型/历史形状、40次计算查询的逐算子时间与来源、内存估计、每rank/全组传输字节；`estimates.csv` 为60个路径值的汇总。没有独立工作负载、重复计时或CI。
- Qwen235B初始TP8/EP8在128K的估计总占用84.535GiB，超出80GiB；失败保留在 `capacity-initial-tp8.json`。最终改TP16/EP16后57.290GiB。最终20个形状均无工具容量警告，最大74.884GiB（DeepSeek）。这不是物理部署成功证据，也不是最优TP搜索。
- DSA模块表 `systems/data/h100_sxm/vllm/0.19.0/dsa_context_module_perf.txt` 包含本图对应BF16组合和local-head数，batch覆盖1，但总序列长度只到32768。按M+64检查，32K/64K/128K历史点均在表外。保存 `dsa_beyond_table_context`；SDK根据表作外推，缓存尾部另用解析prefix修正。
- SDK `op_sources` 的 `silicon` 描述底层表来源，不意味着本请求形状被测量，不能将外推、前缀修正或表算子相加称为端到端实测。保留DSA尾部估计轻微非单调性，不平滑成预设趋势。
- Qwen14B/235B配置长度40960、Llama70B为131072、DeepSeek为163840；按M+64逐行标记 `exceeds_config_context`。表外与配置外是不同边界。全部点都没有精度/原生缓存正确性验证。
- 不含检测、排队、权重加载、故障前复制、软件绑定、DMA设置及资源竞争。DRAM传完整必要历史状态，未用稀疏选中比例假定只传top-k，也未模拟传输计算重叠。
- Figure1仍为独立的Qwen3-14B/A100反事实，冻结成本及图像不变；文稿已分别标注硬件。旧小模型矩阵保留在相邻历史目录。

## 复现

```sh
HF_HUB_OFFLINE=1 /home/comp/zhanzhao/aiconfigurator/.venv/bin/python benchmark/AegisKV/experiments/data/reuse-aiconfigurator-architecture-h100/estimate_reuse.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py --only figure2
sh benchmark/AegisKV/paper/build-motivation.sh
sh benchmark/AegisKV/paper/build.sh
```

可选 `--capacity-check` 仅查询各模型最大历史形状并生成当前配置的 `capacity-check.json`，不会覆盖主矩阵。原初TP8失败文件独立保留。
