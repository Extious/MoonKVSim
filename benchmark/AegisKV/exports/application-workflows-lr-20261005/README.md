# 两个应用 workflow：从左到右的 Agent 依赖图

两张图对应当前确定的软件市场研究报告和代码仓库变更评审场景，仅显示 Agent 职责与任务完成依赖。节点是完整 Agent 任务；所有直接前驱完成后，后继才就绪。各 Agent 内部连续多轮省略，不表示单次调用。横向排列表示依赖方向，不表示实测时间，也不设置整层屏障。

![软件市场研究报告](software-market-research-workflow.png)

![代码仓库变更评审](repository-change-review-workflow.png)

- [两页 PDF](application-workflows.pdf)
- [软件市场研究报告 PDF](software-market-research-workflow.pdf)
- [代码仓库变更评审 PDF](repository-change-review-workflow.pdf)
- [原生可编辑 Draw.io，含两个页面](sources/application-workflows.drawio)
- [依赖与导出核对记录](FIGURE_REVIEW.json)

每张 PDF 宽 168 mm，最终文字约 10.4 pt。高分辨率 PNG 由最终矢量 PDF 渲染；`native/` 保存嵌入可编辑源的原生 PNG/SVG/PDF，`review/` 保存最终尺寸的彩色与灰度检查图。

依赖独立来源为 [WORKFLOW_DEPENDENCIES.json](../../docs/workload-decision-20261004/WORKFLOW_DEPENDENCIES.json)，逐角色请求与应用依据见[场景设计](../../docs/workload-decision-20261004/README.md)。这是本项目设计的应用任务 DAG，不是已测量的生产 trace。没有增加依赖边、实验数字、工具或 KV 标注，也没有修改当前 LaTeX 或切换编辑器。

复现：运行 `build_workflows.py`，再运行 `render_workflows.py` 和 `verify_workflows.py`。原生导出需要 Draw.io 与可用的本地 Xvfb；导出进程使用本目录的独立字体配置。

本次读取科研绘图的适用纠正。历史库中的 `20260923T213943533276Z-d9d508c58b-scientific-figure-aegiskv-technical-page-count-includes-late-floats.md` 内容未通过指纹校验，不能称全部历史已验证，也不向该异常库追加。本次跨线区分的修正与复核记录保存在本项目；未修改旧纠正或绕过全局库保护。
