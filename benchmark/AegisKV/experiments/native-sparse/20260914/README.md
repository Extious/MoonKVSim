# NOSA-1B 真实原生稀疏选块轨迹

2026-09-14。本次已经在 RTX 4090 上运行作者发布的训练后权重与原生稀疏 CUDA 内核，采集全部 28 层的逐 Query、逐 KV 组选块索引。三份真实长文本上都观察到明显的主 KV 访问集中。此目录的数据可以用于“请求内 KV 的访问价值不均匀”这一论文动机。

## 直接结果

固定历史 M=32,768 tokens，分析后续 N=512 个 Query 对历史主 KV 的选块访问。下表三个文档按官方 PG19 测试集文件名排序取前三个，在运行模型前已经固定。百分比为各自请求的实际观测，未把层或 Query 当作独立实验重复。

| 文档 ID | 最热 10% 字节：层 × KV组 × 块 | 最热 20% 字节：层 × 块，包含全部KV组 | 最热 20% 字节：token段，包含全部层 |
|---|---:|---:|---:|
| 10146 | 82.96% 访问 | 92.62% 访问 | 55.72% 访问 |
| 10321 | 80.75% 访问 | 90.27% 访问 | 52.83% 访问 |
| 10356 | 80.65% 访问 | 89.69% 访问 | 53.03% 访问 |

**“少量 KV 承担大量访问”在这批真实 NOSA 轨迹中成立，但选择粒度很重要。** 直接把一个 token 段的全部层一起保护，会掩盖不同层、不同 KV 组的热点差异。对当前系统，一个有证据支持的候选管理单位是 `(request, layer, token-block)`；能否进一步按 KV 组拆分，要由实际分配与搬运布局决定。

上述百分比是对相同窗口的观测频次进行离线排序所得，不是已经实现的在线备份策略命中率。预算按完整物理单元向下取整：32K 历史共 896 MiB 主 KV；“层 × KV组 × 块”的 10% 实际为 2,867 个 32 KiB 单元，即 89.59375 MiB；“层 × 块”的 20% 实际为 2,867 个 64 KiB 单元，即 179.1875 MiB。精确分母、字节和取整结果在 [budget_coverage.csv](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/budget_coverage.csv)。

16K 历史的结果也完整保留：最热 20% 的“层 × KV组 × 块”覆盖 81.30%–82.05% 访问；合并同层全部 KV 组后，相同 20% 字节预算覆盖 60.34%–61.80%。因此集中度不能脱离上下文长度与原生选择预算讨论。

## 三张图及图注

### 1. 实际逐 Query 选块轨迹

![真实逐 Query、逐层选块轨迹](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/figures-legacy/native-sparse-20260914-figures/native-query-block-traces.png)

固定文档 10146，M=32,768。展示后续窗口最初 128 个 Query，在预先固定的第 1、14、28 层、两个 KV 组上的真实选择。横坐标保留历史 token 原始位置；一列对应一个 64-token 块，一行对应一个 Query。蓝色为原生非局部选块；金色为原生首块或局部窗内被选中的块。**竖直蓝带表示同一历史块被许多不同 Query 反复选择**；不同面板的蓝带位置不同，显示层和 KV 组的差异。图中只显示历史块，模型实际也会选到后续窗口中已处于因果可见范围的块。

图没有人为构造分数、替换选择策略或挑选效果最强的层。完整 28 层、全部 M+N 个 Query 的索引均在 `traces/`，不止图示的 128 行。[PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/figures-legacy/native-sparse-20260914-figures/native-query-block-traces.pdf) · [SVG](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/figures-legacy/native-sparse-20260914-figures/native-query-block-traces.svg)。

### 2. 全部 28 层、三个文档的原始位置频率图

![28 层历史块访问频率](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/figures-legacy/native-sparse-20260914-figures/native-layer-block-frequency.png)

每行是一层，每列是原始位置的一个历史块。颜色分母为该层 512 个 Query × 2 个 KV 组；100% 表示这两个组的每个 Query 都选择了该块。图中没有先按热度重新排列 token 位置。右端局部窗、首块和其他位置的长期热点同时保留，不能把全部热点都解释为“语义重要”。[PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/figures-legacy/native-sparse-20260914-figures/native-layer-block-frequency.pdf) · [SVG](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/figures-legacy/native-sparse-20260914-figures/native-layer-block-frequency.svg)。

### 3. 同一请求、相同字节预算下，管理粒度的影响

![真实访问集中度及管理粒度](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/figures-legacy/native-sparse-20260914-figures/native-access-concentration.png)

