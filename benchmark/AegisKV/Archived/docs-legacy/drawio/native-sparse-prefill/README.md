# 原生稀疏 Attention：M 个历史 Token 与 N 个后续 Token 的 Prefill

这组图回答：固定一个层及一个 head / KV 组，后续 Query 如何从因果可见的历史中选择 KV，所选集合如何进入各算法的 attention。

**当前 Draw.io 为五页，每页一个算法：NSA、MoBA、InfLLM-V2、DSA、NOSA。** 各页重复说明 M/N、Query 的绝对位置和因果候选范围，均可单独阅读。原四页版本的可编辑主文件保存在 `archive/four-page/`，旧导出保持原路径。

**证据类型：机制示意。** 选块矩阵为手工构造的合法选择集合，NSA 的局部窗口矩阵按位置规则解析生成；没有运行新模型，没有将示意集合当作真实热点、注意力权重或性能结果。统一使用 M=24、N=8、示意块长 B=4；不同算法的缩小预算不构成等预算对比。实际 NOSA-1B 轨迹使用 B=64，见[真实实验记录](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/README.md)。

## 共同场景

Query 直接按绝对位置标注为 q25–q32。对位置 t ∈ {M+1, …, M+N} 的 Query q_t，其合法候选为：

\[
\mathcal C_t=\{1,\ldots,M\}\cup\{M+1,\ldots,t\},\qquad
\mathcal S_t\subseteq\mathcal C_t.
\]

左侧是 N×M 的历史候选区；右侧是 N×N 的后续 KV 因果下三角，包含当前位置。固定某层，后续 N 个隐藏状态可以投影为这一层的 Q/K/V，并在遵守因果掩码的前提下并行计算各 Query。这里并没有 N 次串行 Decode 的依赖。模型层之间仍有正常的隐藏状态依赖。

在复用/重算场景中，假设历史主 KV 以及本算法必需的压缩、索引等辅助状态有效可用。KV 位于 Peer HBM 或 DRAM 不改变模型的候选集合；选择后，DRAM 中命中的 KV 还需 H2D。辅助状态的恢复以及 H2D 调度不由这组图测量。

共同范围的说明已放入每个算法页；[独立因果范围参考图](/home/comp/zhanzhao/MoonKVSim/output/pdf/native-sparse-prefill-20260914/01-causal-prefill.png) 不计入当前五页主文件。

## NSA

NSA 的压缩分支不仅提供选择原始 KV 块的分数，本身也产生 attention 输出 Oc。精选分支 Os 与局部分支 Ow 分别计算，三者通过学习的门控融合。原论文使用独立的分支 K/V 投影；图中三个 KV 输入对应各自分支。

