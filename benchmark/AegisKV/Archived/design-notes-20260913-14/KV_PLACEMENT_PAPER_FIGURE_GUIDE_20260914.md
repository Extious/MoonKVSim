# 请求内 KV 放置：论文用图精选

2026-09-14。本页只保留与当前论文论点直接相关的五张正文候选，按“放哪里—加载能否隐藏—选哪些块”的顺序介绍。编号是本页导读编号，尚未替换论文正式图号。图 2 已按最新澄清修正为逐层计算、逐层连续传输，仅改变初始 Peer HBM 备份前层数；历史整批图保留供追溯。

图 1–2 是 Qwen3-8B 结构与假设速率下的解析结果；图 3–5 是 NOSA-1B 的真实原生选块观测。两组证据来自不同模型，不能把 Qwen3 的时延结果直接套到 NOSA 的访问比例上。以下介绍不用公式。

| 图 | 论文问题 | 直接展示的关系 | 证据类型 |
|---|---|---|---|
| 1 | 相同容量应放在哪些层？ | 驻留位置与逐层恢复等待 | 等容量解析对照 |
| 2 | 初始备份多少前层，能获得多少收益？ | 备份层数、传输/计算时间比与相对总延迟收益 | 连续逐层流水解析 |
| 3 | 同一个请求是否存在反复被选中的 KV？ | Query 位置、层、KV 组与选块变化 | 真实原生选块轨迹 |
| 4 | 可以给每个 token 段统一分配跨层优先级吗？ | 层号、token 原始位置与访问热点 | 全层真实访问频次 |
| 5 | 管理粒度如何影响有限容量覆盖的访问？ | 字节预算、粒度、历史长度与访问集中度 | 真实轨迹的离线统计 |

**图 1：相同 HBM 容量，前层与后层驻留产生不同等待。**

![图1：等容量下前层与后层驻留的逐层恢复剖面](/home/comp/zhanzhao/MoonKVSim/output/pdf/recovery-layer-profile-20260913/paired-layer-profile.png)

读法：上方两行标出故障时各层历史 KV 位于 HBM 还是 DRAM；中间在同一时钟上对齐 H2D、后缀计算与等待；下方按层号分解等待。先比较初始放置，再沿时间线观察橙色等待出现在哪里。

两种放置均占用 768 MiB Peer HBM，恢复时均需加载 3840 MiB，补算工作量也相同。在图中假设下，前六层驻留的暴露等待为 0，后六层驻留为 23.43 ms。差异来自加载与消费次序，而不是总传输量或计算量不同。

论文用途：支撑请求内分层放置的动机——仅统计备份容量或命中总量不足以解释恢复收益，驻留位置还决定哪些加载落在恢复关键路径上。

适用边界：单一连续复制流、从恢复起点提前预取、缓冲充足、整层就绪后计算、复制与计算无争用。Peer 是固定接管 DP。图中时间不含故障发现和接管排队，不是 GPU 恢复实测。

可用图注：同一请求与相同 Peer HBM 字节预算下，前六层和后六层驻留具有相同的计算量和剩余加载量，但产生不同的逐层等待。该解析示例说明初始驻留位置会影响加载与计算的重叠。

[矢量 PDF](/home/comp/zhanzhao/MoonKVSim/output/pdf/recovery-layer-profile-20260913/paired-layer-profile.pdf) · [可编辑 SVG](/home/comp/zhanzhao/MoonKVSim/output/pdf/recovery-layer-profile-20260913/paired-layer-profile.svg) · [逐层数据](/home/comp/zhanzhao/MoonKVSim/output/pdf/recovery-layer-profile-20260913/layer-events.csv) · [数值摘要](/home/comp/zhanzhao/MoonKVSim/output/pdf/recovery-layer-profile-20260913/summary.json) · [绘图源](/home/comp/zhanzhao/MoonKVSim/output/pdf/recovery-layer-profile-20260913/build_profile.py)

**图 2：逐层流水下，初始前层备份与传输/计算时间比的收益关系。**

![图2：逐层流水与初始前缀备份](/home/comp/zhanzhao/MoonKVSim/output/pdf/layerwise-prefix-benefit-20260914/layerwise-ratio-benefit.png)

2026-09-14 用户明确：备份 8 或 9 层仅指初始 HBM 驻留，实际计算和 KV 传输均逐层执行。当前图已按此修正。横轴只改变初始备份前层数，H2D 从执行起点按层连续复制未驻留的历史 KV；该层 KV 到齐且前一层计算结束，即可开始该层计算。

