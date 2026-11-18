# Motivation revision response — 2026-09-19

**完成状态：本轮已核实的五项动机修改已完成，独立预览及局部检查通过。** 等待三家综合评审清单；尚未开展真实恢复实验，也未证明有限 Peer-HBM 的净收益。此文件供协调任务通过 SSH 读取。

范围：§2 中英文正文、Figure 1/2 图注、Figure 1(a)/2 图源和导出，以及本目录的验证材料。没有编辑 abstract、§3、Figure 3/4/5、共享 `main.tex`/`references.bib` 或构建脚本；没有编译共享 `main.pdf`、提交 Git、修改冻结送审基线或启动硬件/AIConfigurator 新查询。原 Figure 1(b)(c) 图像与数值不变；28 个数据/配置输入文件的哈希全部不变。

## 意见 → 处置 → 文件 → 验证

| 已核实的意见 | 处置 | 修改位置 | 验证与剩余边界 |
|---|---|---|---|
| 昂贵 prefill 不能直接证明 HBM 值得；DRAM 已避免多数重算 | 将论证落到有限容量下的 WCT 分配；明确 DRAM-only 是必要基线。增加孤立请求的增量 WCT 公式、低 Slack/不可隐藏传输等待/前台可用容量三个条件，以及负载、共享带宽、容量、故障频率下的 break-even 验证；无净收益时释放额外 HBM | §2 开头、§2.4，中英文同步 | 对 25 个配置、6 个 Slack 位置验证增量收益在 `[0,D-H]` 内，`Slack >= D` 时为零。该恒等式不证明真实系统收益，完整验证仍待实验 |
| trace 与依赖假设、workflow-max 与 Slack、选择实例与总体证据容易混淆 | 图 1(a) 横轴改为 `Max. duration gap (s)`，子图名强调 workflow maximum；精简图注和正文，分别交代真实时序、Main 依赖假设、按可读性与较长关键前缀选择的实例，以及静态反事实。保留 Main 期间活动，不额外排除 | §2.2、`motivation-figures.tex`、绘图源及 Figure 1(a) 导出 | 重新聚合得到 286/292 组、121 工作流、median 137.758 s、P90 1172.684 s；图值不变。敏感性见下文，无真实依赖标签 |
| Figure 2 同时编码模型和路径，且外推范围不够直观 | 颜色＋线型编码路径（HBM 实线、DRAM 虚线、Recompute 点线）；形状编码模型；Qwen >256K、DSA >32K 的指定外推点用空心标记，其他点仍是静态估计。单轴、3.34×2.35 英寸、四模型最大上下文全部保留 | §2.3、`motivation-prefill-figure.tex`、绘图源及 Figure 2 导出 | 12 条曲线、75 个原值逐点一致；18 个空心点与输入标记匹配。实际 PDF、灰度及嵌入页面已查看，未添加 jitter 或隐藏重合曲线 |
| 相关工作的能力和资源成本应具体，不能把既有能力当 novelty | 明确 DéjàVu 的远端 CPU 复制、GhostServe 的主机 parity 与恢复 I/O/部分重算重叠、LUMEN 的负载感知放置/路由及 reload 辅助、Mooncake 的 KV 池与 SLO 调度；把差异收窄到 workflow delay tolerance 与恢复 KV 的有限快层分配 | §2.1，中英文同步，沿用已有参考文献键 | 已核实一手原文；未声称首次 KV reuse、首次 load-aware recovery、首次 overlap，未声称公平实测超越上述系统 |
| 图注冗长、故障模型与实现参照需清楚 | 缩短 Figure 1/2 图注，详细条件留在正文；定义 worker 可为完整 TP 组，接管者有兼容权重，控制面/token 历史/备份必须存活。全历史 HBM 仅为参照，有限热块方案仍可能需 DRAM | §2.1/2.3、两图图注 | 独立 EuroSys Motivation 预览 4 页，图 1/2 在第 2 页；普通图内最小字号约 10.23 pt，无 Overfull、未定义引用或 LaTeX/package warning；7 条 Underfull hbox 来自参考文献，不存在可见越界 |

本轮没有接受“此前未披露静态/反事实性质”的说法：原稿已披露，本轮调整的是论证力度和阅读成本。

## 文件与可复核产物

- 正文：[Markdown](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/draft/background_and_motivation.md)、[LaTeX](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/sections/background_and_motivation.tex)。
- 图注：[Figure 1](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/sections/motivation-figures.tex)、[Figure 2](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/sections/motivation-prefill-figure.tex)。
- 图源：[render_motivation_row.py](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py)；导出在 `paper/figures/motivation-row/`，更新该目录 `MANIFEST.json` 和 `FIGURE_REVIEW.json`，旧检查记录保存在本目录 `motivation-before/`。
- [独立预览 PDF](/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-external-review-revision-20260919/motivation-preview/motivation-preview.pdf)，SHA-256：`ba28f65272df64f9bfbd1bc233fab41de9dca0de90dbe05e05c301caf790d30d`。
- [修改后第 2 页](/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-external-review-revision-20260919/motivation-renders/preview-page-2.png)、[Figure 2 灰度](/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-external-review-revision-20260919/motivation-renders/motivation-recompute.pdf.gray.png)。
- [检查脚本](/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-external-review-revision-20260919/check_motivation.py)、[数值/编码/元数据检查](/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-external-review-revision-20260919/motivation-checks.json)、[完整审查记录](/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-external-review-revision-20260919/motivation-review.json)。
- 新 Figure 2 PDF SHA-256：`d2e44dc8bafa9c6ad0083044b37d782f4b595e89ecd3e4e38089b4d97bf25e1d`；完整输入/输出哈希见 JSON。

