# 本轮核对后的项目级纠正

来源：2026-10-05 用户明确要求“motivation部分的图像类型绘制方式和风格都不变，只是workflow变了，而且绘制真实的实验结果，background也是同样”。适用范围：MoonKVSim/benchmark/AegisKV 当前 Background/Motivation 图，不泛化到所有会刊或其它章节。

1. 开始重画前先确定原图的职责、图型和视觉基准。只保持字体/配色仍可能违反要求：用机制卡片、新组合图或新容量图替代原时间线/代价条形/三模型曲线不符合本次范围。
2. 原图的数据分解需要相应的直接测量。实测 full-prefill 成本加理论 Slack 不能变成实测 absorbed/exposed WCT。保留原堆叠条形布局时，图例应只命名可核验的实测分量；signed WCT 独立展示，保留负值和重复波动。
3. 工作流 parent completion 不应等待同 worker 的其他 Agent 持有的 cache-release 锁。本轮 isolated replay 把 cache 释放延至 run 边界，依赖由真正任务输出完成触发。取代先前 capture/replay 作为新时间线和单 Agent 对照来源；不重写先前原始记录。
4. GPU KV reuse 路径与重建路径的浮点差异可能改变自由生成的 tokens，即使 greedy decoding 也不能默认输出匹配。F0/F1 的输入、输出均需审计；本轮不匹配的 capture 保留为无效因果比较，最终用冻结新 token 的实际 GPU forward 重放。
5. Native 曲线复用原图口径，按 query 对所有 head 的重复 block 去重，再逐层归一。新图以三个连续请求历史替代 PG19 文本时，range 是这些状态的范围，不能说是独立 task 的置信区间。
6. 七 Agent 时间线增加高度而不缩字；实际导出发现横轴标题/底部图例相碰后，向上重分配 axes，重看彩色、灰度和最终 paper 页面。

7. Motivation 的示意图替换为实测后，Design 里引用同一图的任意单位示例要解除绑定。本轮只改动 `system_design.tex` 的相关解释和图注，保留选择算法与 Design 图本身。

对应核对来源：本目录最终 generators、`ORIGINAL_TYPE_MEASUREMENTS.json`、`review/`，原始实测在 `../../experiments/workflow-motivation-20261005/`。科学绘图库既有记录指纹异常（记录 `20260923T213943533276Z-d9d508c58b`）使 lessons 工具禁止追加；本轮没有重算指纹或换记忆目录绕过，纠正先保留项目内。