不同曲线表示单层传输耗时为计算的 0.5、1、1.25、2、4 倍。纵轴为相对 0 层备份的总延迟降低百分比，计入全部重放计算和加载等待，越往上越好。上横轴是每层 128 MiB 对应的初始 Peer HBM 占用。各曲线分别判断容量和收益的帕累托集合；0 层点明确给出无备份基线。

在该逐层、无争用模型下，更多初始备份不会推迟任何一层就绪或计算完成，收益上升或持平。1.25、2、4 倍分别在前 8、19、28 层达到平台，最大收益分别为 21.74%、50.68%、75.17%。0.5 和 1 倍从前 1 层起分别保持 1.37%、2.70%，它们仍节省第一层的启动加载等待。较慢传输的曲线在平台前接近重合，图中保留全部准确坐标。

[配套带宽/N 三子图 PDF](/home/comp/zhanzhao/MoonKVSim/output/pdf/layerwise-prefix-benefit-20260914/layerwise-relative-benefit.pdf) 保留此前七种实际参数条件，但按逐层语义重算。25 GB/s、512 token 时，备份前 6 层即达到 13.72% 的最大收益。先前每批模型的前 20 层门槛不能用于此处。

论文用途：展示固定执行规则下，初始备份容量与计算/传输相对速度对恢复等待和总延迟收益的影响。时间比值可以合并带宽和重放长度的作用；真实访问稀疏性仍需图 3–5 的选择轨迹证据。流水机制本身也可用于正常推理，不构成故障恢复专有机制的证据。

适用边界：36 层、均匀层耗时、一个计算流与一个 H2D 流、足够缓冲、已加载 KV 保留、计算与复制不互相降速。层数仅对应初始历史 KV 容量，不是整个恢复期间的 HBM 上限。所有结果为未经硬件校准的解析估算，不计故障检测、接管排队、权重加载、备份维护与前台竞争。

[主图 PDF](/home/comp/zhanzhao/MoonKVSim/output/pdf/layerwise-prefix-benefit-20260914/layerwise-ratio-benefit.pdf) · [当前口径与源数据](/home/comp/zhanzhao/MoonKVSim/output/pdf/layerwise-prefix-benefit-20260914/README.md)

历史追溯：此前的[整批扫描](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-sweep-20260914/README.md)、[整批相对收益](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-relative-benefit-20260914/README.md)与[整批时间比值图](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-ratio-benefit-20260914/README.md)保留为曾采用的额外调度约束，不再作为本页当前模型的正文候选。其锯齿和门槛不适用于用户明确的逐层执行模型。当前结果与最初连续逐层模型逐点匹配，并保存了历史与当前结果的配对差异。

**图 3：真实请求中的 KV 会被不同 Query 反复选中。**

![图3：真实NOSA逐Query、逐层、逐KV组选块轨迹](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/figures/native-query-block-traces.png)

读法：横轴是历史 token 的原始位置，每列对应一个 64-token 块；纵轴是后续 Query。三行面板为事先指定的第 1、14、28 层，两列面板为两个 KV 组。蓝色表示原生非局部选块，金色表示原生首块或局部窗口内被选中的块。

竖直色带表示同一历史块被多个后续 Query 反复选择；色带中断和散点体现需求随 Query 变化。跨面板看同一横坐标，可以观察不同层及 KV 组是否选择同一位置。

论文用途：为“真实模型存在可反复利用的请求内访问热点”提供直接观测，同时保留热点变化，避免只用汇总曲线掩盖实际选择过程。

适用边界：这张图展示文档 10146、32K 历史后最初 128 个 Query；实际记录覆盖完整 28 层和完整输入。数据来自完整因果 Prefill，未执行缓存增量恢复或故障注入。竖直色带不能直接证明在线备份预测成功，也不是主 attention 权重或 GPU 物理访存事务。

可用图注：NOSA-1B 对同一长文本请求的真实逐 Query 选块轨迹。预先指定的三个层和两个 KV 组中可见重复访问与动态变化并存，热点位置依赖层和 KV 组。

[矢量 PDF](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/figures/native-query-block-traces.pdf) · [可编辑 SVG](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/figures/native-query-block-traces.svg) · [原始轨迹目录](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/traces) · [采集与统计说明](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/README.md) · [分析绘图源](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/analyze_native.py)

**图 4：热点位置随 Layer 改变，不能仅按 token 位置统一保护全部层。**

![图4：三份真实文档的28层历史KV访问频次](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/figures/native-layer-block-frequency.png)

