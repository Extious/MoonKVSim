# 三系统逐工作流实验与图像口径

本轮目标是比较 Mooncake、DRAM-only AegisKV、AegisKV，在相同输入和配置下解释每个 workflow 的变化。当前实现为连续批处理 DES 上的机制实验适配器。精选图见 [Paper_Draft.md](Paper_Draft.md)，完整配置、未入选图与历史记录见 [Old_Figures.md](Old_Figures.md)；最终运行身份与数值以其中链接的 manifest、CSV 和源码快照为准。

## 三个系统

| 图例 | 正常 KV reuse 与 DRAM | Peer HBM | 解释 |
|---|---|---|---|
| Mooncake | 本地可复用 HBM + 确定性 LRU Store DRAM 模型 | 不建立保护副本 | 外部系统的模拟基线；不是本机运行的原生 Mooncake 服务 |
| DRAM-only AegisKV | 相同正常读取路径；Store 使用 revision-3 PrefixAdmission | 禁用 | AegisKV 的 DRAM 层消融，不再将其称为 Mooncake |
| AegisKV | 相同读取路径和 PrefixAdmission；Source 分别复制到 DRAM/Peer | 启用资源探索配置 | 用于检验 Peer HBM 的资源代价；未取得 QoS 证书，不能据此宣称已实现小于 1% 的干扰 |

三者共享 Qwen3-8B、DP=8/TP=PP=1、8×40 GiB GPU 模型、路由规则、工作流入场顺序与 DAG、连续批处理、正常缓存键、源 seal 规则、传输引擎、输出审计以及逻辑故障触发规则。闭环入场的实际时间会随前序完成时间变化，不强行把各系统的 release 时间改成同一条绝对时间轴。Mooncake 的 LRU 模型没有复现原生服务的异步 lease/watermark 线程；因此图例中的系统名指这里列出的模拟实现。

## 固定配置

| 项目 | 设置 |
|---|---|
| 输入 | 原始冻结 FanOutQA 派生 160 workflows / 1,304 requests，保留精确 token 身份 |
| 顺序 | admission seed=0，peer binding seed=0；每图按 workflow ID 升序，三条线同一个索引指向同一个 workflow |
| 并发 | 基础 C=16 个活跃 workflow，闭环补入；C=8/32 为单独配置 |
| KV | BF16，147,456 B/token，策略 chunk=4,096 tokens；固定模型 revision/ABI |
| GPU | 每 GPU 40 GiB；权重 16,381,470,720 B；固定 runtime 2 GiB |
| DRAM | 基础 10¹² B = 931.323 GiB；32/128 GiB 为单独配置 |
| 通信 | 基础共享 PCIe 有效服务率 25 GB/s；setup 250 µs；5/50 GB/s 单独配置；不是原生 HBM 峰值带宽 |
| 缓存保留 | 请求完成后零活跃权重，保留 TTL=120 s；共享消费者与读取 pin 仍约束回收 |
| PrefixAdmission | 最大复制组 2 个对象；staging=2 GiB、占配额；旧副本在复制 ACK 与验证后才替换 |
| Peer 探索 | 配额上限 8 GiB/GPU，受前台内存包络收缩；额外保留前台 1 GiB、分配器 128 MiB |
| CPU 服务模型 | 单个共享串行控制器。准入服务时间来自冻结 Python 参考实现的平均线程 CPU 时间；共同前台查询 50 µs 是显式模型假设。4× 为敏感性，不是另一台 CPU 的实测 |
| 故障 | 逻辑 focus 在自身约 60% prompt 进度触发 GPU fail-stop，检测延迟 0，120 s 后恢复空 GPU。F1 一个 focus；F2 再选择其因果后代，分别记录实际目标与时刻 |

F1 的首个 focus 由输入中最长 prompt 预先选定，ID 用于稳定打破并列；F2 的第二个 focus 在其后代中按匹配 Mooncake F0 的计算开始时间选择。两次事件的 `context_bucket=96k` 表示共同工作负载域，并不声称第二个请求本身也有 96K token。选择基于固定输入/基线，不能根据 AegisKV 获益大小挑选请求。

## 必须分开的工作负载

原始 trace 只有少量公共前缀，正常 DRAM 读取可能为零。零值必须保留；不能由此推断 DRAM 准入不影响 cache hit rate。

