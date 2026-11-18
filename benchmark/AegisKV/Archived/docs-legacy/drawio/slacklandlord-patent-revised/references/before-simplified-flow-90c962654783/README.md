# SlackLandlord：一个 Agent 的请求如何决定一个 KV 块

[完整 Draw.io：布局页 + 流程页](algorithm-2-patent-revised.drawio) · [完整 PDF](algorithm-2-patent-revised.drawio.pdf)

[单页流程 Draw.io](algorithm-2-rental-management.drawio) · [单页 PDF](algorithm-2-rental-management.drawio.pdf) · [PNG](algorithm-2-rental-management.drawio.png) · [逻辑与布局审查](SEMANTIC_AUDIT.md)

本图以**当前 Agent a 的一次请求访问一个完整 KV chunk x**为入口。该请求每新生成或实际复用一个完整块，就执行一次流程。每个 Agent 独立估值、独立续租；物理共享块仅在汇总剩余 Credit 时合并各份额。

第一页保留原 KV/Pool 布局。第二页是一张完整决策图：中央为逐块主流程，左下为容量竞争循环，右侧为 KV 布局和处理结果。符号在开头，判断框都有明确出口。

## 按图中的步骤阅读

| 步骤 | 操作与结果 |
|---|---|
| ① 当前请求访问 x | 使用 Agent a 本请求的 Slack；本轮 Slack 不变。仅出现一个新请求，不会为它未访问的块续租 |
| ② 读取状态 | 读取 x 的物理状态、各 Agent 余额及 a 的续租请求号；没有副本则使用空分账 |
| 操作未完成？ | x 正在备份或释放时暂存事件；操作完成后重新读取，不重复分配 |
| 本请求已处理或过期？ | 是则保留所有余额并结束；否则继续 |
| ③ 计算收益 | 只计算当前 a 的 G_a,x，不遍历其他 Agent 的收益 |
| ④ 授信或续租 | 只将 a 的份额设为本次 G_a,x；其他份额保留已扣租的余额 |
| ⑤ 汇总 Credit | 汇总所有已登记份额；此时改动仍在临时记录中 |
| 已有副本？ | 是则保存 a 的份额与处理记录，结束；内部块、读取中的块同样可续租 |
| 必要前缀与源就绪？ | 缺失时丢弃临时分账，先处理前缀或等待源；不越过缺口备份后续块 |
| ⑥ 检查容量 | 有空位则准备提交；空间不足进入左侧收租循环 |
| 提交条件仍有效？ | 核验状态、请求版本、读保护和容量；不通过则丢弃未执行试算，返回② |
| ⑦ 执行备份 | 登记本次操作，提交扣租，释放选出的尾块，确认空间后分配与复制 |
| 执行是否成功？ | 释放、分配、复制均成功才进入⑧；失败清理本次未完成分配，按实际已执行状态处理 |
| ⑧ 发布 | 发布当前代次的完整副本、竞争后的余额和 a 的处理记录；其他 Agent 的等候事件随后各自处理 |

## 收益和 Credit

\[
G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}.
\]

T_a(k_a) 使用 x 之前的备份前缀，T_a(k_a+1) 使用包含 x 的前缀；剩余已生成 KV 重算。新生成的 x 之后不假设未知 KV。复用快于对应重算的模型假设使两者的时间差非负。

G_a,x 是**单独考虑 a 时，备份 x 减少的 Slack 外恢复延迟**，单位为时间。内部块复用也按“前缀到 x 之前 / 到 x”为止估值，估值时暂不使用其后备份，实际物理前缀不被挖空。这样为内部块授信，不等于准许删除内部块。

每次有效授信或续租：

\[
c_{a,x}\leftarrow G_{a,x},\qquad
\mathrm{Credit}_x\leftarrow\sum_a c_{a,x}.
\]

这里 c_a,x 是剩余信用，Credit_x 是物理块各份额的总余额。**A 的新请求只刷新 A；B 没有新请求实际访问 x，就不重算或续租 B。** “不续租”不表示免租：容量竞争仍会从各份额扣除相应租金。

没有物理副本时，从空分账开始，先只有当前 a 的初始信用；不因元数据中存在 B 的历史引用而给 B 自动授信。B 后续实际访问已备份 x 时，再按自己的请求、Slack 和收益获得份额。多个 Agent 都需要该块时，按各自真实事件逐次更新，不预付未来请求的信用。

同一“副本代次、Agent、请求号”只授信一次。首次复制也记录本请求已处理，重复命中不再补满。过期请求不能覆盖新请求的 Slack 或余额。未提交的提案不能留下“本请求已处理”的标记，否则同请求重试会被错误跳过。

## 容量竞争循环

| 符号 | 含义、单位 |
|---|---|
| b_x | x 的物理字节数，共享块只占一份 |
| Q | 当前可释放的物理尾块 |
| Y | 本次临时试算已选出的回收块 |
| f | 本次试算可用字节 |
| δ | 本次每字节租金，时间/字节 |

