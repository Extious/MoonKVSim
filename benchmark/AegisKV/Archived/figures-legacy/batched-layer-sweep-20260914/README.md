# 批大小、初始 Peer HBM 驻留与加载等待

2026-09-14。根据用户要求，同时改变流水线每批层数，并令它等于初始 Peer HBM 驻留前缀的层数。每批层数完整扫描 **1–36**；沿用上一版 Qwen3-8B 的成本模型与“只预取下一批、整批历史 KV 到齐后切换”的调度规则。

全量数据覆盖 4 种历史长度、5 种重放长度、3 种假设带宽和 36 种批大小，共 **2160 个解析参数状态**。这些是确定性解析结果，不是实测、校准模拟或 2160 次独立实验；三图复用同一份扫描数据。

## 图 1：同时改变批大小、重放长度与带宽

![批大小、带宽与重放长度](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-sweep-20260914/batch-size-bandwidth-replay.png)

固定可复用历史为 32K。纵轴为每批层数，也是初始驻留层数；横轴为重放 token 数；三个面板分别为 12.5、25、50 GB/s。格内数字和共用色标表示完成全部 36 层期间的累计加载等待，单位 ms。图中展示 13 个代表批大小，全量 CSV 保留每个整数批大小。所有标为 0 的格子在精确运算中确实为零。橙框对应前一版的六层设置。

这张图直接回答：在给定重放长度和带宽下，从少量前层驻留逐步增加驻留层数，等待如何变化。每增加一个初始驻留层，本例 Peer HBM 增加 128 MiB，同时故障后的待加载历史减少 128 MiB。因此比较同时改变了容量与分批方式，不能把全部差异解释为流水粒度本身的收益。

[PDF](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-sweep-20260914/batch-size-bandwidth-replay.pdf) · [SVG](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-sweep-20260914/batch-size-bandwidth-replay.svg)

## 图 2：消除等待的最小每批层数

![最小零等待批大小](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-sweep-20260914/minimum-zero-wait-batch.png)

对每个历史长度、重放长度和带宽组合，枚举 1–36 层，找出累计加载等待首次为零的最小每批层数。由于用户要求批大小与初始驻留层数相同，数字也表示要预先放在 Peer HBM 中的前层数。纵轴恢复为历史长度，保留上一版对历史长度的比较。

32K 历史、重放 512 token 时，三个带宽条件分别需要 **25、20、1 层**，对应初始 Peer HBM 为 **3200、2560、128 MiB**。不是只计算前一批要隐藏的加载，而是验证整个 36 层调度没有暴露等待。

这个门槛仅表示当前整批就绪调度的零等待点。它不包含故障前复制成本、备份更新速率、发生故障的概率、其他请求对 Peer HBM 的需求或前台性能损失，因此不是系统最优配额。当计算慢于或等于加载时，每批一层也可能全部隐藏；当整批加载较慢时，等比例增大完整计算批与完整加载批不会改变它们的相对速度，本模型通常要增加到只剩较短尾批才达到零等待。这是当前调度假设的结果，不能作为其他预取策略的普遍层数要求。

每层历史 KV 容量随历史长度变化：4K、8K、16K、32K 分别为 16、32、64、128 MiB。精确初始 MiB/GiB 已写入 `minimum-zero-wait-batch.csv`，跨历史长度比较不能仅比较层数。

[PDF](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-sweep-20260914/minimum-zero-wait-batch.pdf) · [SVG](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-sweep-20260914/minimum-zero-wait-batch.svg)

## 图 3：完整扫描与尾批影响

![完整批大小曲线与执行时间](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-sweep-20260914/batch-size-detail.png)

固定 32K 历史、重放 512 token、25 GB/s。左图保留 1–36 层的所有整数扫描点；右图分解代表配置的重放计算与暴露等待，并在横轴标出初始 Peer HBM 容量。全部配置的计算量相同，为 170.85530898432 ms。

| 每批 / 初始驻留层数 | 实际分批 | 初始 Peer HBM | 累计等待 | 计算加等待 |
|---|---|---:|---:|---:|
| 6 | 6 + 6 + 6 + 6 + 6 + 6 | 768 MiB | 18.68 ms | 189.54 ms |
| 8 | 8 + 8 + 8 + 8 + 4 | 1024 MiB | 14.95 ms | 185.80 ms |
| 9 | 9 + 9 + 9 + 9 | 1152 MiB | 16.81 ms | 187.67 ms |
| 12 | 12 + 12 + 12 | 1536 MiB | 14.95 ms | 185.80 ms |
| 20 | 20 + 16 | 2560 MiB | 0 ms | 170.86 ms |

8 层一批时，最后只加载 4 层，该尾批能被前一批计算完全隐藏；9 层一批时，最后仍要加载完整 9 层。即使多驻留了一层，批间组织变化仍使等待增加。类似地，8 层与 12 层在此例的等待相同，而初始容量不同。这个非单调结果已保留，未只取能整除 36 的批大小，也未平滑曲线或把尾批补齐。

36 层一批是所有历史预先驻留、无需再加载的边界点，不是通过流水隐藏了额外传输。20 层已在此例达到零等待，继续增大驻留不会进一步降低模型中的执行时间。

[PDF](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-sweep-20260914/batch-size-detail.pdf) · [SVG](/home/comp/zhanzhao/MoonKVSim/output/pdf/batched-layer-sweep-20260914/batch-size-detail.svg)

## 证据和复现

从仓库根目录运行：

```bash
python3 output/pdf/batched-layer-sweep-20260914/build_batch_sweep.py
```

基础源为 `output/pdf/batched-layer-pipeline-20260914/build_batched_pipeline.py`，保持不变。单层算量与 KV 字节模型不变：36 层、GQA KV 头数 8、头维度 128、主 KV 元素 2 字节、TP 为 1，假设有效算力 100 TFLOP/s。计算是使用已有历史补算重放 token 的整层前向，不仅是 attention kernel；历史 KV 被传输，新增 KV 在重放时生成。

原来的六层图不是要求第一批算完时传完全部后续层。新扫描同样只预取下一批，在当前批开始计算时提交，且下一批整批就绪后才切换。对任何不能整除 36 的批大小，最后一批使用实际剩余层数。已经加载的 KV 保留，假设 HBM 足以容纳最终全部历史和新增 KV；初始驻留层数不代表整个恢复期间 HBM 容量的上限。

未计故障检测、接管排队、模型权重加载、启动延迟、共享带宽与算力争用、非矩阵乘计算开销及其他请求。流水重叠也适用于正常推理，本组图不能独立证明故障恢复专有创新。对同一固定重放长度，计算量不随批大小变化；不同重放长度之间，等待更低不能替代总执行时间比较。

验证包括全部 2160 个状态的精确分批事件与逐层参考调度、相邻批持续时间的独立求和、各批数据就绪和串行传输约束、60 个零等待最小值的独立核对，以及与前版 60 个六层状态逐点一致。全扫描中记录 130 个相邻批大小导致等待增加的配置对，作为尾批敏感性的诊断记录，不能作为 130 次独立实验。

导出宽度均为 178 mm，保留 PNG、PDF、SVG 与源脚本。`batch-size-sweep.csv` 是完整状态表，`minimum-zero-wait-batch.csv` 是门槛与容量，`batch-events.csv` 保留所有批次时间，`nonmonotonic-adjacent-cases.csv` 保存非单调配置。`parameters.json`、`validation.json`、`MANIFEST.json` 和 `REVIEW.json` 分别记录假设、计算核对、来源哈希与实际导出审查；没有重新验收整篇论文排版。
