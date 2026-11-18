# SlackLandlord：容量租金版流程图

更新日期：2026-09-08。对应 [最新算法 2 设计](../../algorithm-2/README.md)、[证明](../../algorithm-2/PROOFS.md) 和独立 CPU 参考实现。

主文件：[algorithm-2-patent-revised.drawio](algorithm-2-patent-revised.drawio)

完整阅读版：[四页 PDF](algorithm-2-patent-revised.drawio.pdf)

沿用既有文件名和用户绘制的多 Agent / 共享 KV 布局思路，更新为四页。主决策与收益流程沿一列展开，右侧以 KV 块、恢复时间条和容量变化辅助说明。节点、公式和连线均可在 Draw.io 中编辑。

## 四页分别介绍什么

| 页 | 内容 | PDF | PNG |
|---|---|---|---|
| 1 · Agent、共享 KV 与容量 | 本轮 Slack、逻辑引用、物理去重、提交状态和算法 3 容量接口 | [阅读](algorithm-2-patent-revised-agents.drawio.pdf) | [预览](algorithm-2-patent-revised-agents.drawio.png) |
| 2 · KV 备份准入与回收 | 合法前缀组合、精确/有限预算求解、收益比较、实际释放、复制和提交 | [阅读](algorithm-2-patent-revised-flow.drawio.pdf) | [预览](algorithm-2-patent-revised-flow.drawio.png) |
| 3 · 恢复收益与 KV 示例 | 恢复时间、Slack、前缀扩展/截短、多 Agent 的 DAG WCT、操作收益 | [阅读](algorithm-2-patent-revised-value.drawio.pdf) | [预览](algorithm-2-patent-revised-value.drawio.png) |
| 4 · 容量租金与 Lazy Refresh | Credit、租金松弛上界、跨轮有效区间、延迟精算和组件复用 | [阅读](algorithm-2-patent-revised-lazy.drawio.pdf) | [预览](algorithm-2-patent-revised-lazy.drawio.png) |

## 与旧图的关键区别

- 管理单位仍是物理 chunk；收益和 Credit 针对保持前缀合法的备份状态变化计算。
- 通过工作流 DAG 计算联合 WCT；移除“取多个 Agent 的最大累计收益，再除以当前块字节”的规则。
- Credit 为操作的 WCT 收益变化减去容量价格乘容量变化。价格来自松弛问题；最终分配仍满足整数性与前缀依赖。
- Lazy 使用经过证明的跨轮区间与搜索上界，不假设旧租值键只能上升。
- COPYING 和 RETIRING 均计入实际物理占用；所有分片成功后才发布可恢复前缀。
- 有限预算模式报告最优性差距，不把找到的候选自动标成最优。

**本图采用容量租金语义，不执行旧版累计 L、租值键 H 或按 Agent 分账扣减的余额。** 最新设计中对这一变化的说明仍然适用。收益来自给定恢复时间模型；备份复制带宽干扰暂未加入目标。

## 贯穿数值示例

第 3 页保留用户选定的重算代价 3、4、5 ms；每块加载 2 ms，Slack 为 4 ms：

| 保留前缀长度 | 恢复时间 T | 超过 Slack 的损失 J | 累计收益 U |
|---:|---:|---:|---:|
| 0 | 12 ms | 8 ms | 0 ms |
| 1 | 11 ms | 7 ms | 1 ms |
| 2 | 9 ms | 5 ms | 3 ms |
| 3 | 6 ms | 2 ms | 6 ms |

第 2 页增加 B1，收益为 4 ms。每块 2 MiB、容量 6 MiB 时，A1/A2/A3 的收益为 6 ms，A1/A2/B1 为 7 ms。因此替换 A3，同时保留 A1/A2。

第 4 页的分数松弛忽略前缀，可得到 9 ms 上界；它不能作为可直接提交的方案。[2,6] ms 的 Lazy 区间，以及 24 组件局部更新的 48→2 次精算，分别与参考模型和已有验证报告核对。全部数值均为说明或合成验证数据。

## 符号

每页页脚解释该页符号：

| 符号 | 含义 |
|---|---|
| C、S、S′、b | 可用容量、当前/候选物理备份集合、实际字节数 |
| T、s、J、U | 恢复时间、本轮 Slack、超过 Slack 的损失、单 Agent 前缀收益 |
| D、F | 工作流完成时间、模型内总 WCT 恢复收益 |
| λ、Credit | 容量价格、合法备份操作的净值 |
| UB、gap | 未排除方案的收益上界、当前结果到上界的差距 |
| I、X、R、u、E | 第 4 页的已选块、待定块、剩余容量、恢复收益上界、跨轮输入扰动界 |

## 生成与校验

~~~bash
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/build_diagram.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_design_examples.py
~~~

生成器调用原生 Draw.io Desktop 导出 PDF/PNG，并检测源图是否包含尚未纳入的手工改动。PDF 嵌入完整源图；每张 PNG 嵌入对应页的可编辑 XML。

[MANIFEST.json](MANIFEST.json) 记录源图、设计和导出指纹。[DESIGN_CHECKS.json](DESIGN_CHECKS.json) 记录数值对照。[COMPATIBILITY.json](COMPATIBILITY.json) 记录真实 mxGraph 解码、编辑、保存、重开检查，以及旧 setId 错误的回归。

所有节点 ID 使用前缀，避免 pop 等名称与旧 mxGraph 解码器的原型属性冲突。

## 历史对照

- [上一版累计扣租源图](references/previous-cumulative-rent-136d94493763.drawio)及[旧说明](references/previous-cumulative-rent-design.md)。
- [用户编辑过的早期源图](references/user-edited-19ff14bc521a.drawio)：共享块与 Agent 布局来源。
- [原专利摘录](SOURCE_EXCERPT.md)：原文对照，其中旧公式不代表本版。

本次生成器只更新图件及配套说明；原专利、算法 3 图和生产执行路径不由它修改。
