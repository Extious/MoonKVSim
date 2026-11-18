# 旧实验输出清理（2026-10-04）

按用户“整理项目，同时删除旧实验结果和图像”的要求，移除旧版本的逐次
`summary.json`、事件/流量/资源/控制日志、恢复故障状态，以及旧 native-transfer
条件组件场景的 JSON/NPZ 输出。配置、故障注入方案、workload、时延 profiles、
协议、来源快照、历史完成标记及汇总报告保留。

清理范围包含 formal v1/v2、structural v1/v2、sensitivity v1/v2、capacity/Slack
v1/v2、walltime-primary-v3、low-DMA、quota、post-hoc Slack、mechanism、smoke
及 external-baseline 的历史运行目录，另包括三份 2026-09-23 首轮设计结果和
已归档 Qwen3-8B 的部分原始结果。完整逐文件范围见
[删除计划](../../exports/project-cleanup-20261004/OLD_CAMPAIGN_OUTPUT_DELETE_PLAN.json)。

本批共删除 7,032 个文件、501,773,811 字节。删除前检查了文件状态和本机打开句柄，
Slurm 队列为空；删除后 6,670 个保留文件通过哈希核对。逐文件 SHA-256 见
[删除日志](../../exports/project-cleanup-20261004/OLD_CAMPAIGN_OUTPUT_DELETION_JOURNAL.jsonl)。

当前论文的 `blsc-online-v1/`、`blsc-scale-v1/`、`native-topk-warm/`、BLSC 配置
和当前 `paper/` 保留；实际 native selector 捕获、模型权重和当前输入也保留。
旧 `COMPLETE.json`、`STATUS.json` 和审计描述其原始运行时状态，不能用来证明
被删除的原始输出现在仍可复核。需要事件级复核时，应从保留的配置和来源重新运行。

旧图清理采用保守边界：保留项目 Markdown 提及的图名和所链接目录中的图，
另保留当前论文图、生成器输入及 Draw.io 源。具体保留清单与图像删除记录见
[整理记录](../../exports/project-cleanup-20261004/README.md)。用户指的是哪份
Markdown 尚未明确，因此尚未把保留范围缩小到单份文档。
