# AegisKV: Slack- and Sparsity-Aware KV Backup for Fault-Tolerant Multi-Agent LLM Serving

<!-- EuroSys 2027 投稿雏形（中文写作，图内文字为英文，可直接替换进 LaTeX 模板）。
     证据分级：measured = 真实观测；analytic = 锚定在测量参数上的闭式模型；illustrative = 为固定实验设计而生成的模型数据，图上带红色水印，投稿前必须用模拟器/实机数据替换。
     当前设计：请求可并行 retry，H2D 与计算可重叠；Slack 只决定备份优先级，不规定请求级串行恢复顺序。
     Motivation 图 1：(a) 分支时间差，(b) 五分支 Workflow 结构，(c) WCT 损失；图 2 为独立重算代价图（原图 4）；原调研图 3 撤出本节并保留为资料。设计章暂保留原编号，全文整合时同步：图 5 架构，图 6 集中度（§3.3，实线，256/512-query 窗口），图 7–9 机制。支撑方法选择的 Observation 由 §3 承担。2026-09-15 编号的原图 5（重放所需比例）撤出正文，恢复并集分析保留于 §3.3；旧串行 cascade 与评估图仍为历史材料。
     图源：paper/figures/（MANIFEST.json 区分当前图与历史输出）。
     生成脚本：experiments/scripts/paper/render_motivation_row.py（图 1(a)/(c)、图 2）、build_motivation_workflow.py（图 1(b)，Draw.io 原生导出）、render_draft_20260915.py（原单栏图与图 6–9）、build_draft_overview.py（图 5）；
     模型数据：experiments/native-sparse/20260915/（MiniCPM4-8B、NOSA-1B 的选块轨迹、prefill 与重放时延、交叉模型统计）；
     工作流轨迹：experiments/data/motivation-real-cc/（CC/Weka 轨迹的分支重建）。
     正文引用的每个数字都能在上述脚本的输出（MANIFEST.json、*.json、*.csv）中找到。 -->

**作者：** 待定 · **单位：** 待定

## Abstract

多智能体（multi-agent）应用把一个用户任务展开成由多个 LLM 请求组成的依赖图（workflow），用户感知的是整张图的完成时间（Workflow Completion Time，WCT），而不是某一个请求的时延。GPU fail-stop 故障会让该卡上所有请求的 KV cache 一起丢失；随着 agent 上下文越来越长，重算这些 KV 需要数秒到数十秒。现有 KV 备份把每个请求当作同等重要、把请求内部每个 KV 块当作同等重要，而 Peer GPU 的空闲 HBM 远不足以容纳全部 KV。

本文提出 AegisKV，一个面向多智能体工作流、适用于原生稀疏注意力模型的 KV 备份与恢复系统。它采用两级保护优先级：请求之间，用 workflow 的 Slack（最多可以晚多久而不推迟 workflow 的完成）区分不备份、只备份到 DRAM、Peer HBM + DRAM 三层，优先给低 Slack 请求分配有限的 Peer HBM，并按该请求仍能减少的恢复等待限制配额；请求内部，以 `(layer, block)` 为单位，用层序与稀疏热度选择驻留块，恢复时按热度预取、按选择器的实际需求补取。请求可以并行 retry，H2D 与计算可以重叠，AegisKV 不规定请求级串行恢复队列。系统只读取稀疏 kernel 已有的选块索引，不改变模型的注意力选择。

在 124 个真实多智能体工作流中，91% 的并行分支持续时间差超过在 A100 上实测的 128K 前缀重算时间 22 s，说明不同分支的执行时间显著不均衡；恢复是否被吸收仍取决于具体请求的 Slack，而非持续时间差本身。在两个公开的原生稀疏注意力模型（MiniCPM4-8B 的 InfLLM-v2、NOSA-1B）的真实选块轨迹上，最热 20% 的 `(layer, block)` 字节分别承担 66% 和 90% 以上的访问，而重放一个 64-token 未密封块只需一层 44%–77% 的字节经过恢复路径。闭式流水线模型表明，在拥塞的 6.25 GB/s 路径上，这一顺序把 32K 上下文的装载等待从 115 ms 降到 77 ms（MiniCPM4-8B）或 20 ms（NOSA-1B），MiniCPM4-8B 再将前 17 层的 Top-k 热块驻留 Peer HBM 后，计入预测未命中的按需补取，等待约为 20 ms。这些测量与解析结果支撑两级保护的动机；并行恢复下的端到端 WCT 收益、前台干扰与备份流量仍需通过配对的无故障/故障实验验证，本文不沿用旧串行队列模型的收益数字。
