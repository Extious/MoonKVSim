# Post-hoc Slack mechanism independent review

结论：**PASS，附非阻塞元数据与证据范围说明**。独立读取并校验了 10 个实验运行、5 个 F1/F0 条件配对、155 个冻结源文件；没有执行模拟、调参、改动冻结文件或正式结果。机器可复核结果见同目录 `POSTHOC_SLACK_INDEPENDENT_REVIEW.json`；复跑命令：

```sh
.venv/bin/python benchmark/AegisKV/experiments/evaluation-20260924/reviews/check_posthoc_slack_independent.py
.venv/bin/python benchmark/AegisKV/experiments/evaluation-20260924/reviews/check_posthoc_slack_addendum.py
```

该脚本只实例化冻结源码的 Config、Agent、Tracker 和 GridDurationProfile 以重算算术，没有实例化 CurrentRuntime 或调用 DES。它不依赖原 runner 的 `validate`、`offline_scores` 或现有 `AUDIT.json` 的布尔结论。

## 冻结和唯一变量

`slack-mechanism-posthoc-v1/SEAL.json` 中 PLAN、PROTOCOL、MANIFEST 哈希吻合，MANIFEST 的全部 155 个 source snapshot 哈希吻合。10 个 COMPLETE 均与 job、PLAN、MANIFEST、profile、workload 和全部产物哈希绑定；实际 config/failure 与 PLAN 相等。所有 summary 的 provider 为 GridDurationProfile，执行源码确实把该冻结 profile 对象传入 runtime。

冻结 runner 的 `prepare` 先做容量算术，再写 PLAN、source_snapshot、MANIFEST、SEAL（`run_slack_mechanism_diagnostic.py:128–188`）；`run` 重新 exec 冻结脚本、verify 后才执行任务。文件时间也一致：SEAL 为 **2026-09-24 02:25:15.805752 HKT**，首个运行的 config 为 **02:25:28.114892 HKT**，相隔 12.309140175 s。代码路径和本地文件时间支持“本次十点矩阵前冻结”；它们不是外部时间公证，不能单独证明从未有未记录探索。协议明确标记 post-hoc，且只授权一个预声明矩阵。

全部 job 的 config 差异仅为 `slack_mode` 与 `dram_bytes_per_host`。8 个 DRAM 运行策略一致，两个 Restart 对照明确另用 `policy=none`。workload/profile/手工 priors 相同；每个调用明确 output limit=16384，oracle reservation count 全为零。HBM 初始配额和上限均为零，实际 hot-copy bytes 与 HBM replica byte-time 均为零，因此这是 DRAM 选择机制的隔离例子。

预算算术包括 36 层、每 token 每层 4096 B KV、每 64-token block 每层 16 B selector + 8 B counter；pending append 同时计入新 KV 和整份新 metadata，旧 metadata 尚在 committed account。CP8192 为 **1,208,070,144 B**，已超过被静态算术否决的 1.125 GiB；修正后的 1.25 GiB 足以容纳单分支和下一次 append，却不能同时容纳 CP1280+CP8448（**1,434,583,296 B**）。所有五行预检独立重算相等。这是指定故障邻域的容量条件，不是整个运行期间无限增长均可容纳的承诺。

## 观测与故障入口重算

冻结 `ObservedRuntime._fail` 只在入口 `snapshot(self)`，随后调用一次 `super()._fail(target)`（runner:263–270）；snapshot 只读字段、复制字典/队列/Estimate 和账本值。after-event observer 只追加外部观测列表，不调用 policy、Tracker.slack、profile、schedule、flow 或资源转移。额外 invariant journal 记录是预期差异。

Restart F1 的有/无 observer 对照：summary **字节相同**，events/flows **解压后字节相同**，summary SHA256 为 `cd0e474379c7a8d8f0669bc0f83d37d1773fe53b00fad36dc1886645a2ddf8c2`。必须保留范围：**该 Restart 的 flow 记录为空**；空 flow 相等并不是有 checkpoint 传输条件的逐组实证对照。其他条件的透明性由复制代码的只读审查支持。不能写成十点均有 base/spy 成对验证。

独立审计对全部 5 个 `fault-state.json` 新建冻结 Tracker，逐项复制 Estimate，再以新 GridDurationProfile 通过标准 `__call__` 接口计算重建时间。结果与记录的 guarded/effective Slack、重建成本、E、候选字节全部精确相等；输入 frame 哈希前后不变。没有接触 live runtime 或其 Tracker。此处 guard=0，手工 critical/expensive priors=120/40 s，故两个分支 guarded Slack 为 **0/80 s**，fallback 为空；不是预测精度实验。

五个故障的入口均为 **6.255890594 s**，`wf0/a_critical`、invocation 0、logical 1536/9216、failed worker `{0}`、该 worker 所在 host `{0}`；实际失效 DRAM host 集合为空（worker fault），co-victim Agent 和迁移排队 Agent 集合均为空。两个分支同时在 0.226705019 s 开始，workers 为 0/1，peer 均为 worker 2/host 1。入口 computed 为 1536/8608。重建成本为 **133.793720/851.408365 ms**；DAG 下 expensive 的 E=0，zero 下其 E 大于 critical。离线文件也列出 finished root 的形式 E，它不满足运行时候选资格；不可将其误作保护候选。

## 退休、恢复与 WCT 的闭合证据

紧预算 zero 的 F0/F1 均在 **1.028336003 s** 出现实际退休：critical 的已发布 **CP1024、151,008,768 B** 消失，expensive computed 达 8192，CP7936 加 pending append 占 **1,208,177,280 B**。两者合计比预算多 **17,008,768 B**。审计限定在共同故障时刻之前，避免将 F0 后续 EOS/容量退休误计为本因果见证。

