# SlackLandlord：一次请求中一个 KV chunk 的决策

[完整 Draw.io：布局页 + 流程页](algorithm-2-patent-revised.drawio) · [完整 PDF](algorithm-2-patent-revised.drawio.pdf)

[单页流程 Draw.io](algorithm-2-rental-management.drawio) · [单页 PDF](algorithm-2-rental-management.drawio.pdf) · [PNG](algorithm-2-rental-management.drawio.png) · [逻辑与布局审查](SEMANTIC_AUDIT.md)

**入口是 Agent a 的请求到来，决策其中一个完整 KV chunk x。** 请求中的 KV 按前缀顺序逐块处理：已有完整块可在本请求复用时处理，新块生成并封闭后再处理。一次流程只更新当前 Agent 在这个块上的份额，不因请求到来而给所有历史引用批量续租。

本版恢复 H、L 租值键。第一页保留 KV/Pool 布局，第二页用同一主线覆盖已有副本续租和新副本准入。执行节点 20 个、控制连线 24 条；相较前一版增加一个必要的“结算旧租金”步骤，保留原字号和黑白风格。

## 主线与决策

| 步骤 | 操作与结果 |
|---|---|
| ① 取本请求中的 x | 读取请求 Slack、请求号、块状态与分账；无副本则空分账 |
| 请求筛选 | 先等待正在进行的备份/释放；否则跳过重复或过期请求，其余继续 |
| 新副本就绪检查 | 新副本要求完整可读源与已提交前缀；已有副本的续租不受这个条件限制 |
| ② 估值 | 只计算当前 Agent a 的恢复收益 G_a,x |
| ③ 结算 | x 在 Q 中时按 H−L 算出租后余额，并按原份额比例结算；其他块保持冻结份额 |
| ④ 续租和建键 | 只替换 a 的份额，汇总 Credit，设置 H；已有副本保存后结束 |
| ⑤ 准入试算 | 复制 L、Q 和相关账本；保护必要前缀，按 H 比较候选与可释放尾块 |
| ⑥ 核验与执行 | 核验请求和 L/Q 等版本；提交试算、冻结候选租后份额，撤销回收块资格后释放、分配并复制 |
| ⑦ 发布 | 按复制完成时的当前 L 重建 H；保存租后份额和已处理记录，不重新授信 |

## 收益、分账与 H/L

\[
G_{a,x}=\min\{T_a(k_a)-T_a(k_a+1),\max(T_a(k_a)-s_a,0)\}.
\]

T_a(k_a) 使用 x 之前的备份前缀，T_a(k_a+1) 使用包含 x 的前缀；剩余已生成 KV 重算。新生成的 x 之后不假设未知 KV。采用复用快于对应重算的模型，因此时间差非负。本请求的 Slack 固定。

对已有内部块，仍按“前缀到 x 之前 / 到 x”为止估值，估值时暂不使用其后备份；物理副本不被挖空。只给当前 Agent 算独立收益，不读取 workflow ID，不作联合 WCT 分配。

| 符号 | 含义 |
|---|---|
| c_u,x | 最近一次结算时保存的 Agent u 的信用份额，单位为时间 |
| Credit_x | 结算后的各 Agent 总余额，或冻结期间的总余额 |
| L | 本池累计每字节租金，初值 0；由成功提交的容量竞争推进，非墙钟时间 |
| L′ | 本次试算使用的租金副本；拒绝时不写回 L |
| H_x | 块的租值键，单位与 L 一样，为时间/字节 |
| Q | 按 H 排序的可释放物理尾块最小堆 |
| b_x | 物理字节数；多个 Agent 共享一块只占一份空间 |

**正在参与收租的块**的当前总余额为：

\[
\mathrm{Credit}_x=b_x\max(H_x-L,0).
\]

L 推进时，H 和保存的各 Agent 份额可以保持不变。访问、续租或退出 Q 时，才兑现此前扣租：

\[
c_{u,x}\leftarrow c_{u,x}
\frac{b_x\max(H_x-L,0)}{\sum_v c_{v,x}}
\qquad(\forall u).
\]

所有份额使用**同一个结算前分母**。分母为 0 时跳过。未参与收租的内部块、受保护块和复制中的候选保留冻结份额，不能用旧 H 减去当前 L 补扣暂停期间的租金。新候选在准入前为空分账，跳过此结算。

结算之后，本请求只续租 a：

\[
c_{a,x}\leftarrow G_{a,x},\qquad
\mathrm{Credit}_x\leftarrow\sum_u c_{u,x},\qquad
H_x\leftarrow L+\frac{\mathrm{Credit}_x}{b_x}.
\]

A 的新请求只替换 A 的租后份额。B 即使没有新请求，也要结算其应付租金，但不重算 B 的收益、不补回 B 已花掉的信用。新物理副本最初只有触发本次决策的 Agent 的份额；其他 Agent 之后实际访问时，再各自续租。

重复的“副本代次、Agent、请求号”不再次授信；过期请求不覆盖更新后的 Slack 或余额。只有已有副本的续租保存、或新副本成功发布，才记录本请求已处理。拒绝的提案不能消耗请求处理标记。

## Q 的进出和 H 的有效期

