# `requests.json` 数据集审计与选择

审计日期：2026-08-31  
目标：Qwen3-8B、DP-only、全局虚拟时钟，比较 AegisKV 与 Mooncake 在
`GPU_FAILURE` 下的完整 workflow WCT ECDF。

## 结论

**最终选择：FanOutQA `dev` split，采用 Evidence-Provided 方式构造确定性的
fan-out/fan-in workflow。**

它是真实人工编写并公开发布的 QA 数据集，不是生成的执行 trace：

- 官方仓库：<https://github.com/zhudotexe/fanoutqa>
- 数据许可证：CC BY-SA 4.0；代码许可证：MIT
- 冻结 revision：`989f4c40d9deea1ecb0897d7a17a9c0fe20d5c33`
- 文件：`fanoutqa/data/fanout-final-dev.json`
- SHA-256：`b62a9797732c716e6b17ba4086f277d154d747ce2fa01614cb76a3372e7fb88c`
- 完整任务：310

当前状态是 `READY_FROZEN_FANOUTQA_WORKLOAD`。已冻结排序前缀中的 192 个候选并
得到 171 个合法整任务，最终按预注册的 `sha256(task_id), task_id` 顺序选取前 160 个；
共 1,304 条模型请求，最大请求 86,214 tokens，未启用 evidence 分段，也没有截断、
padding、删分支或跨任务拼接。正式 workload、manifest 和 Wikipedia evidence snapshot
的 SHA-256 均已写入 `requests.json` 与 workload manifest。

源文件并非所有 evidence 都可冻结：候选前缀中 20 个任务含 `###TBD###` evidence，
另有一个声明的 oldid（`1156598522`）被 MediaWiki 官方 API 判定为 `nosuchrevid`。
这些任务按整任务排除；没有回退到 Wikipedia 当前页面。最终 evidence snapshot 含
1,038 个精确 revision。

## 为什么选 FanOutQA

`dev` 中每个问题都提供人工 decomposition。subquestion 有稳定 ID、问题、答案与
`depends_on`；最终入选任务的每个 leaf 均有可读取的 revision-pinned Wikipedia
evidence。它允许我们直接构造：

1. 根问题与公共 system prompt；
2. 满足 `depends_on` 后并行 admission 的 researcher 分支；
3. 每条分支读取其公开 evidence 页面并形成模型请求；
4. 所有顶层结果完成后的最终 aggregation 请求。

对冻结源文件的只读审计结果：

| 指标 | 结果 |
|---|---:|
| 完整任务 | 310 |
| subquestion / task，p50 / p90 / max | 6 / 10 / 46 |
| 最大并行宽度，p50 / p90 / max | 5 / 8 / 45 |
| 具有并行宽度至少 2 的任务 | 310 / 310 |
| 映射后具有最终 fan-in 的任务 | 310 / 310 |
| 源数据 evidence 引用 / 唯一 Wikipedia page | 2,172 / 1,563 |
| 已评估候选 / 通过候选 / 最终 workload | 192 / 171 / 160 |
| 最终请求 / 最大请求 tokens | 1,304 / 86,214 |
| 冻结可读 revision / 永久无效 oldid | 1,038 / 1 |

这类 workflow 适合 AegisKV failure 实验：单个任务包含多个并行分支，失败分支
必须恢复后才能通过最终 join；Evidence-Provided prompt 可形成真实的长输入，
使“恢复已生成 KV”和“重新 prefill evidence”之间存在可测的时间差。failure 绑定
必须由 task ID 与 seed 的预注册规则决定，不能挑最长分支或结果最有利的分支。

## 必须明确的证据边界

FanOutQA 是公开任务数据集，**不是历史 serving trace**。因此：

- 问题、人工 DAG、答案和 evidence 来源是真实公开数据；
- 请求 prompt 由公开字段按冻结模板确定性构造，不声称是原作者运行过的多智能体
  prompt；
- 数据集没有 LLM 调用时间或工具等待时间；适配器协议固定为不虚构 tool delay，
  WCT 表述为模拟的 model-serving workflow completion time；
- 模型时长来自 `engine.json` 的模拟参数，不能称为实测延迟；
- KV block identity 必须由 Qwen3-8B tokenizer 输出和冻结模板计算，不能沿用其他
  tokenizer 的 hash；
- 首轮对原始 evidence prompt 做 131,072-token guard；若通过的独立 task 少于 160，
  才启用确定性的 evidence 分段回退，禁止按比例伪造 token 数、截断、padding、
  删除分支或跨任务拼接；
