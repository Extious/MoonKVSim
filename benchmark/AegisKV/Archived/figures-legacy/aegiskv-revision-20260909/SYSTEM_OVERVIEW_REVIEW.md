# System Overview 修订

本图是设计示意，不是性能结果。按通栏 7 inch 插入，最终 PDF 为 7 × 4.585 inch，最小字体 10.06 pt。上一版为 7 × 6.014 inch；本次以三列资源拓扑减少约 24% 的垂直占用，没有缩小正文字体或省略独立副本路径。

## 表达内容

左侧 Source worker 持有 C0、C1 和当前活动块 C2。Agent A/B 共享同一个物理 C0；Agent priority 使用 slack 与恢复代价，分别驱动每个池的准入。中间 Peer HBM 与 DRAM 的两条复制路径都从 Source 发出，不把 DRAM 画成 Peer 的后续写回层。

Peer worker 中，P0/P1 是其他正常推理的前台 KV，Reserve 用来表达前台预留；C0/C1 是可撤销备份。独立的 Peer HBM controller 根据 headroom 与 forward latency 观察控制借用，不连接 Agent credit 或某个尚未冻结的算法 2 公式。内存区域宽度是定性分区，不表示具体容量比例。

图中两个 tier 的 C0/C1 均表示复制 ACK 已完成的可读副本，展示的是允许的状态，并不保证每次实验两层都拥有相同覆盖。源 Worker 发生故障后，恢复 Worker 从任一存活、兼容且连续的已提交前缀装入新的 primary C0/C1，再重算 C2；两条恢复箭头是备选来源，不能理解成必须读取两份。灰色 DAG 边表达工作流依赖，彩色箭头表达 KV 传输，虚线表达控制。

## 实际查看的参考

- [Mooncake，FAST 2025 Best Paper](https://www.usenix.org/conference/fast25/presentation/qin)：实际查看 [Fig. 2，PDF 第 3 页](../../../benchmark/AegisKV/docs/related_works/figure-references-20260908/mooncake-fast25.pdf)。借鉴资源位置与职责对应、同一系统内不同 KV 区域的分组；未借用其 P/D 调度机制或性能结果。
- [Ensō，OSDI 2023 Best Paper](https://www.usenix.org/conference/osdi23/presentation/sadok)：实际查看 [Figs. 1、3，PDF 第 4–5 页](../../../benchmark/AegisKV/docs/related_works/figure-references-20260908/enso-osdi23.pdf)。借鉴具体对象身份贯穿操作、直接在资源内画数据布局的做法；未借用其 NIC 协议。

两篇论文的 Best Paper 身份于本次工作中重新从 USENIX 官方页面核对。这些只是参考图的具体做法，不是获奖原因或会刊统一要求。

## 检查与修正

第一轮原生导出发现 Grant/revoke 与池级准入说明贴叠，以及窄列 Recovery worker 标题换行溢出。第二轮移动控制标签，并将窄列标题设为与正文相同的 24 px 源字号。修正后查看了实际原生 PNG、7 inch PDF 的 144 dpi 渲染以及灰度预览，检查连线起止、文本遮挡、状态和同名 KV 身份。

XML 唯一 ID、边几何、四条数据边连接对象、PDF 单页和嵌入式 Draw.io、页面文字边界与最小字号检查通过。源图没有 joint WCT benefit 或尚未冻结的算法 2 细节。全篇嵌入排版由主论文生成阶段另行检查。

## 文件

- [PDF](system-overview.pdf)、[PNG](system-overview.png)、[SVG](system-overview.svg)、[可编辑 Draw.io](system-overview.drawio)
- [导出和实际核对记录](overview-manifest.json)
- [生成脚本](../../../benchmark/AegisKV/experiments/scripts/paper/build_revised_overview.py)

生成命令：`.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_revised_overview.py`。重新生成后 manifest 会将视觉核对重置为 PENDING，需要查看新文件才能再次记录通过。
