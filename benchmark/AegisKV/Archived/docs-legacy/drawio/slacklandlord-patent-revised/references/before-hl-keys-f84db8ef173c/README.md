# SlackLandlord：一个 Agent 的请求如何决定一个 KV 块

[完整 Draw.io：布局页 + 流程页](algorithm-2-patent-revised.drawio) · [完整 PDF](algorithm-2-patent-revised.drawio.pdf)

[单页流程 Draw.io](algorithm-2-rental-management.drawio) · [单页 PDF](algorithm-2-rental-management.drawio.pdf) · [PNG](algorithm-2-rental-management.drawio.png) · [逻辑与布局审查](SEMANTIC_AUDIT.md)

本图以**当前 Agent a 的一次请求访问一个完整 KV chunk x**为入口。该请求每新生成或实际复用一个完整块，就执行一次流程。每个 Agent 独立估值、独立续租；物理共享块仅在汇总剩余 Credit 时合并各份额。

第一页保留原 KV/Pool 布局。第二页是一张完整决策图：中央为逐块主流程，左下为容量竞争循环，右侧为 KV 布局和处理结果。符号在开头，判断框都有明确出口。

## 简化后的六步主线

本次将 27 个执行节点整理为 19 个，页面高度从 4530 减至 3410；沿用原字号。收益、信用与准入策略保留，前缀检查提前，重复的状态读取和提交分支合并。

| 步骤 | 操作与结果 |
|---|---|
| ① 读取事件与状态 | 读取当前 Agent、请求、完整块及分账；没有副本则空分账 |
| 事件筛选 | 正在备份/释放则等待；否则，重复/过期事件结束，其余继续处理 |
| 新副本就绪检查 | 仅新副本需要完整可读源与已提交前缀；未就绪先等待，不计算收益 |
| ② 计算收益 | 只计算当前 Agent 的 G_a,x |
| ③ 更新 Credit | 先更新 a 的份额，再汇总共享 Credit；其他 Agent 保留租后余额 |
| 已有副本？ | 是则保存 a 的处理记录和信用，结束；内部块或读取中的块同样可续租 |
| ④ 新副本准入 | 保护前缀，初始化 Q、回收试算；空间不足时进入左侧收租循环 |
| ⑤ 核验并执行 | 冲突且尚未执行则丢弃试算返回①；执行失败按实际状态清理；全部成功才进入⑥ |
| ⑥ 发布 | 保存完整备份和竞争后的剩余信用，记录 a 本请求已授信；不重新补满 |

等待框合并“操作进行中”和“前缀/源未就绪”两种原因，满足各自就绪条件后均返回①。它表示由条件变化唤醒，不是不断执行空循环。

步骤⑤内部仍按“先检查状态、请求、保护和容量，后提交扣租与物理操作”的顺序执行。合并流程框没有删除核验，也没有允许执行后的物理释放被回滚。

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

先令 Y=∅，f 等于 Pool 空闲字节，按图例初始化 Q。必要前缀必须受保护；每次试删后更新 Q。

1. 若 f≥b_x，进入提交前核验。没有淘汰时允许新块 Credit=0。
2. 空间不足时，使用当前 Q：无备份后继、未被读取的已提交块。排除候选必要前缀、其他备份的操作保护块、释放中的块；正在复制的后继也不能失去必要前缀。
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
6. 候选仍有信用时，选择一个 Credit=0 的旧尾块 y，令 Y←Y∪{y}、f←f+b_y。同值按稳定物理块 ID 选择，更新 Q 后返回空间判断。前驱成为可释放尾块后才参加下一轮收租。

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

- [DESIGN_CHECKS.json](DESIGN_CHECKS.json)：19 个执行节点、23 条控制连线、全部判断出口、先估值再续租再汇总、布局与源文件检查。
- [SEMANTIC_AUDIT.json](SEMANTIC_AUDIT.json)：17 组事件/算术检查，包含 2040 个单 Agent Slack 恒等式组合；数值仅用于设计核对。
- [COMPATIBILITY.json](COMPATIBILITY.json)：mxGraph 实际解码、编辑保存重开，以及旧 setId 错误的负向检查。
- [MANIFEST.json](MANIFEST.json)：原生导出文件哈希及实际 PNG/PDF 查看记录。
- [修订前快照](references/before-simplified-flow-90c962654783/ARCHIVE.json)：原样保留用户编辑的源及配套文件；更早历史在 references 中。

```bash
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/build_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/audit_semantics.py
NODE_PATH=/tmp/codex-slacklandlord-drawio-compat/node_modules \
  node benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_compatibility.cjs
```

流程图用于独立缩放阅读。本轮检查的是完整原生导出及关键区域，没有将这张详细图按论文单栏尺寸排版。手动编辑源文件后，应先将改动纳入生成器，再重新生成。
