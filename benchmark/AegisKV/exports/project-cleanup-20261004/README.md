# 项目整理记录（2026-10-04）

按用户要求整理 MoonKVSim 与 AegisKV 的目录，并删除旧实验结果和图像。
目录迁移、明确的旧输出及未被 Markdown 引用的旧图清理已完成。
用户所指的单份 Markdown 尚未确定；图像保留范围暂取项目 Markdown 引用的并集，
没有声称已完成仅保留单份文档引用内容的最终筛选。

## 已执行

| 操作 | 文件数 | 文件内容大小 |
|---|---:|---:|
| AegisKV 资料迁入 `benchmark/AegisKV/` | 1,559 | 305,143,822 字节 |
| 五份归档原始事件结果删除 | 5 | 2,008,010,457 字节 |
| 旧实验逐次结果、日志和条件组件输出删除 | 7,032 | 501,773,811 字节 |
| 未被 Markdown 引用的旧图导出删除 | 1,268 | 148,443,767 字节 |
| 可再生成的工具缓存和 Python 字节码删除 | 1,125 | 54,321,857 字节 |

合计删除 9,430 个文件、2,712,549,892 字节（约 2.53 GiB）。这是被删除文件的
内容大小之和，不是按磁盘配额测得的实际空间回收量。

根目录的 AegisKV `output/pdf/`、`output/analysis/`、`output/notion/`、相关参考页、
专用 schemas 和三方设计比较文档均已迁入 AegisKV。旧的空 `output/`、`.agents/`
及 `.codex/` 已移除。运行模块 `python/moonkvsim/aegiskv/` 和测试
`tests/aegiskv/` 保留包结构；通用 MoonKVSim 的源码、配置和 schema 保留。

Schema 加载路径和相关 runner/test 路径已更新。无故障开销 schema 接受新路径，
并兼容旧结果 provenance 中的历史路径。迁入的 Notion 脚本已修正仓库根目录定位，
本次没有执行发布脚本。

归档稿件的 11 份 Markdown 修复了 1,623 处可唯一定位的图像链接；21 处历史
`output/pdf/` 链接没有可唯一定位的现存目标，原链接保留并记入
[链接修复报告](MARKDOWN_LINK_REPAIR.json)。没有为缺失数据伪造替代文件。

## 保留边界

- 当前 [paper/](../../paper/) 的 42 个文件与整理前哈希一致。
- 当前 `blsc-online-v1/`、`blsc-scale-v1/`、`native-topk-warm/` 及 BLSC 配置保留。
- 当前 native 捕获、输入、模型权重、`.venv` 和 native runtime 保留。
- 实验配置、故障注入方案、workload、时延 profiles、协议、来源快照、汇总报告和
  历史完成记录保留；旧完成记录不证明被删除的逐次输出仍存在。
- Markdown 中提及图名或链接目录的图保留，生成器输入及 Draw.io 源保留。
  具体见 [图像保留清单](MARKDOWN_IMAGE_RETENTION.json)。
- 用户已有源码改动、编辑器文件和无关资料未做恢复、提交或广泛删除。

尚待用户指出“之前一个 Markdown”的路径。当前候选包括
[旧论文初稿](../../Archived/drafts/Paper_Draft_20260916_monolith.md)、
[旧图索引](../../Archived/drafts/Old_Figures.md) 和
[实验设计](../../Archived/drafts/EVALUATION_DESIGN.md)。三者引用范围不同；
确定文件后才能把目前的引用并集缩小到用户要求的保留范围。

## 验证与审计

路径/schema 相关既有测试：**133 passed, 1 skipped, 1 deselected**，见
[validation.log](validation.log)。跳过项缺少外部 normalized Weka trace；
未纳入的旧图生成器测试使用不存在的 `fixture.py` 与占位 implementation hash，
其已有 fixture 不符合严格来源绑定。未削弱验收规则，也未把该项计为通过。

迁移时 1,559 个文件逐一哈希相符。旧实验输出清理后，6,670 个保留文件通过
哈希核对；图清理后，2,801 个保留图像及当前证据文件通过核对。删除前未发现
候选文件有本机打开句柄，检查时 Slurm 队列为空。

| 记录 | 内容 |
|---|---|
| [MIGRATION_PLAN.json](MIGRATION_PLAN.json) | 源/目标路径、大小和迁移前 SHA-256 |
| [PATH_EDITS.json](PATH_EDITS.json) | 代码、文档的路径修正 |
| [source-before/](source-before/) | 修改前的源文件，包含用户原有改动 |
| [RAW_RESULT_DELETION_JOURNAL.jsonl](RAW_RESULT_DELETION_JOURNAL.jsonl) | 五份大原始文件的删除日志 |
| [OLD_CAMPAIGN_OUTPUT_DELETION_JOURNAL.jsonl](OLD_CAMPAIGN_OUTPUT_DELETION_JOURNAL.jsonl) | 旧实验输出的逐文件删除日志 |
| [OLD_IMAGE_DELETION_JOURNAL.jsonl](OLD_IMAGE_DELETION_JOURNAL.jsonl) | 未被引用的旧图导出删除日志 |
| [CACHE_DELETE_PLAN.json](CACHE_DELETE_PLAN.json) | 可再生成缓存的删除范围 |
| [CURRENT_EVIDENCE_BOUNDARY.json](CURRENT_EVIDENCE_BOUNDARY.json) | 当前论文与输入的保留边界 |
| [FINAL_VERIFICATION.json](FINAL_VERIFICATION.json) | 最终路径、schema、保留文件与删除核对 |
| [GIT_STATUS_BEFORE.txt](GIT_STATUS_BEFORE.txt) | 整理前的工作区状态 |
| [GIT_STATUS_AFTER.txt](GIT_STATUS_AFTER.txt) | 整理后的工作区状态 |

审计目录中的执行脚本对应本次文件级操作，已完成的删除脚本禁止重复执行。
