# Proposed claim corrections — NOT APPLIED

**状态：仅供用户审阅的建议；未应用。** 本文件不修改 `system_design.tex`、`motivation.tex`、Evaluation、图或实验结果，不新增实验。用户冻结的前文保持原样。以下建议不能作为“中心主张已经修复”或“评审已经通过”的证据。

本次只读核对的前文版本：

- `benchmark/AegisKV/paper/system_design.tex` SHA256：`cfb92dcfc6c40c7d3a5c996d1628cc94318af863b74b7f04b6546a714fa5fff3`。
- `benchmark/AegisKV/paper/motivation.tex` SHA256：`e0fc57e28db8956485917c3484c5a9f9e172960dbd1f75be206247e3217e0419`。

下列行号对应这些精确字节。`motivation.tex` 第125行包含多个完整段落，因此同时提供原句定位。文中相对实验路径均以 `benchmark/AegisKV/experiments/evaluation-20260924/` 为根；代码路径以仓库为根。修改建议分为：**现在撤去无条件保证/明确启发式**，以及**若坚持更强正向主张，需要另行设计的模型、实验或证明**。后者没有执行，也不被现有483点矩阵自动覆盖。

## 1. O1：把 λ 改为选择阈值，撤去每次故障的无条件 WCT 上界

**当前位置与短原句。** `system_design.tex:230–231` 将 E 直接称为不能被 Slack 隐藏的 delay；`:242–247` 写道：

> “reconstructing an unprotected Agent adds at most $\lambda$ to its workflow”

该段同时在有限容量下按 E 接纳。容量淘汰可以让 E>λ 的 Agent 不受保护；预测误差、重试排队、永久算力损失与多受害者相互作用也未包含在这个逐 Agent surrogate 中。因此候选阈值不是实际 WCT 保证。

**建议替换的完整英文句子。** 用第一句替换230–231行的引式句；随后保留 E 公式。用后四句替换242–247行，后面的重评估机制可保留：

```tex
Applying the isolated-branch model with $R_i=T_a$ and guarded slack
$\sigma_i=s_a$ gives a per-Agent exposure estimate, $E_a=[T_a-s_a]^+$.
Master considers Agent $a$ for Peer-DRAM protection when $E_a>\lambda$.
Here, $\lambda$ is a threshold on estimated exposure, not an upper bound
on the workflow delay caused by a failure.
With $\lambda=0$, every Agent with positive estimated exposure is eligible,
subject to available Peer-DRAM capacity.
If the eligible checkpoints do not all fit, Master admits them in
decreasing $E_a$ order.
```

**现有证据。** `capacity-slack-ablation-v2-corrected/variant-cost-results.csv`、该目录的独立审计及 `sensitivity-campaign-v2-corrected/binding-diagnostics.csv` 显示目标 CP 为16,128 tokens、2,378,388,096B，在2GiB乃至更小预算内不能单独装下。`structural-campaign-v2-main/PAPER_NUMBERS_V2.md` 的 history/prefill seed19显示 DRAM 恢复 service 少0.525124161s，目标 WCT 却多43.329657501s，且无普通 admission 数据支持把后继 latency 全称 queue。`slack-mechanism-posthoc-v2-corrected/PAIRED_RESULTS.json` 支持手设0/80s Slack下的条件选择收益，不能证明普遍延迟上界。

**保留更强主张所需条件。** 必须先定义上界针对孤立分支还是完整故障、是否包含队列/失去容量，并约束预测误差、容量可行性、所有同时受害者与调度变化，再给出证明。增加平均收益实验不能证明无条件 λ 上界。现有数据可支持“该阈值改变选择/流量，在特定竞争条件下改善 WCT”，不能支持一般保证。

## 2. O1/O2：将 G 标成局部排序分数，撤去全局最优及等大小副本的绝对表述

**当前位置与短原句。** `system_design.tex:476–487`：

> “Every protected Agent of a model occupies the same HBM”
>
> “this order removes the most delay within the quota”

`motivation.tex:125` 则要求：

> “The unit of a recovery decision must instead be the complete failure event”

同一段还正确指出独立 Slack 排序可能忽略共同瓶颈。当前 `_rebalance_inner` 实际采用逐 Agent E/G 排序，没有计算受害者集合的联合边际收益；metadata 随 checkpoint frontier 增长，短前缀还可能不足 K 个块，因此连精确等大小前提也不成立。

**建议替换的完整英文句子。** 用下面的段落替换476–487行的等大小/收益/最优性文字，保留 G 公式作为定义，并保留放不下则留在DRAM的机制：

```tex
Each Agent's Peer-HBM copy contains up to $LK$ KV blocks plus the
metadata required for its checkpoint; the metadata footprint depends
on the checkpoint frontier.
We use $G_a=[T^D_a-s_a]^+-[T^H_a-s_a]^+$ as a per-Agent estimate of the
incremental exposed recovery delay avoided by an HBM copy.
Master ranks eligible Agents by $G_a$, skips nonpositive scores, and
admits copies that fit the available quota.
This is a local ranking heuristic: it does not optimize the joint value
of simultaneously interrupted Agents or guarantee a reduction in total
workflow completion time when placement and scheduling change.
```

