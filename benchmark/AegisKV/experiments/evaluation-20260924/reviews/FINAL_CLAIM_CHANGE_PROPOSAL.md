# Final claim change proposal — NOT APPLIED

**状态：未应用，供用户审批具体前文修改范围。** Claude 最终复审结论为 **NOT READY**；本文件不改写该结论。这里只提出文本及相邻中文注释的最小修订，不修改论文、PDF、图、运行代码、数据、原评审记录或原提案，不新增实验。Disclosure、完成483点或通过账本审计均不等于已经验证中心贡献。

## 审阅对象与版本绑定

- 最终评审：`FINAL_OPUS55.md`，SHA256 `f5c57c7d709553748d8b66917b3c2a6ee16921bdee81b2500ad4175e5344ee3c`。
- 评审调用：`FINAL_REVIEW_INVOCATION.json`，SHA256 `f23f5a09b1e41a587c294527a9a34e2ffa2a65cb44183d43866ded2bc8cbfe64`。原输入归档为 `final-reviewed-v2-inputs/`，其 `ARCHIVE_MANIFEST.json` SHA256 `4c53e8b4db5b26d095655f77496781825afc6638c6ff737d5d31ea9d5da9c83f`。
- 保留不变的早期提案：`PROPOSED_CLAIM_CORRECTIONS.md`，SHA256 `e60cbc98f7552ae278516d1f4b3815b7afc60c4d1cd7d74d56eeb84630d58b0f`。下文1–5沿用其具体建议，并补齐中文注释与遗漏的第二个tail上界图注；6–7为最终复审新增项。
- 前文行号对应 `benchmark/AegisKV/paper/system_design.tex` SHA256 `cfb92dcfc6c40c7d3a5c996d1628cc94318af863b74b7f04b6546a714fa5fff3`，以及 `motivation.tex` SHA256 `e0fc57e28db8956485917c3484c5a9f9e172960dbd1f75be206247e3217e0419`；与归档字节核对一致。Motivation第125行包含多个段落，因此同时提供短原句。
- 相对实验路径以 `benchmark/AegisKV/experiments/evaluation-20260924/` 为根；代码路径以仓库为根。对“已评估实现”的描述指已封存483点的源码，后续live改进不得追溯重标这些结果。

**建议审批范围：** 只批准以下七项的指定英文段落/公式解释/图注及相邻中文注释；保留算法定义、反例、null结果和证据来源。并非批准新的实现、补跑或新增贡献。1–5撤去不成立的无条件保证；6条件化正常开销；7区分Tracker目标与已评估proxy。若用户希望保留更强正向主张，需另行审批并完成相应模型/实验/证明，不能通过措辞替代。

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

**中文注释同步范围（若获准应用）：** `system_design.tex:225–226, 237–241`；将“最多增加λ”改为“估计暴露的候选阈值，仍受容量约束”。

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

**中文注释同步范围（若获准应用）：** `system_design.tex:472–475`；明确局部分数、metadata占用可变、无联合最优保证。`motivation.tex:125`仅替换已定位的英文决策单元句，不删共同故障非加性的观察。

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

`:289`保留此前的CP和Top-K说明，将其尾部上界子句改为下面的独立句：

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

**补齐最终复审指出的另一处图注：** `system_design.tex:406–407`的第二句仍写 “tail of at most $Z$ tokens”，建议该完整句子改为 `Each dark segment rebuilds one layer of the uncommitted tail.`。**中文同步范围：** `system_design.tex:262–267, 365–368`，并检查`:280, 401–402`的图示注释是否含上界暗示；英文caption`:289, 407`须同时一致。本次不修改或重绘图文件。

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

**中文注释同步范围（若获准应用）：** `system_design.tex:302–307, 320–324, 365–368, 424–427, 441–443`。对应概念图应被理解为声明假设下的示意，不能以修改文字宣称已验证实际无等待。

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

**中文注释同步范围（若获准应用）：** `system_design.tex:532–535, 550–552`。算法机制可保留；“应对可变前台需求”的目的不能写成现有实验证明其收益。最终180点已完成，修正版primary审计支持Static-HBM/full所有WF WCT相同；引用最终审核包而非重新解释旧版结果。

## 6. 正常开销：区分“未产生副本流量”与“没有成本”，撤去未经校准的 pays little

**当前位置与短原句。** `system_design.tex:522–527`：

> “Normal execution pays little”
>
> “Unprotected Agents incur no cost.”

checkpoint、metadata、计数/排序、控制面和共享链路都可能有成本。未被保护不意味着不受其他Agent副本流量的影响。主矩阵健康WCT相同是在未建模CPU控制成本、DMA slowdown设为零的执行模型下观察到的结果，不能推广为实机零开销。

