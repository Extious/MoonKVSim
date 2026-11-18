# H2D 与 Prefill：已有论文图与报告数值

**逐层 M/N 问题的修正入口：** 用户已明确要比较“当前层以 M 个历史 KV 为前缀处理 N 个 token”，与“加载下一层 M 个历史 token 的 KV”。对应公式、图和边界见 [逐层 M/N 分析](layerwise-mn-analysis/README.md)。下文完整前缀的文献数字保留作背景，不作为该逐层问题的直接答案。

日期：2026-09-11。延续任务“分析算法并转向论文”的固定接管 DP 前提：Peer HBM 就在 retry DP 上，可以直接复用；DRAM 中的有效 KV 要经 H2D 加载。本轮仅查阅论文、裁取原图和绘制已发表数值，没有运行 GPU、模型、故障注入或 GlobalDES 性能实验。

**最直接的参考是 CachedAttention（USENIX ATC 2024）的图 18、19。** 图 18 把完整重算、加载历史 KV、计算新增输入、预加载后的执行时间放在一起；图 19 对比不同预加载缓冲容量。它们研究正常多轮会话；故障后的剩余计算与预取起点需要另外定义。

## 1. 一个可以直接引用的数量级对比

![按论文报告数值绘制](h2d-vs-prefill-published.png)

数据来自 [CachedAttention 会议版 §2.4，正文第 114 页](https://www.usenix.org/system/files/atc24-gao-bin-cost.pdf#page=5)：LLaMA-65B、4 张 A100、同一组 2K token，Prefill 约 360 ms，主存加载 KV 约 192 ms。正文同时报告约 5 GB KV 和 26 GB/s 有效传输带宽。图中的两项是不同操作的成本，不是同一次 retry 的可加组成部分。

192/360≈53% 只是这一配置下两个报告值的比例。该段未给重复次数、误差或清楚的逐 rank 链路核算，本图不补造这些信息，也不外推至 Qwen3、其他并行布局或故障 WCT。完整重算耗时不能替代实际剩余 Prefill 的 overlap 窗口。

- [矢量 PDF](h2d-vs-prefill-published.pdf)，168 × 82 mm。
- [SVG](h2d-vs-prefill-published.svg)、[CSV](reported-times.csv)、[生成脚本](plot_reported_times.py)。
- 复现：`python3 plot_reported_times.py`。只运行绘图和 PDF 渲染。

## 2. CachedAttention 原图定位

以下裁图来自[作者公开稿](https://prongs1996.github.io/assets/pdf/CachedAttention.pdf)第 10 页。它与会议版的版式及部分其他结果不同，**这里明确保留作者稿身份**；图号、关键条件与会议版对应章节已分别核对。引用正式论文时使用上面的 USENIX 会议版。未从柱高数字化出额外精确数据。

![CachedAttention 作者稿 Figure 18](cachedattention-figure18-author-version.png)

图 18：LLaMA-13B，单张 A100，batch=16；每条序列共 1K token，历史/新增比例从 500/500 到 900/100。绿色是完整重算；黄色与橙色表示 KV 加载及新增输入计算；蓝色表示预加载后的结果。历史比例高时，加载时间可能超过剩余计算时间。

![CachedAttention 作者稿 Figure 19](cachedattention-figure19-author-version.png)

图 19：LLaMA-13B，单 GPU，batch=16，每条序列为 1K 历史 token 加 100 新 token。NO-PL 表示不预加载，PL-Bn 表示按 n 层 KV 大小配置读缓冲。预加载后的柱表示暴露出来的总执行时间，不能把其中未显示的加载部分解释为“没有传输”。

图 6、7 是机制时间线，分别位于会议版正文第 115 页和作者稿第 6 页。需要额外检查初始预取发生在何时、用了多少缓冲，以及是否借用了上一项任务的计算窗口；不能直接等同于故障瞬间已有相同数量的 Peer 驻留层。

## 3. 其他相关论文

| 论文与具体图 | 内容 | 与本问题的关系 |
|---|---|---|
| [HCache，EuroSys 2025，图 11(a–c)](https://chenyoumin1993.github.io/papers/eurosys25-hcache.pdf#page=11) | DRAM 后备，不同 GPU/模型的 Recomputation、KV Offload、HCache 恢复速度 | 直接包含主存加载与重算对照；纵轴是 K tokens/s，越高越快，不是毫秒 |
| [CacheBlend，图 10、§5](https://arxiv.org/html/2405.16444) | 选择性重算比例、存储位置、计算/加载流水对 Prefill 延迟的影响 | 与层级重叠相关；包含 SSD 和选择性修复语义，不能全部称为纯 H2D |
| [Cake，ICML 2025，图 3、4](https://arxiv.org/html/2410.03065v2) | 等效 KV 生成/加载带宽、不同 token chunk 的 Prefill 时间 | 用于分析计算与 I/O 平衡；包含 SSD/网络路径，与本地主存 H2D 有区别 |

![HCache Figure 11(a-c)，DRAM 后备](hcache-figure11abc-dram.png)

HCache 原图仅截取图 11 顶部 a–c 三个面板，保留共享图例、轴、模型名和设备标签。其余面板使用 SSD 或其他设置，不能混成同一 DRAM 曲线。

## 4. 当前论文可以使用的论据

已有文献足以说明“复用 KV 后仍存在不可忽略的加载成本，按层预加载有机会隐藏部分成本”。论文自身的问题仍是：固定接管目标下，哪些预先驻留的 KV 能减少重试时无法隐藏的等待，再由 Slack 将其映射为工作流影响。现有论文图不证明本系统的放置算法或 WCT 收益。

来源页、原 PDF 哈希与裁图坐标见 [FIGURE_SOURCES.json](FIGURE_SOURCES.json)；重绘数据口径、最终尺寸和检查记录见 [REVIEW.json](REVIEW.json)。
