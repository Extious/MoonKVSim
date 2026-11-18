# 两个 workflow 的实测 context 与逐轮调用

图中的 Agent 字母与 capture-163125 原始 ID 一致。每个大卡片是一个 Agent；R1、R2 等是它的连续请求序号。箭头传递已完成前置 Agent 的最终文字产物，不传递该 Agent 的 KV。

每次请求都保留完整的角色提示、原问题、范围、已接收的前置产物与自身此前对话。图中 Hk 表示本 Agent 前 k 轮完整 user/assistant 历史，包含当时加入的材料；没有历史压缩。输入 token 数直接读取实际请求记录。

DAG 横向位置表示依赖层次，不是时间轴。依赖已满足的 Agent 可并行调度；同一 Agent 的各轮串行，仍可能等待 GPU 队列。

## 研究报告 workflow：Obsidian 插件比较

Q：哪些插件可实现 Notion 式 Table / Kanban / Calendar / List 多视图？比较各自优缺点。

### Agent C：使用约束（4 轮）

前置：无；逐份读取三份 README

角色 system prompt：You are Agent C. Context and constraints: identify documented installation, compatibility, maintenance, and limitations. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | Projects README | 2,850 | 0 | [call 6](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0006.json) |
| R2 | DB Folder README | 3,587 | 3,087 | [call 12](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0012.json) |
| R3 | Dataview README | 5,874 | 3,848 | [call 20](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0020.json) |
| R4 | 核验并纠正约束稿 | 6,234 | 6,158 | [call 23](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0023.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent A：候选功能（4 轮）

前置：无；逐份读取三份 README

角色 system prompt：You are Agent A. Subjects and methods: extract documented candidate capabilities with source IDs. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | Projects README | 2,847 | 0 | [call 3](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0003.json) |
| R2 | DB Folder README | 3,589 | 3,089 | [call 9](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0009.json) |
| R3 | Dataview README | 5,845 | 3,819 | [call 17](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0017.json) |
| R4 | 核验并纠正功能稿 | 6,180 | 6,104 | [call 22](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0022.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent B：需求与标准（2 轮）

前置：无；原问题 + Projects

角色 system prompt：You are Agent B. Needs and criteria: define the requested Table, Kanban, Calendar, and List criteria; distinguish requirements from inferred needs. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | Projects README | 2,859 | 0 | [call 4](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0004.json) |
| R2 | 核验并纠正标准稿 | 3,174 | 3,098 | [call 10](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0010.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent E：约束评估（2 轮）

前置：A 的功能稿 + C 的约束稿

角色 system prompt：You are Agent E. Contextual assessment: assess how constraints from C qualify capabilities from A. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | 结合使用约束评估 | 573 | 0 | [call 29](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0029.json) |
| R2 | 核验并纠正评估稿 | 882 | 806 | [call 33](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0033.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent D：功能匹配（2 轮）

前置：A 的功能稿 + B 的标准稿

角色 system prompt：You are Agent D. Fit and comparison: compare candidates against the evidence and criteria supplied by A and B. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | 比较功能与评价标准 | 603 | 0 | [call 30](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0030.json) |
| R2 | 核验并纠正匹配稿 | 917 | 841 | [call 34](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0034.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent F：不足与影响（2 轮）

前置：B 的标准稿 + D 的匹配稿

角色 system prompt：You are Agent F. Gaps and implications: explain unmet criteria and uncertainty using B and D. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | 归纳不足与不确定性 | 582 | 0 | [call 37](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0037.json) |
| R2 | 核验并纠正不足稿 | 910 | 834 | [call 44](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0044.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent G：报告综合（2 轮）

前置：E 的评估稿 + F 的不足稿

角色 system prompt：You are Agent G. Report synthesis: answer the original question using E and F, preserving citations and limitations. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | 综合结论回答问题 | 626 | 0 | [call 48](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0048.json) |
| R2 | 核验并纠正最终报告 | 959 | 883 | [call 50](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0050.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

## 仓库问题评审 workflow：Astropy 嵌套模型错误

Q：嵌套 CompoundModel 为什么使 separability_matrix 错判输入/输出依赖？提出修改和测试方案。

### Agent A：行为与接口（3 轮）

前置：无；文档 + core.py 摘录

角色 system prompt：You are Agent A. Behavior and interfaces: explain the documented input/output contract and nested compound-model behavior. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | compound-models.rst | 13,224 | 0 | [call 5](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0005.json) |
| R2 | core.py 相关函数摘录 | 15,477 | 13,555 | [call 11](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0011.json) |
| R3 | 核验并纠正行为稿 | 15,917 | 15,841 | [call 16](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0016.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent B：实现与调用路径（3 轮）

前置：无；相关实现 + core.py

角色 system prompt：You are Agent B. Implementation and call paths: identify the issue-relevant code path, array construction, and nesting behavior. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | separable.py | 2,881 | 0 | [call 7](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0007.json) |
| R2 | core.py 相关函数摘录 | 5,187 | 3,264 | [call 13](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0013.json) |
| R3 | 核验并纠正实现稿 | 5,647 | 5,570 | [call 21](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0021.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent C：测试与覆盖（2 轮）

前置：无；已有测试文件

角色 system prompt：You are Agent C. Existing tests and coverage: identify existing coverage and missing nested-model cases. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | test_separable.py | 1,911 | 0 | [call 8](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0008.json) |
| R2 | 核验并纠正覆盖稿 | 2,214 | 2,138 | [call 14](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0014.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent D：根因分析（2 轮）

前置：A 的行为稿 + B 的实现稿

角色 system prompt：You are Agent D. Root-cause analysis: reconcile A and B; cite source IDs and concrete functions. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | 定位错误根因 | 875 | 0 | [call 28](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0028.json) |
| R2 | 核验并纠正根因稿 | 1,151 | 1,075 | [call 31](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0031.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent E：兼容性风险（2 轮）

前置：B 的实现稿 + C 的覆盖稿

角色 system prompt：You are Agent E. Compatibility and risks: assess risks and contracts using B and C. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | 分析兼容性风险 | 867 | 0 | [call 26](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0026.json) |
| R2 | 核验并纠正风险稿 | 1,160 | 1,084 | [call 32](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0032.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent F：修改方案（2 轮）

前置：D 的根因稿

角色 system prompt：You are Agent F. Change proposal: propose a precise change from D without claiming it has been applied or tested. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | 提出具体修改方案 | 688 | 0 | [call 40](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0040.json) |
| R2 | 核验并纠正修改方案 | 972 | 896 | [call 41](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0041.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent G：回归测试计划（2 轮）

前置：C 的覆盖稿 + D 的根因稿

角色 system prompt：You are Agent G. Regression test plan: propose test inputs and expected invariants using C and D. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | 拟定输入与期望结果 | 883 | 0 | [call 42](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0042.json) |
| R2 | 核验并纠正测试计划 | 1,168 | 1,092 | [call 45](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0045.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。

### Agent H：最终评审（2 轮）

前置：E 风险 + F 修改 + G 测试

角色 system prompt：You are Agent H. Final review: synthesize E, F and G into an issue review; label unexecuted tests. Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.

| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |
|---|---|---:|---:|---|
| R1 | 综合风险、修改、测试 | 1,062 | 0 | [call 49](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0049.json) |
| R2 | 核验并纠正最终评审 | 1,370 | 1,294 | [call 51](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/workflow-motivation-20261005/runs/capture-163125/calls/0051.json) |

核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。