**建议替换的完整英文句子。** 用以下段落替换522–527行；保留具体counter、checkpoint与HBM更新机制，去掉一概很小/零成本的判断：

```tex
Normal execution performs access counting for protected Agents,
checkpoint transfers, and updates to the Peer-HBM placement.
Agents that never receive protection generate no backup-copy traffic,
but prediction, tracking, and interference from other Agents' copies
can still affect their execution.
At checkpoint boundaries, Connectors transfer newly accepted KV and
metadata to Peer DRAM, and Master updates the selected HBM blocks;
hysteresis suppresses near-tied replacements.
The resulting overhead depends on transfer volume, control-plane work,
and compute--DMA interference, and is not assumed to be small.
Our simulations account for modeled transfer traffic and include an
uncalibrated DMA-interference sensitivity study; they do not measure
physical normal-service overhead.
```

**中文注释同步范围（若获准应用）：** `system_design.tex:518–521`。删除“未受保护的Agent没有开销”和“只有counter”等绝对判断；区分不产生自己的备份流量与可能受共享资源竞争影响。不能将模拟字节数写成GPU实测成本。

**现有证据。** `reviews/o1-dma-corrected-v2-audit/dma-scenarios.csv` 中 AegisKV 的四WF-sum端点：系数0.05/0.1使健康mean WCT增加3.327619%/6.655237%；即使在该固定F1中，cohort总WCT仍比Restart多0.386723420/0.738928148s。相同目标下的break-even概率为1.528948/1.493687，不在[0,1]。target-only端点的不同结论另列，不能混用；这些系数和Bernoulli mixture不是物理校准或真实故障率。来源审计为同目录`AUDIT.json`、`FINAL_VALIDATION.json`及`PAPER_O1_NUMBERS_V2.md`。

**若保留正向低开销主张。** 至少需预定义正常流量/字节时间/前台延迟目标及影响模型的适用范围，并显示收益能够补偿同目标的健康成本；“physical low overhead”还需要目标硬件上的干扰与控制开销证据。现有对照可支撑有条件的成本曲线和负结果，不能证明普遍pays little。不得通过只选target-only的较低break-even掩盖cohort的不利结论。

## 7. Predictor：区分 Agent-task wall-time 目标、已审 service proxy 与尚未完成的新实现

**当前位置与短原句。** `system_design.tex:59–62`：

> “Tracker predicts how long the Agent will take to finish its task”

`:68–75`将文本编码器/回归器写成已采用的方法；`:78–80`：

> “duration from submission of invocation $r$ to completion of Agent $a$'s task”

`:119`还将guard描述为 “a calibrated upper quantile of slack overestimation”。该墙钟目标包含当前排队、后续调用和调用间间隔，而已审483点的primary predictor只估计当前调用profile service work，并使用训练role-output先验；guard来自训练decode-duration绝对残差，不是held-out Slack高估校准。

**建议替换的完整英文句子。** 保留Tracker的接口、历史身份和残余DAG定义。将59–80行改为以下“目标—已评估实现”分离段落，不把未来语义回归器写成已训练完成：

```tex
Tracker's intended target at invocation submission is the wall-clock
time until the Agent completes its task, including queue residence,
future invocations, and inter-invocation gaps.
A predictor for this target must use only features available at the
submission and must be trained and evaluated against corresponding
submission-to-task-completion labels.
The implementation used in the reviewed 483-run evaluation instead
uses a controlled proxy: current-invocation operator cost plus a
training-only role output-length prior.
It does not instantiate the proposed semantic encoder or a validated
predictor of whole-Agent wall time.
Subtracting time since submission from this service proxy can make the
estimate nonpositive during queueing and force zero Slack for the workflow.
Consequently, these results evaluate protection under that proxy, not
the accuracy of the intended task-level predictor.
```

将117–119行的符号解释改为以下完整句子，保留pred/succ定义：

```tex
Here $\operatorname{pred}(a)$ and $\operatorname{succ}(a)$ denote
residual predecessors and successors.
The evaluated guard $g_a$ is the training 90th percentile of absolute
decode-duration residuals; it is not a calibrated bound on task-level
slack overestimation.
```

**中文注释同步范围（若获准应用）：** `system_design.tex:57–58, 64–67, 77, 82–84, 106–110`。其中82–84行的先验/时间戳机制可以保留，但应明确训练label实际是什么；106–110行不能继续把当前guard写成已校准的Slack高估分位数。若未来引入了新的target/guard，应按新版本证据重新填写，不沿用本提案的旧proxy描述去概括新版本。