两行分别为 16K 和 32K 历史；三列分别按 `(layer, KV-group, block)`、`(layer, block)`、全层 token 段统计。每条曲线是一份文档的一次真实 Prefill，按该窗口的选块频次排序，横轴为累计主 KV 字节比例，纵轴为累计历史块选中次数比例。灰色斜线是等字节均匀随机选择的数学期望，不是另跑的一组 GPU 结果。各文档均单独画出，没有误差条或伪造独立重复。[PDF](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/figures-legacy/native-sparse-20260914-figures/native-access-concentration.pdf) · [完整曲线数据](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/concentration_curves.csv)。

## 执行配置与真实性

- 模型：[作者发布的 openbmb/NOSA-1B](https://huggingface.co/openbmb/NOSA-1B)，固定 revision `7bdc33fbc1bc80b76b29689ba35ff6a7991b7dee`。发布名称为 1B；本次载入的参数数为 1,622,179,896。
- 28 层、16 个 Q heads、2 个 KV heads、head_dim=128、BF16。作者实现内部复制 Q heads 以匹配原生内核组大小；统计按真实的 2 个 KV 组计算，没有把副本算成额外组。
- 官方默认选择参数：block_size=64，topk=64，压缩窗口 32、步长 16，init_blocks=1，local_blocks=16，dense_len=0。没有调节稀疏度来制造集中现象。
- 作者代码中的类名为 `LlamaSdpaAttention`，本分支调用的是 NOSA 原生稀疏实现。保持 `output_attentions=False`，避免该代码在请求 attention weights 时回退到稠密路径。
- 源码使用 NOSA 训练后的 `A`、`delta` 门控、原生内容选择和局部性选择；这些权重全部从 checkpoint 载入。模型载入报告的 missing / unexpected / mismatched / error 项均为空。源码打印的历史标签 `Use InfLLMv2` 不代表绕过了 NOSA 门控。
- 实际执行作者的 GPU 模型实现，复用本机 SGLang 环境的 Torch；没有通过 SGLang serving 或 Mooncake 运行这次采集。
- 本机 GPU：RTX 4090，gpu10；Slurm 采集任务 **149623，COMPLETED，exit 0**。3 个文档 × 2 种历史长度 = 6 次完整 Prefill，另有 2 次采集开关验证前向。每个文档和长度仅测一次。
- 采集器对原始 `compressed_attention` 返回值做被动记录；还检查了每层两个 stage-2 调用实际得到的位掩码与选择索引一致。位掩码核对窗口为 `[M−512, M+512)`；全轨迹额外检查块级因果范围和去重。
- 开关采集的配对验证请求输出 logits 最大绝对差为 **0**；所有层输出及最终 logits 有限。这验证采集器没有改变观测请求的输出，不是模型任务准确率评测。
- 原始 checkpoint 模型代码、147 个被使用依赖树中的源文件与固定的作者发布版本逐文件核对一致。仅将作者原始 padding 工具和已编译的稀疏函数显式绑定到模型模块，绕过一个把未使用的稠密 FlashAttention 导入与必需稀疏导入放在一起的宽泛 `try/except`；未改选择、权重或 attention 数学。
- 原始配置会使 Transformers 提示 `rope_scaling` 缺少 `factor`。保留作者配置及其显式的 long/short factors 和 attention_factor，没有为消除警告修改 RoPE。本轮结果只声称这一固定发布配置下的真实访问观测，不声称复现作者质量评测。

输入来自 [PG19 官方测试集](https://github.com/google-deepmind/pg19)：

| ID | 文本 | 完整文本的本模型 token 数 |
|---|---|---:|
| 10146 | Reminiscences of Pioneer Days in St. Paul | 62,675 |
| 10321 | Dragon's Blood | 93,863 |
| 10356 | Travels in Morocco, Volume 2 | 84,122 |

各自取开头 M+512 tokens，使用原始 tokenizer，没有拼接重复文本、构造热点词或根据模型结果选样本。原始文本、输入 token 文件、来源 URL 和 SHA256 已保留。

## 统计定义

令 `S[l,g,q]` 为原生选择器给 Query q 返回的有效块索引集合。统计对象是历史区间 `[0,M)`：

```
f[l,g,b] = sum(q=M..M+N-1) 1[b in S[l,g,q]],  0 <= b < M/64
```

每次 `(layer, KV-group, Query, selected-block)` 记一个逻辑访问事件。不是 attention 权重总和，也不是 profiler 观测到的 GPU 物理访存事务。原生实现为加权分母计算两次 stage-2，统计没有据此把同一选择重复计数。

每个完整 64-token 块的主 KV 大小：

- 一层、一个 KV 组：`64 × 2(K/V) × 128 × 2 bytes = 32 KiB`。
- 一层、两个 KV 组：64 KiB。
- 全部 28 层、两个 KV 组：1.75 MiB。

896 / 448 MiB 的总量只包含 32K / 16K 历史的主 K/V，不包括模型权重、压缩 K、选择器 CIS 等辅助状态。辅助状态的完整恢复需求仍需另行建模。

每个分析窗口有 1,705,984 个历史主 KV 选块事件，6 个窗口共 10,235,904 个。不同输入总事件数相同，来自固定的 top-k、N 及因果局部窗，不表示热点位置相同。排除首块和移动局部窗后，非局部事件占 77.31%；对非局部事件重新排序，32K 条件下最热 20% 的“层 × 块”覆盖其中 89.87%–92.96%，所以集中性并非仅由强制局部窗口贡献。

## 对论文方法的支持与边界

可以写入论文的观测：**在 NOSA-1B 的三个真实长文本请求上，恢复窗口对应的历史主 KV 选块具有强烈、依赖层和 KV 组的集中性。这为按请求内部 KV 访问需求分配有限 Peer HBM 提供了实例证据。** NOSA 本身针对局部性训练；它是适合本场景的具体模型，不能据此声称所有原生稀疏模型都具有相同集中度。

这里实际运行的是完整因果 Prefill，再观察末尾 512 个 Query；没有在中途注入故障，没有验证缓存增量 Prefill 与完整 Prefill 的轨迹等价，也没有执行跨 DP reroute。输入为公开长文本，不是 Multi-Agent 工作流。图可以支持访问动机，不能单独证明 H2D、暴露等待或 WCT 改善。

同一次完整 Prefill 中，使用前一个 512-Query 窗口排行，在 32K、20%“层 × 块”预算下，对后一个窗口的离线访问覆盖为 84.90%–88.44%。这只是前后窗轨迹分析，尚未验证故障前的采集可得性、缓存路径一致性及在线管理开销，不能作为在线策略已经实现的证据。

尤其要保留这个限制：同一窗口内，“层 × 块”累计访问并集仍占历史主 KV 的 55.45%–60.62%，全层 token 段并集达到 100%。高频子集之外的冷块依然可能被请求，缓存未命中的依赖仍可能阻塞。后续应将频率、首次需要时间与分层预取时间线共同用于估计**减少多少暴露等待**，再与 Slack/WCT 价值及租金相连。

## 原始数据与本机复算

- [运行前固定的计划](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/PLAN.json)
- [所有结果摘要](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/SUMMARY.json)
- [逐层统计 CSV](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/per_layer_statistics.csv)
- [运行环境和权重信息](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/measured-environment.json)
- [权重载入核对](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/measured-loading.json)
- [采集开关验证](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/measured-observer-validation.json)
- [原生源码一致性核对](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/provenance/NATIVE_SOURCE_VERIFICATION.json)
- [采集日志](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/capture-149623.log)

每个 `traces/pg19-<id>-M<M>-N512/` 包含：

- `input_ids.npy`：实际完整输入；`run.json`：输入/代码来源、状态和每层核对结果。
- `layer-01.npz` … `layer-28.npz`：`selected_blocks`，形状 `[2, M+512, 64]`；前缀较短的 Query 用 `-1` 表示无效条目。模型输出 int32，落盘为经过范围检查的无损 int16。
- `layer-XX-mask.npz`：实际原生内核位掩码的核对窗口，及其 Query 起点。
- `counts.npz`：`current / previous / nonlocal_counts`，形状 `[28, 2, M/64]`。
- `statistics.json`：该请求的各粒度覆盖率及真实字节预算；`last_logits.npy`：真实前向的最后位置 logits。

```bash
cd /home/comp/zhanzhao/MoonKVSim
.venv/bin/python benchmark/AegisKV/experiments/native-sparse/20260914/analyze_native.py
.venv/bin/python benchmark/AegisKV/experiments/native-sparse/20260914/plot_native.py
```

采集代码为 [capture_native.py](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/capture_native.py)，提交文件为 [capture_native.sbatch](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/capture_native.sbatch)。脚本拒绝覆盖已完成的请求目录；新一轮执行应使用新的输出目录。此处的挂钩同步和文件压缩会影响运行时长，因此日志中的耗时明确不是恢复性能基准。

构建过程保留两次因本机 CUDA 开发文件缺失而失败的日志；补齐官方匹配头文件后，构建任务 149622 与采集任务 149623 均成功。所有模型和临时依赖放在 `benchmark/AegisKV/experiments/native-sparse/runtime-20260914/`，未修改 SGLang/Mooncake 源码或原有环境。

图按候选通栏宽度 178 mm 导出 PNG/PDF/SVG；最终检查记录见 [REVIEW.json](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260914/REVIEW.json)。尚未嵌入正式论文版面。
