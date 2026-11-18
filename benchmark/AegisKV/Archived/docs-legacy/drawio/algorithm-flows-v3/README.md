# 算法 2 / 算法 3 完整执行流程（Revision 3）

**先打开 [五页合并 PDF](algorithms-2-3-complete.pdf)。** 修改图形时打开下面的 Draw.io 文件，通过底部页签切换子流程。所有框、判断、文本和连线都是原生可编辑对象；三列分组可以整体移动。

| 算法 | 可编辑源文件 | 单独 PDF | 页签 |
|---|---|---|---|
| 算法 2：PrefixAdmission | [algorithm-2-prefix-admission.drawio](algorithm-2-prefix-admission.drawio) | [算法 2 PDF](algorithm-2-prefix-admission.drawio.pdf) | 2A → 2B → 2C |
| 算法 3：ForegroundBudget | [algorithm-3-foreground-budget.drawio](algorithm-3-foreground-budget.drawio) | [算法 3 PDF](algorithm-3-foreground-budget.drawio.pdf) | 3A → 3B |

这些图解释当前论文、专利修订稿与可执行参考协议中的 **revision 3**，对应成组前缀准入和前台约束配额。父目录中真实 Mooncake prototype 架构图保留的是较早的 SlackLandlord / AIMD 实现；本图不代表 revision 3 已接入 native Mooncake 或完整 DES 实验链路。

## 阅读顺序与页间调用

整体闭环是 **3A 发布额度 → 2A / 2B 计划 → 3B 逐批许可 → 2C 提交或回收 → 新观测回到 3A**。两层使用各自的保护池，从同一个 Source 分别复制到 Peer HBM 和 Store DRAM；共用的源、链路等物理资源仍然共享传输预算。

| 页面 | 展开的执行路径 | 单页 PNG |
|---|---|---|
| **2A：入口与计划选择** | 事件唤醒 → 更新消费者/epoch → 关联已有前缀 → 分别进入 HBM、DRAM → 检查许可和未完成事务 → 从首缺口枚举 → 调用 2B → 选最小最终损失 → `begin` 再校验 | [2A](2a.png) |
| **2B：候选与删除闭包** | 检查封口、源、容量、staging、完成时限 → 在暂定视图中逐轮选最低联合损失/bytes 的合法闭包 → 重算完整最终状态 → 严格改善才收录 | [2B](2b.png) |
| **2C：提交、回收与共享** | PENDING → 分片 ACK → `finish` 再校验 → 原子提交或保留旧 C 并中止 → fenced cancellation → generation 匹配的 FreeACK；另列展开跨轮引用、部分复用、结束与 TTL | [2C](2c.png) |
| **3A：额度决策** | 识别重复/过期报告 → 对账 → 扣除前台和突发预留 → 验证样本与干扰证书 → 立即缩小、保持或按时间扩张 → 发布 Q、α 和到期许可 | [3A](3a.png) |
| **3B：额度兑现与超时** | 执行 `set_quota` → 等待真实释放 → 前台可行性检查；复制逐批原子扣减全部路径 token；watchdog 分别处理复制 deadline、消费者 TTL、read lease、许可到期 | [3B](3b.png) |

2A、2B、3A 按箭头跨列阅读；2C 的中列 R 是共用回收子流程，右列是消费者事件处理；3B 三列是相互触发的处理器，并不要求在全系统中串行执行。虚线表示重试、下一轮或异步事件，具体含义以线旁标注为准。

颜色用于帮助追踪分支：蓝色是正常动作和连接，紫色是子流程/共享契约，橙色是条件、暂停和等待，绿色是成功或允许，红色是中止、撤销和回收，灰色是终止或解释。颜色不替代判断框上的“是/否”。

## 符号与状态

| 符号 | 含义 |
|---|---|
| `C` / `C′` | 当前 COMMITTED 物理对象集合 / 选 victims 时使用的暂定集合 |
| `fᵢ(C)` | 消费者 i 在该 tier 中可恢复的连续前缀长度；已有部分直接复用，新复制从首缺口开始 |
| `X` / `Y` / `Z` | 候选连续新对象组 / 累计删除集合 / 一轮选择的根及其完整后代闭包 |
| `b(·)` | 按唯一物理对象计数的 bytes；共享引用不会重复计入容量 |
| `Q` / `S` | 授予该池的配额 / **包含在 Q 内**的 staging 预留；稳态限额是 `max(0,Q−S)` |
| `Tᵢ(f)` / `sᵢ(t)` / `wᵢ` | 该前缀下的恢复代价（包含完整重算退路）/ 随时间衰减的 Slack / 唯一活跃调用权重 |
| `Φ(C,t)` / `η` | 当前 tier 的加权超 Slack 恢复损失 / 严格改善余量；Φ 是优化代理量，不是工作流 WCT 最优性定理 |
| `Bphysical` | `Bcommitted + Bcopying + Breclaiming`；配额下降或逻辑删除不会使此量立即下降 |
| `Mphys` / `Mfixed` | GPU 总物理容量 / 不可撤销占用 |
| `Mprimary` / `Mnext` | 当前已预留主 KV / 本次额外前台预留，二者不重复计算 |
| `Rburst` / `Ralloc` | 取消与 FreeACK 延迟窗口内的需求增长预留 / allocator 安全预留 |
| `Lalloc` / `Mreg` / `Qpolicy` | allocator 真实可借页 / 注册容量（正数）/ 策略容量上限；不能借页的固定 arena 报 `Lalloc=0` |
| `Qcert` / `D` | 认证域内允许的容量 / 包含已有有效保护、新组与 staging 的有用需求 |
| `α` / `vgrow` / `Δt` | `Q/Mreg`，由额度推导 / 每秒最大扩张 bytes / 相邻有效观测的真实时间差 |
| `ε` | TTFT p99、TPOT p99 相对增加以及 goodput 相对损失的统计上界门槛，默认 1%；这不是已经取得的性能结果 |

