# AegisKV Overview v8：后加的论文角标

本轮只处理用户对黑底编号的纠正：编号应像叠加在完整架构图上的阅读标注，不占据模块内部布局。

内置 imagegen 对 v7 局部修改：删除框内六个编号，将 1（Workflow Tracker）、2（Planner）、3（两侧 Connector）、4（两侧 Adapter）移到各自右上角边框处，缩小圆圈并增加白色隔离边。模块名称恢复自然居中。去掉角标后，架构内容仍完整成立；编号不表示系统组件或执行步骤。

- PNG：[system-overview-imagegen-v8.png](system-overview-imagegen-v8.png)
- 提示词：[system-overview-imagegen-v8-callouts.prompt.md](system-overview-imagegen-v8-callouts.prompt.md)
- 架构与正文对应沿用 [v7 说明](system-overview-imagegen-v7.md)。
- PDF 与实际尺寸渲染位于项目根目录下 `output/pdf/aegiskv-imagegen-20260918/`，文件名前缀 `system-overview-imagegen-v8`。
- 工作宽度 178 mm；PDF 封装生成位图，不是可编辑矢量。旧版及 canonical 图保留。

最终导出核对结果见同目录 `artifact-metadata-v8.json`；本轮不重新评估架构或扩大正文修改范围。

已查看实际 178 mm 彩色/灰度 PDF 渲染：六处编号均为外加角标，不遮文字与箭头端点；模块名称居中，架构关系与 v7 一致。底层库小标签偏小的问题沿用 v7，本次未扩大改动。