**现有证据。** 已审源 `formal-core-v2-corrected/source_snapshot/python/moonkvsim/aegiskv/evaluation_campaign.py:64–89` 定义 `CausalLengthPredictor` 并明确只估计service；`:92–124`训练role先验并用decode-duration绝对残差设guard。`reviews/o1-dma-corrected-v2-audit/PAPER_O1_NUMBERS_V2.md:20–24` 的两个详细F1给出3,122/5,586和3,605/6,518个unfinished-workflow/control-window fallback观察，全由prediction-minus-age≤0触发；该分母不是wall-time占比，也不覆盖所有负载。服务proxy的null不等于否定所有任务级预测器，同样不能称已验证Design predictor。

**进行中工作与审批边界。** 根据主代理通知，另一个代理正在实现training-only wall-time labels。**本报告未把实现、训练、held-out评估或重跑视为完成，也未验证其结果。** 12个训练workflow上的健康submission-to-completion标签能够修正single-invocation目标中的queue遗漏，但本身不验证多调用未来时长、真实tool/think gaps或semantic encoder。未来只有在新源版本/训练标签来源封存、因果特征和训练/评估隔离核对、held-out误差及同ID策略端点评估后，才能为新版本提出另一份措辞；旧483点仍保留proxy身份。不得将policy-dependent评估结局反向作本轮在线预测标签。

## 对最终复审“最小 remedy”的保留意见

接受NOT READY及需补辨识性的核心判断，不等于逐条建议可未经设计直接执行。以下保留意见不改变原评审记录，也不取消负结果。

1. **不能将native访问记录套dense Qwen timing后称为native系统验证。** `FINAL_OPUS55.md`的O2 remedy建议经`demand_provider`重放native记录；hook支持输入不代表计时/模型身份匹配。NOSA/NSA/MiniCPM记录来自不同模型和forward路径；Qwen3 HYBRID grid是dense算子估计。二者拼接最多构成明确标注的混合机制诊断，不能称该native模型的恢复WCT。先核对层数、KV/head几何、因果query域、CP/metadata前沿和trace覆盖，再声明计算模型及误差/敏感性；若要声称native性能，需与相应模型/稀疏执行匹配的时序依据。`native-topk-warm/README.md`、`PROTOCOL.json`及各模型source绑定支持访问证据，不自动提供完整恢复时延模型。
2. **时间推断DAG不等于Design要求的已知固定任务DAG。** `system_design.tex:39–43, 96–104`要求已知Agent任务依赖；`inputs/README.md`与`weka-episode-audit.json`记录Weka只有64-token hashes、跨Agent边为时间推断，509个episode调用重叠、333个跨model。可以研究真实单Agent历史/gap或明确标成推断拓扑的敏感性，不能静默序列化、将相邻时间当结果消费边、替换tokenizer或称为ground-truth known-DAG replay。FanOutQA也应继续称constructed evidence-provided输入，而不是泛称“natural workload”。98,304 profile覆盖不授权将超过40,960的Qwen上下文当native支持；扩展context应另标shape/intervention及质量未验证。
3. **oracle-Slack不是自动成立的WCT上界。** 使用未来完成时间的版本须标为noncausal diagnostic；完美时长信息不使逐Agent贪心选择成为联合最优。只有同目标的可行策略集合、联合选择以及调度/未来状态依赖被明确定义后，才可证明性能上界。不能把一次oracle数值直接称系统可达上限，也不能把policy自己的未来故障结局偷偷注入普通预测器。
4. **固定retry worker是归因对照，不应先验叫实现纠错。** 现有checkpoint holder/routing是策略机制的一部分；更改它可检验路由敏感性，但需固定可行peer、host反亲和与真实状态传输成本，另存新版本。不能为了让WCT更“平滑”删掉已有反例或将控制结果代替原政策结果。同样，确定性调度对1ms扰动的响应是模型敏感性，不是测量噪声；增加20个构造seed不自动产生总体置信区间。

## 可审批范围与未完成事项

用户若批准，最小文本修改范围为上述七项指定前文位置、相邻中文注释和两个tail图注，保留Equation定义而收窄其适用条件。**该批准不应被解释为授权新增模型、实验矩阵、物理测试、推断trace改造或论文已达到投稿标准。** 若用户继续冻结前文，则这些矛盾仍未修复，最终NOT READY意见保持有效。

本文件完成后冻结；原 `PROPOSED_CLAIM_CORRECTIONS.md`、`FINAL_OPUS55.md`、review invocation、归档输入、论文及数据均保持原字节。后续任何采纳/改进应记录新的稿件或实验版本，不覆盖本提案或旧证据。
