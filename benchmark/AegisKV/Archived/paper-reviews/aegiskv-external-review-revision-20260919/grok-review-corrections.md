**勘误（仅针对上次评审中的具体推导错误）**

**1. Tier 条件与 slack 误差方向（§3.5 公式 (1)）**  
原文明确：  
- Tier R：σ_r ≥ R_R  
- Tier D：R_D ≤ σ_r < R_R  
- Tier P：否则（即 σ_r < R_D）  
其中 R_D = R_base + W_0。  

因此**低估 W_0 会使 R_D 变小，P 区域缩小**（更少请求被标为 P），而非上次所说的“过多请求标为 P”。  

关键路径剩余时间**低估**会产生**虚假较大的 slack**，从而降低保护等级（可能从 P 降到 D 或 R）。  

**两分支数值例子**（假设 R_base = 5 s，真实 W_0 = 10 s → 真实 R_D = 15 s；R_R = 40 s）：  
- 分支 A（真实关键，真实 σ = 8 s）：应进 P。若预测剩余时间低估 → 虚假 σ = 20 s → 落入 D，保护不足。  
- 分支 B（真实 σ = 25 s）：应进 D。若 W_0 被低估为 3 s → 虚假 R_D = 8 s → 仍可能进 D 或边缘，但整体 P 区域变小。  

上次方向写反，特此纠正。

**2. §3.6 引用释放语义**  
原文明确：“A successful grant holds a request reference until that LLM request ends, **including a response that hands control to an external tool**. Completion decrements shared references”。  
因此工具调用等待本身**会释放引用**，不能再把它当作 pin 未释放的场景。  

真实仍可能导致物理占用超支的场景应改为：  
- 仍在运行的长 decode（持续生成中的请求）；  
- 安全迁移/复制完成滞后（in-flight 或刚 commit 但引用未及时清零）；  
- 预算突然下调后 referenced copies 的自然 drain 时间过长。  

**3. 已标注 vs 尚缺验证**  
文中已明确：  
- Figure 1(c) 为反事实替换（“counterfactual”“not a trace observation”“does not constitute physical failure replay”）；  
- Figure 2 为静态估计（HYBRID、假设带宽、无 contention）；  
- Figure 5 为 modeled pipeline；  
- Figure 3(a) 来自 Heddle 文献，非本系统 GBDT 实测。  

上次把“已披露的静态/反事实性质”与“端到端验证缺失”混在一起不够精确。应严格区分：已标注的估计性质是诚实的；真正缺失的是运行时误差传播、并发争用、缩容最终回到预算、以及真实故障下的 WCT 测量。

**4. 恢复正确性标准**  
不应一概要求跨不同浮点执行次序 bit-identical。更准确的要求是：  
- 逻辑 KV 状态与 selector 输入在 deterministic 配置下一致；  
- 明确数值容差与允许的随机性边界；  
- 在固定确定性配置（相同 seed、相同算子调度）下验证恢复后 decode 与无故障路径的一致性。  

**5. 阅读确认**  
已完整阅读全部 9 页文本内容（包括 Abstract、§2、§3、Algorithm 1–3、Figure 1–5 的图注与正文描述、全部参考文献）。  
Figure 4 的系统结构、Algorithm 3 的 windowed budget 更新逻辑均已根据文本核对。  
视觉层面（精确灰度对比度、字体是否严格 ≥10 pt、线条粗细）受 OCR/图像渲染限制，无法 100% 可靠确认印刷级细节，但不影响对机制与标注的判断。

**仍有效的核心问题（方向已纠正后）**  
- Slack 预测误差（尤其是关键路径低估 → 虚假大 slack → 保护不足）仍是 P0。  
- 并发恢复时共享带宽缺乏按 slack 的调度/抢占机制仍是接口漏洞。  
- 预算缩容后 referenced 长 decode 或迁移滞后导致的物理超支仍需硬约束。  
- 端到端故障 + 争用下的 WCT 测量与消融仍缺失。  

以上为针对具体推导的勘误，其余评审框架不变。
