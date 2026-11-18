# 算法三：双输入的单窗口 AIMD 决策

每个窗口结束时决策一次，为下一窗口设置 Peer HBM 额度。图中只保留两个外部输入，公式使用 Draw.io 原生数学排版。

[可编辑 Draw.io](algorithm-3-guarded-aimd.drawio) · [单页 PDF](algorithm-3-guarded-aimd.drawio.pdf) · [PNG](algorithm-3-guarded-aimd.drawio.png)

![算法三：两个输入、一次窗口决策](algorithm-3-guarded-aimd.drawio.png)

## 两个输入分别做什么

| 输入 | 作用 | 图中的去向 |
|---|---|---|
| 显存预算 $C_t$ | 决定下一窗口最多允许借多少显存 | 直接约束最终额度，不作为另一份性能惩罚 |
| 前台性能反馈 $e_t$ | 使用一个按工作量校准的推理 step 时延预警，判断是否需要退让 | 进入 AIMD 的减少 / 增加 / 保持判断 |

图中不再把当前额度 $Q_t$、连续稳定窗口数 $z_t$ 当成外部因素：它们是控制器内部状态。备份需求简化为“有待备份内容”的扩张条件，不再计算总需求 $D$ 或以其裁剪额度。额度是使用上限，不会因授权额度而预先占满显存。

复制限速、源端和目标端的传输许可由执行层负责。减少容量额度不能替代传输限速，也不能单独证明已经消除复制干扰。

## 一次窗口决策

显存预算使用互不重叠的容量项：

$$
C_t=\min\left\{L_t,\,[M_{\mathrm{KV}}-P_t-R_t]_+\right\}.
$$

$M_{\mathrm{KV}}$ 已扣除权重与固定运行开销；$P_t$ 包含正常 KV、正常可复用缓存及前台预留；$R_t$ 覆盖下一窗口与回收期间的额外主 KV 增长。$L_t$ 是 allocator 实际支持借出并归还的总额度，包含已经借给保护的页面；不能仅用当前空闲 bytes 代替。

本轮反馈为 $e_t=1$ 时，执行乘性减少：

$$
\widetilde Q_{t+1}=\beta Q_t,\qquad 0<\beta<1.
$$

否则，连续稳定已达到 $K$ 个窗口，且满足 $C_t>Q_t$、有待备份内容、上次调额已完成，执行加性增加；其他情况保持：

$$
\widetilde Q_{t+1}=
\begin{cases}
Q_t+\Delta, & \text{稳定且允许扩张},\\
Q_t, & \text{其他情况}.
\end{cases}
$$

最终统一裁剪并发布：

$$
Q_{t+1}=\min\left\{C_t,\widetilde Q_{t+1}\right\},
\qquad
\alpha_{t+1}=\frac{Q_{t+1}}{M}.
$$

$M$ 是预先固定的容量分母，$\Delta$ 是固定字节步长。无预警且观测有效时，本轮先更新稳定计数为 $\min(K,z_t+1)$，再检查增加条件；性能预警、额度增加或额度被裁剪收缩后重新累计稳定窗口。下一轮从实际裁剪后的有效额度开始。

$e_t=0$ 仅表示本窗口没有达到预警阈值，不能解释为“备份完全没有干扰”。性能基线应匹配 batch、上下文长度等工作量条件；缺失或过期观测不记作稳定，采用零许可的保守处理。图中省略异常处理支路，保持单轮正常决策可读。

周期调额的增长储备需要覆盖下一整个窗口及回收延迟；历史分位数只给出经验风险控制。图中输出是额度，不是物理页面已经归还，也不是低于 1% 开销的性能证明。本次仅修改图与说明，未修改运行算法或启动实验。

## 公式如何编辑与渲染

源文件启用了 `mxGraphModel math="1"`，标签使用 `html=1`，公式以 LaTeX `\(...\)` 输入。上下标、波浪号、最小值算子及分式由 MathJax 排版，仍保留在可编辑的原生标签中。

用 Draw.io 打开源文件后，**Extras → Mathematical Typesetting** 应保持开启；切换该选项可以查看或修改 LaTeX 源码。公式输入和排版方式见 [Draw.io 官方数学排版说明](https://www.drawio.com/docs/manual/text/math-typesetting/)。

PNG 与 PDF 均通过官方 Draw.io Desktop 导出并请求嵌入源图。查看公式应以最终渲染为准；PDF 中的数学符号可能是矢量路径，不能仅用文本提取判断其是否显示。

## 重新生成

在仓库根目录执行。手工修改 Draw.io 后不要重新运行生成器覆盖它。

```bash
.venv/bin/python benchmark/AegisKV/docs/drawio/algorithm-3-guarded-aimd/build_flowchart.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli \
  -x -f png -e -b 20 -s 1.25 \
  -o benchmark/AegisKV/docs/drawio/algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio.png \
  benchmark/AegisKV/docs/drawio/algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli \
  -x -f pdf -e --crop -b 20 \
  -o benchmark/AegisKV/docs/drawio/algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio.pdf \
  benchmark/AegisKV/docs/drawio/algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio
```
