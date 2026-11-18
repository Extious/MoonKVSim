# 论文初稿的逐图审查与证据范围

[论文初稿](Paper_Draft.md) · [历史审查](PAPER_FIGURE_REVIEW_PrefixAdmission_20260908.md)

本轮只优化图像，数据沿用此前冻结的 source-v3 实验。Algorithm 2 仍在调整，按用户要求暂缓实现同步；设计图说明机制，定量图不作为后续修改版本的运行证据。统计图统一三系统颜色、线型和固定 Workflow 映射；示意图使用具体共享块、数值账本、显存比例与同一对象的提交状态。所有输出按 7 / 3.33 inch 绘制，独立 PDF 可直接被 LaTeX 组合。实际字体、来源哈希、账本与最终导出的核对结果见 [本轮核对记录](../../../output/agent-lease-20260908/DELIVERY_AUDIT.json)。

## 从图集到论文初稿

Paper_Draft.md 为中文正文，仅含 Motivation、System Design 和 Evaluation 三部分，12 张正文图连续编号（Motivation 3、System Design 1、Evaluation 8）。Motivation 用三条 Observation 推导设计要求；System Design 只展示一张完整架构；Evaluation 按八个问题选图，配置和机制消融用表格呈现。原 49 个 CSV 与全部未改统计图保持原样，新图由既有证据重新组合。

结构与背景参考 [原论文](../paper/main.tex) 的 [Motivation](../paper/sections/motivation.tex)、[System Design](../paper/sections/system-design.tex)、[Experimental Method](../paper/sections/experimental-method.tex) 和 [Results](../paper/sections/results.tex)。原文的 PrefixAdmission、170 次旧矩阵和 RTX4090 旧结果不移入当前初稿；source-v3、三系统比较及 L40S 组件数据沿当前图像来源。Algorithm 2 后续设计调整仍未同步为本节实验。

正文源为 [agent-lease-draft.md](scripts/paper/templates/agent-lease-draft.md)，图注源为 [agent_lease_draft_captions.py](scripts/paper/agent_lease_draft_captions.py)。 [独立图 LaTeX](../../../output/pdf/aegiskv-agent-lease-20260908/paper-figures.tex) · [可选同行 LaTeX](../../../output/pdf/aegiskv-agent-lease-20260908/paper-pairs.tex) · [图像插入尺寸样张](../../../output/pdf/aegiskv-agent-lease-20260908/paper-placement.pdf) · [正文浏览器预览](../../../output/pdf/aegiskv-agent-lease-20260908/paper-story.html)。尺寸样张只展示图与英文图注，不是中文全文 PDF。

## PaperBanana 内容与风格规格

本轮在 55 组可追溯图中选取 12 张正文图，43 张保留为补充。新增恢复暴露、综合成本、共同坐标原生干扰、逐配置敏感性四种图像，重画完整 System Overview。规划与保留/合并理由见 [紧凑图稿规格](scripts/paper/templates/compact-figure-spec.md)。三条动机分别使用轨迹观测、旧模型推演和解析容量，不能互相混作实验重复。

| 实际查看的参考 | 借鉴对象 | 当前图的应用 |
|---|---|---|
| [Ensō，OSDI 2023](../docs/related_works/figure-references-20260908/enso-osdi23.pdf)，对象状态图 | 同一对象在不同状态下的排列与直接标签 | 子租约、准入、独立提交；不沿用参考论文的机制 |
| [Mooncake，FAST 2025](../docs/related_works/figure-references-20260908/mooncake-fast25.pdf)，资源架构与代价分解 | 物理资源分组、分解柱与相邻证据 | Source/Peer/Store、显存布局、CPU/流量分解 |
| [CausalSim，NSDI 2023](../docs/related_works/figure-references-20260908/causalsim-nsdi23.pdf)，定量比较 | 线型/标记冗余编码、共享图例与分布 | 三系统曲线、入场顺序包络、原生微基准 |

统计图以 Mooncake 灰、DRAM-only AegisKV 橙、AegisKV 蓝为系统编码；组成柱的颜色表示来源，系统另标在横轴。密集 Workflow 图每十对象添加形状标记，连线仍保留全部对象。单栏图例集中于顶部独立区域，字号至少 10 pt；宽图为 7 inch、单栏为 3.33 inch。相邻比较共用可比坐标，局部放大的轴在图注中说明。

