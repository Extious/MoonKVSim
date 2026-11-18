# SlackLandlord：简化流程与符号说明

[单页 PDF](slacklandlord-lazy-refresh.drawio.pdf) · [可编辑 Draw.io](slacklandlord-lazy-refresh.drawio) · [PNG](slacklandlord-lazy-refresh.drawio.png)

流程图保留单列主线、四个菱形判断和两条循环。公式仍在相应流程框内，图底附符号速查。

本轮只简化图文表达：序列编号、共享引用集合编号、版本号、重复池下标、恢复时间的多重下标，以及 Gate / Refresh 等函数缩写改为简短中文；保留租金、Credit、Lazy Refresh 与严格准入判断。**图示仍为设计方案，未修改算法代码。**

## 统计口径

图中保留 **10 类核心记号**，另有 **3 个对象代号**。带不同下标的同一含义只计一类，例如 G_x、G_y、G_k 均属于 G。赋值、集合操作和比较符号单独说明，不计入核心量。

每次流程只处理一个指定目标池，Peer HBM 与 DRAM 分别执行，因此省略所有重复的池下标。创建预演状态后，Q 和 L 均指临时副本；通过最终检查才提交，拒绝时丢弃。这个约定用于省去持久状态 / 临时状态的两套字母，并未合并实际账本。

## 核心符号表

收益相关量必须使用一致的时间单位；下表用“时间”统称秒、毫秒等选定单位，B 表示字节。租金是按价值密度计的预算，不是货币租金。

| 符号 | 含义 | 类型 / 单位 | 在决策中的作用 |
|---|---|---|---|
| Q | 当前合法淘汰前沿的最小堆 | 有序候选容器 | 按安全下界选择下一检查对象；不是 FIFO 队列，也不把所有内部 chunk 都全局排序。 |
| Y | 本次预演拟淘汰的物理 chunk 集合 | 集合 | 可包含多块；用于累计可释放字节及计算整体驱逐损失。 |
| G_k | 保护 chunk k 的当前收益 | 时间 | 由该块减少的超 Slack 损失及共享请求贡献确定；是 Priority 的分子。 |
| P_k | chunk k 的每字节 Priority | 时间 / B | P_k = G_k / b_k；同等字节成本下，越大表示保护价值越高。 |
| b_k | chunk k 的实际分配大小 | B | 用于计算 Priority 与实际容量，包含实际分配粒度的影响。 |
| L | 目标池累计租金 | 时间 / B | 容量压力下推进；其他量不变时，L 增大使剩余 Credit 减少。 |
| H_k | chunk k 的租金阈值 | 时间 / B | H_k = 入池租金 + P_k；当前 L 达到该阈值时，该块剩余 Credit 为零。 |
| credit_k | chunk k 扣租后的剩余价值预算 | 时间 | credit_k = b_k × max(H_k − L, 0)；为零仍须满足前缀、读取等条件才能淘汰。 |
| Θ_x | 新候选 x 允许的 victim 阈值 | 时间 / B | 在预演开始时固定为 L + P_x；仅允许 H_y < Θ_x 的 victim，相等时拒绝。 |
| D_Y | 淘汰整个集合 Y 的当前整体损失 | 时间 | 最终要求 G_x > D_Y；共享与前缀依赖可能使其不同于逐块 G 的简单求和。 |

H 与 Θ 保留为两个记号：H 属于已有 chunk 的租金状态，Θ 属于本次新候选的准入判定。预演期间租金可能推进，但已确定的 Θ 不随之改变。

## 对象、操作和术语

| 记号 | 含义 |
|---|---|
| x | 当前准备备份的新 chunk：已完整生成、尚未在本层得到对应保护。 |
| y | 当前从 Q 中取出并检查的淘汰候选。 |
| k | 任意 chunk 的统称，用来书写通用公式；不是额外队列。 |
| ← | 赋值或更新。 |
| ∅ | 空集合；Y ← ∅ 表示尚未选择 victims，Q = ∅ 表示没有可继续检查的候选。 |
| Y ∪ {y} | 把物理 chunk y 加入淘汰集合；同一物理对象不重复计容量。 |
| max(a, b) | 取两者较大值；max(…, 0) 把负值截断为零。 |
| <、>、= | 严格小于、严格大于、等于；阈值相等不能通过严格准入条件。 |
| Slack | 请求的时间余量，与恢复时间采用相同单位。 |
| 入池租金 | 当前租约开始时记录的池租金。普通价值刷新沿用该值，不重新发满 Credit；真实复用是否开启新租约仍待定。 |
| ACK | 副本复制的完成确认；必须完整且版本有效，才可发布可恢复备份。 |

## 三个关键公式

**请求级 Slack 到 chunk 级价值：**

