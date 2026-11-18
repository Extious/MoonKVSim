# Serving model: teacher-grounded image-generation study

用户要求：根据老师的图注与正文定位，详略得当，先组织语言调用生图模型查看效果。本次交付是布局草图。

依据：老师粘贴文本第 13、15、17、20 行。原始图注的三项职责为 runtime 维护依赖和已接受历史、就绪调用调度到 workers、workers 跨轮次保留对应 KV。图是概念示意，没有实测数据。

## 必须表达

- Workflow runtime 中的两个小型 DAG，明确 fork/join，B1/Tool/B2 显示同一 Agent 的不同调用。
- Runtime 维护的已接受历史，位于 worker KV 状态之外。
- Ready requests 映射到多个 model workers，两个 worker 各自服务来自两个 workflow 的 Agent。
- Worker 内各 Agent 的 KV；只对 B 的跨轮次 reuse/append 展开一个局部例子。
- TP 作为 worker 可由并行组构成的提示，不展开实现结构。

## 合并和省略

四类输入合并为 histories；完整队列与 scheduler 合并为一条 ready-request 分发桥；省略权重、block tables、逐层网格和四份 rank 细节。故障/恢复策略不作为本图主面板。Runtime 与 worker 的分组保留故障背景所需的状态归属。

## 视觉方案

新构图：上方 runtime，下方两个并排 worker，宽高比约 4:3。沿用项目蓝/紫工作流身份及暖色新增 KV，只用规则字体和薄线。已经查看当前可编辑版本的真实预览作为内容/字体参考，不把其密集布局作为生成图约束。

直接使用内置 imagegen；PROMPT.txt 是完整实际提示词。结果作为预览保存在本包，主稿资产保留当前版本。生成后核对边方向、Agent 身份、跨工作流分配、历史与 KV 的归属、文字和实际缩小后的可读性。位图不宣称是可编辑矢量稿。
