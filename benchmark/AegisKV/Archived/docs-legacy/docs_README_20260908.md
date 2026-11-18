# AegisKV 文档索引

## 三方设计与实现对比

[Mooncake 本身、AegisKV on Mooncake、AegisKV on MoonKVSim：详细设计与实现对比](../../../docs/development/mooncake-aegiskv-three-way-design-implementation.md)

这份主文档逐项对照系统架构、控制面与数据面、元数据所有权、实际调用接口、Slack/准入淘汰/AIMD 三个算法、双层复制状态机、故障恢复与清理，并列出实机和模拟的已知差异、配置、验证证据及源码指纹。它区分通用模拟库与论文 runner 实际调用的路径。

## 配套资料

| 资料 | 入口 |
|---|---|
| 算法 2 从最小模型推导、证明、可执行参考与验证；明确区分容量租金和旧累计扣租 | [algorithm-2/README.md](algorithm-2/README.md) |
| Mooncake KV 管理与增加 AegisKV 后的架构图，含可编辑源文件和导出 | [drawio/README.md](drawio/README.md) |
| 当前论文、图像与 LaTeX 章节 | [paper/README.md](../paper/README.md) |
| 论文复现、审计、交付说明与旧稿 | [docs/paper/README.md](paper/README.md) |
| Related works 原始资料 | [related_works/](related_works/) |
| 专利文档、契约、来源清单与审计工具 | [patent/README.md](patent/README.md) |

三方对比主文档保留在仓库 `docs/development/`，以保持现有论文交付脚本和图件说明的引用有效；本目录提供统一入口。
