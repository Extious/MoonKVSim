# SlackLandlord：新 chunk 准入与 Cache hit 续租

[完整可编辑源图](algorithm-2-patent-revised.drawio) · [三页 PDF](algorithm-2-patent-revised.drawio.pdf)

| 页 | 内容 | 独立文件 |
|---|---|---|
| 1 | 保留用户已有的 Agent 生命周期、共享 KV 与容量示意 | [PDF](algorithm-2-patent-revised-agents.drawio.pdf) |
| 2 | 新 chunk 的完整准入、共享分账、Lazy Refresh、收租与 Credit 初始化 | [Draw.io](algorithm-2-admission.drawio) · [PDF](algorithm-2-admission.drawio.pdf) · [PNG](algorithm-2-admission.drawio.png) |
| 3 | Cache hit 的引用登记、延迟刷新、同轮去重与续租 | [Draw.io](algorithm-2-cache-hit.drawio) · [PDF](algorithm-2-cache-hit.drawio.pdf) · [PNG](algorithm-2-cache-hit.drawio.png) |

两张决策图均使用黑线、白底、开头符号说明。共享分账、信用计算与 Lazy Refresh 都放在连线连接的执行框内；独立侧栏只画 KV 引用与 Pool 位置。统一使用 Q，不增加 Q_r。

## 本次重新审查：恢复范围与提交语义

旧图把新 chunk、回收尾块、Cache hit 都写为带独立 `n_a` 的通用恢复式，未把每条路径的已知工作量讲清楚。当前两页去掉该符号，直接使用从当前元数据与代价表得到的两个量：

- `t_a^reuse(j)`：加载并使用前 j 个连续备份块的时间。
- `t_a^recompute(j)`：在前 j 块可用后，重算本次已经存在的其余 KV 的时间。包含后续重算对前缀的依赖，不是只计算单个候选块的重算耗时。

新块 x 刚生成时，x 就是产生它的 Agent 当前已有末尾，`t_a^recompute(k_a+1)=0`。如果处理的是补备份、旧尾块或 Cache hit，该块之后可能已经存在 KV，这部分重算代价必须保留。共享块对每个引用 Agent 分别读取其当前已有工作量；尚未生成的未来 KV 不进入代价表。**删除长度符号不等于删除实际已经存在的后缀。**

两页的统一递推是：

$$
T_a(k_a)=\min_{0\le j\le k_a}\{t_a^{\rm reuse}(j)+t_a^{\rm recompute}(j)\},
$$

$$
T_a(k_a+1)=\min\{T_a(k_a),\;t_a^{\rm reuse}(k_a+1)+t_a^{\rm recompute}(k_a+1)\}.
$$

新生成块没有后缀时，第二式自然简化为 `min(T_a(k_a), t_a^reuse(k_a+1))`。旧块后面的已生成 KV 不能套用这一零后缀简化。复制完成后重新授信也读取当前已有工作量，因为复制期间可能已经生成后续块。

| 重新审查的问题 | 当前图中的修正 |
|---|---|
| 用 `n_a` 混写不同事件，容易被理解为需要知道未来长度 | 两页明确当前已知重算范围，新生成块末尾重算为 0，旧块保留已生成后缀 |
| “Slack 简式适用”没有明确的执行判据 | 所有路径使用同一 WCT 分账；单 Agent Slack 式只展示等价特例，不额外累加 |
| 在构造共享恢复状态之前就执行 WCT 计算 | 先构造各组恢复时间，再按 DAG 拓扑顺序计算每组 WCT，最后分账 |
| 临时计算框提前写“已兑现轮号”容易误实现成真实续租 | 余额和轮号先写临时账本，版本核验通过后才原子提交；重试不消耗真实续租资格 |

一次回收试算保持同一组已知工作量和输入版本，只有临时备份前缀随试删变化。相关工作流的前缀向量改变时，重新计算条件损失；版本改变时丢弃该计划重试。这样才能将逐次损失累加为 D_Y。新请求、普通版本刷新、物理收租三个触发条件仍分别处理。

## 新 chunk 流程

主流程按已知 KV 计算恢复时间，再统一构造各 Agent 的恢复状态、计算工作流 WCT，并按固定 Agent 顺序分账得到 W_{a,x}。单 Agent 的 Slack 式作为同一计算的等价特例保留，不再设置“简式是否适用”的实现分支。按 P_{a,x}=W_{a,x}/b_x 计算密度，G_x=Σ_a W_{a,x} 只汇总一次用于准入。

