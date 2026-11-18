# 实例一、二的新流程图

这两张图已嵌入 [实例一二批注版 Word](../../AegisKV专利交底书-实例一二批注版.docx)，
对应附图 2、附图 3。图内采用本次专利确定的 Agent 分账、H/L 租值键和两个 Pool 独立决策方案。
它们是算法设计示意，不是实现或性能验证结果。

| 图 | 说明 | 可编辑源 | 原生导出 |
|---|---|---|---|
| 附图 2 | 当前 Agent 的恢复收益、旧租金结算、单 Agent 续租和共享块 H | [Draw.io](figure-2-agent-credit.drawio) | [PNG](figure-2-agent-credit.drawio.png) · [PDF](figure-2-agent-credit.drawio.pdf) |
| 附图 3 | 请求检查、续租、新副本试算、尾块回收、实际释放、复制及发布 | [Draw.io](figure-3-slacklandlord.drawio) | [PNG](figure-3-slacklandlord.drawio.png) · [PDF](figure-3-slacklandlord.drawio.pdf) |

## 内容与版式依据

- 内容来自 [本次实例一、二批注](../../reviews/instances-1-2-20260909/comments.json) 和
  [已确认的 SlackLandlord 流程](../../../drawio/slacklandlord-patent-revised/README.md)。
- 参考实际查看过的旧附图 2、3，以及用户指定的
  [算法三 Draw.io](../../../drawio/algorithm-3-guarded-aimd/algorithm-3-guarded-aimd.drawio)。
  仅借鉴分支、间距和公式置于节点内的方式；本次专利图采用黑白线条。
- 附图 2 的两行 KV 图示表示使用不同长度的备份前缀，其后已生成的 KV 仍重算。
  不引入未知后续 KV 长度，不汇总多个 Agent 的精确联合 WCT。
- 附图 3 调用附图 2 完成估值与续租，随后区分已有副本和新副本。
  容量竞争使用固定候选 H，`H_y < H_x` 才能试删；空闲容量允许零 Credit。
  退出 Q 先结算冻结，新尾块和完成复制的块使用当时租金与租后余额建键。
- 图中“等待后回①”和“冲突回①”是明确的重入入口；重复/过期和试算拒绝则结束本次处理。
  元数据核验和提交按原设计序列化；释放或复制执行失败直接进入 ABORTED 清理。
- Word 的插入宽度为 **168 mm**，等比缩放；附图 2 约 202 mm 高，附图 3 约 224 mm 高。
  两图各从新页开始，图注随图放置。正文保留为批注建议，仅这两张图和对应图注直接替换。

## 生成与核对

从项目根目录执行：

```bash
python3 benchmark/AegisKV/docs/patent/figures/instances-1-2/build_figures.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f png -e -s 2 -b 0 -o benchmark/AegisKV/docs/patent/figures/instances-1-2/figure-2-agent-credit.drawio.png benchmark/AegisKV/docs/patent/figures/instances-1-2/figure-2-agent-credit.drawio
```

附图 3 的 PNG 使用 `-s 1.5`；PDF 使用 `-f pdf -e -b 0`。编辑 `.drawio` 后应同步生成器再重建。
原生导出、插入尺寸及 Word 中图片哈希的检查记录见
[FIGURE_REVIEW.json](FIGURE_REVIEW.json) 和 [DOCX 核对记录](../../reviews/instances-1-2-20260909/AUDIT.json)。
原生 PNG/PDF 和按 168 mm 放置的预览用于图像检查；不将它们视为 Word/WPS 全文分页渲染。

![附图2](figure-2-agent-credit.drawio.png)

![附图3](figure-3-slacklandlord.drawio.png)
