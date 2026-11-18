# SlackLandlord：新 chunk 准入与 Cache hit 续租

[完整可编辑源图](algorithm-2-patent-revised.drawio) · [三页 PDF](algorithm-2-patent-revised.drawio.pdf) · [本次审计与修正](SEMANTIC_AUDIT.md)

| 页 | 内容 | 独立文件 |
|---|---|---|
| 1 | 用户已有的 Agent 生命周期、共享 KV 与容量示意，保持原样 | [PDF](algorithm-2-patent-revised-agents.drawio.pdf) |
| 2 | 新 chunk：收益评估、回收试算、准入、复制与首次授信 | [Draw.io](algorithm-2-admission.drawio) · [PDF](algorithm-2-admission.drawio.pdf) · [PNG](algorithm-2-admission.drawio.png) |
| 3 | Cache hit：引用登记、按需评估、分账、续租与租值键更新 | [Draw.io](algorithm-2-cache-hit.drawio) · [PDF](algorithm-2-cache-hit.drawio.pdf) · [PNG](algorithm-2-cache-hit.drawio.png) |

两页使用黑线、白底，符号说明在开头。决策公式位于连通的执行框；独立侧栏只画 KV 引用与 Pool 布局。统一使用 Q，不增加 Q_r。第 2、3 页分别有 25、15 个执行节点，页面高度为 4540、4100；按独立设计图阅读，不作为论文单栏缩印图。

## 收益、授信额度与剩余信用

| 符号 | 含义 | 单位与用途 |
|---|---|---|
| \(T_a(k)\) | Agent a 备份前 k 块时，恢复当前已生成 KV 的时间 | 时间；读取代价模型 |
| \(G_x\) | 一份物理备份 x 带来的总 WCT 改善 | 时间；新块准入与替换比较 |
| \(P_x=G_x/b_x\) | 该物理块的收益密度 | 时间/字节；不另设 Agent 优先级 |
| \(W_{a,x}\) | 从当前总收益分给 Agent a 的授信额度 | 时间；仅在 Credit 分账阶段使用 |
| \(c_{a,x}\) | Agent a 已授信、扣租后剩余的信用 | 时间；可续租或下调 |
| \(\mathrm{Credit}_x=\sum_a c_{a,x}\) | 物理块剩余信用 | 时间；一般不等于当前 \(G_x\) |
| \(H_x=L+\mathrm{Credit}_x/b_x\) | 当前可释放尾块的租值键 | 时间/字节；与累计租金 L 比较 |
| \(D_Y\) | 逐次删除计划中尾块造成的累计 WCT 损失 | 时间；不等于已收租金或被删块 Credit |

收益先直接计算：

\[
G_x=\sum_{w\gets x}\big[\mathrm{WCT}_w(\mathbf T)-\mathrm{WCT}_w(\mathbf T^x)\big].
\]

每个引用 x 的工作流只进入求和一次。这里不按 Agent 排序、不计算 \(W_{a,x}\)，也不读取 Credit。\(\mathbf T\) 与 \(\mathbf T^x\) 分别表示相关引用不用和使用 x 的恢复耗时；其他节点状态不变。工作流完成时间按图中 DAG 递推式计算。

只有初始化或刷新信用时，才按固定 Agent ID 顺序分配 \(W_{a,x}\)。中间状态 \(\mathbf T^{(i)}\) 表示前 i 个 Agent 使用 x；同一 Agent 对应的恢复节点一起切换，不把重复引用当作新的分账主体。逐项差分相消，因此 \(\sum_a W_{a,x}=G_x\)。这是确定性的记账约定，并非唯一的“真实 Agent 贡献”：总收益与排序无关，各 Agent 的额度以及之后的单 Agent 续租可能受排序影响。

## 恢复时间的范围

保留用户对 \(T_a(k)\) 的文字定义；图中不重新加入长度符号或枚举复用块数的公式。按当前指定模型，复用全部可用连续前缀，再重算剩余已生成 KV。备份 x 前后分别用 \(T_a(k_a)\) 和 \(T_a(k_a+1)\)。新生成 x 是生成它的 Agent 当前末尾；已有尾块或复制完成时已经产生的后缀仍须计入代价，不预测未知后续长度。

图中的单 Agent Slack 式是总收益公式的特例：同一工作流中只有该 Agent 的恢复耗时改变，其他路径固定，Slack 与该 DAG 基线一致。多个 Agent 同时恢复时采用联合 WCT 端点计算，不能把各自的单 Agent 简式直接相加。

## 第 2 页：新 chunk

先读取恢复输入并直接计算 \(G_x\)，再建立临时账本与回收计划。x 在试算中视为可恢复，其必要前缀受保护；此时尚未分配真实容量。

容量不足时，检查 Q 中全部可释放物理尾块。引用、轮号或价值输入改变才重新计算额度并结算对应份额；未变则保留余额。**所有尾块都按当前 L 更新 H**，之后才能选取最小租金增量，按余额比例扣除一份物理租金，并只推进一次 L。零信用块跳过除法。逐次删除归零尾块时，按照当前临时前缀计算真实删除损失并累计到 \(D_Y\)。

