# Evaluation 非 Primary 部分只读核对

核对 `evaluation.tex` 的 Methodology、Structure、Operating Range、Native、Scope；Primary 数值及其路由反例按作者要求排除。本文不修改手稿。被核对源与数据 SHA256 见同名 JSON；其他代理后续修改应视为新文稿版本。

## 结论与需要处理的文字

未发现所审新结构、容量/Slack、post-hoc 或 native 数字误引。此前 Scope 将 `LK` 写成整个 rank 的容量上限，是实际范围错误；当前文字已改成 **one Agent's checkpoint**，该问题已解决。

1. **建议补一个实现边界。** repeated-call 控制覆盖排队中的下一次调用恢复，但 `current/runtime.py::_complete` 在完成后立即 `_submit` 下一调用；未建模真实 tool/think 间隔。可在 Scope 增加：`Repeated-call controls exercise queued continuations; inter-invocation tool/think gaps are absent.` 这不否定已实现的 queued-history 恢复，但不能由该恢复推及所有正常迁移/淘汰/空闲期备份复用。
2. **小措辞修正。** post-hoc 的 `no HBM` 宜写 `no Peer-HBM backup`；前台推理仍占主 HBM。紧/松预算的配对可称模拟中的 conditional selection mechanism，不能升级为真实预测准确度或机制发生率，现稿后一句已正确限制。
3. **483 是版本/矩阵事实，不是此时的完成证明。** 五个目录的冻结 runtime 均为 `de3a9ce7...8c5f`（`eosfix1-causal-domain1-queued-history1`），180+135+126+32+10 正确。审查时 Primary 仍在执行；交付时再核全 180 完成和最终审计，不能由矩阵计划推出 483 已完成。

没有发现需要“更乐观”改写的过度收窄。小 HBM 增益、容量下无 CP、non-crossing prediction controls、native 低 coverage 及历史 scale 身份都应保留。Native 的 “few misses” 判断已限定在具体预算与观测，不应泛化为所有稀疏模型/预算都无价值。

## 数字与逻辑核对

| 内容 | 核对结果与依据 |
|---|---|
| 结构 target/cohort | `structural-campaign-v2-main/figures/wct-endpoint-comparisons.csv` 与新文稿全部所引均值/差值一致。history decode 85.3402→76.7718 s，prefill 82.6202→94.6716 s。shared-host target +30.0045/+41.0117 s 与 cohort −16.1094/−19.0067 s 属于不同明确端点。 |
| 单个负例 | history/prefill seed19：恢复 service 567.661226→42.537065 ms，retry queue 同为1.059500110 s；最终 left 调用早0.525124161 s提交、latency多26.173781742 s，join latency多17.680999920 s，target多43.329657501 s；其他七 WF 合计少81.810638672 s。是同一 seed 的时间戳分解；现稿未将普通调用 latency 误称实测 queue。 |
| 恢复分类 | 108 active recoveries 与279 queued-history restores 分开，后者不是 active co-victims；与机制审计一致。 |
| 32点 Slack null | 每个 WF 的 WCT 均未改变；健康备份字节减少4.5828–4.6592%，256GiB下91.0937/95.5078GiB。zero Slack 同时影响 E/G，现稿未误称纯 O1。 |
| 容量不可装下 | 16,128-token target CP 含metadata为2,378,388,096 B =2.215046525GiB，确实超过2GiB，不能称竞争挤出。较大预算下同一目标 CP 不变。 |
| post-hoc 紧预算 | critical CP1280=188,760,960B；noncritical CP8448=1,245,822,336B。1.25GiB=1,342,177,280B，两者各自可装；合计1,434,583,296B不可装。故障同wall/logical位置且无retry queue；DAG/zero ΔWCT23.974643/134.793723ms。4GiB下同为23.974643ms。支持该人工干预条件内的机制，不替代32点null。 |
| H2D/容量 | DRAM在8/64GBps为283.947137/24.015869ms；Aegis额外5.775484/0.715538ms。中心1.802310283/.060973253/.059529382s，紧容量峰值比例.984552025795。 |
| stale与正常成本 | 200ms latency/100ms TTL 下每run52条回复年龄超过TTL，目标无变化；0.05/.1模型化slowdown下健康mean8.677666978/8.957127187s，中心8.398206670s。不能称测得控制器成本。Z64同时改变forward chunk，17.711292058s Restart penalty属joint intervention。 |
| native | `reviews/native-topk-operating-point/` 从原始整数count独立复算所有K16/L4 current/recency/oracle distinct与event coverage，以及K64全部比较项；现稿百分比四舍五入正确。模型不同、L4与dense WCT L11/L1不匹配、continuous counting/即时CP假设、n=3 documents、两种分母不可相加，都已说明。 |
| 异步上界反例 | 6247−1024=5223，且Z256不保证异步发布尾部≤Z；原始 `current-design-20260923/FINDINGS.md` 明确是旧linear-cost慢复制控制。现稿保留历史标记，未混入483。 |

## 近似词数与精简建议

环境未找到 TeXcount/detex。`MANUSCRIPT_APPROX_WORD_COUNTS.json` 及 `approx_manuscript_word_count.py` 提供可复查的**近似源词数**：去注释、数学、citation/ref、LaTeX控制字和figure/table图体；caption单列，保留标题，英语连字符词算一个。它不是提交格式的正式 TeXcount，也不是排版页数。

| 当前 main.tex 输入 | 正文近似词数 | caption |
|---|---:|---:|
| Background |669|34|
| Motivation |2755|298|
| System design |2577|279|
| Evaluation |2725|266|
| 合计 |8726|877|

Evaluation 分段正文约：Methodology972、Primary308（仅计词，不审数值）、Structure324、Operating Range664、Native215、Scope193；另有开头说明。整篇当前已输入部分约9603词含caption，不含参考文献/数学/图体，不代表含尚未写出的 Abstract/Introduction/Related Work。

建议先从重复句压缩，而非删负结果或公平契约：

- Methodology 已声明仿真、无continuous batching、非独立prediction validation；Scope集中承担物理开销/批处理/干扰的限制。Structure中保留“historical scale”和“constructed native drift不足”两个独有信息，其余一般仿真免责声明可以合并。
- “不是独立样本/没有CI/相同F0复用”在 Methodology 说明统计单位后，正文少重复；caption仍需自包含，不必为省词删掉范围不是CI。
- 两段 predictor说明可连续压缩，但不得丢掉“submission age包括queue”和“未来call不泄漏”两项实质边界。
- Structure既有十条件端点总结又有单seed链，均有价值；可精简第三次重复的“local G不是全局WCT保证”句，而保留 seed19 的精确分解及未观测admission提醒。
- Operating Range 应保留32点null与10点posthoc一同出现，以及目标2GiB不能单独fit的解释；这是辨识性条件，不建议为了缩篇删去。126点其余controls可用更紧凑句子并将完整数表继续留artifact。
- Native的 K16 operating point、K64预算边界和event负结果均有独立意义；不可只留K64相对提升。两分母定义与n=3范围在caption/正文的重复可适度合并。
