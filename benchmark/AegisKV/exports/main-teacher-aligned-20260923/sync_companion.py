"""Synchronize the Chinese companion from the immutable pre-edit snapshot.

This is a one-time manuscript migration, not a new experiment or plot renderer.
Bibliography numbers and figure numbers come from the canonical LaTeX build.
"""
from pathlib import Path
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PAPER = ROOT / 'paper'
s = (HERE / 'before/paper/paper_draft.md').read_text()
old_aux = (HERE / 'before/main.aux').read_text()
new_aux = (ROOT / 'exports/latex-build/main.aux').read_text()
old_bib = {n: key for key, n in re.findall(r'\\bibcite\{([^}]+)\}\{\{(\d+)\}', old_aux)}
new_bib = dict(re.findall(r'\\bibcite\{([^}]+)\}\{\{(\d+)\}', new_aux))
entry_re = r'<a id="ref-(\d+)"></a>\s*\n\s*\*\*\[\d+\]\*\* (.*?)(?=\n\n|\Z)'
bib_text = {old_bib[n]: text for n, text in re.findall(entry_re, s, re.S)}
s = re.sub(entry_re, '', s, flags=re.S)
s = re.sub(r'\[\[(\d+)\]\]\(#ref-\d+\)', lambda m: '[@' + old_bib[m[1]] + ']', s)

def figure_block(text, anchor):
    pattern = rf'<a id="{anchor}"></a>\n\n!\[.*?\n\n\*\*图 \d+：\*\* [^\n]+'
    return re.search(pattern, text, re.S)[0]

prefix = figure_block(s, 'fig-agent-prefix-reuse')
cost = figure_block(s, 'fig-motivation-recompute')
s = re.sub(r'## 3　动机与挑战\n.*?(?=## 4　AegisKV 设计)', 'TEACHER_MOTIVATION\n\n', s, flags=re.S)
s = re.sub(r'\*\*图 1：\*\* [^\n]+', '**图 1：** 基于 DAG 的 Agent 工作流服务。工作流 runtime 维护工作流依赖和已接受的 Agent 历史。就绪调用被调度到模型 workers，workers 在 Agent 的迭代 turns 之间保留相应 KV cache。', s)
s = s.replace('本节先介绍架构，再按[第 3.2 节](#sec-motivation-challenges)中三个挑战的顺序介绍各组件。', '本节先介绍架构，再介绍由[第 3 节](#sec-motivation)中的观察所引出的各组件。')
s = s.replace('[图 7](#fig-design-insights)', '[图 3(a)](#fig-kv-value)')
# Existing figure indices are resolved once, before inserting new text.
number_map = {1: 1, 2: 2, 4: 5, 5: 16, 8: 4, 9: 6, 10: 7, 11: 8, 12: 9,
              13: 10, 14: 11, 15: 12, 16: 13, 17: 14, 18: 15}
def renumber(text):
    text = re.sub(r'图 (\d+)', lambda m: '图 ' + str(number_map.get(int(m[1]), int(m[1]))), text)
    text = text.replace('图 2(c)', '图 2(b)').replace('#fig-motivation-recovery-exposure', '#fig-agent-value')
    text = text.replace('fig-motivation-recompute', 'fig-context-recovery')
    return text
s, prefix, cost = map(renumber, (s, prefix, cost))
cost = cost.replace('/preview/recovery-cost.png', '/preview/context_recovery.png')
s = re.sub(r'\\tag\{(\d+)\}', lambda m: r'\tag{' + str(int(m[1]) + 1) + '}', s)

