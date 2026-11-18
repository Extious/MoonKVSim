# Figure 2：恢复路径静态估计（历史同系列版本）

当前论文使用 [`reuse-aiconfigurator-architecture-h100`](../reuse-aiconfigurator-architecture-h100/README.md)，覆盖14B–671B、MoE与DSA；中间版 `reuse-aiconfigurator-multifamily-a100` 也保留。本目录的代码、配置和 JSON/CSV 保持冻结，作为旧图与 Figure 1(c) 成本的复现依据；下文记录历史版本。

本目录是用户授权的暂定 AIConfigurator 版，不是物理恢复实验。三种 Qwen3 配置的同条件静态估计与模型化 H2D 统一到 64-token 已知尾部 KV 完成。选取 Qwen3-4B/8B/14B 是为了在工具支持的同一稠密家族中比较参数规模，并维持相同 A100-SXM/BF16/batch 1/TP 1 配置；不代表跨注意力架构覆盖。当前 Figure 2 在一个单栏坐标系中绘制全部 45 点，颜色编码路径，线型与标记编码模型；数据未作偏移或合并。完整协议与未执行的后续物理测量见 [计划](../../plans/reuse-latency-insight.md)。

```sh
MPLCONFIGDIR=/tmp/aegiskv-motivation-mpl HF_HUB_OFFLINE=1 /home/comp/zhanzhao/aiconfigurator/.venv/bin/python benchmark/AegisKV/experiments/data/reuse-aiconfigurator-a100/estimate_reuse.py
MPLCONFIGDIR=/tmp/aegiskv-motivation-mpl HF_HUB_OFFLINE=1 /home/comp/zhanzhao/aiconfigurator/.venv/bin/python benchmark/AegisKV/experiments/data/motivation-compact-cc/estimate_costs.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py
```

- `estimates.json`：15 个模型/历史长度点的两类计算查询、全部算子时间与数据来源、内存检查，以及旧十支实例的精确长度查询（当前四支实例单独保存在相邻 `motivation-compact-cc/recovery-costs.json`）；不把 kernel 表中的 silicon 标签解释为端到端实测。
- `estimates.csv`：作图汇总。DRAM = HBM + `transferred_bytes / 32e9 * 1000`（ms），无重叠。不同模型使用各自 KV 形状；4B/8B 均 147456 B/token，14B 为 163840 B/token。
- `configs/PROVENANCE.json`：三个官方 HF 配置的固定 revision、来源 URL、SHA-256；只下载配置，未下载权重。保存 `max_position_embeddings=40960` 原值；64K/128K 是超出配置的性能形状，未进行精度验证。
- HYBRID：可用算子表与经验/性能模型的组合；所有恢复曲线仍为静态估计。HBM 为完整历史在实际接管 GPU 驻留，不代表有限 Peer 热块方案。
- `source_sha256` 固定生成脚本、模型配置、AIConfigurator SDK、系统 YAML 与可被所选后端查询的表文件。TTFT 汇总被 SDK 舍入为三位小数，保存的主值采用未舍入的算子和，并核对舍入一致。
- 不含故障检测、排队、权重加载、故障前复制、绑定/分配/DMA 设置与竞争；没有物理正确性验证、文本 workload、五次重复或 CI。

当前 Figure 1 使用相邻 [`motivation-compact-cc`](../motivation-compact-cc/README.md) 的独立成本脚本，保持本目录的模型、系统、精度和 64-token 尾部口径。此处旧十支成本仅为历史记录；重新跑本目录脚本后需再跑 compact 成本脚本同步引用哈希。
