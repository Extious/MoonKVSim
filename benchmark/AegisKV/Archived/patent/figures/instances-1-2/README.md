# 实例一、二的流程图

两图嵌入 [实例一二批注版 Word](../../AegisKV专利交底书-实例一二批注版.docx)。
实例一负责收益计算，实例二使用该收益执行租值管理；结算、续租与 H 建键只出现在附图 3。

| 图 | 输入与输出 | 可编辑源 | 原生导出 |
|---|---|---|---|
| 附图 2 | 本请求 Slack 和前缀恢复代价 → 当前 Agent 的恢复收益 G、收益密度 P | [Draw.io](figure-2-agent-credit.drawio) | [PNG](figure-2-agent-credit.drawio.png) · [PDF](figure-2-agent-credit.drawio.pdf) |
| 附图 3 | G 和本池分账 → 旧租金结算、单 Agent 续租、H/L 准入与尾块淘汰、传输备份 | [Draw.io](figure-3-slacklandlord.drawio) | [PNG](figure-3-slacklandlord.drawio.png) · [PDF](figure-3-slacklandlord.drawio.pdf) |

## 本轮同步（2026-09-10）

本轮以用户手工编辑的附图 3 为准，保留全部文字、节点位置、连线及五步结构，
直接原生导出后嵌入 Word。源文件 SHA-256 为
`2a74bc7d1f3f34a1aaf0974799f7417ab0a54db9df3f2a4ca7fc6fed35ce458a`。
实例二批注和中文伪代码对应到①读取输入、②已有副本续租或新副本初始化、
③初始化待淘汰集合与剩余空间、④试删尾块、⑤更新累计租金并传输备份。
分母为零、临时队列、保护、释放与传输完成等细节保留在对应批注中。

两图原有的绘图与算法约定如下。

参照用户当前的 [算法三源图](../../../drawio/algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio)
重新导出并查看后，采用其黑白流程框、少量条件分支和公式置于节点内的布局。
未沿用该目录中较早的彩色 PNG，也未改变算法三。

附图 2 保留两个输入、一个收益计算框和一个输出框，移除共享分账与租值键。
附图 3 先判断本池是否已有 x 的已提交备份，再分为已有副本续租与新副本准入。
所有已有副本都按实际 L 结算旧租金，随后只续租当前 Agent；是否在 Q 不影响收租。
没有副本时从空分账初始化候选信用，令 `L′ = L`，以 `H_x = L′ + G_a,x / b_x` 建键。
候选 x 不在 Q，其 H 单独用于准入比较；已有块保留最近授信或续租时建立的 H。
Q 只包含已提交且可安全释放的已有尾块；备份提交后，x 符合条件才加入 Q。
内部块、受保护块和复制中的块均随 L 收租，成为尾块或解除保护时直接以原 H 入 Q。
附图 3 仅从附图 2 读取 G，不重复展开 Slack 与恢复时间的公式。
请求去重、就绪检查和冲突重读作为入口约定，完整条件保存在实例二 S1、S4 和伪代码中。
两图都不引入未知后续 KV 长度、命中/LRU 融合或联合 WCT 分配。

- 每个 Agent 分别计算 G；总 Credit 仅汇总租后份额。本请求只替换自己的份额。
- 空闲容量允许零 Credit；空间不足时仅在 `max(L′, H_y) < H_x` 时试删，候选耗尽或同时耗尽均拒绝。
- 试算租金按 `L′ = max(L′, H_y)` 推进，防止已经耗尽信用的内部块暴露为尾块后导致租金倒退。
- 候选和全部已有块的 H 在试算中保持不变；剩余信用统一按 `b max(H − L′, 0)` 计算。
- 实际状态用 L 结算，试算用 L′ 计算，核验后才提交 `L = L′`；每次租金推进无需遍历所有块。
- 拒绝提案丢弃临时账本。实际释放完成才分配复制；执行失败不回滚已释放备份与 L。
- 复制成功后按当时的 L 结算余额并保留原 H 发布；Peer-HBM 和 DRAM 分别执行。
- 保留用户精简后的五步主流程，不恢复已删除的附加说明、发布节点或失败分支；传输完成后的发布与失败处理保留在专利 S4/S5 与伪代码中。

Word 插入宽度为 **168 mm**，附图 2 约 **101 mm** 高，附图 3 约 **193 mm** 高。
原正文保留为批注修改，图像与图注直接替换；批注作者为 `zhaozhan`，批注直接说明如何修改。
修订前文件保存在 [本轮快照](../../reviews/instances-1-2-20260909/before-user-flow-sync-20260910/)。

## 导出与核对

`.drawio` 是当前可编辑源，`build_figures.py` 只校验并更新 `STRUCTURE.json`，
不重绘或覆盖源图。旧生成器保留在修订前快照中。

```bash
python3 benchmark/AegisKV/docs/patent/figures/instances-1-2/build_figures.py
python3 benchmark/AegisKV/docs/patent/reviews/instances-1-2-20260909/verify_rent_semantics.py
```

使用 Draw.io 官方 CLI 包装器导出，两图的 PNG 均使用 `-x -f png -e -s 2 -b 0`，
附图 3 的 PDF 使用 `-x -f pdf -e --crop -b 0`，按图形边界导出为一页；
附图 2 的既有单页 PDF 保留。源图修改后直接重新导出，并核对实际图形边界，
包括位于页面原点上方的标题。批注同步脚本在写入前核对本轮图源与现有 Word 的哈希。

[图稿核对](FIGURE_REVIEW.json)、[DOCX 核对](../../reviews/instances-1-2-20260909/AUDIT.json)
记录图源哈希、原生导出及插入尺寸检查。
[租金算术核对](../../reviews/instances-1-2-20260909/RENT_CHECKS.json)
覆盖 Q 内外统一扣租、过期内部块暴露、零信用候选、单 Agent 续租与复制期间收租；属于设计核对。
[按 Word 插入宽度制作的预览](../../reviews/instances-1-2-20260909/figures-at-word-size.pdf)
用于核对图像和图注；它不是 Word/WPS 全文分页渲染。
图稿属于设计示意，不作为实现、性能或最优性证明。

![附图2](figure-2-agent-credit.drawio.png)

![附图3](figure-3-slacklandlord.drawio.png)