为保持 Motivation 与实际方法一致，建议仅将第125行的上述 “unit ... must” 一句替换为以下两句；保留共同故障具有非加性这一观察和分析例子：

```tex
These non-additive effects motivate evaluating protection at the
complete failure-event level, including all interrupted Agents and
their residual dependencies.
Our current policy approximates that objective with per-Agent scores
rather than jointly optimizing victim sets.
```

**现有证据。** `python/moonkvsim/aegiskv/current/runtime.py:615–690` 给出逐 Agent排序与逐对象容量检查，`:682–685`加入 frontier相关metadata；`current/model.py:125–134`定义metadata字节。修正版主实验已有完整配对 `formal-core-v2-corrected/runs/Qwen3-8B-load0.9-{dram,aegiskv}-F1-1/summary.json`：故障均在35.020635564s、同Agent/逻辑5433位置；HBM使首个新token提前1.099886ms，但62个WF的WCT总和增加3.402435834s，单个非目标WF增加3.411234922s。这些差值由当前 v2 summary直接复算，未使用旧版数值替代。两文件SHA分别为 `f88e7cdc151e752c732a51dd15c6e8456fcde997ab416fa62fcb21b28d6856f6`、`72af2210fce0bd35255ad5cf51d5e75b238c8bd32ec22634144338081f0cc3dc`。此例反驳无条件全局收益解释，不反驳固定调度、孤立分支分析中的局部公式。

**保留更强主张所需验证。** 若要宣称联合选择收益或最优性，需要明确故障集合、实际不同大小副本及目标函数；可在小规模有限预算DAG上与精确集合枚举/联合边际选择对照，并给出所宣称最优性的数学条件。现有 shared-host 结果展示相互作用，post-hoc单关键支路展示条件收益，但二者均未验证联合选择优化。

## 3. O2/恢复：撤去异步 checkpoint 的 tail≤Z 保证

**当前位置与短原句。** `system_design.tex:272–278`：

> “the KV of the at most $Z$ accepted tokens after it”
>
> “With $Z=256$, the rebuild is one short prefill”

同一上界还出现在图注`:289`、恢复正文`:369–370`和`:380–382`，不能只改一处。

**建议替换的完整英文句子。** 替换272–278行关于tail上界/固定重建长度的句子：

```tex
After a failure, the retry target restores the latest committed
checkpoint and rebuilds the accepted tokens beyond its frontier.
The interval $Z$ controls checkpoint generation granularity, but
asynchronous publication can leave more than $Z$ accepted tokens
uncommitted when copying falls behind.
Reducing $Z$ changes checkpoint frequency and may also change compute
partitioning; the actual replay length depends on the committed frontier
at failure.
```

`:289`将完整图注末句改为：

```tex
The accepted tokens beyond the latest committed checkpoint are rebuilt
during recovery.
```

`:369–370`改为：

```tex
During recovery, the engine rebuilds the uncommitted tail layer by
layer, and sparse attention selects blocks for those tokens as usual.
```

`:380–382`按下一项整体替换，避免残留同一上界。若未来应用这些建议，对应中文注释也需要同步；本报告未修改它们。

**现有证据及版本边界。** 历史 `benchmark/AegisKV/experiments/current-design-20260923/FINDINGS.md:19–23` 明确记录6,247 accepted、CP1,024，差5,223>Z256；这是 pre-freeze linear-cost 反例，不能称修正版483点中的结果。当前 `structural-campaign-v2-main/recovery-events.csv` 的72条有保护 active恢复中，最大该差值为256、没有超界；这个有限参数范围内未触发超界不构成一般证明。当前runtime仍在异步传输完成后发布CP，没有强制将接受进度限制在已提交frontier后Z以内的背压约束。

**若坚持上界。** 需要在实现/模型中加入并证明对应的提交背压或吞吐/并发条件，且重新评估其正常执行成本；不能靠降低复制压力、删去旧反例或仅补现有结果表来证明上界。当前最小修复是撤去保证，保留异步 checkpoint 机制。

## 4. O2：将 Top-K 及深度式改为预算/时序近似，撤去“小 miss 即消除等待”的一般结论

**当前位置与短原句。** `system_design.tex:314–316`：

> “Master removes both by placing ... the Top-$K$ blocks”

`:380–382`：

> “Misses are few, because Top-$K$ sets cover most accesses”

`:431–439`由前L层在HBM推导无等待式；`:447–450`称实际并发恢复的有效B已离线测量。当前主实验用配置带宽和operator profile，前L层也仅部分驻留。`motivation.tex:125` 已正确说明 retrospective concentration不保证future accuracy，无需将其改成更强句子。

**建议替换的完整英文句子。** 替换314–316行的保证式描述：

```tex
Master attempts to reduce these exposed transfers by placing the
Top-$K$ blocks of each of the first $L$ layers in Peer HBM.
Selected blocks outside that replica can still cause transfer stalls.
```