单请求贡献 = max(保护该块前的恢复时间 − Slack, 0) − max(保护该块后的恢复时间 − Slack, 0)。

两次恢复时间来自同一成本快照，并考虑可恢复的连续前缀。这计算的是当前 chunk 带来的边际改善；不会把整份请求的紧迫度重复发给所有 chunk。多个请求共享该物理 chunk 时，先按选定规则汇总各请求贡献得到 G_k，再计算：

\[
P_k = G_k / b_k.
\]

图中的“汇总”暂未固定为求和或取最大值；它必须与最终整体损失的计算一致，也没有因此恢复旧版的命中率 / LRU 加权项。

**租金与剩余 Credit：**

\[
H_k = \text{入池租金} + P_k,\qquad
credit_k = b_k\max(H_k-L,0).
\]

租金只在容量压力下推进；普通刷新改变当前价值而不重置入池租金。Q 只暴露合法尾块，不代表前面的 chunk 可以丢弃其租金与价值元数据。

**严格准入：**

\[
\Theta_x=L+P_x,\qquad H_y<\Theta_x,\qquad G_x>D_Y.
\]

Θ 在预演开始时计算一次。D_Y 必须按完整 victim 集合、共享引用和前缀依赖计算；在共享场景中，要计入新保护 x 对驱逐损失的影响。G_x 与 D_Y 必须属于同一决策快照和损失模型，不能把不同快照的 Priority 直接相加减。

## 图中省略符号但仍保留的约束

“刷新后仍为最小项”要求 y 的最新 H 不大于其余所有候选的安全下界。剩余堆为空时，这一比较通过；进入取候选步骤前 Q 已为空则直接暂停。比较失败时，把 y 的下界更新为刚计算的 H，再重新入堆。

元数据变化可证明价值不降时保留原下界；可能降值时修复受影响的下界。仅更新版本号并不够。一次比较使用固定快照，分组条目必须展开到实际物理候选，且索引须覆盖全部合法候选。

每选中一块都更新 Y、预演租金和拟释放空间，再暴露新的合法尾块。共享前缀可能影响多个前沿，不能简单把“每请求一个尾块”当作完整共享索引，也不能重复释放共享对象。候选自身必需的前缀及读取中的对象不得被驱逐。

图中的前置检查包括源可读、复制许可、时限、quota、前缀合法性、读取占用、未完成复制 / 回收账本及版本。规划空间不等于已释放的物理地址；分配须等待必要的释放确认。

通过后沿旧版顺序淘汰 Y、提交租金、分配并复制，完整有效 ACK 后才发布保护。失败不自动恢复已淘汰的 Y；暂停的是本层备份，主推理和另一层独立继续。共享汇总、续租和安全下界索引仍需实现与验证，图示不代表新旧实现完全等价。

## 来源与兼容性检查

流程骨架参考 [Mooncake 旧设计](/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/design/current_design.md) §2.3—2.4，以及 [slack_landlord.py](../../../../../python/moonkvsim/aegiskv/slack_landlord.py)、[rental_value.py](../../../../../python/moonkvsim/aegiskv/rental_value.py)、[lazy_refresh.py](../../../../../python/moonkvsim/aegiskv/lazy_refresh.py)。共享前缀参考 [prefix_frontier.py](../../../../../python/moonkvsim/aegiskv/prefix_frontier.py)。

已修复部分 Draw.io 编辑器打开时的 `setId is not a function`：原节点 ID `pop` 与旧版 mxCodec 的 Array 对象表中的 `pop` 方法冲突。所有非根节点及其引用现统一加 `slr-` 前缀；这个兼容性修复继续保留。原因可对照 [mxCodec 对象表实现](https://raw.githubusercontent.com/jgraph/mxgraph/master/javascript/src/js/io/mxCodec.js) 与 [mxCellCodec 的 setId 调用](https://raw.githubusercontent.com/jgraph/mxgraph/master/javascript/src/js/io/mxCellCodec.js)。

[verify_compatibility.cjs](verify_compatibility.cjs) 使用真实 `mxgraph@4.2.2` 解码器复现原冲突，再验证修复文件的全部节点与引用，以及编辑、保存、重新加载。[COMPATIBILITY.json](COMPATIBILITY.json) 记录验证结果及所测源文件哈希。验证所需的 `mxgraph@4.2.2`、`jsdom@26.1.0` 可放在临时目录，通过 `NODE_PATH` 提供，无需加入项目依赖。


[build_diagram.py](build_diagram.py) 生成可编辑原生 XML，并通过官方 Draw.io CLI 导出 PNG / PDF。[MANIFEST.json](MANIFEST.json) 记录来源和输出哈希、符号统计与验证结果。

```bash
uv run python benchmark/AegisKV/docs/drawio/slacklandlord-lazy-refresh/build_diagram.py
```
