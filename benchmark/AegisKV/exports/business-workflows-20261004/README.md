# 软件采购选型与新品发布营销：Agent 依赖图

用户最新要求优先选择更熟悉、具体的场景，并将每个 Agent 的逐轮 prompt 写在文字中。本图仅显示角色与材料依赖：采购选型 7 个 Agent，营销发布 8 个 Agent。两个固定 DAG 都有并行、局部汇合、共享前驱和跨层依赖。

这些是明确适配的业务应用设计，不是上游原样拓扑、运行 trace 或实验结果。图的节点位置不表示耗时；示例输入为虚构，正式实验必须使用真实材料。

- [应用与来源依据](../../docs/business-workflows-20261004/README.md)
- [每个 Agent 每轮的 prompt](../../docs/business-workflows-20261004/PROMPTS.md)
- [完整请求 messages](../../docs/business-workflows-20261004/REQUEST_BLUEPRINTS.json)
- [应用约束](../../docs/business-workflows-20261004/application-spec.json)、[请求结构核验](../../docs/business-workflows-20261004/VALIDATION.json)
- [可编辑图源](sources/business-workflows.drawio)：第 1 页中文，第 2 页英文
- [中文 PNG](business-workflows-zh.png)、[中文 PDF](business-workflows-zh.pdf)
- [英文 PNG](business-workflows-en.png)、[英文 PDF](business-workflows-en.pdf)
- [图复核](FIGURE_REVIEW.json)、[依赖核验](review/dag-checks.json)

采购例：D 只等 A/B；F 只等 C/D，可以在 E 未完成时推进。营销例：M 只等 J/K，N 只等 K/L；M 不等待排期，N 只使用用户预先规定的资产 ID，O 完成成稿与排期的绑定。所有直接前驱在本 Agent 第一轮前完成；各 Agent 内部连续处理自己的材料、生成和检查任务。

PDF 按 168 mm 宽准备；`review/` 有同尺寸彩色、灰度预览。全部箭头为任务完成依赖，跨线弧代表没有连接；每个节点是 Agent 任务，不是单次模型调用。每个 Agent 需要哪些原始文档与前驱产物均在应用规范中定义，图不增加隐藏的逐轮反馈。

```bash
python benchmark/AegisKV/docs/business-workflows-20261004/build_blueprints.py
python benchmark/AegisKV/exports/business-workflows-20261004/build_business_workflows.py --output benchmark/AegisKV/exports/business-workflows-20261004/sources/business-workflows.drawio
python benchmark/AegisKV/exports/business-workflows-20261004/verify_dag.py
python benchmark/AegisKV/docs/business-workflows-20261004/validate_blueprints.py
python benchmark/AegisKV/exports/business-workflows-20261004/render_business_workflows.py --language zh
python benchmark/AegisKV/exports/business-workflows-20261004/render_business_workflows.py --language en
python benchmark/AegisKV/exports/business-workflows-20261004/prepare_final_size.py
```

绘图基础类来自相邻 `two-workflow-scenarios-20261004/build_two_workflows.py`；只复用原生绘图元素与配色，不采用旧实验或旧数据。未修改当前论文。
