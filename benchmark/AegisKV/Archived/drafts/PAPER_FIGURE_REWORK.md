# 三系统论文图像重做记录

本轮要求：Mooncake、DRAM-only AegisKV、AegisKV；同一配置按 workflow ID 配对；独立图、清楚图例；补齐正常复用、前台 HBM/排队、CPU、传输争用；逐一审查正文 10 图及 Motivation 3 图，最终入口为 FIGURES.md。

本轮增加了机制模拟实现与完整工作负载矩阵。精选的 21 张独立图见 [Paper_Draft.md](Paper_Draft.md)，其余 165 张本轮图及历史记录见 [Old_Figures.md](Old_Figures.md)；[FIGURES.md](FIGURES.md) 仅保留导航。筛选保留负面与混合结果，将重复诊断、代表性不足的故障结果和小样本物理 pilot 归档。解释范围见 [THREE_SYSTEM_PROTOCOL.md](THREE_SYSTEM_PROTOCOL.md)。这些输出是模拟研究证据，不是原生 serving 性能或 QoS 认证。

## 实现

- `python/moonkvsim/aegiskv/mechanism_experiment.py`：接入现有连续批处理、HBM 账本和流体传输 DES；AegisKV DRAM/Peer 使用 PrefixPool 的成组计划、staging、复制完成验证。Mooncake 单独使用 LRU Store 模型。
- `shared_prefix_v3`：缓存键取消请求私有盐；共享身份保持模型与工作负载配置固定。正常 HBM 的可写尾块尚无 COW，因此仅复用完整 policy/source 边界。
- 正常完成后按零活跃权重保留 TTL=120 s。ForegroundBudget 已接入：严格模式无证书时配额为零；主实验明确使用内存包络约束下的 Peer 资源探索。复制事务的 staging、ACK、过期释放与账本对齐，不等同于完整 Algorithm 3 的 QoS 认证。
- 记录真实 Python 准入实现 thread CPU time；不能标成 native 推理 CPU。CPU 模型使用冻结的各系统参考实现平均准入报价，前台查询共同假设 50 µs，并增加 4× 服务代价敏感性。
- 新独立 schema `controlled-revisit-trace` 标记 exact-input revisits 为 synthetic，保留原始 span 与轮次。正常 trace schema 仍要求非 synthetic。
- 入口：`scripts/run_three_system_mechanisms.py`；冻结与矩阵脚本分别为 `freeze_three_system_source.py`、`run_three_system_campaign.py`。最终统一源码为 `output/three-system-20260908/source-v6`；最终执行与提取路径为同目录的 `campaign-final`、`data-final`。更早的 `source-v1` 至 `source-v5` 和开发执行单独留档，不计入最终 38 次执行。
- 修复正常 GET 的异步 HBM 等待与唤醒、已加载请求的推进次序、缓存失效转重算的时间原点，以及 Peer TTL 释放后拒绝新准入时的 HBM 账本同步。测试覆盖这些会改变实验正确性的分支。

## 矩阵与图像口径

14 组配置、38 个系统执行项；每个配置/系统一次执行。原始 160 workflows/1,304 requests 与受控两轮 160 workflows/2,608 requests 分开；所有系统按 workflow ID 配对。图中点不是 run 编号，也不以 160 个 workflow 伪造 160 次独立重复。

原始 F0、受控复用 F0、F1/F2、C=8/16/32、DRAM=32/128/931.323 GiB、共享路径=5/25/50 GB/s、CPU 服务代价=1×/4×、零 Slack 和严格无证书 Peer 控制分别保留配置身份。三系统主比较在每一配置下使用同一份最终源码、工作负载和公共参数。

WCT/命中率/CPU/HBM 等待/调度等待/复制量逐 Workflow 导出；GPU 显存与链路利用按时间另图展示。恢复前缀 materialize、恢复 decode 和最终请求完成分开。所有科学图为独立 PDF/SVG/PNG，机制图另保留 Draw.io；背景、参数和证据限制写入索引正文。

## 逐图处理

| 图 | 当前问题 | 本轮目标 |
|---|---|---|
| G01-01 分支与恢复动机 | 混合观测与反事实；合图 | 单独导出观测分布、工作流示例、反事实后果，分别注明证据 |
| G01-02 KV 容量与传输 | 解析模型和物理 pilot 混排 | 单独导出容量、路径传输代价；保留真实硬件范围 |
| G01-03 架构 | revision-3 设计图 | 核对实际实现映射，设计图无需强行添加三条系统曲线 |
| G01-04 提交与恢复 | 机制图 | 核对 staging、复制 ACK、失败与恢复身份；完善图注 |
| G01-05 工作负载 | 子图、部分刻度不足 | 独立绘制 prompt、workflow calls 分布；新增 revisits 标明派生性质 |
| G01-06 健康开销 | 缺 Mooncake、正常 reuse、机制指标 | 三系统逐工作流 WCT/差值/命中率；请求等待/TTFT/TPOT；逐 GPU HBM；CPU 与链路竞争 |
| G01-07 故障影响 | 缺外部基线、混合 run 分布 | 三系统按同一 workflow ID 展示 F1 WCT 与各自 F1−F0 罚时 |
| G01-08 恢复来源 | seed 点、只有两个配置 | 三系统匹配故障对象的恢复 token 来源、prefix-ready、工作流后果，独立图 |
| G01-09 消融 | 旧算法名及版本 | 区分三系统主比较与 revision-3 机制消融，逐工作流评估 |
| G01-10 敏感性 | 不含 Mooncake、多个子图 | 三系统并发/DRAM 容量/带宽下的 WCT、复用、排队，分别出图 |
| G01-11/12/13 | 与正文 G01-01 内容复用 | 独立检查，避免把重复格式当作新实验 |

## 完成核验

最终矩阵 38/38 执行完成。231 项机制、调度、PrefixAdmission、ForegroundBudget 与 HBM 测试通过；151 项实验集成与 schema 测试通过。原始事件重新核对工作流 WCT、实际命中、输出身份、链路字节和内存守恒。逐图 PDF/PNG 审查、字号与边界、输入与导出哈希及 Markdown 链接的最终记录位于 `campaign-final/DELIVERY_AUDIT.json` 和 `VISUAL_REVIEW.json`，通过 FIGURES.md 访问。

受控复用主配置下，三者 Mean WCT 为 53.3891 / 64.0476 / 69.7440 s；正常 DRAM 命中贡献为 48.080 / 26.539 / 18.895%。这组结果不能支持“无故障保护开销很低”。AegisKV 的 HBM 分配等待和抢占次数更少，但纯 GPU 排队更长；这些相反方向的变化均保留，不能只选某项指标概括整体影响。