受控 revisits 将每个原始 workflow 的完整 DAG 执行两轮，下一轮根节点依赖上一轮所有叶节点。token、模型和理想节点时长固定，workflow ID 保留，span ID 增加轮次后缀：160 workflows / 2,608 requests。它使用独立的 `controlled_revisit_trace` schema，明确 `synthetic=true`，不是新采集的用户访问，也不是同一个实验运行两次后作平均。该配置用于主动施加复用机会，结果不能冒充真实重复访问分布。

命中率分母包含首轮冷访问和第二轮重访的全部 prompt tokens。除公共前缀等首轮共享外，即使第二轮几乎完全命中，合并两轮的命中率也只接近 50%；不能把它与仅计算暖访问的命中率混用。

两种负载都只作配置内三系统配对。每个配置/系统执行一次；160 个点是 160 个 workflow，不是 160 次运行或 160 个独立统计重复。曲线连接仅帮助匹配，ID 顺序没有时间趋势含义，不由这些点构造总体置信区间。

## 指标定义

| 图像指标 | 定义与边界 |
|---|---|
| Workflow WCT | 首次 release 到最后请求完成，包含 DAG 与服务影响，排除入场 slot 等待 |
| WCT 差值 | 同一 workflow 的 AegisKV 或 DRAM-only WCT 减 Mooncake WCT，Mooncake 曲线恒为零 |
| 故障罚时 | 同一系统、同一 workflow 的 WCT(F1/F2)−WCT(F0)；变化的并发与后续调度也包含在内 |
| Token hit rate | 实际正常服务复用的本地 HBM + DRAM + Peer token 数 / prompt token 数。故障恢复 token 另外统计；当前正常 Peer 读取为零 |
| DRAM hit contribution | 实际正常 DRAM 复用 token / 全部 prompt token；它不是“命中请求比例”，也不是以已访问 DRAM 的 token 为分母的条件命中率 |
| Request hit rate | 至少正常复用一个 token 的请求数 / 请求数。公共 64-token 前缀可能使此值很高、但 token hit rate 很低 |
| GPU scheduler queue | 首次实际计算开始 − 实际进入 GPU 调度队列；进入时间取 driver 的首次 admission 事件，GET 等待另列 |
| Foreground HBM wait | 为正常 DRAM GET 目标取得 HBM 的显式等待区间；结束于获得空间、缓存失效转重算、或 GPU 故障 |
| Precompute wait | 首次计算 − 原始 release，包含 CPU、HBM 等待、DRAM GET、调度排队；不能称为纯 GPU 排队 |
| TTFT / TPOT | release 到首个对外输出；TPOT 是每请求首末对外 token 间隔的平均值，单 token 请求无 TPOT 样本。TPOT 的 CDF 用对数横轴，同时保留常见区间与抢占造成的长尾 |
| HBM 轨迹 | 1 s 窗内按时间加权均值；Peer 包含 committed 和 pending；同时检查所有账户相加等于总容量 |
| 空闲 HBM 低于 1 GiB | 由事件区间精确积分，仅反映未分配空间。可回收缓存也占 HBM，不能把低 FREE 独立解释为推理受阻；需结合 HBM 等待、抢占和调度延迟 |
| CPU 图 | Python 参考准入函数的 `thread_time_ns`；按 workflow 汇总并绘制调用分布。不是 DES 总墙钟，也不是原生 serving CPU 利用率 |
| Controller service 图 | 对每个 workflow 的查询与准入服务报价求和，另画相对 Mooncake 的差值；整个矩阵使用同一份冻结报价。它表达模型中的 CPU 服务需求，与共享主机上参考 Python 线程计时的波动分开 |
| CPU 队列 | 根据冻结服务报价推进模拟时钟；前台查询和准入共享一个队列。报价没有覆盖原生 RPC、线程调度或全部控制器逻辑 |
| 链路流量 | 由实际 flow 区间积分得到的 GB/s，每个物理共享链路只计一次，保留已中止传输实际消耗的字节 |
| 逐 Workflow 复制量 | 传输归属到源请求所属 workflow，分别累计后台复制与正常 GET 的实际字节。包含中止前已传输部分；汇总传输量包含实验收尾阶段，链路时间曲线截至 workload 完成 |
| GET slowdown | 成功 GET 的实际数据服务时间 / 以该路径最窄资源独占服务所需时间；setup 包含在 GET 总延迟中，不把固定路径瓶颈误当争用。逐 workflow 的 P95 图没有 GET 时留空；不是零延迟 |
| Prefix ready | 故障到 `CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED` 事件的间隔，仅指可恢复前缀已经装入目标 primary |
| Resumed decoding | 故障到 `recovery_ready_ns` 的间隔，包含未保护 suffix 重算和静默输出重放；不能把这个字段当成纯前缀加载时间 |
| Failure to completion | 故障到该逻辑请求最终完成，另于其所属 workflow 的 WCT 统计 |

