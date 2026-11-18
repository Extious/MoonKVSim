### 正常运行的复用与排队成本

这里让原始 160 个 Workflow 各完整执行一次，共 1,304 个请求，不添加重复 DAG。三系统使用相同输入、资源、并发上限和种子，各执行一次无故障模拟。图 {{wct_id}} 与图 {{cache_id}} 使用完全相同的三次运行和 Workflow 排序；后文按 Agent 进度注入故障的实验也可复用这三次 F0，不能重复计为新增运行。

单轮结果中，Mooncake、DRAM-only AegisKV 和 AegisKV 的平均 WCT 分别为 {{mean_wcts}} s。AegisKV 相对 Mooncake 的均值变化为 {{mean_change}}%，逐对象有 {{slower}} 个变慢、{{faster}} 个变快。此前两轮重复 DAG 中“平均增加 4.92%”的结果不适用于这一单轮负载。这里保留全部正负差值；一次完整运行不能证明开销等效于零，也不提供重复运行的置信区间。

{{wct_figure}}

{{healthy_table}}

WCT 只计该 Workflow 首次释放到全部请求完成；并发门限之前的等待不计入。完整批次时长和同 ID 的释放/完成时刻一并保留，避免将准入变化误解释为对象服务改善。TTFT P99 的对象是这一轮的 1,304 个请求。

图 {{cache_id}} 直接回答“每个原始 Workflow 推理完成后，实际命中了多少缓存”。每个点先汇总该 Workflow 全部原始请求的正常路径命中 token，再除以全部 prompt token；本地 HBM、DRAM、Peer 分层计数，冷请求保留在分母中。命中一次很短的公共前缀也算一次请求命中，所以请求命中率与 token 命中率分别记录。

{{cache_figure}}

{{cache_table}}

三系统的 DRAM 和 Peer 命中均为零。Mooncake 与 DRAM-only 的本地命中共 82,048 tokens，AegisKV 为 82,112 tokens；AegisKV 在 159 个 Workflow 上与 Mooncake 的命中量完全相同，另一个只多命中 64 tokens。三者实际执行的 prefill 总量分别为 {{prefill_totals}} tokens，全部运行均未发生正常抢占。因此，本批单轮数据不支持用“缓存命中下降导致额外 prefill”解释 AegisKV 的 WCT 长尾。完整逐 Workflow 的分层命中、请求命中、实际 prefill、释放/完成及 WCT 已保存在[配对数据表]({{paired_csv}})中。

增量最大的 Workflow 是 `{{focus_id}}`：Mooncake 与 AegisKV 的 WCT 分别为 {{focus_wcts}} s，增加 {{focus_delta}} s。两系统该对象都命中 448 tokens、执行 66,235 个 prefill tokens，均无抢占。图 {{cost_id}} 沿各系统实际最晚完成的前驱回溯至根，将这条完成路径上的 GPU batch 参与区间、等待/调度间隙和控制/传输/依赖释放间隔作互斥分解，求和等于该 Workflow 的 WCT；不同系统的关键路径可能经过不同分支。

{{cost_figure}}

{{cost_table}}

其中，GPU batch 参与历时增加 {{gpu_delta}} s，等待/调度间隙增加 {{queue_delta}} s。更直接的证据来自同一个最后汇合请求：其 prompt 为 250 tokens、输出为 47 tokens；三系统都命中 64 tokens，只计算 186 个 prefill tokens，均参与 47 个 GPU step。Mooncake 中该请求的初次等待为 1.744 s、batch 参与历时为 0.269 s；AegisKV 中分别为 11.306 s 和 18.712 s。同期其他请求在这些 batch 中执行的 prefill 从 1,291 增至 192,182 tokens，说明该短请求的 decode 与更多长 prefill 共同执行，等待更重的批次完成。[请求与同批事件证据]({{batch_evidence}})保留了具体请求 ID 和时间边界。

这条轨迹将该对象的延迟增量定位到混合批次执行和队列竞争。Batch 参与历时包含同批其他请求带来的耗时，不能视为该请求独占 GPU 的计算时间；缓存命中相同也不保证相同排队、相同批次或相同 WCT。各系统的控制服务、保护活动与释放时序不同，但进一步区分这些因素各自的因果贡献，仍需固定 CPU 报价、调度或保护活动的对照。当前 DMA-to-forward 慢化系数为零，不能从这里推断真实 DMA 对 GPU forward 的干扰。

{{effective_reuse_plan}}

下表给出同三次单轮运行的控制工作及传输量。Python 参考 CPU 是宿主线程计时，模拟控制服务来自冻结报价，两者不能相加；字节数也不能直接转换成 Workflow 时延。原始 DRAM 读取为零，保留这一结果，不人为添加第二轮来制造复用收益。

{{resource_table}}

{{native_overhead_plan}}

Peer HBM 是否挤占前台空间，还需要将物理占用与完整生命周期排队对齐；额度曲线本身不足以回答这一问题。对应原生验证与算法 3 消融保留在 P8。