独立编译命令（工作目录为 `benchmark/AegisKV/paper`）：

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  -outdir=/home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-external-review-revision-20260919/motivation-preview \
  motivation-preview.tex
```

局部检查命令（仓库根目录）：

```bash
.venv/bin/python output/pdf/aegiskv-external-review-revision-20260919/check_motivation.py
```

## 已有数据的低成本敏感性复算

以下复算只检查口径和说明性实例，不改论文图值，不增加真实依赖标签或模拟运行数。

| 从最后分支结束到后续 Main 开始的额外上限 | 保留组 | 工作流 | workflow-max gap 中位数 / P90（s） |
|---|---:|---:|---:|
| 不加上限（现图） | 286 | 121 | 137.758 / 1172.684 |
| 30 s | 226 | 104 | 134.198 / 841.479 |
| 10 s | 211 | 100 | 129.400 / 743.792 |
| 5 s | 184 | 93 | 131.545 / 658.815 |
| 1 s | 9 | 8 | 70.205 / 315.753 |

中位数在 5–30 s 的事后筛选下相近，但 P90 与样本覆盖变化明显，1 s 时只剩 8 个工作流；不能宣称时序代理已验证或所有分布稳健。原 286 组中，96 组在分支执行期间有 Main 请求提交，265 组有 Main 请求执行；两者都不排除 fan-in。全组 gap 中位数为 133.431 s，与图中每工作流最大值口径不同。

Figure 1(b) 的选择记录有 3 个合格候选，选中的是关键分支前缀最长者。保持离线 Slack 不变、统一缩放 Figure 1(c) 四个静态代价时，0.25/0.5/1/2 倍下最大 WCT 损失为 A2；4 倍时转为 A4（A2 128.722 s，A4 133.771 s）。这是未校准的代价敏感性，说明排序依赖代价和 Slack 的共同作用，不能固化为“总是保护原关键分支”。没有将 CC 时序或哈希块计数当作 native selector trace。

## 一手文献核对

- [DéjàVu §4.2.3、Appendix E](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/06/7085_d_j_vu_kv_cache_streaming_for_.pdf)：KV 复制及流水线故障恢复；不将它描述为没有恢复协议。
- [GhostServe §4.2、§6.1、§8](https://proceedings.mlsys.org/paper_files/paper/2026/file/d99e8e80a6c41e148db686918dd7eab3-Paper-Conference.pdf)：已有 partial recomputation/I/O overlap；静态并行拓扑及硬故障能力有明确边界。
- [LUMEN §4.2–4.5](https://arxiv.org/html/2606.17787v1)：已有 checkpoint placement/retry/load 协调和 reload 辅助，不能省略其资源与负载处理能力。
- [Mooncake FAST 2025](https://www.usenix.org/conference/fast25/presentation/qin)：DRAM/SSD KV 池和请求 SLO 下的吞吐优化。这里引用的是论文架构，不推断最新 Mooncake 实现的全部故障能力。

## 未解决的实验与整稿事项

1. **有限 HBM 相对 DRAM-only 的净收益**：配对固定模型、worker/TP 拓扑、workflow ID/到达顺序、故障逻辑进度、相同已提交前缀和尾部；扫描负载、共享 host/link 拓扑与有效带宽、Peer 容量和复制率。报告全部工作流的 WCT、正常服务吞吐/TTFT/TPOT、复制流量与 HBM 占用，同时保留无收益/负收益区域。静态图未含共享瓶颈，不能凭多个 retry 推断排队级联收益。
2. **Break-even 判据需要数据**：在匹配工作负载上令 `G_F` 为有限 HBM 相对 DRAM-only 在故障场景的平均 WCT 净改善（含受影响与未受影响工作流），`C_0` 为无故障场景的平均 WCT 增量。对于已定义场景混合概率 `p`，平均收益要求 `p*G_F > (1-p)*C_0`。若二者均为正，交点为 `p*=C_0/(G_F+C_0)`。这是待测量后的判据，不是已知生产故障概率或当前结果；尾部/SLO 仍须单独比较。
3. **同终点与正确性**：RTX 4090 诊断作业 153195 的缓存批量尾部和完整前向输出差异尚未解决，旧结果不能用于本图。还缺同条件 H2D/恢复实测、原生 sparse KV 与辅助状态恢复正确性、长上下文精度及实际容量验证；按照用户指令本轮不启动这些实验。
4. **公平故障模型与相关工作基线**：当前接管合同是失效 worker/TP 组之外已有兼容模型的存活 worker；不能直接把 GhostServe 的 memory-flush/静态拓扑结果当成同等硬故障接管基线。需要统一失效范围、备份存活域和 reload/接管开销，再比较方法。
5. **整稿集成**：本任务只检查独立 §2 PDF。算法/协调任务统一重编共享 `main.pdf` 后仍需检查总页数、两图浮动位置和跨节引用。Figure 1(c) 保留 Qwen14B/A100 静态配置，Figure 2 为 H100，不把两图数值串成同一次实验。旧选择记录里“与 Figure 2 配置相同”的描述是历史版本语境；当前正文、图注及审查记录明确分开，冻结数据输入未改写。

**交接状态：可由算法任务统一集成编译；本轮源文件和图像修订完成，新增实验证据及后续综合评审尚待处理。**