准入条件保持为：

\[
\begin{cases}
G_x\ge0,&Y=\varnothing;\\
G_x>D_Y,&Y\ne\varnothing.
\end{cases}
\]

失败试算不改真实余额、轮号或备份。成功计划核验版本后提交；释放 Y 并等待 ACK，再检查容量、分配和复制 x。复制成功后，根据发布时实际前缀评估当前额度，**首次**初始化 \(c_{a,x}=W_{a,x}\)，此时 \(\mathrm{Credit}_x=G_x\)。最终核验与发布必须原子执行，同一分配代次只发布一次。输入改变则重新计算额度；副本失效则清理。

重复到来的 x 已有备份时转第 3 页，已有复制时合并事件。旧分配的 ACK 无效；复制失败不初始化新 Credit。回收已经发生后，已释放的旧备份不能通过“丢弃临时计划”恢复。

## 第 3 页：Cache hit

新请求只更新该 Agent 的当前轮号、Slack 与代价信息，不遍历所有 KV。旧轮号及重复事件不覆盖当前输入。对于命中的 x，登记逻辑引用并保护实际读取期间的分配；本 Pool 缺少备份时才转第 2 页。

内部块或正在读取的块保留余额、退出 Q，等成为可释放尾块再继续。此时读取当前账本和 L：

- **引用、轮号与价值版本未变**：跳过收益评估和分账，保留剩余信用，直接更新 H。
- **发生变化**：先直接计算当前 \(G_x\)，再单独分配 \(W_{a,x}\)，最后按下式更新余额。

\[
c_{a,x}\leftarrow
\begin{cases}
0,&\text{Agent 结束或引用解除};\\
W_{a,x},&\text{首次授信或新轮尚未兑现};\\
\min(c_{a,x},W_{a,x}),&\text{本轮已兑现}.
\end{cases}
\]

兑现时记录对应 Agent 的当前轮号；A 续租不会补回 B 已付的租金。解除引用仍保留已兑现轮号，防止同轮解除后重挂重复授信；生命周期结束后重新创建 Agent 使用新的身份。多次未兑现的新请求合并为最新轮号，不逐轮累加额度。

两条路径都用当前 L 重建 H，并原子核验、写入余额、轮号和 Q。本次不推进 L，也不新增物理副本。**不重算收益不代表可以复用旧租值键；重入 Q 也不代表获得新信用。**

## 执行约束与验证范围

Q 按物理块检查已提交、无任何备份后继、未固定读取、未释放及不属于候选保护前缀；共享块检查全部依赖。输入版本覆盖引用集合、Agent 轮号、已生成 KV、恢复代价、工作流 DAG 及相关工作流恢复前缀。租金账本、L、分配代次与容量使用独立的提交校验，不能仅用 Slack 版本替代。

回收试算使用同一组输入；临时前缀变化后更新条件损失与尾块价值。输入或账本版本冲突使未执行计划失效。复制期间变化只能按当前物理状态重新处理，不宣称此前已执行的删除仍满足最新输入下的收益保证。算法 3 缩小容量时由单独容量回收路径暂停新准入并回收；正在复制、释放的分配仍计入占用。

[审计报告](SEMANTIC_AUDIT.md)列出具体修正、反例与边界。[DESIGN_CHECKS.json](DESIGN_CHECKS.json)检查图中路径、符号、公式层次、第一页保留及 8 项已有 CPU 核算；另核对两组恢复范围与 44 个 Slack 等价式条件。[SEMANTIC_AUDIT.json](SEMANTIC_AUDIT.json)包含 5 组针对本次问题的精确反例检查。

本次修改设计图及配套说明，未修改专利、Mooncake/MoonKVSim 运行代码。[早期 CPU 参考设计](../../algorithm-2/AGENT_LEASE_DESIGN.md)仍使用严格准入与较早的事件接口；已有核算通过不代表新事件路径或并发复制协议已经实现。固定 ID 分账不保证公平性；逐块贪心不保证未来收益最优。本次不声称实测性能、Landlord 竞争比或投稿结果。

[COMPATIBILITY.json](COMPATIBILITY.json)检查 mxGraph 4.2.2 解码、编辑、保存与重开，其中 `reproduced_error` 是历史危险 ID 的负例。[MANIFEST.json](MANIFEST.json)绑定源图、实际导出与检查记录。

```bash
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/build_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/verify_decision_flows.py
.venv/bin/python benchmark/AegisKV/docs/drawio/slacklandlord-patent-revised/audit_semantics.py
```

手动修改原生源后，仅刷新导出使用 `build_diagram.py --export-only`。生成器检测到后续手动编辑会停止覆盖。本次调整前的[用户手动源图](references/before-gain-credit-audit-06f9e9e4d5ea-algorithm-2-patent-revised.drawio)已归档；更早的[精简前源图](references/before-compact-reuse-88112af84cd5-algorithm-2-patent-revised.drawio)也保留。
