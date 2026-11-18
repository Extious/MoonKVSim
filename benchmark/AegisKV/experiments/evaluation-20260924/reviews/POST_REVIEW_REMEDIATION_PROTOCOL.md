# 最终复审后的补充工作与证据边界

本文件记录 final Opus 5.5 评审之后的工作；不是原始预注册，也不改变 `FINAL_OPUS55.md` 的 **NOT READY** 结论。已审输入的 158 个文件在 `final-reviewed-v2-inputs/` 原样保存。新运行有自己的协议、源码快照、模型和结果，不将旧 483 条运行追溯标记成新预测器结果。

## 已完成

- Evaluation 的报告修订补入 retry queue/service 归因、结构矩阵 6/10 target 和 2/10 cohort 不利单元，以及 DMA 下 F1 的 cohort 成本。PDF 仍为 12 页技术正文加 2 页参考文献；实际复查了变化的 9–12 页彩色/灰度。该稿尚未通过新一轮外审。
- `primary-placement-attribution-v2/` 独立重建全部 90 个策略对比，核对 180 个 COMPLETE 和 820 个来源文件。单个目标的改善不能代替所有工作流的改善；普通调用的 submit-to-finish latency 不被误称为 queue wait。没有新增 DES 或独立样本。
- `walltime-predictor-training-v1/` 使用原 12 个训练 Workflow、95 个单调用 Agent，在两模型三个负载的六条健康轨迹上捕获 570 个 Context/Agent-completion 标签。按 Workflow 留一交叉拟合角色先验和回归器；同一 Workflow 的三个负载不跨折。新 guard 来自训练条件内的正向 CPM Slack 误差，使用离线、受队列影响的参考，不是反事实 WCT 上界。模型是固定的轻量文本哈希回归器；尚未验证语义编码器或自然多调用预测。
- `../low-dma-postreview-v1/` 完成 24 个新增条件：系数 0.002/0.005/0.01/0.02 × Restart/DRAM/AegisKV × F0/F1。原 0/0.05/0.1 的 18 条仅引用，不重复算成新增样本。所有新流的字节和资源速率约束通过独立检查；保留每 host 的 D2H payload bytes/s，分母为整条运行窗口。仍使用旧 service proxy；不是新预测器结果、硬件校准或实测故障率。完整封存见 `PACKAGE_COMPLETE.json`。

## 正在独立推进

| 包 | 固定比较与规模 | 能回答的问题 | 不能推出的结论 |
|---|---|---|---|
| `../walltime-primary-v3/` | 原 180 个模型/负载/策略/故障条件；同 62 Workflow、原顺序和到达时间、同五个逻辑 80% 故障；仅换为已训练 walltime predictor、对应 role prior 和训练 guard | 修正预测目标后，原主矩阵的保护、流量、恢复和 WCT 是否改变；六条健康 none 轨迹的外部留出预测误差 | 不把测试误差反馈用于调参；不证明语义编码、多调用预测、连续批处理或真实硬件收益 |
| `../native-transfer-postreview-v2/` | 三模型各三文档；两个 M；四 residency 策略；三 H2D 带宽；四声明的计算参数，共 864 场景 | 原生因果 query 需求下，给定准备好的 checkpoint/辅助状态，first-L raw-KV 驻留怎样影响传输与 KV-ready 时序 | 非 native 端到端 WCT；不含选择器/压缩/metadata 准备成本；不是 current runtime 的 LoadBatch 时间粒度复现；层/query/参数点不当独立样本 |
| `../quota-pressure-postreview-v1/` | 原四完整 Workflow；六策略、三个 HBM margin、两个 DMA 参数、F0/F1，共 72 条 | 在由最大声明 foreground 需求定义的小 allocatable HBM pool 边界下，实际 ceiling/pressure 是否触发，以及动态与安全固定配额的差异 | FCFS 不是连续批处理；小 pool 是构造的容量干预，不是实测 80GB GPU 压力；没有发生的 pressure 不可声称已验证 |

Native 的 prepared-only v1 保留未执行；独立审查发现统计和复用绑定问题后，在任何 matrix 时序结果产生前修正并另存 v2。条件没有按观察到的收益调整。所有 residency 策略共用同一后台顺序；future-frequency Oracle 只作为非因果参考，不称延迟最优。

Quota 比较的 pool 为 `max(prompt + declared output-limit footprint) + reserve + margin`，当前四 Workflow 对应最大 foreground 5,039,327,808 B、reserve 2 GiB、margin 0/32/128 MiB。所有请求必须可单独放入。固定 32/128/4096 MiB comparator 在控制窗口重新应用 `min(fixed target, live safety ceiling)`，与动态策略共享实际账本、回收和 reader lease 规则；不能故意采用越过 reserve 的不安全对手。该实验使用已训练 8B walltime 模型及 guard，保留负值和 null。

## 仍需用户范围决定

用户此前要求“前面的内容暂时不需要修改，只关注 Evaluation”。因此前文仍保持原字节。七项逐句收窄提案在 `FINAL_CLAIM_CHANGE_PROPOSAL.md`，已请求用户确认具体范围；没有答复不能视为批准。提案中第七项描述的是已审旧 service proxy，若未来获准应用，应根据新版本实际完成的证据重新写对应句子，不能用旧描述概括新模型。

补充模拟的完成、账本 PASS、图像可读和披露负结果，都不自动意味着三项中心贡献已获验证或论文已达到投稿标准。全部新包完成后，应重写当前 Evaluation 的版本边界、重新审查实际排版，并用实际输出进行下一轮独立评审；不能要求评审给出预定的正面结论。