容量不足时，左侧是实际回收分支：建立 Q，逐个核对全部尾块的版本；版本未变时跳过收益重算，否则重新计算 W、兑现尚未处理的新轮并限制其他余额。全部尾块检查完毕后才计算 δ、按余额比例分摊物理租金，并且只推进一次 L。试删一个归零尾块，按当前临时前缀计算损失，更新 Q 后重新检查容量。

准入条件保留用户确认的两种情况：Y 为空时 G_x≥0；Y 非空时 G_x>D_Y。临时计划中的 x 只用于估计替换后的恢复前缀，不提前占用真实容量。失败计划不改真实账本或备份；成功计划等待释放 ACK 后再分配与复制。发布前根据实际前缀计算授信，并原子核验版本。

## Cache hit 流程

新请求仅更新该 Agent 的当前轮号和输入，不遍历全部 KV。处理命中的 x 时先核对本 Pool 是否已有可恢复副本；没有时，从首个未备份的完整块开始执行第 2 页。已有副本则登记逻辑引用，实际读取期间固定该物理分配。

- **内部块或仍在读取的块**：保留剩余信用与已兑现轮号，等待其成为可释放尾块。这是延迟计算收益、兑现续租的路径。
- **可释放尾块且版本未变化**：保留现有余额，同轮重复命中不补信用。
- **需要刷新**：重新计算全部有效引用的 WCT 分账。只有首次授信或尚未兑现的新轮才能获得该 Agent 的新额度；本轮已经兑现的份额只保留或下调。

A 续租不会补回 B 已支付的信用。同一 Agent 同一轮解除引用后再引用，也不能重新获得首次授信，因此已兑现轮号需要保留到该生命周期结束。结束后重新创建 Agent 必须使用新的生命周期身份。

**本次明确了 Cache hit 可触发当前安全尾块的按需刷新**；内部块继续延迟到尾块竞争。这扩展了此前只在收租前兑现的触发点。多个尚未兑现的请求可合并为最新轮号，不能把每次命中或每轮授信累加。

## 必要的实现约束

Q 中的可释放性按物理块检查：已提交、无备份后继、未固定读取、不属于本次候选的保护前缀。共享块的所有依赖均须检查。内部块和固定读取块保存余额，退出尾块收租；重新暴露时先刷新再比较。

收益缓存的版本覆盖 Agent 轮号、引用集合、已有 KV 数、恢复代价、工作流 DAG 和相关工作流全部恢复前缀。仅检查某个 Agent 的 Slack，或者只检查旧堆顶，都不足以决定是否可以跳过重算。

计算期间若租金推进，旧余额也可能过期。因此两条流程都在发布前核验租金账本版本；并发实现需以原子提交或锁保护轮号、余额、L、容量和分配代次。图中“重试”“等待”框分别由重新调度与相应完成事件继续，不代表忙等。

当算法 3 缩小容量时，由容量回收路径暂停新准入并回收；正在复制或释放的分配仍计入占用。该控制路径不在本次两类事件图中展开。物理复制失败时，已经释放的旧备份不能当作已回滚。

## 检查与边界

这是设计图，未修改专利原文或 Mooncake / MoonKVSim 运行代码。[DESIGN_CHECKS.json](DESIGN_CHECKS.json) 检查执行节点连通、公式、分支、符号及第一页保留，并运行 8 项已有 CPU 精确信用核算检查，包括共享不重复计价、单 Agent 续租、同轮去重、前缀余额保留与试算回滚。

另用两组精确算术核对“新块末尾”和“已有块带已生成后缀”的恢复时间，并检查 44 个单 Agent Slack 等价式条件。这些是公式与示意代价检查，不是实测时延。这些核算不代表新 Cache hit 事件流程或零收益准入已部署。[此前 CPU 参考设计](../../algorithm-2/AGENT_LEASE_DESIGN.md)仍采用严格准入与较早的事件接口。没有宣称全局最优、经典 Landlord 竞争比或实测性能收益。PDF 按独立设计图尺寸检查，未声称可直接缩印为论文单栏图。

[COMPATIBILITY.json](COMPATIBILITY.json) 使用 mxGraph 4.2.2 检查三页的解码、编辑、保存与重开；其中 `reproduced_error` 是针对历史危险 ID 的回归用例，并非当前源图报错。[MANIFEST.json](MANIFEST.json) 记录源文件和导出指纹。

```bash
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/build_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_decision_flows.py
```

手动修改原生源后，仅刷新完整导出使用 `build_diagram.py --export-only`。生成器检测到后续手动编辑会停止覆盖。此次改图前的 [上一版源图](references/before-online-review-8f438d425dc7-algorithm-2-patent-revised.drawio) 和更早的 [用户手动源图](references/user-edited-before-complete-flows-366963e6769e.drawio) 均已保存。