## 本轮修复与能力边界

共享缓存键绑定模型/ABI、完整祖先前缀和源块内容，不使用请求私有盐。正常 HBM 可写尾块尚无 COW 模型，只复用完整 policy/source 边界，可能保守地少复用尾部不足一个策略 chunk 的内容。

前台 DRAM GET 使用真实 DES 传输与目标预留。目标空间不足时等待；异步完成唤醒 GPU 调度。已完成加载且持有预留空间的请求在普通冷请求之前获得推进机会，并保留下一策略步的空间，防止相互持有资源造成循环等待。这是三系统一致的模拟调度规则，不能称为原生 Mooncake 的现成实现。

等待期间缓存可能失效。此时按实际仍驻留的前缀更新命中量，从当前模拟时刻进入重算队列，同时保留原始 release/WCT 起点。Peer TTL 释放独立同步到 HBM 账本，即使随后的新准入被拒绝也不能继续占用已经释放的字节。最终矩阵统一使用修复后的 `source-v6`，不把开发期混合版本串成敏感性曲线。

当前成本信号来自冻结理想节点时长和 CPM，不训练或运行 GBDT。GPU 批次时序未用目标 A100 标定；传输之间共享容量，但没有建立推理 kernel 与 DMA 的硬件 HBM 带宽竞争模型。物理释放 ACK 按 fenced DES 同步释放处理，不是测得的取消/释放时延。

ForegroundBudget 的严格无证书配置应给出零 Peer 配额。为观测 Peer HBM 的资源影响，主机制实验使用显式 `capacity_guarded_exploration`；没有伪造 QoS 证书，也没有把它等同于完整 Algorithm 3 的认证执行。该区别必须保留在图注与论文方法中。原生 serving CPU/GPU 性能、异步释放时间、目标硬件校准和完整 QoS 认证仍需另外取得证据。

## 逐图审查结论

| 原图 | 新图处理与可支持结论 |
|---|---|
| G01-01 / 11 / 12 / 13 | 观测分支 gap、具体 workflow、反事实恢复后果分别导出；124-workflow 观测、单例 DAG、旧 235B 反事实分别说明，避免重复计样本 |
| G01-02 | 解析 KV 容量与 2×RTX4090 host-staged 路径样本各一张；保留样本数 2/4/1/1 和聚合率定义，不当作 A100 标定 |
| G01-03 | 独立架构图保留数据/控制图例；图中设计组件与本轮适配器的实现差距按上文说明 |
| G01-04 | 拆为 tier 提交时序、故障时可恢复前缀、复制到新 primary 后重算三个独立 Draw.io；逻辑顺序没有实测时间比例 |
| G01-05 | prompt、workflow calls、context bins 各自导出；calls 横轴覆盖实际最大 27，128K 零样本不隐藏 |
| G01-06 | 三系统逐 workflow WCT/差值/命中率，加纯 GPU 排队、HBM 等待与占用、CPU、带宽争用；原始输入与受控复用分开 |
| G01-07 | 三系统逐 workflow 故障 WCT、相对 Mooncake 差值、各自相对 F0 罚时，不再以 run/seed 作为主横轴 |
| G01-08 | 同一逻辑 focus 的恢复 token 来源、prefix-ready、恢复 decode、请求完成分别出图；不把不同受害请求的平均值冒充配对结果 |
| G01-09 | 用零 Slack 与严格无证书 Peer 控制检查当前机制；旧 SlackLandlord/AIMD/LRU 消融保留为历史版本，不改名冒充新算法 |
| G01-10 | 并发、DRAM 容量、带宽、CPU 服务代价分别扫参数，每个点仍是三系统相同配置；保留逐 workflow 差值作为补充 |

图像导出为独立 PDF/SVG/PNG。所有曲线使用清晰的系统图例，样本数、输入来源、配置和证据限制写在 Markdown/LaTeX 图注中，图内不堆积 run 标识和小字。可编辑机制图保留 `.drawio`。

Workflow 曲线按 7.2 inch 宽导出，适合论文双栏通栏；CDF/小型比较按 3.5 inch 宽导出，适合单栏。原始字号不小于 10 pt。LaTeX 可以将两张窄图并排，或把两张 Workflow 图上下组合；将 7.2 inch 图直接缩至半栏会同时缩小文字。机制图推荐通栏，按 7.2 inch 缩放后的最小字号约 11.2 pt。
