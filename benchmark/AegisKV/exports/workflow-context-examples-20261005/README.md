# 两个 workflow 的 context 与轮次实例

研究实例使用 DeepResearchBench DRB-66 的 Obsidian 插件比较，评审实例使用 SWE-bench Verified 的 astropy__astropy-12907。DAG 和角色协议为项目设计；图中 36 次请求的轮次、输入 token 数、材料序列和前置产物来自 capture-163125 的健康 F0 原始记录。

![研究报告实例](research-context-example.drawio.png)

![仓库问题评审实例](review-context-example.drawio.png)

## 如何阅读

- 一个大卡片是一个 Agent，R1/R2 等是其连续的模型请求。字母与原始采集 ID 一致，没有应用 serving_model 图内的显示别名。
- 每个 Agent 的 C0 包含公共 context（原问题 Q、任务范围、各自角色 system prompt）及其已完成前置 Agent 的最终文字产物。根节点没有前置产物。
- 每轮实际 context 为 C0 + H(r-1) + 本轮新增 user 请求；Hk 包含该 Agent 前 k 轮完整请求、所提供材料和模型回答。图中逐轮列出新增材料或任务请求的中文摘要，并显示实测输入 token 数。
- 数据依赖等待发生在 Agent 开始之前。运行期间不会等待其他 Agent 的中间轮次反馈，也不会向其他 Agent 传递本 Agent 的 KV。下一节点读取最终文字产物形成自己的 context。
- DAG 横向位置是依赖层次，不是实测时间轴。依赖满足的 Agent 可并行调度，同一 Agent 的多轮串行；实际 GPU 队列仍会引入等待。工具准备发生在计时之前，计时阶段没有工具调用。

## 交付与核对

保留两份可编辑 `.drawio` 源、内嵌源的 PNG/SVG/PDF、生成脚本和完整 context 索引。没有插入论文、改写 main.tex 或重新编译主稿。

- [研究实例源](sources/research-context-example.drawio)
- [评审实例源](sources/review-context-example.drawio)
- [逐 Agent context 与原始请求链接](CONTEXTS.md)
- [逐请求 context 原文与哈希索引](CONTEXTS.json)
- [来源与语义核对](AUDIT.json)

实际输出只有模型自检，部分请求达到生成 token 上限；图展示真实执行协议，不代表应用答案通过独立质量验证。评审实例没有应用补丁、运行测试或提供官方 solution；研究材料仅为预先选取的三份固定版本 README。

详细实例图按 320 mm 宽度核对彩色、灰度与 PDF 实际渲染，以便阅读全部 context。不能直接缩入约 85 mm 单栏。每张大卡片同高只是排版规则，不表达执行时长。

本次经验库读取报告一条历史指纹错误：`20260923T213943533276Z-d9d508c58b-scientific-figure-aegiskv-technical-page-count-includes-late-floats.md`。因此未向记忆库追加或修改条目。当前图的修正与核对保留在本目录。
