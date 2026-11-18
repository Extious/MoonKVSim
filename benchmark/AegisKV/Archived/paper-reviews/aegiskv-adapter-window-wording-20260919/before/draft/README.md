# 论文草稿（中文）

拆分自 2026-09-16 版 `Paper_Draft.md`（原文快照：[`Archived/drafts/Paper_Draft_20260916_monolith.md`](../../Archived/drafts/Paper_Draft_20260916_monolith.md)）。
初次拆分时正文逐字保留，只调整图链接与数据、脚本路径；后续章节修订记录如下。
`system_design.md` 于 2026-09-17 改写为终稿形态：去除草稿期的过程性说明与证据等级标注，保留全部设计内容与数字，
可直接翻译为论文 §3；层流水线图（现图 7）同日重新渲染，仅更改图内标注文字，数值不变。
同日晚间按新的设计主线重组 §3：Slack 只决定请求的层级与顺序；块大小与每层热集大小 $K_l$ 离线校准；前层数 $L$ 与 Peer 预算 $B$
在放置窗口内固定（闭式 $F^\star=\beta(W_0-W_{floor})$）；热块身份在线滚动。算法 1 改为"Slack 排序、足迹整体放入"，删去有用配额 $B_{use}$。
架构图重画为只含模块名与编号箭头的版本；图 9 改为显式流水线扫描（暴露等待 vs Peer 驻留字节，标出地板与 $F/L$）。
`introduction.md`、`conclusion.md`、`evaluation.md`（消融项）与 `appendix_draft_status.md` 中提到有用配额的句子同步改写，其余逐字未动。
`background_and_motivation.md` 于 2026-09-18 按“Motivation 说明要解决什么，Observation 支撑如何设计”的分工调整：Motivation 包含图 1 的三个子图：(a) 分支差 ECDF，(b) 同一五分支 Workflow 结构，(c) 恢复代价与 WCT 损失；长上下文重算代价（原图 4）单独作为图 2。§2.2–2.3 使用连续论述，不再列“观察 1–4”；§2.4 定义问题、目标与约束，具体的方法依据由 `system_design.md` 承担。原图 3 的模型发布调研及其论述撤出本节，图文件保留为资料。按用户最新要求，图 1 为一个跨双栏 Figure 的三个并排子图，共用总图注；图 2 为独立单栏图；原模型发布调研图称为“原调研图 3”。新增英文 LaTeX 初稿及 EuroSys 2027 SIGPLAN 预览，见 [`../sections/README.md`](../sections/README.md)。本轮不修改另一任务正在调整的 §3 与总览图；设计章图号和对原图 4 的引用在全文整合时同步。集中度图仍在 §3.3（图 6）。

2026-09-18 后续整合：`system_design.md` 现按“观察/启示 → 三层架构 → 分层保护 → 层块放置 → 预算准入 → 并行接管 → 运行时”展开。
图号统一为 3–7；① Tracker、② Planner、③ Recovery Manager、④ Adapter 与小节对应，Connector 不单设小节。
当前图源是 `figures/system-overview-v10.drawio`；`main.tex` 已连接英文 Background/Motivation 与 System Design。
较早日志中的“本轮不修改设计章”“终稿形态”描述历史轮次；当前仍保留端到端验证边界，不能视为投稿完备。

当前职责（2026-09-18 最新修订）：§3.4 Recovery Manager 在到达时绑定 retry/Peer 目标；§3.5 KV Master 在 Adapter 给定的 checkpoint 间隔下决定 R/D/P 层级、热块候选和准入顺序；§3.6 Adapter 每 5 秒按故障风险和前台内存需求更新统一 $Z$、统一 $L$ 及各目标 Peer 预算。固定比例 $h$ 决定每层候选数量，实际驻留受增量准入、提交状态和引用保护约束；预算收缩只回收安全的零引用副本。算法 3 展示新控制流程，尚无对应实现与端到端验证。旧日志中的 Planner、逐请求层数、闭式足迹和整请求抢占属于历史版本。当前图源为 system-overview-v11.drawio，图号 3–5，算法 1–3，组件编号为 ① Tracker、② Recovery Manager、③ KV Master、④ Adapter。

| 顺序 | 文件 | 内容 |
|---|---|---|
| 1 | [`abstract.md`](abstract.md) | 标题、证据分级与图源说明（注释）、Abstract |
| 2 | [`introduction.md`](introduction.md) | §1 Introduction |
| 3 | [`background_and_motivation.md`](background_and_motivation.md) | §2 Background and Motivation（图 1(a)–(c) 与独立图 2） |
| 4 | [`system_design.md`](system_design.md) | §3 AegisKV Design（图 3–5、算法 1–3）；Tracker → Recovery Manager → KV Master → Adapter |
| 5 | [`implementation.md`](implementation.md) | §4 Implementation |
| 6 | [`evaluation.md`](evaluation.md) | §5 Evaluation（配对协议与实验计划；端到端结果待并行恢复实现后补充） |
| 7 | [`related_work.md`](related_work.md) | §6 Related Work |
| 8 | [`conclusion.md`](conclusion.md) | §7 Conclusion |
| 9 | [`appendix_draft_status.md`](appendix_draft_status.md) | 附录 A（草稿状态）、附录 B（自审与修正）；不进入投稿 |

合并为单个文件（按上表顺序拼接即可复原全文）：

```bash
cd benchmark/AegisKV/paper/draft
cat abstract.md introduction.md background_and_motivation.md system_design.md implementation.md \
    evaluation.md related_work.md conclusion.md appendix_draft_status.md > /tmp/AegisKV_draft.md
```

图文件在 [`../figures/`](../figures/)，原图的数据来源、哈希与模型参数记录在 `../figures/MANIFEST.json`，三图并排版本另见 `../figures/motivation-row/MANIFEST.json`；
正文中每个数字对应的脚本输出见 `abstract.md` 顶部注释。
