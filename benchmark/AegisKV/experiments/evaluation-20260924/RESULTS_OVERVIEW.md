# AegisKV 当前设计：模拟结果与证据边界

恢复路径的因果选择域和排队历史恢复已修正，74 项 current-runtime 回归通过。五组替代矩阵固定使用同一源码版本 `checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`。旧版本仍保留，账本审计通过不等于修正后的恢复语义正确；重跑不增加统计样本。

v2 主矩阵 180 点、结构 135 点、敏感性 126 点、容量/Slack 32 点及事后机制 10 点全部完成并通过各自审计，共 483 条条件。主实验中断后的 3 点从冻结源码补跑，原 177 点的完成记录和摘要哈希全部未变。Claude Opus 5.5 的[v2 最终复审](reviews/FINAL_OPUS55.md)结论仍为 **NOT READY**；原输入封存在 `reviews/final-reviewed-v2-inputs/`。论文目前正在更新，旧版彩色/灰度检查不能用于修改后的文件。单独的 v3 版面预览已压到 12 页技术正文，但其主实验数值仍明确标为待替换的 v2，不能作为完成版。新的 walltime predictor 已完成训练，原 180 条主条件正在 `walltime-primary-v3` 独立重跑，不能追溯用于已审483点；[前文七项修改提案](reviews/FINAL_CLAIM_CHANGE_PROPOSAL.md)与[预测器更新候选](reviews/FINAL_CLAIM_PREDICTOR_UPDATE_V3.md)均为 NOT APPLIED，待用户决定冻结前文的范围。

后续工作见[复审补充协议](reviews/POST_REVIEW_REMEDIATION_PROTOCOL.md)。[低DMA补充24点](low-dma-postreview-v1/RESULTS.md)、[原生raw-KV组件864场景](native-transfer-postreview-v2/RESULTS.md)及[配额压力72点](quota-pressure-postreview-v1/RESULTS.md)均已完成独立审计。低 DMA 仍用旧 service proxy；原生组件不产生 native WCT；配额组仅在健康轨迹的目标完成之后出现压力，adaptive 与固定配额的配对 Workflow 端点相同，尚不支持适配收益。已完成补充方法正在接受独立的 Claude Opus 5.5 复审，整稿仍需新一轮评审。下文各表仍对应已封存 v2，不混入未完成 v3 或上述不同证据类型。

## 实现与数据入口

- [实现覆盖表](../../docs/DESIGN_IMPLEMENTATION_COVERAGE.md)：Tracker、完整 Peer DRAM、checkpoint Top-K/decay/hysteresis、增量 HBM gain、AIMD、共享资源恢复，包含代码与测试定位。
- [主实验](formal-core-v2-corrected/)：Qwen3-8B TP1、Qwen3-32B TP4，3 个名义负载、5 种策略、5 个固定故障及各自健康基线；62 个完整 held-out 工作流。
- [结构结果](structural-campaign-v2-main/PAPER_NUMBERS_V2.md)：目标工作流与全工作负载分别统计，保留 3 个 seed 的负结果和恢复分解。
- [辅助结果](reviews/PAPER_NUMBERS_V2.md)：126 点资源/模型控制、32 点容量/零 Slack 控制，以及健康 DMA 成本和统一目标下的 break-even。
- [事后 Slack 独立审计](reviews/POSTHOC_SLACK_V2_INDEPENDENT_REVIEW.md)：10 个构造条件，另有 2 个观测透明性检查。
- [原生选择诊断](native-topk-warm/RESULTS.md)和[K16/K64 对照](reviews/native-topk-operating-point/RESULTS.md)：3 个模型、各 3 个 PG19 文档。
- [版本对比](reviews/v1-v2-comparison/README.md)：相同解压输入、priors、profile、默认参数、活动故障身份及健康输出的一致性。
- [Evaluation 源](../../paper/evaluation.tex)：前置章节保持原文件，仅从 main 接入新章节与参考文献。

## 主实验：目标 WCT 与 Agent 恢复分开报告

以下均为五个固定故障身份的描述性均值，WCT penalty 为各自策略 F1−F0；不是随机故障总体或独立重复试验。HBM gain 为 DRAM−AegisKV，正值表示改善。

| 模型 | 名义负载 | Restart 目标 penalty(s) | DRAM 目标 penalty(s) | Restart Agent 恢复(s) | DRAM Agent 恢复(s) | Agent HBM gain(ms) |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3-8B | 0.3 | 0.529911 | 0.061972 | 0.956403 | 0.488464 | 0.219979 |
| Qwen3-8B | 0.65 | 0.529911 | 0.061972 | 0.956403 | 0.488464 | 0.219464 |
| Qwen3-8B | 0.9 | 1.994430 | 2.070490 | 2.694406 | 1.970189 | 0.508370 |
| Qwen3-32B | 0.3 | 1.426993 | 1.124137 | 1.910054 | 1.607198 | 0.027498 |
| Qwen3-32B | 0.65 | 0.661287 | 0.067892 | 1.144348 | 0.550953 | 0.027499 |
| Qwen3-32B | 0.9 | 1.484912 | 0.185925 | 2.221522 | 1.253272 | 0.035886 |

[原始逐身份端点](formal-core-v2-corrected/endpoints/per-identity.csv)、[独立恢复表审计](reviews/coprimary-v2-crosscheck/AGENT_LATENCY_EVIDENCE.json)保留 sink/non-sink、queue/service 和负值。DRAM 的 retry queue 占六个 cell 平均总恢复延迟的 62.22%–90.63%。8B 高负载第二个故障中，HBM 让目标提前 1.10ms，却改变随后路由，使另一个工作流晚 3.41s，62 工作流总 WCT 多 3.40s。Static-HBM 与完整 AegisKV 的逐工作流 WCT 相同，不支持 quota 自适应的 WCT 优势。

