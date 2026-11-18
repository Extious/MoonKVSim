# Evaluation 诊断图修订

这五张图重新表达冻结 source-v3 的历史模拟，生成过程没有运行实验、修改算法或改变数据。它们解释现有结果为何不能证明预期收益；不把重画结果变成当前未冻结算法的性能证据。

## 图的研究问题与口径

| 图 | 本次改变 | 仍然存在的证据限制 |
|---|---|---|
| [逐 Workflow WCT 差](eval-workflow-delay.pdf) | 同一 160 个 ID、同一个 Mooncake 无故障排序，纵轴直接使用 WCT 差值秒数；三系统的绝对 WCT、原百分比保留在 CSV | 没有裁去尾部。3d0739b1 从 25.553 s 增至 155.130 s，差 129.577 s，原百分比为 +507.083%。这是真实的不利历史结果，不是坐标误差 |
| [重访 DRAM 初始命中](eval-initial-reuse.pdf) | 只画 revisit-1；每个 Workflow 分别以该轮所有 prompt token 为分母。CSV 保留 all-visit/revisit-only 的完整计数和两个分母 | 全局 token 加权率为 Mooncake 94.256929%、DRAM-only AegisKV 81.568436%、AegisKV 82.244958%。不能平均 Workflow 点得到全局率；首次查询命中不等于后来真正避免的计算 |
| [有效 prefill 进度](eval-preemption-progress.pdf) | 对同一离群 Workflow 中同一 span 提取三系统真实 scheduler 步骤，并各自对齐该 Workflow 的首次 release。阶梯使用状态边界，不画吞吐插值 | AegisKV 抢占造成进度归零，104.929 s 后再准入。该图展示无故障 HBM 压力抢占路径，不隔离证明某一个保护组件独自造成了延迟 |
| [F0→F1 配对 WCT](eval-fault-paired-wct.pdf) | 三个案例各比较同一个 Workflow，九行独立显示自身 F0 与 F1 的绝对 WCT；开放/填充标记和箭头表达变化方向 | 四行负变化完整保留。历史协议匹配焦点请求与 token 进度，没有固定整个受害集合；三个案例不是三个随机重复 |
| [恢复 token 来源](eval-fault-token-source.pdf) | 与配对 WCT 图逐行同序，27 条分项记录保留；Peer HBM 图例明确为 0 | 九行 Peer 恢复全为零。token 数没有覆盖后续 DAG，不能把局部恢复或完整 WCT 变化归因于 Peer |

## 进度曲线的依据

目标 span 为 `fanoutqa:3d0739b161908b67:2ff5a0169b37cd46:revisit-1`。Mooncake/DRAM 的步骤从冻结原始 gzip 各读取一次，AegisKV 使用诊断阶段已抽取的事件；输出只保留必要的计数和时间，不复制 prompt 内容。提取结果保存在 [preemption-progress-events.json](../../aegiskv-revision-20260909/preemption-progress-events.json)，输入哈希与全部导出哈希在 [diagnostics-manifest.json](diagnostics-manifest.json)。AegisKV 原始文件的追溯见 [DIAGNOSIS_PROVENANCE.json](../../aegiskv-revision-20260909/DIAGNOSIS_PROVENANCE.json)。

图中共有 43 条状态边界，分别来自 Mooncake 的 1 个 prefill step、DRAM-only AegisKV 的 2 个 prefill step、AegisKV 的 18 个 prefill step，以及 1 次抢占重置。AegisKV 的全局抢占/再准入时间为 102.367437007/207.296763004 s；以该 Workflow 首次释放 76.067748511 s 为零后，横轴位置为 26.299688496/131.229014493 s。

重置点不是补造的零值：已记录的抢占事件保存 `victim_num_computed_tokens_before_preemption=63161`；冻结 [scheduler.py](../../agent-lease-20260908/source-v3/python/moonkvsim/integration/vllm/scheduler.py) 的 `_preempt_for_recompute` 在同一个 DES 事件内执行 `request.preempt()` 和 `request.num_computed_tokens=0`。再准入步骤的实际 before 计数也为 0。抢占期间的零进度平线表达无有效前缀进度，没有画成持续计算；其他系统已结束的短 prefill 轨迹也没有延长到 AegisKV 的结束时间。

## 统计单位与实际核对

三系统各有一次 F0 冻结运行；三个故障案例各有三系统 F1 运行。五图复用相同的 3 次 F0 与 9 次 F1，不产生新重复样本。160 个 Workflow 是同一次运行中的配对对象，不能作为 160 次独立系统重复或制造运行间置信区间。

五张独立图均为 7 inch 矢量 PDF，并保留 PNG、SVG、CSV。实际查看了最终五张 PNG 与五张 PDF 的 144 dpi 插入宽度渲染；进度、配对 WCT 和 token 来源还检查了灰度显示。所有字体至少 10 pt，文字在页面内，图例拥有独立空间。

首轮发现图例字体上沿略越过 PDF 边界，已下移图例后重新导出。C2 Mooncake 的 F0/F1 仅差 0.111 s，短箭头会小于 glyph 大小而误导；现保留原坐标，直接标 +0.11 s，未人为错开点。逐 Workflow 图完整保留正负尾部，故障图保留全部案例和零值。

生成脚本：[render_revision_diagnostics.py](../../../benchmark/AegisKV/experiments/scripts/paper/render_revision_diagnostics.py)。重新生成会把视觉核对状态设为 PENDING；须实际查看新导出才能再次记录 PASS。全篇中文排版由主文稿整合步骤另行核对。