故障入口 tight-zero 只剩 expensive 的 **CP8448、1,245,822,336 B**，剩余 96,354,944 B 放不下 critical CP1280 的 188,760,960 B；tight-DAG 保留 critical CP1280。是“已保护后被退休”，不能写成 critical 从未得到保护。故障入口 critical computed 已达 1536，但可用 committed frontier 仍为 1280；不能用候选 frontier/bytes 代替已提交副本。

| 条件 | critical 故障时 CP | F0 WCT (s) | F1 WCT (s) | 配对 ΔWCT (ms) |
|---|---:|---:|---:|---:|
| 1.25 GiB DAG | 1280 | 99.155361841 | 99.179407105 | 24.045264 |
| 1.25 GiB zero | 0 | 99.155361841 | 99.290155564 | 134.793723 |
| 4 GiB DAG | 1280 | 99.155361841 | 99.179407105 | 24.045264 |
| 4 GiB zero | 1280 | 99.155361841 | 99.179407105 | 24.045264 |
| 1.25 GiB Restart | 0 | 99.155361841 | 99.290155564 | 134.793723 |

紧预算差异是 **110.748459 ms**，4 GiB 差异为零。五个失败条件均在 worker 2 重试，检测 1 ms，记录的重试排队 0；有/无 CP 的 admitted→first-new-token 服务为 **34.703782/145.452241 ms**，差值与 WCT 差值精确相等。critical 在所有 F1 仍是 join 的最后完成父节点，join submit 等于 critical finish，join 自身 latency 相同。这给出保护→恢复→依赖完成的具体链条；没有把普通 request latency 误称为普通 admission queue。

以上服务端点是 **first new token**，不是 EOS，也不是 `restore_done_ns`。24.045264 ms 是配对 workflow 完成差，不应与 34.703782 ms 恢复服务混用。

10 个运行均 complete、记录输出计数一致、terminal allocations=0；独立由 observer 账本重算的 DRAM byte-time 与 summary 精确相同，各 host peak 与 summary 相等且不超预算。这不等于重新执行数值注意力核或验证新生成答案语义，也不声称进行了全传输独立速率审计。

## 保留负结果及非阻塞说明

此前 `capacity-slack-ablation-v1` 的 **32 个 summary 哈希仍与原审计一致**。独立重新读取四个预算×F0/F1 的 8 组 Aegis/DAG versus zero 比较，各组四个 Workflow 的完成记录仍完全相同。新十点是看到该 null 结果后设计的单个 constructed mechanism 例子，必须同时保留，不能替换、合并为同一采样总体或改称预先计划的主实验。它包含 5 个相关条件配对、**1 个固定 Workflow 实例**，没有总体 CI；也不验证自然 Agent 行为、手工 priors 的准确性、CB、Peer HBM 收益或硬件 overhead。健康 WCT 相等依赖当前零 DMA compute slowdown 模型。

**P2 / nonblocking metadata:** 冻结 `slack-mechanism-posthoc-v1/MANIFEST.json:178` 的 timing 仍写 `configured linear compute`；实际 runner、冻结 profile 哈希和每个 summary 均绑定 **GridDurationProfile / AIC HYBRID shape grid**。不得改写已封存 manifest。主代理已安排追加 `TIMING_METADATA_ERRATUM.json`；该追加文件应说明文字字段过时，并保留原 manifest/seal 哈希。该描述问题不改变上述十点的实际执行或独立绑定 PASS。

## 追加复核：非空传输对照与勘误均已完成

初检指出 Restart flow 为空后，主代理单独授权以**相同冻结输入和源码**补跑一次 tight-DAG F1 无 observer 验证。原实验 spy 运行没有重跑，PLAN、PROTOCOL、MANIFEST、SEAL 均未改变。独立审计只读取这一新增验证，没有执行模拟；原审计脚本保持不变，新追加复核脚本为 `check_posthoc_slack_addendum.py`。

独立逐字节比较 `validation/tight-dag-F1-base-runtime` 与 `runs/dram1342177280-dag-F1`，summary、config、failure 均一致；events/flows 解压内容非空且完全相同。核对得到：

| 产物 | 记录数 | 解压字节数 | SHA256 |
|---|---:|---:|---|
| summary.json | — | — | `d254b28bb4c8c8c4350868b436d001a8426c9dd144fe10f7616e97a002f77811` |
| events.jsonl.gz | 1387 | 418771 | `65894656898c815d20eff1f5cfb588ae9170f829849507d6bc8026da37728fa0` |
| flows.jsonl.gz | 158 | 61240 | `fe23ae7362a77a04d1f25f8e1ecf32160a37e2d17c80a74795042b15e38a2da5` |

同时复核 `NONEMPTY_OBSERVATION_TRANSPARENCY.json` 的 PLAN/MANIFEST/profile/workload 和验证脚本/追加说明哈希，以及所有 155 个冻结源文件和原十点 summary 哈希。因此观测透明性的实证范围现为 **Restart F1 + 这一固定非空 checkpoint/recovery DRAM F1**，补齐了初检指出的空-flow 对照缺口；仍不能泛化为所有可能 workload 或十个条件逐一验证。计数为 **10 个实验运行、5 个条件配对、2 个验证运行**，实验样本增加数为零。

`slack-mechanism-posthoc-v1/TIMING_METADATA_ERRATUM.json` 已生成，SHA256 为 **`7c3960b31f0bec101cd0b97d687b34a1df99b02f413595a9f98f05c6202e97d3`**。独立核对其绑定的 44 个原始文件哈希与当前文件一致，实际 profile 仍为固定 GridDurationProfile，linear fallback 未使用；数字结果和原 seal 不变。初检 P2 现有追加勘误明确处理，保留为可追溯的非阻塞描述问题。