motivation = r'''<a id="sec-motivation"></a>

## 3　动机

如第 2 节所述，发生故障的 Agent 可以根据持久化输入重建 KV cache，也可以恢复幸存的 KV checkpoint[@strati2024dejavu][@cao2026lumen]。重建避免了正常执行期间的 checkpoint 开销，但需要重新 prefill Agent 累积的历史。Checkpoint 避免了这种重复计算，但随着 Agent 历史增长，会持续消耗内存与 I/O 资源。

本节首先量化为什么完整保护所有 Agent 的 KV 状态成本过高，随后提出指导 AegisKV 设计的三个观察。

### 3.1　完整 KV 保护成本高昂

Agent 的 KV 状态会在迭代执行过程中不断增长。后续调用通常包含此前的模型输出、工具结果和其他 Agent 的输出。因此，工作流后期发生的故障可能比早期故障丢失多得多的 KV 状态。

我们在两张 A100 PCIe 40 GB GPU 上使用 Qwen2.5-7B-Instruct-1M[@qwen2025qwen25oneM][@jiang2024minference]，以 TP=2、BF16 权重和 KV 状态、batch size 为 1，量化由此产生的恢复成本。我们将完整 KV 重建与从 HBM、主机 DRAM 和共享存储复用 KV 进行比较。完整重建从空 KV cache 开始，prefill 整个上下文。每条复用路径均从相同的历史 KV 状态开始，并处理一个额外 token。

当上下文长度为 1M tokens 时，完整重建耗时 571.2 s。复用历史 KV 状态后，从 HBM、主机 DRAM 和共享存储就绪所需的时间分别降为 1.3 s、2.7 s 和 10.2 s。对应的历史 KV 状态在两个 TP ranks 上共占 57.9 GB。因此，保留 KV 可以避免数百秒的重建，但单个长时间运行的 Agent 就可能需要数十 GB 的 checkpoint 容量。

### 3.2　O1：不同 Agent 的恢复价值不同

Agent 的 KV 重建时间并不直接决定它对工作流完成的影响。[图 2(a)](#fig-agent-value)展示一个 fork–join 工作流：A2 决定汇合时刻，而 A1 提前 91.2 s 完成。短于这一时间间隔（称为 slack）的延迟不会推迟下游阶段。

这种分支差异在我们分析的 traces 中很常见[@semianalysis2026cctraces]。在 121 个包含根据时序推断的 fan-in 组的工作流中，最大分支时长差的中位数为 138 s，90 分位数为 1,173 s。由于 trace 没有显式依赖边，这些差值并非故障时 slack 的直接测量，但它们表明并行 Agent 对延迟的容忍程度可能存在显著差异。

[图 2(b)](#fig-agent-value)将示例工作流与其中四个活跃 Agent 的实测 KV 重建时间结合起来。相近的重建延迟并不会产生相近的工作流延迟。重建 A1 耗时 33.2 s，但该延迟落在 A1 的 91.2 s slack 以内，不会推迟汇合。重建 A2 的耗时与之相近，为 32.6 s，但 A2 没有 slack，因此全部延迟都会推迟汇合。A3 和 A4 的 slack 吸收了部分重建时间，分别留下 16.3 s 和 18.0 s 的工作流完成时间增量。

对于单独考虑的分支 $i$，这一关系为：

$$
\Delta W_i = \max(0, R_i - \sigma_i), \tag{1}
$$

其中，$R_i$ 是恢复延迟，$\sigma_i$ 是剩余工作流 slack。因此，保护最大或重建成本最高的 KV 状态，不一定能带来最大的工作流收益。

一次 worker 故障还可能中断多个 Agent。它们的恢复价值并非总能相加：如果另一个受影响分支仍是瓶颈，加速一个被延迟的分支可能无法提前汇合。因此，保护决策应同时考虑 Agent 在工作流中的位置，以及被同一故障影响的其他 Agent。

<a id="fig-agent-value"></a>

![图 2：不同 Agent 的恢复价值不同](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/agent_value.png)

**图 2：** 不同 Agent 的恢复价值不同。由于并行 Agent 的 slack 不同，相近的 KV 重建时间会产生不同的工作流延迟。纹理部分在汇合前被吸收；实色部分推迟汇合。(a) 在假定全部分支汇合的条件下保留 trace 时序。(b) 报告三次重建测量的中位数与 min–max 范围；WCT 增量是在保持其他执行不变的条件下计算得到的（[附录 A](#sec-motivation-protocol)）。

### 3.3　O2：不同 KV 区域的恢复价值不同

即使对一个重要的 Agent，不同 KV 状态对快速恢复的价值也不相同。[图 3(a)](#fig-kv-value)显示，历史 KV 访问集中于部分块。对于三个被评估的稀疏注意力模型，最热的约 20% 历史块分别贡献了 87.64%、74.76% 和 56.54% 的访问。

仅凭访问频率还不够。在按层顺序恢复时，前面层的计算可以与后面层的传输重叠。复制那些传输本来就会被隐藏的块，不会缩短恢复时间。只有缺失时会引起暴露等待的 KV 状态，才会直接影响恢复时间。因此，将某个 Agent 的完整 KV checkpoint 放入接管 HBM，可能消耗远多于快速恢复实际所需的容量。系统应区分避免完整重建所需的完整状态，以及为了减少恢复停顿而必须立即可用的状态子集。

<a id="fig-kv-value"></a>

![图 3：不同 KV 区域的恢复价值不同](/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/paper/figures/preview/kv_value.png)

**图 3：** 不同 KV 区域的恢复价值不同。(a) 历史访问集中于部分 KV 块。(b) 只有暴露在恢复路径上的缺失 KV 传输才会增加恢复时间。(a) 中的模型为 NOSA-8B[@huang2026nosav2]、NSA-8B[@fasa2026minicpm4nsa] 和 MiniCPM4.1-8B[@openbmb2025minicpm41]。曲线使用三个 PG19 文本的 32,704-token 前缀中最后 512 个 Queries；每个 Query 对同一历史 64-token 块跨 heads 只计一次，并对全部 32 层及文本取平均。阴影表示文本间的 min–max，排序是事后统计。(b) 为示意：L1 KV 已驻留，L2 在 L1 计算期间加载，而较晚完成的 L3 传输产生暴露等待。

### 3.4　O3：复制容量随时间变化

快速 KV 副本与前台推理共享 HBM。随着请求到达与完成、Agent 历史增长，以及活跃执行对 KV 状态和临时工作区的需求变化，可用于复制的 HBM 也会变化。因此，固定复制预算可能效率低下：高负载时，大预算可能挤占前台执行状态；低负载时，小预算又可能使可用 HBM 闲置。复制必须适应可安全使用的容量，避免干扰前台服务。

**小结。** 这些观察共同说明，高效故障恢复需要在两个层面进行选择，并随时间调整。系统必须根据 Agent 对工作流完成的影响区分 Agent，根据 KV 区域对暴露恢复延迟的影响区分 KV 区域，并随前台需求变化调整快速复制容量。第 4 节介绍 AegisKV 如何实现这三项要求。'''
s = s.replace('TEACHER_MOTIVATION', motivation)
s = s.replace('### 4.4　KV Master：面向工作流的分层放置', prefix + '\n\n### 4.4　KV Master：面向工作流的分层放置')
s = s.replace('## 附录 A　Motivation 测量协议', '<a id="sec-motivation-protocol"></a>\n\n## 附录 A　Motivation 测量协议\n\n' + cost)

