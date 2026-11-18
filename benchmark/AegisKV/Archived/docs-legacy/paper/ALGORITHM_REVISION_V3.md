# 算法 2、算法 3 修订记录

2026-09-06。完整定义及条件性证明位于[专利修订技术交底](../patent/ALGORITHMS_2_3_REVISION.md)，
并同步到 [Word](../patent/AegisKV-算法2-3修订技术交底-v3.docx)、
[论文设计章节](../../paper/sections/system-design.tex) 和 [论文 PDF](../../paper/main.pdf)。

| 问题 | 当前修订 |
|---|---|
| 后插入尾块是否阈值一定最高 | 给出反例；取消历史 credit/rent，计算当前删除闭包的真实联合损失 |
| 生成中低价值请求是否继续备份 | 可以暂停该 tier；相关状态改变后从第一缺口重评估，不永久封闭，不影响正常生成 |
| 单块零收益堵住有收益前缀 | 对已生成连续块成组准入，受源可读、复制预算、有效期和 staging 上限约束 |
| 多轮共享与驱逐 | 内容身份和消费者分离；共享物理字节只计一次，删除影响所有活跃引用；完成轮只保留有界零权重 TTL |
| 删除旧块后新复制失败 | staging 在 Q 内，正常替换复制成功后才切换前缀；失败保留旧保护 |
| 回收返回丢失/迟到 ACK | generation 标记、回收任务持续保留、物理 ACK 前不减账 |
| AIMD 滞后于 burst | 分配前事件检查，预留前台/增长界/allocator margin，立即收缩，稳定且有需求才限速增长 |
| 低显存占用仍可能干扰 | 联合限制 HBM、源/目标/链路带宽及单个 DMA batch，并要求有域内干扰证据 |
| 怎样定义几乎零开销 | 默认 1% 可配置目标；配对无故障实验中 p99 TTFT、p99 请求 TPOT 和 goodput 损失的一侧置信上界 |

## 已经执行的验证

通过 159 个 revision-3 参考实现测试和 33 个旧 Landlord/AIMD/专利契约回归。
新增三个模块通过 Ruff 和严格 mypy。参考测试包括 81 个收益组合和 41 个内存需求枚举，
以及两层独立准入/复制/确认、紧急收缩、回收 ACK 丢失及重试的组合事件。
确切命令、日志、JUnit 和源码哈希见
[VALIDATION.json](../../experiments/results/algorithm-revision-v3/VALIDATION.json)。

```bash
uv run python benchmark/AegisKV/experiments/scripts/validate_algorithms_revision.py
sh benchmark/AegisKV/paper/build.sh
```

这证明参考状态机在这些输入中的行为，不是全状态空间形式验证，不是数据面性能试验。
新模块没有接管 `experiment.py` 中的旧 `mooncake_prompt_v1` 路径，也没有修改 native C++。
`revision_runtime.py` 把新 pool、前台预算和路径令牌连接为可执行串行事件适配器。

## 论文和证据的版本规则

算法 2 为 `PrefixAdmission`，算法 3 为 `ForegroundBudget`。正文删除了把它们当成已经
执行过旧实验的描述；摘要、引言、实现、实验方法、局限和结论明确分隔两个版本。
System Overview 的 Draw.io 源与官方导出同步，原生 Mooncake 的中文架构图仍描述真实旧实现。
统计图和 170 次原始模拟产物不变，不从旧数据推导新算法收益。

正文中与伪代码重复的说明已压缩，完整推导保留在技术交底。当前 PDF 为 14 页：12 页技术正文、2 页参考文献，
含 10 幅图和 3 个算法；未缩小正文字号。满足页数要求不代表已具备新算法的实机/性能证据。发布状态见 [REVISION_STATUS.json](REVISION_STATUS.json)。
旧交付包及其 PASS 审计保留为旧稿历史，不能用于当前 PDF。

下一轮研究证据需要：实际 allocator 借页与分配前 hook、source lease/取消/释放 ACK、
native 共享对象/组替换接入、匹配负载下的实机干扰认证、冻结新执行源码后的新实验。
算法的局部严格改善不等于工作流延迟改善；1% 是待认证目标，没有现成实机证书。
没有任何技术修改能够保证不被评审质疑，修订的目标是使假设、行为、证明与证据互相一致。
