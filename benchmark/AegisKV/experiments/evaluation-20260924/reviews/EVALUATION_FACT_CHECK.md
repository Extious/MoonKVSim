# Evaluation source/protocol fact-check

审查时间：2026-09-24 01:53 HKT（2026-09-23 17:53 UTC）。只读审查；没有改论文、运行源、冻结快照或已有结果，没有重跑 campaign。

审查的 `benchmark/AegisKV/paper/evaluation.tex` 为 276 行版本，SHA256 `f7468ecc661aa2ee7d72e661a3f73c708174de309bf664a3dfa8e93b9db414d2`。下列论文行号对应此版本。作者在审查期间加入了 sensitivity 段落；其 Z=64 联合干预说明已纳入本审查。

结论：未发现现有 structural/native 正文数值错引，新增 sensitivity 主要数值也与 CSV 一致。没有发现需要否定已完成结果的新 P1。需要修正或补足以下方法表述，尤其 baseline 定义、验证层级、组间版本及 forward 切分的因果边界。

下文 `formal/`、`struct/`、`sens/` 分别指本目录上级的 `formal-core-v1/`、`structural-campaign-v1/`、`sensitivity-campaign-v1/`；`frozen runtime` 指相应目录 `source_snapshot/python/moonkvsim/aegiskv/current/runtime.py`。

## 可操作发现

### P2-1：All-DRAM 是 threshold ablation，仍使用 Slack 排序

- 论文 84–87 行：`All-DRAM, which protects every eligible Agent` 没有交代受限容量下的排序和筛选，容易被理解成去除 workflow awareness 的 baseline。
- `formal/` frozen runtime 603、617–619 行仍计算 Slack 和 `exposed=max(0,T_recompute-Slack)`；`all_dram` 仅绕过 `exposed > tolerance`。628–636 行按 `(-exposed, key)` 排序，只有 checkpoint 能装入 host budget 才入选；637–642 行会退休未入选对象。
- 最小改法：写成 **disables the protection threshold while retaining exposure-based ordering and capacity admission**。不要将它标为 no-Slack。新 sensitivity 的 `slack_mode=zero` 是另外的干预，不能倒推为旧 primary All-DRAM 的语义。

### P2-2：Static-HBM 的额度是初始 128 MiB，且保留前台合法性回收

- 论文 66–67 行给出 adaptive policy 的 4 GiB cap/128 MiB initial，87 行仅说 Static-HBM 关闭 adaptive quota，缺少该对照的实际额度和安全例外。
- `formal/PLAN.json` 的 `initial_quota_bytes=134217728`，`hbm_cap_bytes=4294967296`。Frozen runtime 691 行跳过 Static-HBM 的 AIMD update；651 行实际使用 adapter quota。851–865 行仍可为 foreground admission 回收 hot copies；888–894 行仍按 foreground safety ceiling 降低额度。
- 最小改法：**Static-HBM starts from a non-growing 128 MiB quota per rank, retaining foreground safety reclamation**。它不是固定 4 GiB，也不是不可回收的 HBM pinning；安全收缩后没有 AIMD 自动增长。

### P2-3：每 run 的输出验证强度、保留的 memory 数据需要精确描述

- 论文 22–23 行说 output token identities 每 run 都被检查。Frozen runtime 1245 行直接从输入的固定 token 序列赋值 `primary_tokens`；1267–1268 和 1504–1506 行检查 emitted token **总数**。`audit_profile_campaign.py:281–299` 检查每 invocation 的报告长度和总数，并未对一个独立产生的逐 token 输出流计算身份/hash。`output_tokens_exact=True` 不等于模型数值/生成质量验证。
- 最小改法：表述为 **fixed-token replay with no missing or duplicate logical output counts**，随后保留 epoch fencing、byte conservation、terminal release 的 simulator correctness checks。不要让读者误解为数值模型执行的 identity equivalence test。
- 论文 111–112、168–170 行将 pending/committed memory、physical byte ledgers 泛称为全部保留。实际 summary-only run 保留计数、峰值、积分和 in-run invariants；没有每个 reservation/transfer 的完整历史可供外部逐事件重审。
- `struct/` 冻结 `run_structural_campaign.py:99–105` 只对两个预声明点启用 detailed logs：seed 7、Aegis、left.decode 的 skew 与 long-decode。`MAIN_TRACE_MECHANISM_AUDIT.json` 的 `trace_checks` 也是 2。最小改法：**aggregate byte/occupancy summaries for every run and full transfer ledgers for two prespecified structural runs**。其他 campaign 的 detailed 子集另列其自身数量，不与 summary-only 的检查强度混用。

### P2-4：分组声明 output reservation 和 source version，避免将不同组当作同一运行协议

