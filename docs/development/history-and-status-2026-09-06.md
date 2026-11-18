# MoonKVSim 当前状态补充（2026-09-06）

本记录接续 [9 月 5 日的历史梳理](history-and-status-2026-09-05.md)。该文件中的
Cursor / Codex 数量、旧实验与七图论文均为当时快照，不再代表当前交付。
本机可读取已保留的项目会话；这不意味着能看到云端或其他机器上的全部历史。

## 本次对齐的依据

用户指定的 Mooncake 会话为 `01a06fae-403a-7852-97c1-475ca121b4c8`，
本地原始文件位于 `.codex/sessions/2026/09/05/`，会话工作目录为 Mooncake。
本次读取其记录，并核对实际设计、Controller、Router、connector/gate、HBM
与 `physical-pilot-146426` 产物。参考工作树有未提交改动，使用逐文件 SHA-256
绑定实现；没有修改 Mooncake 或历史会话。

## 当前实现与实验

默认实验配置现在使用 `mooncake_prompt_v1`：4096-token prompt chunk、完成前向
后才可见、源端独立 HBM/DRAM 准入、共享 ordinal、请求隔离、rendezvous 路由和
固定备用目标。配额按注册池计算，恢复复制到独立主 KV 空间，并维护读租约、
容量等待及 CompleteRequest 清理。库中的 `legacy_v3` 仍用于历史兼容。

这仍是 CPU 离散事件模拟。理想 CPM、未校准的 A100 服务时长、prompt-only
保护等边界已写入论文；不能据此声称完整实机等价。实机 4090 功能小试验的
结果单独呈现，未证明速度提升，也没有自然触发 DRAM 准入。

新证据根目录为 `output/paper-simulation-8b/20260906-alignment/`。
`source-v2/SOURCE_SNAPSHOT.json` 冻结 383 个执行输入，`campaign-v2` 的
170 次策略测量全部重跑，每次 160 workflows、1,304 calls，并逐份重新加载
原始事件独立验收。旧 200 次实验与 source-v1 策略结果均未混入。source-v1
的 20 个无保护逻辑故障计划按哈希导入，理由与原始执行绑定保留在清单中。

定向测试 127 项、相关回归 184 项通过（两组有重叠）；原生 Controller 差分
260 个案例、connector finalizer 的 6 个结果/重试序列通过。验证范围是所列
模块和策略语义，不是整个仓库或真实数据路径的无条件通过声明。

## 论文与结论

[当前论文](../../benchmark/AegisKV/paper/main.pdf)为 13 页，含
10 幅彩色矢量图、3 个完整算法、4 张表和 15 项引用。Motivation、System
Overview、提交与恢复、实机小试验和局限已纳入。

full 相对 DRAM-only 的整体平均故障罚时差为 +0.031571 s，95% CI 为
[-0.159076, +0.222218] s；健康期保护流量增加约 91.8%。当前证据未确定
稳定的 WCT 优势。最大上下文为 86,214 tokens，128K 桶为空；没有填充或
截断来制造覆盖。负面与不显著结果完整保留。

交付与复现入口：

- [论文目录与下载包](../../benchmark/AegisKV/docs/paper/REVISION_OVERVIEW.md)
- [实现对齐与边界](../../benchmark/AegisKV/docs/paper/MOONCAKE_ALIGNMENT.md)
- [完成报告](../../benchmark/AegisKV/docs/paper/COMPLETION_REPORT.md)
- [复现步骤](../../benchmark/AegisKV/docs/paper/REPRODUCE.md)

工作树仍是 `aegiskv` 分支上的混合未提交状态，HEAD 为
`b10886754ed4890285d1320cbb5fe679a9979166`。实验冻结的是上述文件清单，
并非声称整个当前工作树已提交或干净。没有启动 GPU 作业。
