# SlackLandlord：独立 Agent 收益与共享 Credit

[完整 Draw.io：布局页 + 统一流程页](algorithm-2-patent-revised.drawio) · [完整 PDF](algorithm-2-patent-revised.drawio.pdf)

[单页流程 Draw.io](algorithm-2-rental-management.drawio) · [单页 PDF](algorithm-2-rental-management.drawio.pdf) · [PNG](algorithm-2-rental-management.drawio.png) · [语义审计](SEMANTIC_AUDIT.md)

2026-09-09 修订。每个 Agent 独立计算恢复收益，只有 Credit 汇总多个 Agent 的份额。算法不读取 workflow ID、Agent 间的并行关系或联合恢复时间向量。两种事件保留在同一流程页：新块准入，以及新请求实际复用已有块后的续租。

## 1. 每个 Agent 的收益

对引用块 x 的 Agent a：

\[
G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}.
\]

- s_a 是该 Agent 最近请求的 Slack，本请求生成 KV 期间不变。
- k_a 是 x 前面的块数。
- T_a(k_a) 使用 x 之前的备份前缀，T_a(k_a+1) 使用包含 x 的备份前缀。
- 恢复范围只包含当前已生成的 KV；使用全部可用前缀，剩余部分重算。新生成的 x 之后没有尚未生成的重算工作。
- 假设备份复用快于对应重算，因此 T_a(k_a+1)≤T_a(k_a)，G 非负。

G_a,x 表示**单独考虑该 Agent 时，备份 x 减少的 Slack 外恢复延迟**。它的单位是时间。多个 Agent 即使属于同一 workflow，也各自使用自己的输入计算；不做固定 Agent ID 顺序的收益分配。

内部块复用时，同样以“备份前缀到 x 之前”和“到 x”为止估值，估值时暂不使用后继备份，实际布局不改变。这是对该块作为前缀末端时的授信估值，不是在物理备份中挖洞。

## 2. 初始信用和续租

| 量 | 含义与单位 |
|---|---|
| G_a,x | Agent a 的独立恢复收益，时间 |
| c_a,x | Agent a 对 x 的剩余信用，时间 |
| Credit_x=Σ_a c_a,x | 共享物理块的剩余信用，时间 |
| b_x | 共享物理块实际占用的字节，只计一份 |
| δ | 一次竞争收取的租金密度，时间/字节 |
| Q | 当前可释放的物理尾块 |
| Y、f | 临时回收计划中的块、计划可用字节 |

新块在分配之前，逐个为登记引用的 Agent 计算 G，建立临时信用：

\[
c_{a,x}\leftarrow G_{a,x},\qquad
\mathrm{Credit}_x\leftarrow\sum_a c_{a,x}.
\]

已有备份被 Agent a 的**新请求实际复用**时，用 a 的新 Slack 和当前已生成 KV 重算 G_a,x，只更新 a：

\[
c_{a,x}\leftarrow G_{a,x},\qquad
\mathrm{Credit}_x\leftarrow\sum_a c_{a,x}.
\]

其他 Agent 的余额完全不变。例如 A 续租后额度为 4，B 已花到只剩 1，共享 Credit 为 5；不能重新加回 B 的初始额度。新 Agent 首次实际引用已有备份，也只新增自己的份额。

每个“物理副本代次、Agent、请求号”只授信或续租一次。初次复制授信也记录本请求已处理；同一请求的重复命中或重试保留原余额。过期请求不得覆盖新 Slack 或续租记录。内部块和读取中的块也立即续租，不需要进入 Q。

Credit 是**授信后扣除租金的余额**，不是每次检查都重新计算的即时收益。不再遍历 Q 重算全体份额，也不因仅出现新的请求号而自动续租。没有 Agent 结束事件；没有实际复用就没有续租。

## 3. 容量不足时的竞争

必要前缀已提交、源完整可读后，建立临时回收计划：

\[
Y\leftarrow\varnothing,\qquad f\leftarrow\text{Pool 空闲字节}.
\]

全部收租与试删先写临时记录。若 f≥b_x，进入计划提交；无需淘汰时允许初始 Credit_x=0。

空间不足时，Q 只包含无备份后继、未被读取的已提交块，排除 x 的必要前缀、正在释放的块。Q 为空或新块 Credit 已为零时拒绝新块。

新块 x **也参与本次试算收租**，避免旧块无条件归零后任何新块都可取代它：