替换331–332行关于K的实证选择口径：

```tex
We fix $K$ before evaluation and report held-out coverage separately,
without assuming a guaranteed hit rate.
```

替换380–382行：

```tex
The frequency and volume of misses depend on the native selector,
checkpoint state, and placement budget; historical access concentration
does not ensure that misses are rare.
Misses become known when their queries select blocks and can delay
recovery if transfers cannot be hidden by available computation.
```

在深度式之前明确假设，用以下完整句子替换431–434行的无条件时序叙述，公式作为该参考调度下的关系保留：

```tex
For an idealized reference schedule, assume uniform layer times,
complete residency of the first $L$ layers' recovery demand, and
sufficiently early release of all later transfers.
Under these assumptions, no layer waits when
$(\ell-L)h\le(\ell-1)r$ for every $\ell\le N$.
```

替换439行并收窄447–450行的校准口径：

```tex
This reference relation is a depth-selection approximation, not a
no-wait guarantee for partial Top-$K$ residency or query-dependent misses.
Our simulations set $L$ using configured effective bandwidth and
training-context operator estimates; these inputs are not a measurement
of bandwidth obtained by concurrent recoveries on a serving system.
```

**现有证据。** `reviews/native-topk-operating-point/operating-point-coverage.csv`、`RESULTS.md` 对K16/L4给出 NOSA/NSA/MiniCPM Current query-block event coverage为15.6970/11.4575/5.3652%；其distinct coverage为8.3133/4.1987/4.0564%。这些不是物理miss率，但不能支持该预算下“覆盖多数访问”。`structural-campaign-v2-main/PAPER_NUMBERS_V2.md` 明确long-decode两个人工四块bank均可装入K16；`formal-core-v2-corrected/PRIORS.json`及配置是dense Qwen3、L11/L1，与native L4模型不同。当前恢复按实际缺块获取，说明正确性可独立于低miss假设；它不证明深度式消除实际等待。

**保留正向O2所需验证。** 需要实际native因果query需求与有辨识力的不足预算、逐层计算/传输时序、metadata及checkpoint lag、相同故障/预算的DRAM基线相结合，检验暴露等待与WCT；若仍要求无等待保证，另需证明传输释放与第一L层驻留假设。可以另行设计模拟，但当前483点未完成这个联合验证。改变图注或把offline coverage折算成WCT不能替代它。

## 5. O3：保留安全配额机制，将动态前台压力下的正收益标为尚未验证

**当前位置与短原句。** `system_design.tex:536–539`：

> “O3 shows that the HBM that foreground serving can spare changes with load”

`:553–558`描述pressure触发乘法缩减及稳定窗口增长。这些算法步骤可以保留；问题是把已实现/账本安全读成已经验证动态前台压力下的系统贡献，当前执行模型并未提供该证据。

**建议替换的完整英文句子。** 替换536–539行的引入，保留后面的capacity公式：

```tex
To accommodate potentially changing foreground memory demand, Adapter
maintains a bounded Peer-HBM replica quota for each takeover rank.
Master admits each replica only when its KV and metadata footprint fits
the available quota.
```

在553–558行的算法描述后加入以下限定句；它不改变AIMD机制：

```tex
The evaluation checks allocation safety but does not establish a WCT
advantage from quota adaptation under load-varying batch memory pressure.
```

**现有证据。** 当前主实验FCFS每worker仅一个active invocation，见 `python/moonkvsim/aegiskv/current/runtime.py` admission路径与 `formal-core-v2-corrected/runs/*/config.json`。修正版两个保留详细日志的 `Qwen3-8B-load0.65-aegiskv-F1-2/events.jsonl.gz`、`Qwen3-32B-load0.65-aegiskv-F1-2/events.jsonl.gz` 中，8B仅4条增长、0缩减/0 pressure（最大quota192MiB），32B没有quota变化/pressure（初始128MiB）。这些范围只针对这两条详细run，不外推为483条所有quota事件计数。静态/full的最终同ID WCT比较应以修正版180点最终审计为准；无论数值是否完全相同，当前模型都未验证continuous-batch前台内存压力下的收益。账本审计支持容量安全，不等于证明调节优于固定quota。

**保留正向O3所需验证。** 需要能产生并记录前台内存压力的负载/执行模型，固定相同请求与故障，比较固定quota与动态quota的正常WCT、准入停顿、HBM容量/字节时间及故障收益；必须保留固定quota更好或无差异的情况。可以是明确声明的模拟干预，不必冒充新GPU测量，但它超出现有483点。若当前不增加该模型，最小修复是把O3限为已实现、安全性检查通过而收益未验证的机制。

---

**封存说明：** 上述五项是未应用的审阅提案，不是补丁。它们将三个中心问题拆成可单独审阅的文本更正。所有英文替换句仅存在于本文件，冻结前文及实验结果未改变；未宣称新增验证或已解决评审意见。本文件完成后停止修改，后续若用户允许修订前文，应另行记录具体采纳项与新的稿件版本。