- 论文 46–47 行的 512-token reservation 正确对应 primary FanOutQA，但 50–58 行结构化 workload 段落应补充其 **16,384-token declared output cap**。
- 证据：`struct/source_snapshot/python/moonkvsim/aegiskv/evaluation_scenarios.py:238–249`。Reservation 会影响 admission 和 foreground memory pressure；不宜让读者推断各组都使用 512。
- Primary 和 structural 的 MANIFEST 为 `checkpoint-decay-hysteresis-incremental-g-20260924`；sensitivity 为 `...-eosfix1`，另包含 Slack mode 配置。论文 15–23、172–218 行目前没有标明这条 source boundary。
- 最小改法：artifact/protocol 表或一段脚注标出 campaign ID、source hash/version、reservation、模型/DP、统计单位。不要将两版本结果合并为一次同源 sweep。下面的 EOS 边界核查支持已完成 structural 点未触发旧问题，但它不把旧冻结源变成新源。

### P2-5：F1−F0 包含 failure-boundary forward 分区变化，不能称纯故障/传输开销

- 论文 95–104、107–111 行定义 token-aligned 故障和 paired WCT；定义本身正确，但 limits 应注明 AIC forward shape 的这项变化。
- `formal/` frozen runtime 1090–1126 行：正常 prefill 按 chunk/checkpoint 边界推进，目标故障 token 若落在 forward 内，会将该 forward 截短。冻结 `evaluation_profile.py:71–117` 依据每次 forward 的 shape 计价，短 forward 仍有固定成本。
- 离线分区算术见下表。它是“正常无故障分区”与“仅额外插入故障 token 边界并继续正常执行”的 raw service 差，**不是已观察 F1 中可独立扣除的恢复分量**。实际 retry 重做的区间及 queue/capacity 后果另有变化。
- 最小改法：**Logical fault alignment may also split a modeled prefill forward; paired WCT includes the resulting shape-dependent service and scheduling effects.** 原始差只有约 10–16 ms，不能据此推断 WCT 偏差同样小，也不能在无 queue 反事实时从 ΔWCT 中减去该值。

### P3：两个精度修正和一个完成状态门槛

- 论文 78 行：8,704 是 median prompt context **向下对齐 checkpoint 后**的值；冻结 `evaluation_campaign.py:134–135` 先取 median 再 `//Z*Z`。建议写 checkpoint-aligned median training context。
- 论文 116 行：62-workflow p50/p95/p99 应加 **primary** 限定。Structural 主 run 是 8 workflows；sensitivity 是 4；native 是每模型 3 documents，均不是 62-workflow 样本。
- 论文 101 行的“135 main runs and eight scale controls are reported”与 124 行“complete 135-run”应分开完成门槛。截至本次快照：primary 102/180 COMPLETE；structural 主矩阵 135/135，scale 4/8，合计139/143；sensitivity126/126。135 主矩阵 complete 表述成立。不要在四个128-workflow点尚未完成时将全部八个 scale 标为已完成。运行中的计数是时点记录，不是最终判定。

## Failure-boundary 原始 service 算术

`fault_partition_costs.py` 读取并核对冻结 PLAN/control、workload、profile 和 profile 实现 hash。每个表格行覆盖三个 load、五个 policy 的同一个故障身份；没有启动 DES、重跑180点或引入 queue 反事实。

| 故障序号 | Agent 身份 | Prompt/output tokens | 故障逻辑 token | 相位 | 8B 额外 service (ms) | 32B 额外 service (ms) |
|---|---|---:|---:|---|---:|---:|
| 0 | `07381c55a61df50a/final` | 275 / 46 | 257 | prefill | 12.695811 | 16.377461 |
| 1 | `4ca77c9fca665fdd/6dae310bff90ff1b` | 6786 / 5 | 5433 | prefill | 10.284584 | 14.115157 |
| 2 | `4d3d6f1c14f3fdbb/final` | 350 / 95 | 356 | decode | 0.000001 | 0.000001 |
| 3 | `832589258f8bf42e/f637941dbbbf9b9c` | 20676 / 3 | 16544 | prefill | 10.046642 | 13.933721 |
| 4 | `d88a046051e878a4/final` | 300 / 57 | 286 | prefill | 12.691402 | 16.368314 |

故障序号 0 不是 healthy F0。Decode 的 1 ns 差来自 DES forward 分组的 ceil；profile 仍逐 token 累加 decode，没有额外一次模型 forward 的语义。JSON 保留原区间、分区及所有对应 job IDs。

Sensitivity 的 `prefill_chunk_tokens` 始终为256，但 `Z=64` 强制每个 forward 在64边界结束。对同一52 invocation 做无失败、无prefix复用的原始调用服务求和：

