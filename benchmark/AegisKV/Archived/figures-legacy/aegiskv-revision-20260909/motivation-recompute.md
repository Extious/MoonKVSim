# Motivation Observation 3：长上下文放大故障后的重算代价

![完整前缀重算随上下文增长](motivation-recompute.png)

[PDF](motivation-recompute.pdf) · [SVG](motivation-recompute.svg) · [CSV](motivation-recompute.csv) · [来源与审查记录](motivation-recompute-manifest.json) · [绘图代码](../../../benchmark/AegisKV/experiments/scripts/paper/render_motivation_recompute.py)

**建议正文。** Agent 在多轮模型调用中不断积累上下文；当执行该请求的 GPU 故障，未保留下来的 KV 需要重新计算。图中固定模型和并行配置，只增加丢失前缀长度：从 16 Ki 增至 128 Ki tokens 后，Qwen3-8B 的完整前缀重算预测由 0.49 s 增至 9.16 s，Qwen3-32B 则由 1.72 s 增至 32.82 s。两者分别增长 18.7 和 19.1 倍。因此，长上下文使一次故障后的状态重建成为不可忽略的计算开销。是否转化为相同幅度的 Workflow 延迟，仍取决于前述分支 Slack，以及实际的排队、恢复来源和资源竞争。

**建议图注。** 长上下文的完整前缀重算代价。Qwen3-8B 与 Qwen3-32B 在 A100-80GB、TP4/PP2、BF16 配置下，按 8 Ki-token 分块累加单请求 prefill 预测；Ki=1,024。每条线连接四个历史 AIConfigurator SILICON 配置预测点，无故障运行或重复测量。

本图的单位是确定性配置预测点，两个模型各四点，共八点；不是八个 run，没有统计误差条。仅重画冻结数值，未执行 predictor、模拟器或故障实验。预测使用 `sglang-0.5.10` 后端、prefill scale 1.05，batch 中一个请求、DP1、TP4、PP2、EP1。图没有恢复传输、故障检测、队列、decode replay 或 DAG 传播；不构成 AegisKV 相对 Mooncake 的收益证据，也不能混用为当前 Qwen3-8B DP8/TP1 Evaluation 的实测延迟。

原图为旧项目 `sglsim/AegisKV/doc/figures/motivation-recovery-scaling.png`，实际查看后沿用其上下文—重算时长表达。原始 24 行 CSV、原绘图器和原 predictor 均已保存在 [sources/motivation-recompute](sources/motivation-recompute/)；CSV 中记录的 generator 和 predictor SHA 与保存的源码逐项匹配。底层性能数据库的具体 revision 未被旧导出固定，因此本轮只保证冻结数值及代码来源，未声称完整环境可重新得到同一数值。

正文排除了原图 235B/TP8/PP4/EP8 曲线：原 README 已明确其 94 层无法被 PP4 整除、物理 PP runtime 未验证；全部原始记录保留。原图 Peer HBM、Local DRAM、SSD 的内嵌曲线来自另一套未经校准的模型无关路径系数，本图讨论单请求重算代价，不使用这些路径作收益分母。

图按 3.333 × 2.9 inch 导出，最小文字 10 pt。已逐项核对八行数据不变、每点的分块时间求和、零刻度、线型和 marker，并实际查看最终 PNG 和按 84.67 mm 插入宽度渲染的 PDF。首版最低点的 marker 接近坐标边界，第二版增加零线下的空白，保留全部非负数值。

复现绘图：

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_recompute.py
```

重画会将 manifest 的人工视觉审查状态重置为待检查，需对新导出再次核对。
