# Runtime prediction: analytical bounds

这张图回答：**仅已知相关工作的 Runtime WAPE 时，能对误差覆盖率推导出什么，以及完美预测参考线是什么？**

它不是实测 CDF，也不是“相关工作已经达到的理论最优”。核对的文献未报告该预测问题的可达最优误差或其分布。原论文 Table 1 中最低的 Runtime WAPE 是 Predictor 的 7.25%，GBDT 为 11.05%；这只是同表方法中的最低报告误差。

## 定义与推导

设配置 i 的正实测耗时为 T_i，相对绝对误差为 e_i = |T_hat_i - T_i| / T_i，权重 w_i = T_i / ΣT_i。则：

```
WAPE = Σ |T_hat_i - T_i| / Σ T_i = Σ w_i e_i
F_w(ε) = Σ w_i 1[e_i ≤ ε]
F_w(ε) ≥ max(0, 1 - WAPE / ε), ε > 0
```

最后一行直接来自非负误差的 Markov 不等式；横轴 ε 与 WAPE 必须使用相同单位。图采用百分比。ε = 0 时下界取 0。

注意：F_w 按**实测耗时加权**，不是配置数、请求数或 agent 数的占比。给定 WAPE 不能推出普通逐 agent CDF。图中两条彩色线是下界，不是该方法的实际误差分布，也不是它的最优表现。随着阈值增大下界接近 100%，这来自解析公式，不能解读为新的预测实验发现。

灰色虚线假设全部误差为 0，故 ε ≥ 0 时覆盖率为 100%。这只是完美预测的定义，不是非零 WAPE 方法的拟合结果，也不表示存在能够预知未知输出、工具等待和未来循环的在线预测器。它也不是原论文 Figure 5 中的调度 Oracle。

例如，按报告值计算，阈值 20% 时 Predictor 的加权覆盖率下界为 63.75%，GBDT 为 44.75%。计算将原文保留两位小数的 WAPE 作为名义值；如果需要精确到报告舍入精度之外的保证，需要未舍入数值。上下文、模型、硬件、训练设置和误差结构变化之后，这些界不能直接作为新测试集的保证。

## 来源与范围

- Wang et al., *Latency-Aware Orchestration for Multi-Agent LLM Workflows on Heterogeneous GPUs*, arXiv:2609.03335v1, [§4.4 / Table 1](https://arxiv.org/html/2609.03335v1#S4.SS4)，2026-09-18 核对。
- 原文的 2,798 个 Qwen3 部署配置是它的测试样本；此图没有获得这些配置的逐样本测量值，没有生成或假冒这些样本。
- 原文预测对象是给定模型、请求和设备配置的执行成本，不是完整多轮 agent 的剩余墙钟时间。
- 数值输入复用 `../../../experiments/data/agent-runtime-relatedwork/reported-runtime.json`。
- 本图为独立解析候选，未替换 Figure 3(a) 或修改主稿结论。它适合解释汇总误差能支持的数学界，不能独立证明 agent 执行时间可被准确预测。

## 文件与复现

- `runtime-prediction-bounds.{pdf,svg,png}`：3.34 × 2.65 inch 单栏，10.05 pt 字体。
- `analytical-curves.csv`：解析函数的采样网格，**不是预测样本**。
- `caption.txt`：可复用的完整图注。
- `MANIFEST.json`：来源、公式、前提和文件哈希。
- `pdf-render.png` / `pdf-render-gray.png`：实际 PDF 的彩色 / 灰度渲染。

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_runtime_prediction_bounds.py
```