- seed 只用于 failure 绑定与 tie-break，同一 task 的多个 seed 不能冒充独立 ECDF
  样本。

## 主要公开候选比较

| 候选 | 优点 | 排除或降级原因 |
|---|---|---|
| **FanOutQA dev** | 310 个真实人工任务；显式 decomposition/depends_on；公开答案与 revision-pinned evidence；CC BY-SA 4.0 | 不是历史 serving trace；请求与时序必须确定性构造并明确标为 modeled |
| NVIDIA ODR | 真实 Open Deep Research trace 结构，显式 parallel start/end | 官方只发布了方法、统计和一个 Coder 示例；100 条 ODR artifact 不可下载 |
| DiscoPosse Weka with subagents 051826 | Apache-2.0；96 条真实 production session；绝对时间与 64-token hash；36 条含 subagent | 严格整任务 128K guard 下通过的 26 条全部没有 subagent；保留 fan-out 的任务均越界 |
| SemiAnalysis Weka 062126 | Apache-2.0；真实 Claude Code；公开 KV hash | 严格完整且 128K 合法的 fan-in workflow 只有 4 条，不足以支撑任务级 ECDF |
| PatronusAI TRAIL / GAIA | MIT；117 条公开 OpenDeepResearch trace；完整任务边界 | 审计到的逻辑 LLM 调用为串行 delegation，不是所需并行 fan-out/fan-in |
| UW TraceLab | 大规模真实公开 coding trace，token/cache/timing 信息丰富 | subagent spawn/join 由时间窗推断，没有 source-observed 的完整任务 DAG |
| synthetic OCEL / generated agent traces | 显式并行、样本多、格式整齐 | 结构与时序由生成器制造，不满足真实数据要求 |

对 `DiscoPosse/cc-traces-weka-with-subagents-051826` 的审计固定在 revision
`a44978b737db7652e67a5d0cea658cb2fe2afe25`，原始 `traces.jsonl` SHA-256 为
`93f7e9e7d4c888ffb4e73423c88dc2184a54a72c52b8630b8f9fcbe78f11d521`。
其 96 条 trace 中 36 条含 subagent、最大并行宽度 15；但以源 token count 做
保守的 `prompt + output <= 131072` 整任务 guard 后，26 条通过者均无 subagent。

## 派生 workload 的通过门槛

1. 从上述 revision 取得官方 `dev` JSON并验证 SHA-256、310 个唯一 task ID 和
   CC BY-SA 4.0 许可证。
2. 冻结数据集指定 revision 的 Wikipedia evidence，记录 snapshot/revision 与
   每个页面内容 hash；不从当前在线页面静默获取新版本。
3. 冻结 prompt 模板与 Qwen3-8B tokenizer revision；每个模型请求记录 token IDs、
   64-token policy-source block hash、prompt/output token 数。
4. 按人工 `depends_on` 生成因果边，并增加唯一 final aggregation sink；不得根据
   运行结果改变 DAG。
5. 先对未经分段的原始 prompt 做整任务 128K guard。实测排序前 192 个候选中 171 个
   完整通过，已直接冻结前 160 个，未启用回退。
6. 若首轮少于 160，按 Qwen3-8B token 边界将每个超限 evidence 确定性切成多个子请求；
   每个子请求的 `prompt + output reserve <= 131072`，随后增加一个局部 fan-in 汇总该
   evidence 的分段答案。所有原始 evidence token 必须恰好保留一次。
7. 对分段后的完整 workflow 重新执行 128K guard；若仍少于 160，停止主 ECDF。
8. manifest 记录 source revision、source/data/license hash、模板与 tokenizer hash、
   首轮与回退后的通过/拒绝 task ID、分段边界、局部 fan-in DAG、每个 task 的
   fan-out/fan-in 审计和派生 artifact SHA-256。
9. AegisKV 与 Mooncake 使用完全相同的 task、workflow concurrency、failure branch、
   failure progress 和 seed；同时报告 WCT、恢复延迟、恢复字节与 recompute token。

当前 `replay.workflow_concurrency = 16` 表示闭环同时 admission 最多 16 个完整问题
workflow。workflow 内部的 researcher fan-out 不额外占 workflow slot；只有 final
aggregation 完成后才释放该 slot。

正式 paper sweep 使用 `seeds = [0, 1, 2, 3, 4]`。seed 是 failure 绑定和确定性
tie-break 的五个独立重复，不改变冻结的 160 个 workflow，也不把
`workflow x seed` 计为更多 ECDF 任务；统计以 seed-level 配对观测为采样单位。
