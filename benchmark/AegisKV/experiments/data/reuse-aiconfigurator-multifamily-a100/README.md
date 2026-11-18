# Figure 2：跨系列小规模估计（历史版本）

当前 Figure 2 使用 [`reuse-aiconfigurator-architecture-h100`](../reuse-aiconfigurator-architecture-h100/README.md)，覆盖14B–671B、MoE和DSA。本目录数据及脚本保留复现；以下为历史版本说明。

当前论文采用 **Qwen3-4B、Llama-3.1-8B、Qwen3-14B**：两个系列、三个规模，均由固定版本 AIConfigurator 直接支持，统一 A100-SXM、vLLM 0.14.0、HYBRID、BF16、batch 1、TP/PP 1。它们均为稠密 GQA；本组不声称覆盖稀疏注意力或 MoE。

所有数值为 CPU 查询生成的静态估计，未启动实机实验。完整协议及未执行的物理计划见 [恢复延迟方案](../../plans/reuse-latency-insight.md)。

## 数据与复现

```sh
HF_HUB_OFFLINE=1 MPLCONFIGDIR=/tmp/aegiskv-motivation-mpl /home/comp/zhanzhao/aiconfigurator/.venv/bin/python benchmark/AegisKV/experiments/data/reuse-aiconfigurator-multifamily-a100/estimate_reuse.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py --only figure2
sh benchmark/AegisKV/paper/build-motivation.sh
sh benchmark/AegisKV/paper/build.sh
```

- AIConfigurator 0.9.0、commit `4b9d9dc51e02b5e9d4acc3688f3edf41693834c6`。`configs/PROVENANCE.json` 保存配置来源与 SHA；Qwen 使用已固定的官方 HF revision，Llama 逐字复制该 commit 内置的 `meta-llama--Meta-Llama-3.1-8B_config.json`，没有伪称新下载的 HF revision。上游定义见 [Meta 模型卡](https://huggingface.co/meta-llama/Llama-3.1-8B)。
- `estimates.json` 保存 15 个模型/长度点的算子时间、来源、内存检查和输入 SHA；`estimates.csv` 为 45 个路径延迟的作图汇总。HYBRID 使用可用算子表及性能模型，算子数据来源不等于请求级恢复实测。
- 旧同系列矩阵在 `../reuse-aiconfigurator-a100` 冻结保留。脚本核对其全部来源哈希，并断言两条 Qwen 模型的全部数值与旧版完全相同。Figure 1(c) 继续使用 `../motivation-compact-cc/recovery-costs.json`，没有重算或修改其成本。
- 三路径统一以已知 64-token 尾部前向完成、M+64 KV 可继续 decode 为终点。HBM：`isl=M+64,prefix=M`；Recompute：`isl=M+64,prefix=0`。采用未舍入算子和，并核对 API TTFT 舍入结果。
- DRAM = HBM + 全历史字节 / `32e9 B/s`。字节 = `2 × layers × KV_heads × head_dim × 2 × M`；Llama 未显式提供 `head_dim`，按配置 `hidden_size / num_attention_heads = 128` 推得，与 SDK 一致。32 GB/s 是系统 YAML 的 PCIe 假设，未测有效带宽，不含传输计算重叠。
- Qwen 配置长度为 40960；Llama 为 131072。每一行按 **M+64** 判断 `exceeds_config_context`：Qwen 的 64K、128K 点超出配置，Llama 的 128K 历史加尾部也超出 64 tokens。超限点仅为性能形状，不证明长上下文精度或引擎部署有效性。
- 三路径均不计检测、排队、权重加载、故障前复制、绑定/分配/DMA 设置及竞争。HBM 是完整历史驻留参照，不代表 AegisKV 的有限热块 Peer 方案。没有文本 workload、重复计时或置信区间。

## 128K 历史结果

| 模型 | 历史 KV (GiB) | HBM (ms) | DRAM (ms) | Recompute (s) |
|---|---:|---:|---:|---:|
| Qwen3-4B | 18 | 35.002 | 638.982 | 31.355 |
| Llama-3.1-8B | 16 | 35.032 | 571.903 | 31.578 |
| Qwen3-14B | 20 | 58.669 | 729.757 | 49.611 |

图为单栏、单坐标：颜色区分路径，线型和标记区分模型。保留所有绝对值及真实重合，不按参数量强制排序或偏移数据。15 个形状均无工具容量警告；最大估计占用约 64.774 GiB，不等于真实运行成功。
