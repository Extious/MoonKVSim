# 单个请求的 KV 生产、Priority 与 Credit

**状态：请求流程说明与设计讨论，不修改算法实现。** 主流程解释当前 revision 3；历史租金 Credit 是尚未选定、尚未重新接入的选项。原来的三页算法 2 图展开的是完整协议，本图按单个请求的生产过程组织。

[可编辑 Draw.io](request-kv-production-and-admission.drawio) · [PDF](request-kv-production-and-admission.drawio.pdf) · [PNG](request-kv-production-and-admission.drawio.png)

## 1. 单个请求的主流程

1. 请求进入：绑定模型/内容身份、路由、保护目标，记录 Slack、恢复代价模型、有效期与共享引用。
2. 执行 Prefill / Decode，逐步生成主 KV。每次完整 chunk 封口时触发保护评估，不等待请求全部结束。未封口的可变页不作为共享保护对象。
3. 对每个目标池分别查看已经 COMMITTED 的连续前缀。全命中不重复复制；部分命中从首缺口开始。不能跳过缺失祖先去保护不可恢复的后缀。
4. 从首缺口枚举已经生成、源仍可读的候选组 X；单个 chunk 是组大小为 1 的特例。之前暂停的缺口可以与本次新完成的块一起重评估。
5. 检查额度、staging、源/路径许可、时限及 pending/reclaim 状态；计算当前保护收益。如果需要腾空间，在暂定状态中选择合法删除闭包，并重算完整替换结果。
6. 有严格改善且资源允许的计划才预留并复制。复制期间旧保护保持可见；分片 ACK 齐全且重新校验通过后提交，否则中止。撤销后的物理容量仍等 FreeACK 才释放。
7. 没有可行计划只暂停本 tier 备份；推理继续。新 chunk、价值/引用变化、许可或容量恢复、FreeACK 触发重试。
8. 请求结束时退出活跃恢复收益。仍被其他调用引用的共享对象不随该请求一起清空；无引用、无 pin 且无存活依赖的对象按回收协议释放。

## 2. Priority 的建议定义

Priority 应表示 **当前状态下，每字节新保护可减少多少超出 Slack 的恢复损失**。它不是由 chunk 序号或插入时间固定决定的。

先定义恢复损失代理：

\[
\Phi_r(C,t)=\sum_{i\in\mathcal A(t)}w_i[T_i^r(f_i(C),t)-s_i(t)]_+.
\]

其中 C 为本 tier 已提交对象集合，f 为连续可恢复前缀，s 为当前 Slack，w 默认 1。未知未来请求不提前算成活跃收益；不同实际调用分别计入收益，但共享物理 bytes 只计一次。这个量是本 tier 的条件恢复损失代理，不是精确工作流 makespan，也没有隐含未经校准的故障概率。

候选组的新增收益与优先级：

\[
A(X\mid C,t)=\Phi_r(C,t)-\Phi_r(C\cup X,t),\qquad
P_{add}(X\mid C,t)=\frac{A(X\mid C,t)}{b(X)}.
\]

如果 X={k}，这就是一个 chunk 的当前新增保护 Priority。A 的单位是加权毫秒，P 的单位是加权毫秒/byte。P 是上述目标的派生解释量，当前参考模块并没有新增一个持久化 `Priority` 字段。

举例：一个 16 MiB 的块将恢复时间从 120 ms 降到 80 ms，当前 Slack=90 ms，w=1。那么恢复损失从 30 ms 降到 0，A=30 ms，P=1.875 ms/MiB。若 Slack=150 ms，两种恢复都被 Slack 吸收，本代理下 A=0。零收益单块仍可与之后**已经生成**的块构成正收益组，所以本次暂停不封死未来。

### T 和 Slack 如何得到

对本次已生成进度 n，可在所有可用恢复前缀 u 中取最便宜的恢复方案：

\[
T_i^r(f,t)=\min_{0\le u\le f}
\left\{\widehat T_{read}^r(u,t)+\widehat T_{recompute/replay}(u\rightarrow n,t)
+\widehat T_{fixed}(t)\right\}.
\]

u=0 包含完整重算；有更多可用前缀只会增加选项，不强制加载代价更大的副本。读取估计应包括启动、有效吞吐与相关排队成本；重算/重放应区分 prompt 和已生成输出。模型、TP 配置、KV 大小、传输路径和当前进度都影响这些估计，不能用“token 数乘一个通用常数”替代所有成本。

当前 `Consumer.recovery_ms` 是**调用方传入**的恢复曲线；参考模块检查其形状和单调性，不自动测出曲线。Slack 来自上游预测/工作流分析，并按当前 ticket 时间更新。因而公式可以明确，但实机参数、估计误差及其校准仍需独立完成，不能把元数据层可计算等同于已有准确实测。

### 新增 Priority 与驱逐 Priority 要区分

删除某个共享祖先，需要连同其已提交后代形成合法闭包 Z。当前候选 X 已纳入暂定评价时，选择 victims 使用：