`PENDING` 占用容量但不可恢复。`COMMITTED` 才能被读者获取。`ABORTED` 是复制组终态，其已分配内存仍进入 `RECLAIMING`，直到 Worker 的 FreeACK 才释放账面占用。终态迟到的 shard ACK 不会复活对象；旧 generation 的 FreeACK 不会释放后来重新分配的同名对象。

## 原先关注的情况在何处处理

1. **尾块较晚到达，是否还需要逐块历史 credit？** 2B 使用当前连续前缀损失和完整删除闭包重新评估。共享祖先的删除会影响多个消费者，因此不能根据某个请求尾块的分数就推断所有前缀应该一起删除。
2. **请求还在生成，但当前新块不值得备份？** 2A 只暂停该 tier 的保护，推理继续。新 KV、价值、引用、容量、FreeACK 或许可事件会重新触发评估，不永久封死未来保护。零收益首块可与之后已经生成的块组成候选组；不假设未来 KV 已存在。
3. **Agent 多轮复用？** 2C 首先关联兼容的共享对象。全命中不复制；部分命中只从缺口重新准入。不同真实活跃调用各计一次收益，同一个物理对象只计一次 bytes；结束轮可保留有 TTL 的零权重引用。
4. **Burst 到来时 α 调整滞后？** 3A 在前台预留之前检查新增需求，并用 Rburst 覆盖撤销延迟窗口；收缩立即发布。3B 仍以真实物理占用检查前台是否能分配，不能把“发布更小 α”当成已经拿回内存。
5. **低显存占用是否就意味着几乎没有推理干扰？** 3A 还要求工作域匹配的实测干扰证书，3B 同时限制共享路径速率和 DMA 批量。样本过期、域变化或前台违约会暂停或撤销 HBM 保护；watchdog 不会制造健康样本来累计稳定时间。

## 源码与外部接入责任

| 页面 | 可执行参考源码 | 论文位置 |
|---|---|---|
| 2A / 2B | [prefix_frontier.py](../../../../../python/moonkvsim/aegiskv/prefix_frontier.py)：`frontier`、`harm`、`plan`、`_victims`、`begin`；[revision_runtime.py](../../../../../python/moonkvsim/aegiskv/revision_runtime.py)：`begin_independent` | [算法 2 LaTeX](../../../paper/sections/algorithm-prefix-admission.tex) |
| 2C | [prefix_frontier.py](../../../../../python/moonkvsim/aegiskv/prefix_frontier.py)：`acknowledge_shard`、`finish`、`reclaim_tasks`、`acknowledge_free`、`acquire_read`、`collect_expired` | 同上 |
| 3A | [foreground_budget.py](../../../../../python/moonkvsim/aegiskv/foreground_budget.py)：`MemoryEnvelope`、`_certificate_valid`、`observe` | [算法 3 LaTeX](../../../paper/sections/algorithm-foreground-budget.tex) |
| 3B | [revision_runtime.py](../../../../../python/moonkvsim/aegiskv/revision_runtime.py)：`observe_foreground`、`copy_batch`、`watchdog`；`TransferBudget.take`、`PrefixPool.set_quota` | 同上 |

完整算法说明见 [专利与论文算法修订稿](../../patent/ALGORITHMS_2_3_REVISION.md)。图中的真实 source lease、placement/layout 验证、Worker DMA 取消与 FreeACK、allocator 原子预留以及 QoS 实测认证，是完整协议要求的接入责任。参考模块接受调用方提供的可读集合、观测和 ACK；它不自行验证真实 GPU 已停止 DMA，也不自行完成物理干扰测量。恢复时必须先预留 primary 目的地，再获取有期限的源读取 lease；lease 过期只发起取消，完成/取消 ACK 到来后才解除 pin。

## 导出与核验

生成器是 [build_flowcharts.py](build_flowcharts.py)。在仓库根目录运行：

```bash
uv run python benchmark/AegisKV/docs/drawio/algorithm-flows-v3/build_flowcharts.py --export
```

导出调用本机官方 Draw.io Desktop CLI；PNG 嵌入对应单页 XML，单算法 PDF 嵌入整本 XML。合并 PDF 保留五页原始矢量内容、目录书签，并附带两份 `.drawio` 文件供提取编辑。脚本会覆盖该目录内生成的图；若已经在 Draw.io 手工修改，请先保存副本。

[MANIFEST.json](MANIFEST.json) 记录源码、生成器和交付文件的 SHA-256、页数与导出检查结果。检查包括 XML ID/端点/几何边界、PDF 内嵌源文件一致性、中文文本可提取及页边界、PNG 内嵌页码。原生 PNG 的人工视觉检查另记录在 manifest 中；重新生成后会重置为待检查。这些是文档检查，不是算法性能或 native 集成验证。
