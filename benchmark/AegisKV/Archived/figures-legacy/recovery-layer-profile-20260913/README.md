# 固定请求、等 HBM 容量的逐层恢复剖面

这是论文机制图的可复算解析样例，非 GPU 测量、真实模型执行或完整 Workflow 故障实验。未修改已有算法、论文或实验数据。图采用 178 mm 宽度。

![逐层恢复剖面](/home/comp/zhanzhao/MoonKVSim/output/pdf/recovery-layer-profile-20260913/paired-layer-profile.png)

模型维度来自 [Qwen3-8B 官方配置](https://huggingface.co/Qwen/Qwen3-8B/blob/main/config.json)。计算公式沿用[此前单层 M/N 分析](/home/comp/zhanzhao/MoonKVSim/output/pdf/h2d-prefill-evidence-20260911/layerwise-mn-analysis/README.md)。

- 固定 36 层、32768 个有效历史 token、512 个需要前向的后缀 token、BF16、单请求、TP=PP=1。
- 两种放置均保留相同完整历史备份；在接管 DP 的 HBM 中分别预驻留前六层或后六层。恢复无需 Peer 到另一 GPU 的复制。
- 每层历史 KV 有效载荷为 128 MiB。两种方案都预驻留 768 MiB，都从 DRAM 加载 3840 MiB；每层都处理相同的 512 个后缀 token。
- H2D 从时间零按未驻留层顺序连续进行。目的空间充足；复制与计算独立；层开始前等待该层历史 KV 完整就绪。真实执行可将门放在 attention 前，本示例未建模提前 QKV 投影。
- 有效计算速率 100 TFLOP/s、H2D 25 GB/s 为明确假设。计算采用 FLOPs 模型，未独立加入 HBM 读取、启动、同步、争用和检测/排队成本。
- 恢复后历史 KV 共 4608 MiB；后缀新增 KV 最终另需 72 MiB。实际分配还需计入模型权重、页面碎片和临时空间。低备份额度不等于低恢复工作集。

图中的三块证据分别回答：驻留在哪里；传输是否赶上消费；哪些层的暴露等待发生变化。六层是依据此前解析参数展示机制的选择，不是通过真实请求数据证明的推荐层数；此例不能外推为少量 HBM 总能获得显著收益。

`layer-events.csv` 提供全部 72 个层事件；每行是同一确定性解析例子中的一个层，不是独立实验重复。字段包括初始 HBM 字节、H2D 字节、复制起止、KV 就绪、计算起止、暴露等待和逻辑复用 token。`summary.json` 给出派生总量。`build_profile.py` 保留绘图及事件推导源码。

“复用 token/字节”不是另一段可独立相加的时间；HBM KV 的消费发生在 attention 内部。未来测量应分别记录元数据绑定、QKV/选择器/attention/FFN 等算子及复制事件，按关键路径计算等待，不能把有重叠的传输时间与计算时间直接相加。

建议未来实证图使用同样布局，替换为真实事件日志；再保留预先固定的一组请求状态的配对差值，验证示例机制是否具有普遍性。稀疏版本需要真实选择轨迹，不在本图中构造热点或填入假命中率。

本例的加载边仅建模 H2D，假定相应 DRAM 数据已经可以从接管节点发起复制。若实际 DRAM Pool 还需要网络读取，实证时间线必须补上网络事件及其与 H2D 的依赖，不能把 25 GB/s 直接当作已经校准的 Pool 端到端速度。

原生稀疏候选模型、固定配置草案、执行路径检查和逐块日志要求见 [SPARSE_PLAN.md](/home/comp/zhanzhao/MoonKVSim/output/pdf/recovery-layer-profile-20260913/SPARSE_PLAN.md)。
