# Teacher Design: four components and peer-owned memory

本次按用户 2026-09-23 的三点指示重构老师稿：开头先使用通用 HBM，到 Router 介绍具体 Peer HBM/Peer DRAM 与放置选择；取消独立 DRAM Pool；详细设计仅分 Tracker、Router、KV Master、Adapter 四节。

## 最终结构与职责

| 小节 | 内容和责任 |
|---|---|
| 3.1 Tracker | 每个节点是一次 invoke；同一 Agent 的历史消费者跨调用保留；剩余时长和 guarded Slack。 |
| 3.2 Router | 选择执行 worker、故障域外兼容 peer；定义 Peer HBM 与 Peer DRAM；根据 Master's 已选集合和优先级分配前 L 层 HBM、溢出及后层 Peer DRAM；处理接管与重新绑定。 |
| 3.3 KV Master | Agent selection (O1)、KV region selection (O2)、Online Management；完整候选/受害者价值检查，调用 Router.Place，管理 manifest、复制提交和保留期限。 |
| 3.4 Adapter | 根据前台压力调整各 TP rank 的 HBM 配额；缩容驱动向同一 peer 的 DRAM 迁移，容量不足时明确重新选择。 |

四小节前只有简短引言和架构图。Connector 执行复制并向 Master 反馈，不增加第五小节。O1/O2/O3 对应关系保留在各组件内部。

## 拓扑和语义

Peer DRAM 指选定 peer worker 的主机内存分配，未引入独立内存服务。图例是两台主机，每台一个 TP=2 worker：各自 host DRAM 在本主机边界内，并接到本机两个 rank 的 Connector；保留对应 TP rank 的跨 worker 路径。若实际同机多个 worker 共用 DRAM，则共用一份物理容量账本，逻辑配额不能重复计算容量。Host 故障保护必须选择不同故障域的 peer。

Router.Place 消费 Master 已选区域，前 L 层所选区域优先 Peer HBM；溢出及已选后层进入同一 peer 的 DRAM。两层仍是部分备份，稳态每个所选对象一份独立副本，迁移过程同时计量新旧分配。原 peer 开始执行同一历史后，其本地状态可以复用，但独立保护需要新 peer 上完成的复制。缺失 KV 的依赖闭包重建和全前缀 fallback 保留。

## 图源、数据和检查

- `teacher-system-overview`：保留 Application/Controller/Engine 和 DP/TP 几何，删除原独立 DRAM、公共访问总线，新增每 host 的 DRAM 及本地连接；Router/Master 是双向方案交换。
- `teacher-selective-recovery`：沿用构造的 5/12 区域示例，明确 H/D 都位于同一个 peer。`data/selective-state.json` 记录 DP1/Host1；`data/peer-topology.json` 记录主机和连接责任。
- `teacher-invocation-reuse`：保留 A(1) → A(2) → A(3) 及兼容前缀示意，逻辑历史条不代表全量备份。

三图均为设计示意，无实验样本数或置信区间，不构成实现或性能证据。`sources/` 保存可编辑 Draw.io；`figures/` 保存原生带 XML PNG/PDF；只有论文 PDF 图与预览进入 `paper_teacher/`。

`review/check_revision.py` 的 29 项有限检查全部通过，包括四小节次序、引言用语、Router 中双层定义、算法调用、DRAM 主机归属/边界/本地双 rank 连接、跨 worker rank 对齐、无悬空边及原有部分备份/复用检查。老师 Background/Motivation 字节不变，canonical `paper/` 的 44 个文件和文件集合不变。

最终论文为 8 页，未发现 undefined references/citations、LaTeX 错误或 Overfull box。保留已有参考文献 underfull 与 ACM 算法周围间距提示。实际查看了更新图的原生导出与最终第 3–8 页；第 4、6 页另检查灰度。最终图宽 84.6825 mm，最小图中文字约 10.16–10.17 pt，无嵌入位图。合并了重复介绍，避免只含末条参考文献的第 9 页，未缩小字号。

复核命令（仓库根目录）：

```bash
bash benchmark/AegisKV/experiments/scripts/paper/render_teacher_design.sh
sh benchmark/AegisKV/experiments/scripts/paper/build_teacher_paper.sh
python3 benchmark/AegisKV/exports/teacher-four-components-peer-memory-20260923/review/check_revision.py
```

`before/` 仅存修改前快照。当前 PDF hash、检查结果和字体数据见 `review/checks.json`。本次未运行新性能实验。