\[
\delta=\min\left\{
\frac{\mathrm{Credit}_x}{b_x},
\min_{y\in Q}\frac{\mathrm{Credit}_y}{b_y}
\right\}.
\]

对 y∈Q∪{x}，使用扣租前的 Credit_y，将一份物理租金按 Agent 的余额比例分摊：

\[
c_{a,y}\leftarrow c_{a,y}
\left(1-\frac{b_y\delta}{\mathrm{Credit}_y}\right),\qquad
\mathrm{Credit}_y\leftarrow\sum_a c_{a,y}.
\]

每块共支付 b_y δ；Credit 为零时跳过除法。实现须先读取该块总余额，再更新各 Agent，不能边更新边改分母。

收租后**先检查新块**。Credit_x=0 则拒绝，包括新旧块同时归零的情况。否则选择一个 Credit=0 的旧尾块 y，加入临时回收计划：

\[
Y\leftarrow Y\cup\{y\},\qquad f\leftarrow f+b_y.
\]

同值用稳定的物理块 ID 选择。仅试删尾块，其前驱成为尾块后才能在下一次循环参与收租；内部块此前的余额不被扣除。重复检查空间，直到足够或拒绝。

这替换了旧版 G_x>D_Y 的联合 WCT 净收益准入条件。当前算法只通过共享 Credit 竞争，不再另算跨 Agent 总收益或联合删除损失。

## 4. 提交与复制

计划不通过时，丢弃整个试算，实际备份和实际信用保持不变，包括曾被试删的尾块。

计划通过时，核验 Pool/引用输入/余额版本、源与必要前缀代次、读保护和容量。通过一致性检查后提交收租和回收计划，释放 Y、确认物理空间可用，再分配并复制 x。复制成功才发布当前代次的完整备份。

**复制成功保存竞争后剩余的 Credit，不重新按 G 补满。** 否则会退还新块刚支付的租金。记录各 Agent 本请求已授信，防止首次复制和随后的重复命中分别授信。

已有复制合并事件，不重复分配；并发的新请求实际复用事件应保留请求号，按事件顺序处理。核验冲突时在执行物理释放之前重新决策。复制失败或释放阶段发生异常时按实际状态清理，不把已释放备份当作可回滚的临时记录，也不能让旧 ACK 发布新代次。具体并发协议仍待运行实现验证，图中不声称已部署。

## 5. 模型含义与边界

- **Credit 是独立 Agent 收益形成的可累加租金优先级，不等于多个 Agent 同时恢复时的精确 workflow WCT 改善。** 当前策略刻意不判断共享 Agent 的串并行关系。
- 份额使用最近一次实际访问的信息；不对未知未来请求、Agent 活跃概率或未来 KV 长度作保证。恢复耗时模型还需校准。
- 只在成功提交的竞争中扣除真实信用。连续被拒绝的弱候选不会让旧块自动过期，因此不保证无复用块最终一定被淘汰。
- 只租尾块能维持前缀合法性；逐块竞争仍是在线策略，没有全局最优、联合 WCT 单调改善或经典 Landlord 竞争比证明。
- 本次修改的是设计流程图及其审计，不是 MoonKVSim/Mooncake 运行算法，也未修改专利原文。

## 6. 来源与检查

保留了用户第一页的全部几何布局，以及缺失前缀框的手动位置。修订前文件已原样归档到 [before-independent-agent-credit-d2ecac2495e4](references/before-independent-agent-credit-d2ecac2495e4/ARCHIVE.json)。更早的方案仍留在 references 中。

当前检查：

- [DESIGN_CHECKS.json](DESIGN_CHECKS.json)：流程连通、Agent 独立公式、分账/续租/收租顺序、保留布局和受保护文件哈希。
- [SEMANTIC_AUDIT.json](SEMANTIC_AUDIT.json)：12 组精确算术与事件检查，其中包含 2040 个单 Agent Slack 恒等式组合；不作为实测数据。
- [COMPATIBILITY.json](COMPATIBILITY.json)：实际 mxGraph 解码、编辑保存重开，以及旧 setId 错误的负向复现。
- [MANIFEST.json](MANIFEST.json)：原生导出文件、源哈希、实际 PNG/PDF 查看记录。

重新生成（不要覆盖尚未纳入生成器的手动修改）：

```bash
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/build_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/audit_semantics.py
NODE_PATH=/tmp/codex-slacklandlord-drawio-compat/node_modules \
  node benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_compatibility.cjs
```

图是可缩放阅读的详细算法设计图；本轮没有调整论文的实际插图尺寸或验证投稿版式。