同一页分别画出精选分支 Os 的蓝色矩阵和局部分支 Ow 的金色矩阵。精选矩阵中的白色位置不能解读为“整个 NSA 不使用这里的信息”：压缩表示仍可能携带这些位置的信息，局部分支也会读取自己的窗口。图中精选分支每行选择两个完整可见块；q29 选择 B7，说明已经因果可见的后续段 KV 也可以被选择。同一 Query 的同一 GQA 组共享选择，不同 Query、不同层/组不要求相同。[NSA 原论文 §3.2–3.3](https://arxiv.org/html/2502.11089v1)

局部分支示意窗口 W=4，定义为包含当前位置的 4 个 Token，位置范围为 max(1, t−W+1) ≤ j ≤ t。q25 使用 KV22–25，q28 使用 KV25–28，q32 使用 KV29–32；每行窗口逐 Token 移动，全部窗口内 KV 参与该分支的 attention，无须经过 Top-k 选择。B1–B8 在这个矩阵中只是位置参考，并非按块移动的窗口。W=4 是缩小示意参数，不是 NSA 原论文的实验配置。[NSA 滑动窗口分支 §3.3.3](https://arxiv.org/html/2502.11089v1#S3.SS3.SSS3)

![NSA 的三个分支](/home/comp/zhanzhao/MoonKVSim/output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page/01-nsa-prefill.png)

## MoBA

MoBA 以 Q 与每块 K 的均值的内积打分，再选择块。当前块强制保留，其 attention 内部使用因果掩码，从而避免完整当前块的均值把未来信息带入路由。图中两块历史 KV 加一个当前块；同在 B7 的 q25–q28 仍可选不同历史块。[MoBA 原论文 §2.2](https://arxiv.org/html/2502.13189v1)

![MoBA](/home/comp/zhanzhao/MoonKVSim/output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page/02-moba-prefill.png)

## InfLLM-V2

InfLLM-V2 在稀疏路径中先对子块 K 平均池化，计算 Q 相关分数，聚合同一 GQA 组的 heads，再以 max pooling 得到原始块评分。选择集合包含相关块、首部块和局部块；去重后执行一个主 attention，压缩表示不再产生 NSA 那种独立输出。图中仅一个动态块，另有首块和两个局部块。实际块大小、窗口和预算依模型配置变化。[InfLLM-V2 原论文 §3.2–3.3](https://arxiv.org/html/2509.24663v1)

![InfLLM-V2](/home/comp/zhanzhao/MoonKVSim/output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page/03-infllmv2-prefill.png)

## DSA

DSA 通过轻量 Lightning Indexer 对因果可见的历史条目评分，逐 Query 选择 Token 下标，随后在对应的 MLA KV 上计算主 attention。它需要额外的索引 K 状态。图中仅六个 Token；块边界只是与其他面板对齐的位置参考，不把 DSA 的逻辑选择变成整块选择。实际 DeepSeek-V3.2 配置为 2,048 条目。[DSA 原论文 §2.1](https://arxiv.org/html/2512.02556v1)

![DSA](/home/comp/zhanzhao/MoonKVSim/output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page/04-dsa-prefill.png)

## NOSA

NOSA 将 query-aware 选择与 query-agnostic 重要性选择结合。先保留 Query 相关块及固定块，再依据 CIS 补齐剩余预算；图中的 B3 假设在这段窗口持续具有足够高的 CIS，因而反复入选。绿色只表示由 CIS 补入，不保证真实模型存在永久固定块。可见候选增长或保护集合变化仍可能改变结果。原始 NOSA 实现还在 attention 的加权归一化中使用 CIS，这里没有修改该数学定义。[NOSA 原论文 §3.1](https://arxiv.org/html/2510.13602v2)；[本次实际实现](/home/comp/zhanzhao/MoonKVSim/tmp/native-sparse-20260914/NOSA-1B/modeling_llama_long_infllmv2.py:1085)

![NOSA](/home/comp/zhanzhao/MoonKVSim/output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page/05-nosa-prefill.png)

本次真实模型实验选用 NOSA-1B。但这组缩小机制图的颜色和集合均是人为示意，不能用其覆盖率证明真实模型热点，也不能从颜色直接推导 H2D 次数或恢复 WCT。

## 文件与复现

- [五页可编辑 Draw.io](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/drawio/native-sparse-prefill/native-sparse-prefill.drawio)
- [五页 PDF，每页一个算法，178 mm 宽](/home/comp/zhanzhao/MoonKVSim/output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page/native-sparse-prefill-178mm.pdf)
- 每张图还保留独立 Draw.io、原生 PNG/SVG/PDF。独立导出含 Draw.io 源；合并阅读 PDF 仅保留矢量图。
- [构造集合与静态核对](/home/comp/zhanzhao/MoonKVSim/output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page/schematic-masks.json)
- [版式与来源检查](/home/comp/zhanzhao/MoonKVSim/output/pdf/native-sparse-prefill-20260914/one-algorithm-per-page/REVIEW.json)

```bash
.venv/bin/python benchmark/AegisKV/docs/drawio/native-sparse-prefill/build_diagrams.py
.venv/bin/python benchmark/AegisKV/docs/drawio/native-sparse-prefill/export_diagrams.py
```

候选论文插入宽度为 178 mm，主文字约 10 pt，位置刻度约 9.3 pt。最终尺寸是本次排版选择，并非期刊要求。没有改动论文正文、真实实验数据或模型代码。
