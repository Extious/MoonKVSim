# SlackLandlord：两页简化版

2026-09-08。第 1 页保留 Agent、共享 KV 与 Pool 布局，原第 2–4 页合为一页。绘制风格直接参照 [算法三 Guarded AIMD](../algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio)：单列主流程、菱形判断、两侧分支、节点内公式。

符号现已对齐 [原专利](../../patent/AegisKV专利交底书-final-version.docx) 的第 90、91、125 段（`document.xml` 中从 0 计数）。**符号表放在第 2 页开头、输入节点之前**；第 1 页使用的容量与 Agent 记号也在开头解释。单列流程和决策逻辑保持不变。

[可编辑 Draw.io](algorithm-2-patent-revised.drawio) · [完整两页 PDF](algorithm-2-patent-revised.drawio.pdf) · [第 2 页单页 PDF](algorithm-2-patent-revised-flow.drawio.pdf)

![SlackLandlord 最小决策流程](algorithm-2-patent-revised-flow.drawio.png)

## 第 2 页怎么读

1. 尝试一个已完整生成的连续备份前缀，需要比较时才刷新恢复收益 \(G_X=W_X\)。
2. 检查可用字节 \(f\) 是否足够容纳候选新增字节 \(b_X\)。
3. 若不足，试删当前 \(P_y=G_y/b_y\) 最小的可释放尾块 y，更新 \(Y,D_Y,f\)。空间足够立即停止。
4. 用联合回收损失 \(D_Y\) 计租：\(\mathrm{Credit}_X=G_X-D_Y\)。
5. 继续比较其他已生成终点，避免第一块零收益就永久放弃长前缀。
6. 执行正 Credit 最大的候选；若没有则保持。复制确认后才发布连续前缀。

右侧保留一个贯穿例子：A 的前缀收益为 0、1、3、6 ms，新候选 B1 收益 4 ms。只删 A3 的损失为 3 ms，Credit=1 ms，因此换入 B1，继续保留 A1/A2。下方分别说明 Lazy Refresh 和容量缩小的处理。

## 算法也做了简化

删去在线动态规划、全局搜索、分数松弛、最优性 gap 与跨轮上下界。收益仍用真实恢复代价模型和工作流 WCT 计算；共享块只存一份，同一工作流的多 Agent 联合计价。

**这是按当前收益做局部替换的 SlackLandlord 设计。** 容量租金直接用实际回收损失结算，不是原先累计 L 扣减历史余额的分账租金。Credit 的计算有明确收益依据，但贪心选择不保证全局最优；多个独立前缀必须联合备份才有收益时可能漏解。完整规则、边界与可执行参考见 [最小算法说明](../../algorithm-2/README.md) 和 [simple_slacklandlord.py](../../algorithm-2/simple_slacklandlord.py)。尚未接入生产运行路径。

## 专利记号如何沿用

| 专利符号 | 当前图中 | 含义及变化 |
|---|---|---|
| \(s_i,T_i^r,J_i^r\) | \(s_a,T_a,J_a\) | Slack、恢复时间、超过 Slack 的损失；管理对象已改为 Agent a，省略 Peer-HBM 层下标 r |
| \(W_x^r,G_x^r\) | \(W_X,G_X\) | WCT 恢复收益、备份收益；只保留恢复项，因此 \(G_X=W_X\) |
| \(P_y^r=G_y^r/b_y\) | \(P_y=G_y/b_y\) | 当前尾块的单位字节优先级，替换上一图的 ρ；\(G_y\) 由本次试删损失计算 |
| \(Y,D_Y^r\) | \(Y,D_Y\) | 拟淘汰集合、其联合损失；以 \(D_Y\) 替换上一图的 K |
| \(f\) | \(f\) | 初始为空闲字节，试删后增加可回收字节；实际复制仍须等待实际释放 |
| \(x,b_x\) | \(X,b_X\) | **集合扩展**：X 包含连续、缺少的新增物理块；\(b_X\) 是它们去重后的总字节；单块时 X={x} |
| \(J_i^r\) | \(J\) | **联合计算扩展**：相关工作流的总 WCT 损失，同一工作流按 DAG 计算，不能直接相加各 Agent 的 \(J_a\) |
| — | \(\mathrm{Credit}_X\) | **净收益记号**：\(G_X-D_Y\)，不表示累计扣租后的历史余额 |

上一图中的 S、V、F、U(k)、ρ、K 不再出现在当前流程中。使用专利的“加入前/后”“删前/后”计算恢复损失变化；候选 X 已假设加入后，才计算试删尾块的损失，因此共享工作流的计价含义未变。每次试删增加 \(G_y\)，顺次累计得到联合损失 \(D_Y\)。

原专利复合权重在本范围下等价于 \(\lambda_w=1,\lambda_h=\lambda_l=0\)。本次统一记号不恢复已经移出当前策略的 L、H、Θ 和旧堆排序规则；也不把“联合回收损失”改叫“历史扣租余额”。

[第 1 页 PNG](algorithm-2-patent-revised-agents.drawio.png) · [第 1 页 PDF](algorithm-2-patent-revised-agents.drawio.pdf)

## 校验与历史

原生 Draw.io 导出、数学排版和实际 mxGraph 的解码/编辑/保存/重开结果分别记录在 [MANIFEST.json](MANIFEST.json)、[DESIGN_CHECKS.json](DESIGN_CHECKS.json)、[COMPATIBILITY.json](COMPATIBILITY.json)。数值与策略检查见 [SIMPLE_VALIDATION.json](../../algorithm-2/SIMPLE_VALIDATION.json)，包含局部策略漏掉并行联合收益的负面用例；这些是 CPU 元数据验证，不是物理性能结果。

```bash
.venv/bin/python benchmark/AegisKV/docs/algorithm-2/test_simple_slacklandlord.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/build_diagram.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_design_examples.py
```

- [合并前的四页源图](references/capacity-rent-four-pages-c46d699b9e06/algorithm-2-patent-revised.drawio)及[四页 PDF](references/capacity-rent-four-pages-c46d699b9e06/algorithm-2-patent-revised.drawio.pdf)。旧导出、生成器与检查报告一并保留，代表当时的复杂方案。
- [符号调整前的两页源图](references/before-patent-notation-21d755bdd5cf.drawio)：包含上一版 S、V、F、ρ、K 记号，供对照。
- [更早的累计扣租图](references/previous-cumulative-rent-136d94493763.drawio)及[旧说明](references/previous-cumulative-rent-design.md)。
- [用户编辑过的早期源图](references/user-edited-19ff14bc521a.drawio)与[原专利摘录](SOURCE_EXCERPT.md)。

本次调整符号与排版；原专利、算法三源图及决策参考代码保持原样。
