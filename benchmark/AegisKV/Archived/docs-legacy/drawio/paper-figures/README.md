# 正文机制图与三联 Motivation

这是 2026-09-06 全文图像修订的 Draw.io 入口；原生 Mooncake / 增加 AegisKV 的
详细中文对照仍在[上一级](../README.md)。下列英文图直接用于正文。

| 图 | 可编辑来源 | 查看 |
|---|---|---|
| 三联 Motivation | [时间尺度 workflow](motivation-workflow.drawio)；[两个定量面板](motivation-panels/) | [三联合成 PDF](motivation-real-cc.pdf) / [PNG](motivation-real-cc.png) |
| System Overview | [Draw.io](system-overview.drawio) | [PDF](system-overview.pdf) / [PNG](system-overview.png) |
| Commit / Recovery | [Draw.io](commit-recovery.drawio) | [PDF](commit-recovery.pdf) / [PNG](commit-recovery.png) |

所有 .drawio 均为原生节点、连线、文本；`.native.pdf/.native.png` 是官方 Desktop
带 XML 导出，普通 PDF 为按论文 7 inch 宽度归一化的矢量版本。
Motivation 的统计面板由 Python 生成，不把观测 ECDF 手工描成 Draw.io 曲线。

本目录为论文图源的同步副本，修改后应从[正文生成脚本](../../../experiments/scripts/paper)
重新导出并同步。证据、CSV、原始 trace 重建和边界见
[逐图修订说明](../../paper/FIGURE_REVISION.md)。

System Overview 已更新为 revision-3 设计及参考执行器语义；上一级两张中文图仍对应实际 Mooncake 旧实现。新图不是 native 集成完成的证据。
