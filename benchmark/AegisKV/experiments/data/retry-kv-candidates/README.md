# Figure 3(b) 选块策略的离线诊断

此分析只在已有原生稀疏访问轨迹上重新排序候选，不执行模型 forward、故障注入、KV 搬运或新增 GPU 实测。当前论文及 Figure 3(b) 未替换。

## 口径

- 三个模型各 3 个已使用过的 PG19 文档，每文档一个 checkpoint；这是探索性分析，不是新的独立测试集。
- 历史 32,768 token，历史末尾 512 Query 可用于打分，随后 64 Query 仅用于评估。
- 每层 512 个历史块，选择 205 个（40.039%）；每块为 64 token、包含该层所有 KV heads。
- 必需 sink/local 块、同分时的位置排序和跨层/文档聚合均与原图一致。
- 原始频率、最近位置、理想上界的文档均值和范围已逐项复现，误差小于 1e-12。
- 所有源文件哈希与原图记录核对；新增候选不使用目标尾部的选择。

## 均值覆盖率（%）

| 方法 | NOSA-3B | MiniCPM4-8B | SeerAttention-Qwen3-8B |
| --- | ---: | ---: | ---: |
| 原始 512-query 频率 | 77.82 | 53.57 | 43.02 |
| 最近 token 位置 | 59.73 | 50.93 | 41.96 |
| 最近 64-query 频率 | 79.35 | 55.99 | 43.14 |
| 最近 128-query 频率 | 79.49 | 55.20 | 43.16 |
| 时间衰减频率（半衰期 128 Query） | 78.75 | 54.67 | 43.14 |
| 窗口出现计分（半衰期 128 Query） | 79.28 | 54.50 | 42.83 |
| 原图理想上界 | 93.75 | 58.98 | 43.28 |
| 保留必需块的理想上界 | 93.75 | 58.98 | 43.28 |

## 方法与解释

- 64/128-query 频率：仅缩短观察窗口，仍按原生选择次数排序。
- 时间衰减频率：把过去 512 Query 分为 8 个 64-query 窗口，按离当前的距离衰减，半衰期为两个窗口。
- 窗口出现计分：一个块在同一个 64-query 窗口内被选多少次都只记一次，然后使用相同衰减。Seer 的 native query block 本来就是 64 Query，保留这个语义。
- 所有候选共同列出，没有在目标尾部调参；按模型挑最高值只用于描述此次探索，不能作为已验证的自适应策略。
- 简单窗口调整产生小幅提升；Seer 的窗口出现计分下降，保留该负结果。
- 两种理想上界在这组数据中相同。上界受当前每层固定配额和整组 KV-head 放置对象约束。

## 其他可借鉴方向（尚未在本地验证）

- [SnapKV](https://arxiv.org/abs/2404.14469)：末尾观察窗口、按 head 的 attention score 聚合与邻域 pooling；这里的原生选块频率并不是 SnapKV attention score，现有 trace 没有保存完整分数，不能称为 SnapKV 复现。
- [Ada-KV](https://arxiv.org/abs/2407.11550)：借鉴按 head 分配预算的思路。AegisKV 可评估以物理 KV head/group 为对象的放置，上界、字节预算、索引和传输成本需重新比较；GQA 中共享的物理 KV 不按 query head 重复存储。
- [Quest](https://proceedings.mlr.press/v235/tang24l.html)：使用已知 Query 和页 min/max key 摘要估计页重要性。
- [InfiniGen](https://www.usenix.org/conference/osdi24/presentation/lee)：用当前层输入与下一层的部分 Q/K 提前估计下一层需求。这类运行时信号适合评估恢复过程的取数，不能直接当作 checkpoint 时已知未来 Query。
- 借鉴上述评分或预算分配时，未驻留的原生必需 KV 仍须从有效副本取得；不能把压缩论文的质量容忍度当作恢复正确性约定。

## 可复现文件

- `protocol.json`：固定候选方法和统计口径。
- `documents.csv` / `layers.csv`：全部文档和层结果。
- `summary.json`：文档均值、最小值和最大值。
- `source-sha256.json`：原始 trace、原始汇总及分析脚本哈希。
- 分析脚本：`benchmark/AegisKV/experiments/scripts/paper/analyze_retry_kv_candidates.py`。
