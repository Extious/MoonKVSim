# NOSA-1B 真实轨迹：请求内主 KV 访问集中度

2026-09-14。在本机 RTX 4090 上，使用作者固定版本的 NOSA-1B 权重和原生 CUDA 内核，已经采集 3 个 PG19 文档 × 16K/32K 两种历史长度的完整 28 层逐 Query、逐 KV 组选块轨迹。Slurm 任务 149623 完成，权重加载无缺失，采集开关验证 logits 差为 0。

32K 历史、后续 512 个 Query 的真实观测：

- 按“层 × KV组 × 64-token 块”划分，最热 10% 主 KV 字节覆盖 80.65%–82.96% 的历史块选中次数。
- 同层全部 KV 组必须合并备份时，最热 20% 字节覆盖 89.69%–92.62%。
- 同一 token 段必须包含全部层时，最热 20% 字节仅覆盖 52.83%–55.72%。

因此，请求内优先级至少应考虑 `layer × token-block`，再由真实缓存分配/复制粒度决定是否拆分 KV 组。数据支持 NOSA 模型中的访问集中动机；频率尚不能直接等同于恢复等待或 Workflow Completion Time 收益。NOSA 本身针对局部性训练，现象还需要在目标 Agent 工作负载与其他目标模型上检查适用范围。

[完整图像、数据定义、证据边界、原始逐层轨迹与复算命令](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/README.md)。

![真实逐 Query 选块轨迹](/home/comp/zhanzhao/MoonKVSim/output/native-sparse-20260914/figures/native-query-block-traces.png)

本次实际运行完整原生 Prefill，分析其末尾窗口；尚未执行故障、增量缓存恢复、Peer HBM/DRAM 分层或 Multi-Agent serving。16K 的较弱结果与各文档差异全部保留。下一步的恢复价值仍需沿[请求内 KV 方法规格](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/docs/paper/REQUEST_KV_POLICY_SPEC_20260914.md)把访问首次需要时间、H2D 与层计算重叠、冷块等待和 Slack 对齐。
