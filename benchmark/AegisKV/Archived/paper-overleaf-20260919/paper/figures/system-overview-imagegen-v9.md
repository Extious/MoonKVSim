# AegisKV System Overview v9：策略、执行与论文排版

## 本轮修正

按用户四点反馈修改 v8，使用内置 imagegen 生成并做两次局部修正，共三次模型调用。

1. 全图恰好四个黑底白字外加角标：① Workflow Tracker，② KV Placement Planner，③ DP0 Connector，④ DP0 Adapter。DP1 保留相同组件，不重复编号。编号标识正文介绍的模块类型，不是系统组件或执行顺序。
2. Planner 决定 KV 放置与传输策略，图中副标题为 `Placement & transfer policy`，灰色虚线 `Transfer plans` 从 Planner 右边缘引出。Connector 只执行计划，副标题为 `Executes transfer plans`。完成上报、实际传输、资源/就绪事件属于执行接口，不把 Connector 描述为第二个策略制定者。
3. 删除 `Store Master extension`，删除 Connector 内的 Store Client / Transfer Engine 小框，DRAM KV Store 不附实现框架名称。Overview 展示 AegisKV 的逻辑系统设计；底层实现与复用关系在 Implementation 中交代。v7 中把 Master 部署关系放在 Overview 中的建议不再沿用。
4. 减小层标题与边框视觉重量，统一左右 DP 的模块基线、内边距和内存条尺寸；对齐 Controller 两列的上下模块。删除重型图例外框，扩大中央 Peer 路径标签空间，简化过小的实现标签。

保留三层架构、等价 DP、较小 Peer 区、Peer 本地读取和两条独立复制路径。Peer 条带是容量示意，不是数据比例。请求与状态/计划箭头连接整个引擎层，适用于两个 DP；没有把物理数据流画经 Controller。

## 实际查看的论文参考

| 参考 | 实际查看位置 | 本轮借鉴 |
|---|---|---|
| [RACER: When KV Meets Embeddings](https://arxiv.org/pdf/2605.04450#page=5) | PDF 第 5 页 Figure 7；同时查看相邻 Figure 8 | 紧凑的分组、决策与执行边界、对齐的模块与内存区域、详细机制在后续图中展开 |
| [LiveUpdate: Near-Zero-Overhead Freshness](https://arxiv.org/pdf/2512.12295#page=6) | PDF 第 6 页 Figure 7 | 层次与路径分开编码，节制使用底色，重复实例采用一致组织 |

只借鉴绘图组织，不迁入参考论文的算法、性能结论或节点拓扑。本地读取原 PDF 并渲染后查看；参考文件与裁出的图位于 `tmp/pdfs/aegiskv-overview-references/`。来源 PDF 的哈希和页码保存在 `output/pdf/aegiskv-imagegen-20260918/artifact-metadata-v9.json`。

## 正文映射

- ① / §3.2：DAG 进度与 Slack；P90、CPM、动态 DAG 与滞回在正文展开。
- ② / §3.2–3.4：分层、请求内层/块足迹与 Slack 整体准入；下发放置和传输计划。
- ③ / §3.5：按计划复制/装载和完成上报；不设置第二套放置、准入或传输策略决策。
- ④ / §3.3、§3.5：引擎观测、KV 管理、前台保护与恢复执行；恢复时的实际需求和就绪条件通过执行接口处理。

本轮修改图稿与说明，不替换当前 `system_design.md` 或 canonical 图，也不把图稿改动视为新版端到端实现结果。

## 图注候选

**AegisKV system overview.** Workflow Tracker (1) derives workflow Slack, and KV Placement Planner (2) decides KV placement and transfer policy. Transfer plans are executed by the Connector (3), while the Adapter (4) integrates KV management and recovery with each inference engine. Recovery Manager instructs the Router to retry affected requests on their preassigned DPs. Both DPs have equivalent modules and a smaller reclaimable Peer region beside Local KV; corresponding modules are annotated only once. Peer and DRAM data paths are independent and bypass the control plane. Black circles are textual cross-references, not execution steps. Memory proportions are schematic; request and control interfaces apply to all DPs.

## 迭代与核对

- 初稿已满足唯一编号、策略/执行标签和去除实现父级名称，但 `Transfer plans` 箭头落在 Recovery Manager 下方，容易产生错误归属。
- 第二轮将该箭头起点明确接至 Planner 右边界，经独立空白通道下达引擎层，并保留单独向上的状态反馈。
- 第三轮将 KV Directory 的左右边界与 Planner 对齐。
- 最终查看了原始 PNG 与 178 mm 宽 PDF 的 144 DPI 彩色、灰度渲染。四个角标清晰且无重复，文字无遮挡；Planner 的计划路径和独立状态反馈可追踪；两侧 Connector、Adapter、HBM 和 DRAM 路径保留；无标题穿线或裁切。灰度版通过线型、位置和直接标签区分路径。

## 交付

- [PNG](system-overview-imagegen-v9.png)
- [初始提示词](system-overview-imagegen-v9-reference-redesign.prompt.md)
- [两次修正提示词](system-overview-imagegen-v9-refinement.prompt.md)
- PDF：项目根目录 `output/pdf/aegiskv-imagegen-20260918/system-overview-imagegen-v9.pdf`
- PNG SHA256：`2754638ee10f10be733a30a791856af6b25d6bd95a293788197896a93df70565`
- 1484×1060 像素，工作宽度 178 mm，约 212 DPI。PDF 是位图封装，非可编辑矢量；这是未替换 canonical 资产的新候选。