设计图采用可编辑矢量对象；提交状态图中的填充表示已提交，虚线轮廓表示 pending，划除表示释放/中止；不同图中的虚线含义由局部标签与图注明确。Q 边界透明以保持对象可见。AIMD 的 C/Q/Used 分栏显示，额外前台需求先裁剪授权，物理容量由 free ACK 确认。

## 逐图优化与核对

| 图 | 证据类型 | 本轮优化 | 科学口径与范围 | 去向 |
|---|---|---|---|---|
| [1 并行分支留下多少时间差](Paper_Draft.md#paper-motivation-branch-gap) | 观测动机 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | 124 个具有重叠分支的观测 Workflow，每个对象取最大分支持续时间差；对数秒轴。它说明分支存在不均衡，还不能直接作为可消费的因果 Slack。 | 正文 |
| [3 长上下文副本的容量代价](Paper_Draft.md#paper-motivation-kv-capacity) | 解析计算 | 容量曲线与参考线直接标注；参考线明确为扣除权重和 runtime 后的容量。 | 按 Qwen3-8B BF16 的 147,456 B/token 计算，96 Ki tokens 的一份 / 两份 KV 为 13.5 / 27 GiB。参考线仅扣模型权重和 2 GiB runtime，尚未扣动态前台 KV，不能视为 Peer 配额。 | 正文 |
| [4 数据路径与三个算法的职责](Paper_Draft.md#paper-system-overview) | 设计示意 | 一张完整架构：Source/Peer/DRAM/Recovery 四个资源域，同名 C0/C1 贯穿独立复制及恢复，P0/P1 保留给无关前台；独立显存反馈闭环。 | 同一 Source 分别向 Peer HBM 和 Store DRAM 复制；实线为数据，虚线为控制。Algorithm 2 管理物理块上的 Agent 子租约，Algorithm 3 独立限制目标 GPU 允许借给备份的显存。 | 正文 |
| [A1 按联合 Workflow 收益分账](Old_Figures.md#agent-lease-supplements) | 设计示意 | 三种状态共用毫秒轴；填充表示工作，虚线表示恢复；Join 与边际分账可手算。 | 同一 DAG 的两条分支共享一个物理块；按固定 Agent 顺序逐个加入恢复改善，WCT 为 12→12→10 ms，分账为 0+2 ms。单个分支的重算下降不等于整个 Workflow 等额缩短。数值为可核算示意。 | 补充 |
| [A2 信用跨请求保留，按 Agent 新轮更新](Old_Figures.md#agent-lease-supplements) | 设计示意 | 透明 Q 边界保留内部对象；同宽信用条分别显示 A/B 余额与已花信用。 | 共享尾块 X 上 A/B 信用为 6/4，竞争尾块 Y 为 2；按物理容量收租后 X 为 4.8/3.2，Y 淘汰。仅 A 进入新轮时 X 变为 6/3.2；同轮命中不能补回已花信用。内部块 R 不参加尾块收租。 | 补充 |
| [A3 单块试算、释放与提交](Old_Figures.md#agent-lease-supplements) | 设计示意 | 同一前缀树贯穿释放与提交；可读集合、两种准入门及 ACK 次序明确标出。 | 每个状态都只画一个共享 R；只从可释放尾块 Q 选牺牲者。空闲门为 G≥0，替换门为 G>D。版本核验后应用试算，free 完成后分配，复制 ACK 后才可恢复；失败不复活已释放的旧块。 | 补充 |
| [A4 独立的显存借用上限控制](Old_Figures.md#agent-lease-supplements) | 设计示意 | 按比例画 40 GiB；三种控制条件分别对照 C、Q、Used；下一步需求与 free ACK 分开。 | 40 GiB 示意布局明确区分前台、保留量、备份和 FREE。C 是硬上限，Q 是允许借用的额度，均不是实际占用；增长、预警减半和容量裁剪单独展示。实现使用 50 ms 窗口、连续 4 个稳定窗口、每次增 1 GiB、β=0.5。 右列表示下一步前台需求增加 4 GiB，裁剪后旧副本仍占 4 GiB，物理 free ACK 到达才降至 2 GiB。 | 补充 |
| [A5 独立提交决定故障后能恢复的前缀](Old_Figures.md#agent-lease-supplements) | 设计示意 | 同一个 C1 对齐两个 tier 的提交与故障；恢复路径显示装入前缀和重算后缀。 | 同一 C1 的 Peer ACK 已到、DRAM 尚 pending 时 Source 故障，两个 tier 因而留下不同前缀。恢复仍须装入新 primary 并重算缺失后缀；图中间距仅表示逻辑次序。 | 补充 |
| [A6 输入的 Prompt 长度分布](Old_Figures.md#agent-lease-supplements) | 输入统计 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | 冻结输入的 1,304 个原始请求；Ki=1,024 tokens。两轮扩展不作为新原始样本。总上下文最大 86,214 tokens，不能据此声称覆盖 128K。 | 补充 |
| [A7 输入的 Workflow 规模](Old_Figures.md#agent-lease-supplements) | 输入统计 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | 160 个原始 Workflow 的调用数分布，最大为 27。样本单位是 Workflow；不是 160 次完整系统运行。 | 补充 |
| [5 同配置逐 Workflow 的 WCT](Paper_Draft.md#paper-f0-revisit-wct) | 未标定机制模拟 | 固定 Workflow ID 与顺序；折线保留每个对象，每十个对象加识别标记；差值图加清晰零线。 | 每点是同一个 Workflow；从首次 release 至最后请求完成，不含活跃 slot 外的入场等待。三系统只按 Mooncake 的同一序列对齐，保留全部尖峰。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 | 正文 |
| [A8 逐 Workflow 的完成时间变化](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 固定 Workflow ID 与顺序；折线保留每个对象，每十个对象加识别标记；差值图加清晰零线。 | 各系统 WCT 减同一 Workflow 的 Mooncake WCT；零线为 Mooncake，正值更慢、负值更快。与上一图使用同一 ID 映射，不按差值重新排序。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 | 补充 |
| [A9 单一入场顺序的 WCT 分布](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | seed 0 的完整 160 对象经验分布；主文使用三种入场顺序的分布包络补充稳健性，本图保留为单配置核对。 | 补充 |
| [7 DRAM 准入是否保住正常复用](Paper_Draft.md#paper-f0-revisit-dram-hit) | 未标定机制模拟 | 固定 Workflow ID 与顺序；折线保留每个对象，每十个对象加识别标记；差值图加清晰零线。 | 正常服务实际复用的 DRAM token / 全部 prompt token，包含冷访问和精确重访；恢复 token 不计入。它是 token 命中率，不是请求命中比例。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 | 正文 |
| [A10 实际复用来自哪一层](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 分解柱从零起，图例放在独立顶部区域；系统标在横轴，颜色与纹理表示组成。 | 将全部 prompt token 互斥分解为 Local HBM、Store DRAM、Peer HBM 和重新计算，合计 100%。Peer 备份写入量不会被计为正常服务的命中收益。 | 补充 |
| [A11 正常请求的 GPU 调度排队](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 固定 Workflow ID 与顺序；折线保留每个对象，每十个对象加识别标记；差值图加清晰零线。 | 每个 Workflow 内请求的平均 GPU-ready→运行等待。GET、CPU 和等待分配 HBM 分开计量，不能把它们都写成 scheduler queue。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 | 补充 |
| [8 前台因 HBM 准入而等待多久](Paper_Draft.md#paper-f0-revisit-hbm-wait) | 未标定机制模拟 | 固定 Workflow ID 与顺序；折线保留每个对象，每十个对象加识别标记；差值图加清晰零线。 | 每个 Workflow 内请求的平均前台 HBM 等待；Peer 是否增加排队，需要同时看显存余量、动态消融和原生干扰微基准，不能仅凭跨系统的一个均值归因。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 | 正文 |
| [A12 GPU 的低空闲显存时间占比](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | 按每张 GPU 的时长加权，统计 FREE 低于 1 GiB 的执行时间比例；保持真实 GPU 编号和同一阈值。包含可回收的普通缓存，低余量不等于 OOM、HBM 带宽饱和或服务违约。 | 补充 |
| [A13 请求 TTFT 的完整分布](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | 所有 2,608 个请求从 release 到第一个输出 token 的经验分布；与只量 GPU prefill 的耗时不同，包含执行路径上的等待。 | 补充 |
| [A14 请求平均 TPOT 的尾部](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | 每系统 2,432 个分母有效的请求先计算首 token 后的平均 TPOT，再绘制包含等号的经验生存比例；保留完整尾部。它不是逐 token ITL 分布，也不是跨运行置信区间。 | 补充 |
| [A15 逐 Workflow 的 CPU 服务报价变化](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 固定 Workflow ID 与顺序；折线保留每个对象，每十个对象加识别标记；差值图加清晰零线。 | 对准入和前台派发的固定 CPU 服务报价按 Workflow 归因，再减 Mooncake；全局控制 CPU 单独计量。这条曲线不是每个 Workflow 的实测 CPU 利用率。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 | 补充 |
| [A16 进入模拟时序的控制 CPU 服务](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 分解柱从零起，图例放在独立顶部区域；系统标在横轴，颜色与纹理表示组成。 | 固定服务报价的总和，分为前台派发和准入；经过同一个控制器队列。提交、回收和 AIMD 的全部 CPU 工作量还没有完整转成因果延迟。 | 补充 |
| [A17 Python 参考实现的实际 CPU 工作量](Old_Figures.md#agent-lease-supplements) | Python 参考 CPU 实测 | 分解柱从零起，图例放在独立顶部区域；系统标在横轴，颜色与纹理表示组成。 | 按线程 CPU 时间分解前台派发、准入与 DAG、提交、回收与 AIMD，扣除嵌套计量避免重复。它是本参考实现的组件工作量，未覆盖原生服务的全部 CPU。 | 补充 |
| [A18 实际传输量的组成](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 分解柱从零起，图例放在独立顶部区域；系统标在横轴，颜色与纹理表示组成。 | 累计模拟内传输的字节，分为正常 GET、DRAM 写入和 Peer 复制，纵轴 TiB。更多副本写入与较少正常命中可能同时发生，不能仅比较总字节得出带宽无争用。 | 补充 |
| [A19 保护流量是否拖慢前台 GET](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | 每个成功正常 GET 的实际传输服务时长 / 同字节量独占链路时长；横轴倍率。不同系统的命中对象和 GET 数量会变，CDF 是描述性分布。 | 补充 |
| [A20 逐 Workflow 的后台复制量](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 固定 Workflow ID 与顺序；折线保留每个对象，每十个对象加识别标记；差值图加清晰零线。 | DRAM 与 Peer 实际后台传输之和，按源 Workflow 归因；与固定 Workflow 顺序的 WCT 图配套诊断。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 | 补充 |
| [A21 逐 Workflow 的 Peer 复制量](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 固定 Workflow ID 与顺序；折线保留每个对象，每十个对象加识别标记；差值图加清晰零线。 | 只统计实际 Peer 传输，不用 AegisKV 总流量减 DRAM-only 来估算。Mooncake 与 DRAM-only 为重合零线。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 | 补充 |
| [A22 25% 进度选点的逐 Workflow 故障代价](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 三个故障位置共用纵轴；每十对象设识别标记，保留全部 160 个对象及正、负、零值。 | 三系统各用本系统 F1 减配对 F0；均为同一 2,608 请求输入。选点依据 Mooncake F0 的 25% 完成进度附近第一轮长请求，在其 prefill 60% 触发单 GPU 故障。包含已完成对象的零值与调度重排产生的负值。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 三个故障位置使用同一纵轴范围。 | 补充 |
| [6 50% 进度选点的逐 Workflow 故障代价](Paper_Draft.md#paper-f1-q50-workflow-penalty) | 未标定机制模拟 | 三个故障位置共用纵轴；每十对象设识别标记，保留全部 160 个对象及正、负、零值。 | 三系统各用本系统 F1 减配对 F0；均为同一 2,608 请求输入。选点依据 Mooncake F0 的 50% 完成进度附近第一轮长请求，在其 prefill 60% 触发单 GPU 故障。包含已完成对象的零值与调度重排产生的负值。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 三个故障位置使用同一纵轴范围。 | 正文 |
| [A23 75% 进度选点的逐 Workflow 故障代价](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 三个故障位置共用纵轴；每十对象设识别标记，保留全部 160 个对象及正、负、零值。 | 三系统各用本系统 F1 减配对 F0；均为同一 2,608 请求输入。选点依据 Mooncake F0 的 75% 完成进度附近第一轮长请求，在其 prefill 60% 触发单 GPU 故障。包含已完成对象的零值与调度重排产生的负值。 每隔 10 个对象添加识别标记，连线保留全部 160 个 Workflow。 三个故障位置使用同一纵轴范围。 | 补充 |
| [A24 不同故障位置的尾部 Workflow 损失](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 三系统紧凑图例；颜色、线型和标记联合编码；仅连接实际执行的设置。 | 每个预定故障位置，对全部 160 个配对 Workflow 的 F1−F0 求 P95。三个位置是不同干预，不是同条件三次独立重复；实际参考进度另表给出。 | 补充 |
| [A25 保护缩短的是哪个恢复阶段](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 九根柱保持故障位置分组；系统与恢复阶段分别编码，图例独立于柱体。 | 每根柱追踪同一个预定焦点请求：从故障到前缀装入，再到后缀计算与解码恢复；Peer/DRAM 恢复 token 和重算 token 另存 CSV。只缩短前缀装入不等于总恢复获益。 每个故障位置的柱从左到右均为 Mooncake、DRAM-only AegisKV、AegisKV；颜色表示系统，纹理表示恢复阶段。 | 补充 |
| [A26 何种故障概率下才能抵消正常开销](Old_Figures.md#agent-lease-supplements) | 模拟结果的解析混合 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | 解析混合 E[WCT]=(1−p)·F0+p·平均 F1，假定一次完整执行至多一个故障，三个预定位置等权。p 是分析参数，不能解释成观测故障率、MTBF 或多次故障结果。 | 补充 |
| [A27 更换入场顺序后的正常 WCT](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 相同对象的三个入场顺序以线和包络表达；CDF 保留完整尾部，顶部留出刻度空间。 | 三种预定入场顺序包含相同 160 个 Workflow；每个经验分位的线为中位数、阴影为三个顺序的最小/最大值，不是置信区间，也没有合并成 480 个独立样本。无故障、资源和两轮输入均相同。 | 补充 |
| [A28 更换入场顺序后的故障代价](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 相同对象的三个入场顺序以线和包络表达；CDF 保留完整尾部，顶部留出刻度空间。 | 三种预定入场顺序包含相同 160 个 Workflow；每个经验分位的线为中位数、阴影为三个顺序的最小/最大值，不是置信区间，也没有合并成 480 个独立样本。每个顺序各自从 Mooncake F0 选择中期故障，再减本系统对应 F0。 | 补充 |
| [A29 真实 forward 与 DMA 并发：batch 1](Old_Figures.md#agent-lease-supplements) | 真实 GPU 组件微基准 | batch 1/4 共用 0.96–1.36 倍纵轴；统一四系列编码，保留中位数与全观测范围。 | batch=1，额外触达分配 8 GiB；prompt 为 512/2,048/4,096 tokens。每个测量块内用相同 prompt 的无复制 forward 归一化；Peer 输入、输出和 DRAM 写入分开测。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 补充 |
| [A30 真实 forward 与 DMA 并发：batch 4](Old_Figures.md#agent-lease-supplements) | 真实 GPU 组件微基准 | batch 1/4 共用 0.96–1.36 倍纵轴；统一四系列编码，保留中位数与全观测范围。 | batch=4，额外触达分配 8 GiB；prompt 为 512/2,048/4,096 tokens。每个测量块内用相同 prompt 的无复制 forward 归一化；Peer 输入、输出和 DRAM 写入分开测。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 补充 |
| [A31 分配容量与复制争用分别测量](Old_Figures.md#agent-lease-supplements) | 真实 GPU 组件微基准 | 局部秒轴与完整观测范围；颜色、线型、空心标记同时区分四种复制条件。 | batch=4、prompt=4,096，额外触达分配 0/8/16 GiB；比较四种 DMA 条件的真实 forward 时长。纵轴放大局部变化，零 OOM 只适用于这批条件。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 补充 |
| [A32 真实复制速率随前台计算变化](Old_Figures.md#agent-lease-supplements) | 真实 GPU 组件微基准 | 单栏紧凑图例与方向标记；保留中位数及最小/最大值，单位和组件测量范围不变。 | batch=1、额外占用 8 GiB，按每个块的实际复制字节 / 复制完成时间聚合；256 MiB 缓冲反复复制。这里的并发有效速率不是链路标称容量。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 补充 |
| [A33 撤销备份后的实际释放延迟](Old_Figures.md#agent-lease-supplements) | 真实 GPU 组件微基准 | 单栏紧凑图例与方向标记；保留中位数及最小/最大值，单位和组件测量范围不变。 | 1/4/8 GiB 分配各 20 次：等待异步写入 fence 与 allocator free+empty_cache+同步分开测。两部分都是实测完成时间，不能直接替代原生服务的回收延迟。 标记和误差线为 20 次测量的中位数与最小/最大值。 | 补充 |
| [A34 原生复制线程的 CPU 需求](Old_Figures.md#agent-lease-supplements) | 真实 GPU 组件微基准 | 单栏紧凑图例与方向标记；保留中位数及最小/最大值，单位和组件测量范围不变。 | batch=1、额外占用 8 GiB，测量整个 forward 窗口的进程 CPU / 墙钟时间，以核数表示；包含本微基准的复制线程与 CUDA 同步等待。它不等价于原生 AegisKV 准入 CPU 或整台服务器利用率。 每条件含同一次 GPU 分配中的 5 个随机交错测量块；标记和误差线为中位数与最小/最大值，不是置信区间。 | 补充 |
| [A35 Algorithm 2 / 3 的正常服务消融](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | 分别去掉 DAG 联合价值、将空闲门改为严格 G>0、或将动态 Peer 改为静态容量上限。相同输入与 CPU 报价，每次只改一个因素；减少保护可能降低正常开销，也可能损失恢复覆盖。 | 补充 |
| [A36 惰性计算是否保持同样的准入决策](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 绝对操作计数从零起；千位分隔，保留 Lazy/Eager 的完整尾块检查与价值计算。 | DRAM-only 上比较 Lazy / Eager：两者都检查全部可释放尾块，只允许跳过版本未变的价值计算。比较每次接纳/拒绝与牺牲块序列必须完全相同；计数包含被拒绝的试算。 | 补充 |
| [11 AIMD 授权与实际副本占用](Paper_Draft.md#paper-aimd-quota-and-occupancy) | 未标定机制模拟 | 时序线型和独立图例区分硬上限、授权与实际占用；轴上 GiB，图注明确八卡合计。 | 在 30% DMA 额外 forward 时长的敏感性条件下，按 50 ms 窗口汇总 8 张 GPU 的 C、Q 和实际副本。物理占用含 pending；模拟器在 fence 后同步 free，真实释放时长另图测量。 两张控制时序图共用横轴范围，各曲线保留自身观测终点。 | 正文 |
| [A37 预警反馈是否随控制变化](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 0–20% 显示全部观测；统一线型区分动态与静态，保留各自执行终点。 | 同一 30% 争用假设下，比较 Guarded AIMD 和只保留显存上限的 Static Peer；1 s 桶内统计产生归一化 forward 预警的目标窗口比例。预警不是请求 SLO 违约率。 纵轴 0–20% 覆盖全部观测值。 两张控制时序图共用横轴范围，各曲线保留自身观测终点。 | 补充 |
| [A38 强争用下动态控制的 WCT 影响](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。 | 相同 30% DMA 假设，比较 DRAM-only、Guarded AIMD 和 Static Peer；静态版本仍尊重显存硬上限。容量守恒与前台时延保护是两个不同问题。 | 补充 |
| [A39 共享路径带宽敏感性](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 三系统紧凑图例；颜色、线型和标记联合编码；仅连接实际执行的设置。 | 实际执行 5/25/50 GB/s，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 | 补充 |
| [A40 DRAM 容量与正常命中](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 三系统紧凑图例；颜色、线型和标记联合编码；仅连接实际执行的设置。 | 实际执行 250 GB / 1 TB，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 | 补充 |
| [A41 活跃 Workflow 并发敏感性](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 三系统紧凑图例；颜色、线型和标记联合编码；仅连接实际执行的设置。 | 实际执行 16/32 个活跃 Workflow，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 | 补充 |
| [A42 CPU 服务报价的敏感性](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 使用明确刻度的局部秒轴辨认小差异；三个系统共用范围，全部设置与数值不变。 | 实际执行 1×/2× 固定 CPU 报价，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 纵轴展示实际秒值的局部范围，以辨认小幅差异。 | 补充 |
| [A43 硬件 DMA 争用系数的敏感性](Old_Figures.md#agent-lease-supplements) | 未标定机制模拟 | 使用明确刻度的局部秒轴辨认小差异；三个系统共用范围，全部设置与数值不变。 | 实际执行 0/5/30% 额外 forward 时长，其余保持默认；每个点是该配置的整批汇总，三系统配对。连线只连接已测设置，不能外推为连续函数。CPU/DMA 系数是模型参数。 纵轴展示实际秒值的局部范围，以辨认小幅差异。 | 补充 |
| [2 重算代价与 Workflow 损失并不等价](Paper_Draft.md#paper-motivation-recovery-exposure) | 轨迹锚定反事实 | 从旧五分支 CSV 重画独立吸收/暴露条形图；不与 Qwen3-8B 实验混用。 | 同一五分支轨迹中，分别在 349.5 s 假设单分支故障。柱长为模型化重算时间，分为被并行执行吸收和推迟汇合两部分。旧 Qwen3-235B/A100 配置的反事实推演，不是实测故障或后文 8B 实验。 | 正文 |
| [9 控制计算与传输成本](Paper_Draft.md#paper-evaluation-resource-cost) | 分项实测 CPU 与模拟 | 五个成本逐项相对 Mooncake 归一化，实测与模拟逐行明示；独立对数轴与三系统形状；正文保留绝对量。 | 每行分别相对 Mooncake 归一化，横轴为对数倍率。Python CPU 为参考实现实测，其余为模拟服务与传输指标；各行不能相加。GET 的对象总体随命中策略变化，较少读取不等于较高效率。 | 正文 |
| [10 复制对真实 GPU forward 的干扰](Paper_Draft.md#paper-evaluation-native-interference) | 真实 GPU 组件微基准 | 将 batch 1/4 的 120 个既有观测放在一个共同坐标；条件不连线，保留五块配对倍率的中位数及全范围。 | Qwen3-8B BF16/SDPA，双 L40S 的一次独占分配，额外分配 8 GiB。两组 batch 共用纵轴，Peer 方向相对于前台 GPU。点为五个配对测量块的倍率中位数，误差线为最小至最大值；无跨条件连线。 | 正文 |
| [12 不同资源条件下的相对 WCT](Paper_Draft.md#paper-evaluation-configuration-effects) | 未标定机制模拟 | 八个单因素配置逐行对照同配置 Mooncake；统一百分比轴，配置间不连线，完整均值留在 CSV。 | 每行只改变默认配置的一个因素，分别相对该行 Mooncake 归一化；负值更快，正值更慢。CPU/DMA 系数为模型敏感性参数。八行代表八种配置，未用异质条件构造误差线。 | 正文 |

## 验证与剩余范围

52 项针对性回归覆盖 Agent 分支/轮号、同轮信用、Q 尾块刷新、拒绝回滚、复制提交、AIMD 与连续推理调度。实验源码先冻结，再执行矩阵；运行正确性不等于实际硬件性能得到验证。

原生组件新增 360 个 forward 样本与按对象大小各 20 次释放测量。尚缺原生三系统端到端服务、在线预测器校准、多工作负载及多故障泛化。相关限制已进入主文图注，不能将形式正确或审查 PASS 写成系统收益已获证明。

设计语言沿用 [Best Paper 实际图页审查](../docs/paper/BEST_PAPER_FIGURE_REVIEW.md) 的具体对象、状态对比和相邻证据组织；未复制参考论文的图像或数据。
