# 8B 主实验负例：更早恢复改变后续路由

只读分析 `formal-core-v1` 的冻结 PLAN、config、summary、COMPLETE 及已有 submit events；没有重跑正式实验。`check_primary_8b_adverse.py` 检查90个8B run的 COMPLETE→summary、job、config、workload绑定，并生成带输入 hashes 的 `PRIMARY_8B_ADVERSE.json`。本报告解释模拟器内的观测，不代表物理系统测量。

## 结论和总量

在 `Qwen3-8B-load0.9-*-F1-1` 中，Aegis 相对 DRAM 的目标 Workflow 快 **1.099886 ms**，但62个 Workflow 的 WCT 总和增加 **3.402435834 s**，均值增加54.8780 ms。分布恰好为：

- 1个非故障 Workflow，`8f0c326505148464`，慢3.411234922 s；
- 8个 Workflow（含目标）各快0.001099886 s，共改善0.008799088 s；
- 53个 Workflow 的 WCT完全相同。

相同条件下 healthy DRAM/Aegis 的逐Workflow完成记录相同，所以这个 cross-policy F1 差也等于相应 paired ΔWCT 的 cross-policy 差。

可证明的最小解释是：恢复提前1.1 ms沿worker1传播，在后面的fork提交时跨过一个已有请求的完成边界；当前按未完成请求数路由的规则因此给该fork分配了不同worker，改变最慢分支和join的释放时间。无需、也不应将没有记录的普通 admission 延迟称为已测queue时间。

## 故障和恢复条件完全对齐

| 项 | DRAM 与 Aegis |
|---|---|
| 目标 Agent / invocation | `4ca77c9fca665fdd/6dae310bff90ff1b` / 0 |
| 故障时刻 | 35.020635564 s |
| 逻辑 token / 总token | 5433 / 6791 |
| 失效 worker | `{0}`，其映射host为`{0}`；scope为worker，未删除host DRAM |
| 其他 active interrupted co-victim | 空集合，两边相同 |
| 排队迁移 Agent | `{9543466daff141b6/final}`，两边都迁到worker1 |
| Retry worker / admitted | 1 / 35.918420766 s |
| Detection / retry queue | 1 ms / 896.785202 ms |
| Checkpoint / replay tail | 5376 / 57 tokens |

必须区分 active co-victim 与排队迁移集合；recoveries只有目标不等于失败worker上没有其他排队请求。

| 时序 | DRAM | Aegis | Aegis − DRAM |
|---|---:|---:|---:|
| Recovery service (ms) | 167.718651 | 166.618765 | −1.099886 |
| First new token (s) | 36.086139417 | 36.085039531 | −0.001099886 |
| 目标 invocation finish (s) | 36.134929606 | 36.133829720 | −0.001099886 |
| 目标 Workflow WCT (s) | 6.545709994 | 6.544610108 | −0.001099886 |

Aegis在故障点具有176个HBM KV blocks及每rank22,176 bytes metadata；DRAM没有HBM副本。两边full restore均早于first-new-token，因此本case未触发旧源的EOS等待边界。

## 路由跳变的可重建证据

后续非故障 Workflow `8f0c326505148464` 的root在两边均于 **116.107340965 s** 完成并提交5个子Agent。此时worker1上的已有请求 `7c6edfe35e844a5d/889e15bbdc2b6055` 的完成时刻为：

- DRAM：116.107485904 s，比fork提交晚0.144939 ms；
- Aegis：116.106386018 s，比fork提交早0.954947 ms。

这正是1.099886 ms差值跨越fork提交边界。根据完整 request 的 submit/finish 和最终worker，在该时刻之前提交、尚未完成的请求数为：

| Worker | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---:|---:|---:|---:|---:|---:|---:|
| DRAM | 3 | 4 | 4 | 5 | 4 | 5 | 5 |
| Aegis | 2 | 4 | 4 | 5 | 4 | 5 | 5 |

这是 **queued+busy的合计**，不是分别测量queue长度或queue等待时间。所有这些Agent均为一次调用，目标fault早已恢复完成，之后没有新的故障/worker迁移；该计数可从现有记录重建。

冻结 `source_snapshot/python/moonkvsim/aegiskv/current/runtime.py:796–803` 选择最小 `(len(queue)+busy, worker_id)`；这些新调用 `local_prefix_tokens=0`，没有本地prefix亲和减项。按 submit events 的确切顺序逐次加一，脚本能完全复现：

| 子Agent后缀 | DRAM worker | Aegis worker |
|---|---:|---:|
| `31f19cc85afccd8a` | 1 | 1 |
| `417bc84216239640` | 1 | 1 |
| `7e373d2913c8ed97` | 2 | 1 |
| `aa894efc7d8dace9` | 3 | 2 |
| `2df1f08dbdd7db94` | 5 | 3 |

子Agent `7e373d2913c8ed97` 的提交时刻完全相同，但finish从125.222336141变为131.108013926 s，invocation latency增加5.885677785 s。两个其他改路由分支分别提早2.586999764和1.114756263 s；收益/损失均保留。

DRAM最晚分支为`417bc84216239640`，127.696779004 s完成；Aegis最晚分支变为`7e373d2913c8ed97`，131.108013926 s完成。Join因此晚3.411234922 s提交；其自身 invocation latency在两边都精确为1.135066020 s。最终 WCT分别为26.141659804与29.552894726 s。冻结runtime 1448–1454行的所有前驱完成后释放规则与该分解一致。

上述证据支持当前离散路由规则下的负例，不支持“HBM传输争用使普通queue多等待5.89 s”这一未测分解；也不建立生产continuous-batching系统中的同样幅度。

## Static-HBM 与 Aegis 的零 WCT 差

8B全部18个matched条件（3个load，各1个F0和5个F1）中，`workflows`、`requests`、`recoveries` 三个对象均逐字段完全相同。因此不能从这组结果声称adaptive quota改善WCT。

资源行为并不相同。以本case为例，Static-HBM→Aegis的单rank replica峰值由127,137,472增至231,123,904 bytes；记录的hot传输由23,477,185,952降至21,898,464,192 bytes。该结果是“此工作负载未体现完成时间增益”，不是“controller未运行”或“动态quota普遍无用”。

## 保留 load0.65 的 checkpoint 负例

以下是先在每个固定故障内对62个Workflow取mean，再对5个预声明故障场景取mean的描述性结果；不是310个独立样本，也不生成置信区间。Healthy mean各策略均为8.313899299 s。

| Policy | F1 mean WCT (s) | Mean paired penalty (s) | 相对none的F1 mean差 (ms) |
|---|---:|---:|---:|
| none | 9.058062067 | 0.744162768 | 0 |
| All-DRAM / DRAM | 9.079612436 | 0.765713138 | +21.550369 |
| Static-HBM / Aegis | 9.079608368 | 0.765709069 | +21.546301 |

其中fault3的全Workflow mean使DRAM比none高117.551240 ms，其他四个场景小幅改善，因而五场景总体仍稍差。本报告不进一步归因该另一个案例。逐场景值和所有zero/negative结果保留在JSON中。

`check_primary_8b_adverse.py` 与报告均不更改正式数据。普通请求未记录admitted timestamp的限制、五故障场景不独立重复、不同workflow共享同run的依赖关系应保留在论文解释中。