| Z | Prefill forward 数 | Prefill service (s) | Prefill + decode service (s) |
|---:|---:|---:|---:|
| 256 | 2,689 | 78.247872209 | 90.425696061 |
| 64 | 10,687 | 158.700765395 | 170.878589250 |

Raw prefill service 增加80.452893186 s；这是52调用的求和，**不是 makespan、target WCT 或总 WCT 反事实**。`sens/paired-workflows.csv` 的 none target paired ΔWCT 为1.802310283→17.711292058 s。论文214–217行现已正确称为 computation/checkpoint 联合干预；保留该限定，不能仅解释为 checkpoint traffic。

## Recovery 指标和 EOS 的边界

现有论文 110–111 行用 failure-to-first-new-token，并未直接把它称为 EOS；请继续保持区分：

| 字段/术语 | 冻结 runtime 中的含义 |
|---|---|
| `replay_done_ns` | computed frontier 重新到达故障前 durable frontier；1271–1272行 |
| `first_new_token_ns` | 故障后首次产生 durable frontier 之外的输出token；1273–1276行 |
| `service_ns` | retry admitted 到 first-new-token；可能包含剩余正常 prompt Prefill 和第一个 Decode，不只 checkpoint tail reconstruction |
| `restore_done_ns` | 所有 checkpoint KV/metadata 后台复制结束；950–967行 |
| request `finish_ns` / WCT | invocation/最后Agent完成；旧源1415–1430行有等待后台restore的逻辑，新EOSfix取消不再需要的cold复制 |

建议 figure/data 中避免不加定义的 `ready`。`replay_done`、first-new-token、full restore、EOS 是四个不同端点。已有正文 shared-host “recovery service” 的数字对应 admitted→first-new-token，数值没有错，但应在 metrics 定义里补全端点解释。

旧 structural 结果的 EOS 排除证据不能只靠 `restore_done <= request.finish`，因为旧 `_complete` 本身存在等待逻辑。本次另做只读下界检查：72个主矩阵 checkpoint recoveries 中，60个在 first-new-token 前已完成 full restore；另外12个是 long-decode，restore 仅比 first-new-token 晚5.904655–49.075716 ms，此时仍有至少1,650个输出token待Decode。用整个冻结 grid 的最小 Decode成本11,328,232 ns/token，再保守扣除每token36 ns的逐层整数误差，最短剩余计算下界为18.6915234 s，远大于49.1 ms。因此这些点在用户可见 EOS 前已经完成 restore；没有将 request-finish 当作 EOS 来反证等待不存在。

上述检查的实现与输入 hashes 在 `check_structural_eos_boundary.py`、`STRUCTURAL_EOS_BOUNDARY_CHECK.json`。它只说明已完成 structural 主矩阵不暴露此旧边界问题；不对其他 sparse 工作负载作普遍保证，也不声称旧源已含EOS修复。

## 已核实、无需改成更强结论的结果

- Structural 主矩阵：skew decode target penalty34.7442→21.7116 s；history decode93.3087→81.2288 s。十个 scenario/phase 的 DRAM→Aegis mean差仅0.02739–0.69983 ms，正文0.027–0.700 ms准确。
- Shared-host prefill：mean target penalty402.9874→405.7360 s；mean retry queue74.18→38.97 s、service1130.35→62.75 ms均正确。Seed7的 WCT恶化111.1003 s，recovery/joinsubmit增加3.77551 s，join invocation latency增加107.32481 s；其他两seed改善100.82909和2.02535 s。正文明确没有 ordinary admission timestamp，未把join latency冒称queue，且该pair故障walltime/worker/co-victim集合确实相同。
- Native warm selector：K64 current distinct覆盖32.77/16.76/15.45%，对recency +2.36/+0.97/−1.07pp；oracle33.25/16.79/16.53%，event-weighted59.90/36.04/22.35%，raw replacement0.15/0.88/1.19MiB；均对应warm数据，不是旧cold分析。13,824是selected-set一致性检查次数，不是独立统计样本。正文的3-document均值/range和不可推断runtime hit/WCT的限定恰当。
- 新 sensitivity：H2D8→64GB/s的DRAM283.96→24.02ms、HBM增益5.78→0.72ms；center none/DRAM/Aegis1.8023/.0610/.0595s；DRAM0.25/1GiB时无checkpoint并退化到restart、98.45%峰值；TTL200ms/100ms的过期reply现象与不验证预测准确性的结论，均与所列控制记录一致。不能把一个fixed target的未变化推广为通用robustness。
- 论文将 native sparse selector、constructed synthetic demand、Qwen dense service区分开，未把它们拼成原生 sparse serving 测量；保留此证据边界。

复现本报告新增算术：运行 reviews 下两个Python脚本即可；两者均通过 Ruff。只读算术结果不是新的实验样本，也没有扩大 primary/structural 的 n。
