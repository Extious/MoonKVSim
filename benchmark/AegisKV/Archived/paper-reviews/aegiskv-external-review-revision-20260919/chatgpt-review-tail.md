# ChatGPT 评审尾部补发

网页对话：https://chatgpt.com/c/6aae1081-a1a4-83ec-90a8-2db8c1a398dd

原回复在读取接口的20,000字符上限截断。本文件是向同一对话请求补发第六节至结尾后收到的回复，不冒充逐字抓取的原始尾部。

## 六、五个最有价值的英文改写或图表重构建议

### 1. 摘要末句：删除尚未得到支持的性能承诺

建议用于当前节选：

> **AegisKV uses estimated workflow slack to prioritize KV protection; trace analysis and recovery-cost models motivate the design, while end-to-end benefits and normal-service overhead remain to be evaluated.**

将来有完整实验后，再替换为带具体配置、指标和边界的结果句，而不是恢复 “substantially” 和 “negligible” 这类无量化词。

### 2. §3.3：把 planning slack 与执行保证分开

> **The Tracker computes planning slack from predicted segment durations and the currently declared dependency graph; it does not provide a delay guarantee under prediction error or resource contention.**

随后直接说明如何使用预测不确定性，避免一句免责声明承担全部鲁棒性责任。

### 3. §3.6 开头：直接揭示预算与占用不是一回事

> **The Peer budget is an admission target rather than a hard occupancy limit: replicas referenced by live requests may delay memory reclamation after a budget reduction.**

这应出现在容量控制机制的开头，而不是等读者读完算法后才理解。若改成可撤销引用设计，再按实际不变量重写。

### 4. 图 4：从“组件集合图”改成“接口与状态图”

建议使用跨双栏布局：上半部分展示决策所有权，下半部分展示对象生命周期。保留四条最重要的区别：

**requested placement → admitted allocation → committed coverage → recoverable state**

图中直接标注 *“Requested placement is not committed coverage.”* 同时显示 \(B_p\) 是目标预算、\(L_r\) 是目标深度，以及 directory/commit metadata 位于何种存活域。删除重复 GPU 内部小格子，把字号恢复到至少 10 pt。

### 5. 图 5：同时标出恢复终点与后续恢复债务

保留四种流水线，但为每条明确标出：

**“Tail replay complete”** 与 **“Background restoration complete”**

在图下附一行参数账本：测得的计算参数、假定或测得的带宽、\(h\)、mandatory/auxiliary bytes、Peer resident bytes。将共享带宽和不可抢占 DMA 作为至少一组对照；不要让尾部重建完成后的 cold-KV 传输在视觉上被忽略。

---

## 最终修改优先级

**先解决 A02–A06 的正确性、容量和目标函数问题，再完成 A08–A16 的决策有效性与系统验证，最后收紧叙事和图形。** 新颖性定位 A07 应同步进行，否则可能实现完毕后才发现主要收益已经被更简单的既有策略解释。

当前最值得投入的不是继续增加超长上下文模型曲线，而是完成一个小而闭合的证明链：

> **真实依赖与故障 → 可恢复状态 → 可行资源分配 → 实际并发接管 → 工作流收益与正常服务代价。**

只要这条链得到扎实验证，AegisKV 有机会成为有说服力的 EuroSys 系统论文；目前的问题不在选题不重要，而在**最关键的跨组件承诺还没有成为可检查、可实现、可证伪的系统机制**。

---

**问题性质注明：**

**确定的稿件问题：** A01、A17、A18 属于当前文本、图形或形式一致性问题。其中 A01 确定的是“摘要的性能断言没有得到本次所提供材料的支持”，不是“作者没有做过实验”；摘要的结果性表述与节选末尾列出的待验证事项应当对齐。:chatgpt-content-reference{index="0"} :chatgpt-content-reference{index="1"}

**按所述规则可推出的条件性设计问题：** A04、A06，以及 A11 中 \(R_D>R_R\) 时的路径选择情形。它们分别对应不可撤销引用下的回收限制、局部请求评分与联合工作流损失的差距、恢复路径成本排序未受保证的问题；所构造条件下的机制问题可以成立，但不等于已经观察到实现故障，也不等于实际性能影响已经量化。:chatgpt-content-reference{index="2"} :chatgpt-content-reference{index="3"} :chatgpt-content-reference{index="4"}

**仍需实现契约、论证或实验确认的问题：** A02、A03、A05、A09、A10，以及 A11 的评分与边界行为，需要明确实现契约并进行测试；A07、A08、A12–A16 主要需要补全相关工作或动机论证，并通过相应实验确认增量、适用范围和实际影响。这些条目中已经指出的“稿件说明不足”与“实现确有缺陷”不是同一结论。**本轮评审没有对代码仓库作出“无实现”的判断；节选未提供实现或实验，不等于仓库没有实现或作者未做实验，也不能将其视为已经验证的结果。**