先令 Y=∅，f 等于 Pool 空闲字节。必要前缀必须受保护。

1. 若 f≥b_x，进入提交前核验。没有淘汰时允许新块 Credit=0。
2. 否则更新 Q：无备份后继、未被读取的已提交块。排除候选必要前缀、其他备份的操作保护块、释放中的块；正在复制的后继也不能失去必要前缀。
3. Q 为空或 Credit_x=0 时拒绝候选，丢弃整个试算。
4. 候选 x 与 Q 中的块一起支付租金：
   
   \[
   \delta=\min\left\{\frac{\mathrm{Credit}_x}{b_x},
   \min_{y\in Q}\frac{\mathrm{Credit}_y}{b_y}\right\}.
   \]
   
   对 y∈Q∪{x}，各 Agent 按扣租前余额比例分摊：
   
   \[
   c_{a,y}\leftarrow c_{a,y}
   \left(1-\frac{b_y\delta}{\mathrm{Credit}_y}\right),\qquad
   \mathrm{Credit}_y\leftarrow\sum_a c_{a,y}.
   \]
   
   每个物理块只支付一份 b_y δ。零余额跳过除法；各份额更新使用同一个扣租前分母。
5. **先检查候选**。候选归零或与旧块同时归零，均拒绝候选，已有副本和余额不变。
6. 候选仍有信用时，选择一个 Credit=0 的旧尾块 y，令 Y←Y∪{y}、f←f+b_y。同值按稳定物理块 ID 选择，返回空间判断。前驱成为可释放尾块后才参加下一轮收租。

此策略按剩余信用竞争，不另算跨 Agent 联合 WCT 删除损失。内部块不参加尾块收租，保留余额；备份布局始终满足连续前缀约束。

## 提交边界

本图将 Pool 元数据处理序列化，并要求提交前核验输入与物理状态仍有效。锁不会因等待异步复制结果而阻塞所有后续请求：进行中的操作登记在目录中，相关块保留必要保护；新的相关事件进入等待路径。

- 未执行的试算失败：不扣实际信用，不释放实际块，不保存候选的请求标记。
- 开始执行计划后：实际扣租、释放与分配按执行结果保留；已经释放的备份不能回滚成“仍存在”。
- 发布前：只接受匹配副本代次的操作确认；未成功不发布。释放或分配失败也走失败处理，无需等待一个不会发生的复制成功事件。
- 发布时：保存竞争后的剩余 Credit，不重新按 G 补满；否则会退还新块在竞争中支付的租金。
- 并发到达的 Agent 事件：先等待进行中的操作，结束后重新读取，再各自估值、续租。不能重放一份旧的全体 Agent 账本覆盖后来余额。

这些是设计约束；并发释放/复制协议尚未由本轮运行代码验证。

## 合理性与适用范围

在本图约定的完整块事件、有效请求、可用恢复成本和前缀约束下，流程覆盖了一个 KV 事件的续租、新副本准入、等待、拒绝、重试和发布结果。不会因为 A 的新请求把 B 已花掉的信用重新加入，也不会在失败试算后错误扣除实际余额。

Credit 是独立 Agent 收益形成的可累加租金优先级，**不等于多个 Agent 同时恢复时的精确 workflow WCT 改善**。本图不读取 workflow ID 或判断串并行关系。

逐事件准入不积攒被拒绝候选的信用，也不保证利用尚未处理的其他 Agent 需求得到全局最优结果。连续失败的试算不扣真实租金，因此没有无访问块必然到期的保证。没有 Agent 结束事件，历史引用也不等于未来一定会访问。

本轮没有修改 MoonKVSim/Mooncake 的运行算法或专利原文；设计算术审查不是实机时延、性能或并发协议验证。

## 检查与复现

- [DESIGN_CHECKS.json](DESIGN_CHECKS.json)：27 个执行节点、30 条控制连线、全部判断出口、先估值再续租再汇总、布局与源文件检查。
- [SEMANTIC_AUDIT.json](SEMANTIC_AUDIT.json)：16 组事件/算术检查，包含 2040 个单 Agent Slack 恒等式组合；数值仅用于设计核对。
- [COMPATIBILITY.json](COMPATIBILITY.json)：mxGraph 实际解码、编辑保存重开，以及旧 setId 错误的负向检查。
- [MANIFEST.json](MANIFEST.json)：原生导出文件哈希及实际 PNG/PDF 查看记录。
- [修订前快照](references/before-agent-event-flow-476918a9d2cd/ARCHIVE.json)：原样保留用户编辑的源及配套文件；更早历史在 references 中。

```bash
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/build_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/audit_semantics.py
NODE_PATH=/tmp/codex-slacklandlord-drawio-compat/node_modules \
  node benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_compatibility.cjs
```

流程图用于独立缩放阅读。本轮检查的是完整原生导出及关键区域，没有将这张详细图按论文单栏尺寸排版。手动编辑源文件后，应先将改动纳入生成器，再重新生成。