used = set(re.findall(r'\[@([^\]]+)\]', s))
assert used <= new_bib.keys(), sorted(used - new_bib.keys())
assert new_bib.keys() <= bib_text.keys(), sorted(new_bib.keys() - bib_text.keys())
s = re.sub(r'\[@([^\]]+)\]', lambda m: '[[' + new_bib[m[1]] + ']](#ref-' + new_bib[m[1]] + ')', s)
bibliography = '\n\n'.join(f'<a id="ref-{n}"></a>\n\n**[{n}]** {bib_text[key]}' for key, n in sorted(new_bib.items(), key=lambda x: int(x[1])))
s = s.replace('## 参考文献', '## 参考文献\n\n' + bibliography)

# Fill the missing explicit targets for existing figure links.
anchors = {
    'system-overview': 'fig-system-overview',
    'retention-value': 'fig-retention-value',
    'sparse-recovery': 'fig-sparse-recovery',
    'recovery-pipeline': 'fig-design-pipeline',
    'renewable-credit': 'fig-renewable-credit',
}
for filename, anchor in anchors.items():
    if f'<a id="{anchor}"></a>' not in s:
        s = re.sub(r'(!\[[^\n]+/preview/' + filename + r'\.png\))', f'<a id="{anchor}"></a>\n\n' + r'\1', s)
for number, anchor in [(1, 'alg-workflow-tracker'), (2, 'alg-placement')]:
    if f'<a id="{anchor}"></a>' not in s:
        s = re.sub(r'(?m)^(\*\*算法 ' + str(number) + r'[^\n]*)', f'<a id="{anchor}"></a>\n\n' + r'\1', s)
s = re.sub(r'\n{3,}', '\n\n', s).rstrip() + '\n'
(PAPER / 'paper_draft.md').write_text(s)
(HERE / 'companion-mapping.json').write_text(json.dumps({
    'bibliography_numbers': new_bib,
    'old_to_new_figure_numbers': number_map,
    'active_teacher_motivation_translated': True,
    'disabled_draft_retained_in_english': True,
    'equation_tags': re.findall(r'\\tag\{(\d+)\}', s),
    'references_grouped_before_appendix': True,
}, ensure_ascii=False, indent=2) + '\n')
print('Chinese companion aligned: 16 figures, 7 equations,', len(new_bib), 'references.')