\[
P_{evict}(Z\mid C',X,t)=
\frac{\Phi_r((C'\setminus Z)\cup X,t)-\Phi_r(C'\cup X,t)}{b(Z)}.
\]

这个值越低，删除每字节造成的损失越小。删除闭包后要更新 C′ 并重新计算；共享依赖的边际价值不能简单相加。

最终准入判断仍然是：

\[
\Phi_r(C,t)-\Phi_r((C\setminus Y)\cup X,t)>\eta,
\]

并满足真实物理容量、staging、时限和许可约束。Priority 高不代表一定应备份；它也不替代完整最终状态的净收益比较。

## 3. Priority 如何对应 Credit

**Credit 没有一个脱离淘汰机制的通用换算公式。** 当前 revision 3 不保留历史 Credit；旧版采用 `H=L+P` 的租金阈值。重新选择历史 Credit，就需要明确其单位、扣减及刷新语义。

先在**对象价值固定、上下文固定**的独立缓存模型下说明数学关系。设对象 k 的大小为 b，准入价值为 A，P=A/b，插入时池租金为 Lins：

\[
Credit_k^{init}=A_k=b_kP_k,
\qquad H_k=L_{ins}+P_k,
\qquad Credit_k(t)=b_k[H_k-L(t)]_+.
\]

| 量 | 意义 | 单位 |
|---|---|---|
| P | 初始单位字节价值 | ms/byte |
| H | 对象租金耗尽阈值 | ms/byte |
| L | 本池累计压力租金 | ms/byte |
| Credit | 剩余保留预算 | ms |
| Credit/b | 剩余单位字节预算 | ms/byte |

经典 Landlord 在容量不足时按对象大小扣减 Credit：令 δ=min(Credit/b)，每个对象扣减 b·δ，等价于 L 增加 δ；零 Credit 对象成为驱逐候选。这里的压力租金不是墙钟时间自然流逝。缓存命中时的续额规则也属于算法定义的一部分。[Neal Young：Online paging and caching，Landlord 伪代码](https://www.cs.ucr.edu/~neal/publication/Young08Paging.pdf)

例如 b=16 MiB、A=30 ms、P=1.875 ms/MiB、Lins=4 ms/MiB，则 H=5.875 ms/MiB。L 升至 5 时，Credit=14 ms；L 升至 5.875 时，Credit=0。**H=Lins+P 是阈值，不能直接称为剩余 Credit。**

### 为什么这个关系还不是完整的 AegisKV Credit 算法

1. **价值变化：** Slack、当前生成进度、恢复路径和共享引用会改变 P。继续沿用插入时 P 会过时；每次观测就设置 H=L+P 则会反复续额，把“被检查”误当成“获得新保留预算”。
2. **共享闭包：** 删除前缀可能影响多个请求和多个后代。闭包之间可能重叠，不能把各 chunk Credit 简单求和当作准确删除损失。
3. **异步失败：** 试探准入、复制失败、撤销以及真正物理释放之间有时间差。租金在何时提交、失败是否回滚，必须有显式事务语义。
4. **准入与强制回收：** Credit=0 只是一种排序/老化信号。普通替换仍须检查完整净收益和前缀依赖；前台硬收缩即使遇到正 Credit 也必须能撤销安全对象，FreeACK 与 read pin 规则仍然有效。

所以，不能仅补上 `Credit=b×Priority` 就宣称动态、共享前缀算法已经定稿。经典模型的证明不自动覆盖这些扩展。

## 4. 本轮建议与尚待选择的部分

**建议保留当前 revision 3 的边际收益/删除损失决策。** 把 Priority 明确为当前状态下的收益密度，以完整替换净收益作最终准入依据。保留或移除历史 Credit 是策略选择，当前尚不能把它画成主线中的已确定步骤。

若希望继续使用租金 Credit，应将它作为独立的保留/老化策略，先定义刷新事件、累计租金提交规则以及共享闭包的处理，再与当前无历史 Credit 的策略进行同工作负载比较。若只是把当前 A 改名为 Credit，则二者只是同一个数，并没有增加历史预算机制；应避免让读者误以为采用了 Landlord。

## 5. 对应文件与检查

- 当前元数据和当前收益计算：[prefix_frontier.py](../../../../../python/moonkvsim/aegiskv/prefix_frontier.py)。
- 独立层准入入口：[revision_runtime.py](../../../../../python/moonkvsim/aegiskv/revision_runtime.py)。
- 旧版 P、H、L：[rental_value.py](../../../../../python/moonkvsim/aegiskv/rental_value.py)。旧版还存在加权复用/LRU 项，不能把它们与 revision 3 的 Φ 默认混用。
- 当前完整协议：[算法 2 / 3 五页图](../algorithm-flows-v3/README.md)。
- [生成器](build_request_flow.py) 和 [源码/导出哈希清单](MANIFEST.json)。生成器复用五页图的原生 Draw.io 排版组件，官方 CLI 导出并检查 XML、PDF 中文与嵌入源文件。

```bash
uv run python benchmark/AegisKV/docs/drawio/request-lifecycle/build_request_flow.py
```