[O1 对照](reviews/o1-dma-corrected-v2-audit/PAPER_O1_NUMBERS_V2.md)计入完成及取消前已传的备份字节：DRAM 相对 All-DRAM 在三种负载下节省，8B 为 10.21%/5.70%/−0.095%，32B 为 10.81%/7.98%/1.16%。全体 WCT 均值相同，但一个 32B 高负载故障有两条工作流差异 ±4.113s，不能据均值断言逐工作流相同。两个详细 F1 日志的零 Slack fallback 为 3122/5586 与 3605/6518 个 unfinished-workflow/control-window 观察（55.89%/55.31%），不是健康全负载比例或时间占比。

## 结构干预：恢复变快不保证目标工作流变快

以下为 3 个构造 seed 的描述性均值，单位秒。正的“DRAM 收益”表示比 Restart 的自身 F1−F0 更小。

| 场景 | 故障阶段 | 目标 DRAM 收益 | 全 8 工作流均值 DRAM 收益 |
|---|---|---:|---:|
| skew | prefill | −14.430271 | −2.886489 |
| skew | decode | 0.980115 | 3.280516 |
| balanced | prefill | 0.610657 | 0.473494 |
| balanced | decode | 0.851918 | 0.527698 |
| history | prefill | −12.051406 | 3.332858 |
| history | decode | 8.568424 | 0.066350 |
| long drift | prefill | −30.621940 | 0.341192 |
| long drift | decode | −21.241536 | −6.634696 |
| shared host | prefill | −30.004457 | 16.109393 |
| shared host | decode | −41.011725 | 19.006702 |

history-prefill seed 19 中，DRAM 的活动恢复快 0.525124161 s，retry queue 相同。下一次 left 调用提前提交，但调用延迟多 26.173781742 s，join 调用延迟再多 17.680999920 s，使目标 WCT 恶化 43.329657501 s；其他 7 个工作流总和改善 81.810638672 s。全工作流均值因此改善 4.810122646 s。这是相同 seed、相同故障的时间戳分解，没有把未记录的普通 admission 冒称 queue。

135 点中有 108 条活动中断恢复和另外 279 条排队历史恢复，分类不混用。10 个场景/阶段均值的额外 HBM 目标收益范围为 0.000147–0.874737 ms；long-drift 的两个四块 bank 都能放入 K16，不能支持真实 native hotspot 预算不足时的鲁棒性结论。

## 容量与 Slack：保留自然回放的 null 和构造机制的有条件结果

32-run 容量/零 Slack 对照中，AegisKV 与零 Slack 变体的所有配对工作流 WCT 相同。健康备份传输量减少 4.58%–4.66%，包含完成 checkpoint、hot placement 及取消前已传字节。2 GiB 无法容纳目标自己的 checkpoint；较大预算下目标 CP16128 不变。该干预同时作用于 E 和 G。

另一个事后构造诊断禁用 HBM，让关键 Agent 与具有手工先验 80 s Slack 的昂贵分支竞争 1.25 GiB peer DRAM。预算能装各自检查点但装不下两者。DAG 保留关键 CP1280，零 Slack 保留昂贵 CP8448，故障增量分别为 23.974643 和 134.793723 ms，差 110.819080 ms。预算放宽到 4 GiB 时差异消失。故障身份、逻辑位置、墙钟和零 retry queue 均匹配；这验证构造竞争条件下的机制，不验证自然工作负载出现频率或预测准确性。

## 资源和健康成本

126 点控制的中心目标 penalty：Restart 1.802310283 s，DRAM 0.060973253 s，AegisKV 0.059529382 s。H2D 由 64 降至 8 GB/s，DRAM penalty 从 24.015869 增至 283.947137 ms；额外 HBM 收益从 0.715538 增至 5.775484 ms。0.25/1 GiB DRAM 下目标没有检查点，0/32 MiB HBM 下没有目标增量收益。

DMA slowdown 0.05/0.1 使健康均值增加 3.327619%/6.655237%。以“没有故障/这一个固定故障”的假想混合为例，统一目标的净收益为 pD−H。0.1 下 AegisKV 目标工作流的 break-even p 为 0.140613348，而四工作流总和的 p 为 1.493687130，超过 [0,1]，没有可行 break-even。不能混用整个工作负载的健康成本与单目标的恢复收益；这也不是测得的故障率。

预测倍率、TTL 和 λ 的非跨界控制没有目标 WCT 差异，是有限配置的代码路径检查。Z64 也将 forward 限到 64 tokens，不能把其差异全归于 checkpoint 间隔。

## 原生选择与论文边界

K16/L4 下，Current 对 NOSA/NSA/MiniCPM 的 distinct-history coverage 为 8.31%/4.20%/4.06%；event coverage 为 15.70%/11.46%/5.37%，并不支持“misses are few”。K64 时相对 Recency 的 distinct coverage 为 +2.36/+0.97/−1.07 个百分点。完整历史计数、即时逻辑 publication、3 文档的离线访问诊断不是运行时 hit rate，也不是 dense Qwen L11/L1 的 WCT 收益。

主回放使用 FanOutQA 构造 DAG、gold answers、单调用 Agent；自然多调用分布未被验证。AIC HYBRID 算子时长没有端到端校准；FCFS 单 active invocation 不覆盖 continuous batching、真实控制器成本或实测 GPU/DMA 干扰。历史 v1 的 128-workflow CPU/RSS 和更早线性时长的 copy-lag 反例均保留版本标签。所有负结果、旧 seal 和审稿拒绝原文保留。
