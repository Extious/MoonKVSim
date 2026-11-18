# 实例一、二的流程图

两图嵌入 [实例一二批注版 Word](../../AegisKV专利交底书-实例一二批注版.docx)。
实例一负责收益计算，实例二使用该收益执行租值管理；结算、续租与 H 建键只出现在附图 3。

| 图 | 输入与输出 | 可编辑源 | 原生导出 |
|---|---|---|---|
| 附图 2 | 本请求 Slack 和前缀恢复代价 → 当前 Agent 的恢复收益 G、收益密度 P | [Draw.io](figure-2-agent-credit.drawio) | [PNG](figure-2-agent-credit.drawio.png) · [PDF](figure-2-agent-credit.drawio.pdf) |
| 附图 3 | G 和本池分账 → 旧租金结算、单 Agent 续租、H/L 准入与尾块淘汰、执行发布 | [Draw.io](figure-3-slacklandlord.drawio) | [PNG](figure-3-slacklandlord.drawio.png) · [PDF](figure-3-slacklandlord.drawio.pdf) |

## 本轮调整（2026-09-10）

参照用户当前的 [算法三源图](../../../drawio/algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio)
重新导出并查看后，采用其黑白流程框、少量条件分支和公式置于节点内的布局。
未沿用该目录中较早的彩色 PNG，也未改变算法三。

附图 2 保留两个输入、一个收益计算框和一个输出框，移除共享分账与租值键。
附图 3 在主线中结算并续租，仅从附图 2 读取 G，不重复展开 Slack 与恢复时间的公式。
请求去重、就绪检查和冲突重读作为入口约定，完整条件保存在实例二 S1、S4 和伪代码中。
两图都不引入未知后续 KV 长度、命中/LRU 融合或联合 WCT 分配。

- 每个 Agent 分别计算 G；总 Credit 仅汇总租后份额。本请求只替换自己的份额。
- 空闲容量允许零 Credit；空间不足时仅在最小尾块键满足 `H_y < H_x` 时试删，同键拒绝。
- 候选 H 固定，持续在 Q 中的 H 不随试算租金重建；保护块冻结，新尾块按当前租金建键。
- 拒绝提案丢弃临时账本。实际释放完成才分配复制；执行失败不回滚已释放备份与 L。
- 复制成功后用当时的 L 和租后余额建键并发布；Peer-HBM 和 DRAM 分别执行。

Word 插入宽度为 **168 mm**，附图 2 约 **101 mm** 高，附图 3 约 **182 mm** 高。
原正文保留为批注修改，图像与图注直接替换；批注作者为 `zhaozhan`，批注直接说明如何修改。
修订前文件保存在 [本轮快照](../../reviews/instances-1-2-20260909/before-separated-figures-20260910/)。

## 生成与核对

```bash
python3 benchmark/AegisKV/docs/patent/figures/instances-1-2/build_figures.py
```

使用 Draw.io 官方 CLI 包装器导出，两图的 PNG 均使用 `-x -f png -e -s 2 -b 0`，
PDF 使用 `-x -f pdf -e -b 0`。手工编辑源图后须将修改同步到生成器。

[图稿核对](FIGURE_REVIEW.json)、[DOCX 核对](../../reviews/instances-1-2-20260909/AUDIT.json)
记录图源哈希、原生导出及插入尺寸检查。
[按 Word 插入宽度制作的预览](../../reviews/instances-1-2-20260909/figures-at-word-size.pdf)
用于核对图像和图注；它不是 Word/WPS 全文分页渲染。
图稿属于设计示意，不作为实现、性能或最优性证明。

![附图2](figure-2-agent-credit.drawio.png)

![附图3](figure-3-slacklandlord.drawio.png)