Q 只包含已提交、没有需要保留的备份后继且当前可安全释放的物理尾块。读取、候选必要前缀、其他进行中备份的保护块及释放中的块均被排除；共享前缀的后继必须全部检查。

- **退出 Q：** 先按退出时的 L 结算份额，再冻结。不扫描无关块。
- **进入 Q：** 使用当前 L 和冻结份额设置 H=L+Σc/b，不补缴未在 Q 中期间的租金。
- **持续留在 Q：** L 推进时 H 不变，只有续租才重新设置该块 H 并更新堆位置。

这三条是 Q 维护契约，读取保护、前缀变化、复制完成和失败清理都要遵守。图中⑤覆盖必要前缀退出和临时 Q；回收框覆盖新暴露尾块入队；已有副本保存与⑦分别更新续租块和新发布块。保护状态变化本身不产生新的收益或授信。

## 用 H 比较候选与尾块

⑤先建立临时状态：L′=L、Y=∅、f=Pool 可用字节。需要退出 Q 的必要前缀按当前租金结算并冻结；其余原有 H 保持不变。

1. f≥b_x 时进入提交核验；空闲容量允许 Credit_x=0。
2. 空间不足且 Q 为空，拒绝 x。
3. 取 Q 中 H 最小的尾块 y；同 H 按稳定物理块 ID 选择。
4. **只有 H_y<H_x 才继续。** 否则候选先耗尽或同时耗尽信用，拒绝整个试算。
5. 令 L′←H_y，试删 y，更新 Y、f 和 Q。新暴露且可释放的尾块 z 以 H_z=L′+Σc_u,z/b_z 入堆。持续在 Q 中的 H、候选 H_x 均不重建。
6. 返回容量判断，直到空间足够或拒绝。

H_y<H_x 等价于推进租金直到旧尾块归零后，候选仍有正信用。一次推进对当时 Q 中的块和候选按物理字节收租，通过 H−L′ 表示各自余额；不再遍历所有块逐份额扣账。暂停的内部块没有参与这次收租。

拒绝时丢弃临时 L′、Q、分账和回收计划，实际 L、备份、余额和请求标记均保持不变。候选 H 在整次试算中固定，不能每回收一块就按新的 L′重新补满。

## 复制、发布与并发边界

⑥提交前核验请求、池租金与 Q 版本、块状态、保护及容量。任何相关状态变化都要求丢弃尚未执行的试算并重读。元数据提交序列化；等待异步复制时不持有覆盖整个 Pool 的长锁。

提交后 L←L′。新候选此时只有当前 Agent 的份额，冻结为：

\[
c_{a,x}\leftarrow b_x\max(H_x-L^{\prime},0).
\]

同时提交保护变化和有效的账本状态，撤销 Y 的恢复资格后执行物理释放、分配和复制。复制中的 x 不在 Q，期间不支付其他准入产生的租金。相关 Agent 请求等待后重读，不覆盖后续余额。

复制完成时，用**当时的 L**重建 H=L+Σc/b，再按保护状态入 Q 或保持冻结。这里只改变键的租金基准，不重算 G，也不退还 x 在准入竞争中已付的租金。只有本代次全部操作成功，才发布完整可恢复副本并保存已处理记录。

执行后的失败按实际状态清理未完成分配、容量占用与 Q；不能把实际已释放的备份恢复为“仍存在”，也不能回退已经影响其他键的 L。尚未实际释放的占用继续计入容量。这里规定提交边界，未由本轮并发服务代码验证。

## 核对与适用范围

- [DESIGN_CHECKS.json](DESIGN_CHECKS.json)：20 节点、24 连线、公式及全部出口、原第一页布局和受保护文件不变。
- [SEMANTIC_AUDIT.json](SEMANTIC_AUDIT.json)：26 组设计算术核对，含 2040 个单 Agent Slack 组合、12288 个 H/L 与显式扣租对照案例。
- [COMPATIBILITY.json](COMPATIBILITY.json)：实际 mxGraph 解码、编辑保存重开及旧 setId 错误负向检查。
- [MANIFEST.json](MANIFEST.json)：源与原生导出哈希、实际 PNG/PDF 查看记录。
- [修订前原样快照](references/before-hl-keys-f84db8ef173c/ARCHIVE.json)：保留用户保存的源与前版配套文件；本次与前版单页的节点、文字和几何一致，差异为 Draw.io 保存元数据与 XML 序列化。

对照检查覆盖准入结果、回收顺序、全部保留块的逐 Agent 余额、前缀与读取保护、同值拒绝，以及失败试算不改实际 L。它验证给定设计模型中的两种记账方式；不证明全局最优、真实恢复成本、并发协议或性能。

Credit 是可累加优先级，不等于多个 Agent 同时恢复时的精确联合 WCT 改善。没有 Agent 结束事件，失败试算不扣真实租金，因此不承诺闲置块一定到期。运行算法、专利原文和算法三均未在本轮修改。

```bash
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/build_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/audit_semantics.py
NODE_PATH=/tmp/codex-slacklandlord-drawio-compat/node_modules \
  node benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_compatibility.cjs
```

本图用于独立缩放阅读，不是按论文单栏尺寸排版的图。手动编辑源文件后，先保留修改并纳入生成器，再重新生成。
