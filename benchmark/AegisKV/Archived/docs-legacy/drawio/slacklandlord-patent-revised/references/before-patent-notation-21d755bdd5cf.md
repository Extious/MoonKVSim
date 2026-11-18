# SlackLandlord：两页简化版

2026-09-08。第 1 页保留 Agent、共享 KV 与 Pool 布局，原第 2–4 页合为一页。绘制风格直接参照 [算法三 Guarded AIMD](../algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio)：单列主流程、菱形判断、两侧分支、节点内公式。

[可编辑 Draw.io](algorithm-2-patent-revised.drawio) · [完整两页 PDF](algorithm-2-patent-revised.drawio.pdf) · [第 2 页单页 PDF](algorithm-2-patent-revised-flow.drawio.pdf)

![SlackLandlord 最小决策流程](algorithm-2-patent-revised-flow.drawio.png)

## 第 2 页怎么读

1. 尝试一个已完整生成的连续备份前缀，需要比较时才刷新恢复收益。
2. 检查草案占用是否超过算法 3 给定的容量。
3. 若超额，试删当前恢复损失/字节最小的可释放物理尾块，每次一块，空间足够立即停止。
4. 租金 K 是累计回收损失；Credit = 新增收益 G − K。
5. 继续比较其他已生成终点，避免第一块零收益就永久放弃长前缀。
6. 执行正 Credit 最大的候选；若没有则保持。复制确认后才发布连续前缀。

右侧保留一个贯穿例子：A 的前缀收益为 0、1、3、6 ms，新候选 B1 收益 4 ms。只删 A3 的损失为 3 ms，Credit=1 ms，因此换入 B1，继续保留 A1/A2。下方分别说明 Lazy Refresh 和容量缩小的处理。

## 算法也做了简化

删去在线动态规划、全局搜索、分数松弛、最优性 gap 与跨轮上下界。收益仍用真实恢复代价模型和工作流 WCT 计算；共享块只存一份，同一工作流的多 Agent 联合计价。

**这是按当前收益做局部替换的 SlackLandlord 设计。** 容量租金直接用实际回收损失结算，不是原先累计 L 扣减历史余额的分账租金。Credit 的计算有明确收益依据，但贪心选择不保证全局最优；多个独立前缀必须联合备份才有收益时可能漏解。完整规则、边界与可执行参考见 [最小算法说明](../../algorithm-2/README.md) 和 [simple_slacklandlord.py](../../algorithm-2/simple_slacklandlord.py)。尚未接入生产运行路径。

## 图内符号

| 符号 | 含义 |
|---|---|
| S、X、V | 当前备份、候选缺少的连续块、备份草案 |
| C、b、bᵧ | 备份可用容量、物理字节数、尾块 y 的字节数 |
| T(k)、s、U(k) | 保留前 k 块的恢复时间、本轮 Slack、累计 WCT 收益 |
| F | 多工作流的总 WCT 恢复收益；同一工作流按 DAG 联合计算 |
| G、K、Credit | 新增恢复收益、累计回收损失、两者之差；单位均为 ms |
| ρᵧ | 当前回收尾块 y 的 WCT 损失/字节；仅候选前缀之外且未被读取固定的物理尾块可参与 |
| [z]₊ | max(z,0) |

[第 1 页 PNG](algorithm-2-patent-revised-agents.drawio.png) · [第 1 页 PDF](algorithm-2-patent-revised-agents.drawio.pdf)

## 校验与历史

原生 Draw.io 导出、数学排版和实际 mxGraph 的解码/编辑/保存/重开结果分别记录在 [MANIFEST.json](MANIFEST.json)、[DESIGN_CHECKS.json](DESIGN_CHECKS.json)、[COMPATIBILITY.json](COMPATIBILITY.json)。数值与策略检查见 [SIMPLE_VALIDATION.json](../../algorithm-2/SIMPLE_VALIDATION.json)，包含局部策略漏掉并行联合收益的负面用例；这些是 CPU 元数据验证，不是物理性能结果。

```bash
.venv/bin/python benchmark/AegisKV/docs/algorithm-2/test_simple_slacklandlord.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/build_diagram.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_design_examples.py
```

- [合并前的四页源图](references/capacity-rent-four-pages-c46d699b9e06/algorithm-2-patent-revised.drawio)及[四页 PDF](references/capacity-rent-four-pages-c46d699b9e06/algorithm-2-patent-revised.drawio.pdf)。旧导出、生成器与检查报告一并保留，代表当时的复杂方案。
- [更早的累计扣租图](references/previous-cumulative-rent-136d94493763.drawio)及[旧说明](references/previous-cumulative-rent-design.md)。
- [用户编辑过的早期源图](references/user-edited-19ff14bc521a.drawio)与[原专利摘录](SOURCE_EXCERPT.md)。

本次仅修改算法设计、参考决策与图件；原专利、算法三源图保持原样。