读法：每行是一层，每列是一个历史 token 块，颜色是该层后续 512 个 Query 与两个 KV 组中的选中比例。三个面板对应三份在运行前确定的文档。横轴保留原始位置，没有按热度重排。

横向看每层热点集中在哪里，纵向看同一 token 段在不同层是否同样热门，再跨文档观察分布是否一致。首部、局部窗口与内容相关位置共同出现，不能把全部深色区域都解释为语义重要性。

论文用途：支撑至少按“请求、Layer、token 块”组织候选的设计。图 3 展示时间上的选择变化，本图展示完整模型深度上的位置差异，两者用途不同。

适用边界：这是 NOSA-1B 在三个 PG19 文档上的观测；不同层不是独立请求重复。颜色已经合并同层两个 KV 组，掩盖了组内差异；是否进一步拆分 KV 组，需要由实际分配与复制布局决定。图本身不决定 HBM 放置或恢复收益。

可用图注：三份真实长文本中，NOSA-1B 全部 28 层的历史块访问频次。热点保留原始 token 坐标，显示同一位置在不同层的需求存在差异，为分层、分块管理提供依据。

[矢量 PDF](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/figures/native-layer-block-frequency.pdf) · [可编辑 SVG](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/figures/native-layer-block-frequency.svg) · [逐层统计](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/per_layer_statistics.csv) · [来源与采集配置](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/README.md)

**图 5：字节预算和管理粒度共同决定能够覆盖多少访问。**

![图5：NOSA真实访问集中度及管理粒度对照](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/figures/native-access-concentration.png)

读法：横轴是按同一窗口的观测频次排序后累计的历史主 KV 字节比例，纵轴是累计选块访问覆盖。三列分别按“层、KV组、块”“层、块”“包含全部层的 token 段”统计；两行分别为 16K 和 32K 历史，每条曲线是一份文档。20% 容量点用实心点标出。

同一容量点跨列比较，显示管理粒度的影响；同一列跨行比较，显示历史长度的影响。在 32K 条件下，约 20% 的“层、块”字节覆盖 89.69%–92.62% 的访问；若同一 token 段必须连同全部层一起保留，20% 字节仅覆盖 52.83%–55.72%。16K 条件下的集中度较弱，图中保留了这些结果。

论文用途：给出“少量容量覆盖较多访问”的定量证据，并解释为什么只按全层 token 段管理会损失选择空间。它是访问层面的容量曲线，适合接在原始位置图之后。

适用边界：同窗口离线排序不是在线备份命中率。横轴只计主 KV，不含压缩、索引等辅助状态。访问覆盖不等于避免的首次加载比例，更不等于恢复等待减少比例；高频集合之外的冷块仍可能被需要。三份文档、两种长度共六次完整 Prefill，每种输入长度配置运行一次；三张 NOSA 图复用了这批数据，不能相加成更多独立运行。

可用图注：NOSA-1B 在三个长文本上的历史主 KV 访问集中度。按同窗口频次离线排序，不同管理粒度在相同字节预算下获得不同的访问覆盖；上下两行保留历史长度变化带来的差异。

[矢量 PDF](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/figures/native-access-concentration.pdf) · [可编辑 SVG](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/figures/native-access-concentration.svg) · [完整曲线](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/concentration_curves.csv) · [各预算精确字节与覆盖率](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/budget_coverage.csv)

**正文组织建议。** 图 1–2 说明层间放置与加载调度，但必须保留两图不同的就绪规则；图 3–5 连续说明原生稀疏访问。版面紧张时，图 3 的逐 Query 细节与图 4 的全层汇总可在后续排版中整合，但整合前应保留原图和原始统计口径。当前已更新本导读的图 2，尚未替换论文正式排版。

**这些图还没有回答的部分。** 同一原生稀疏模型上，故障前选出的块能消除哪些首次加载等待，仍缺需求揭示、首次使用、实际加载就绪与计算依赖对齐的恢复图。Failure rate、Slack、前台竞争和不同模型架构的放置收益也尚未由这五张图建立。已有解析图与真实访问图可以支撑两个独立动机，不能拼接成已验证的端到端备份收益。

旧的理论图目录说明中“尚无原生稀疏访问轨迹”记录的是当时状态；后续真实数据以本页图 3–5 的 NOSA 来源为准。

核对记录：此前核对五张 PNG、图 1 数值摘要及图 5 的字节预算与文档对应关系。图 2 扩展为 2160 个分批解析状态、60 个最小零等待批大小和完整整数曲线，并提供逐批与逐层事件核对、178 mm 宽 PNG/PDF/SVG 及实际渲染检查。旧图原文件没有修改；未重新验收整篇论文排版。
