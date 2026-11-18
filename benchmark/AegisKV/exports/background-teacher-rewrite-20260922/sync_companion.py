"""One-time scoped integration against the saved pre-edit Chinese companion.

Use the current compiled main.aux as the source of citation/figure numbering.
Other prose is preserved byte-for-byte except reference renumbering.
"""
from pathlib import Path
import json
import re

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent.parent
PAPER = ROOT/'paper'
old = (OUT/'before/paper/paper_draft.md').read_text()
aux = (ROOT/'exports/latex-build/main.aux').read_text()
numbers = dict(re.findall(r'\\bibcite\{([^}]+)\}\{\{(\d+)\}', aux))

# Old companion numbers were manually appended, and already differed from
# BibTeX ordering before this task. Map to stable keys before renumbering.
keys = '''anthropic2025multiagent reflexDataset cao1997greedydual cao2026lumen
chiu1989aimd deepseek2025v32exp deepseek2025v32model deepseek2026v4model
ding2026reflex fasa2026minicpm4nsa gao2024cachedattention gao2025hcache
huang2026nosav2 jayakody2026ghostserve jiang2024minference kelley1959cpm
lin2024parrot lanlFailureData longcat2026sparse minimax2026m3 mooncake2026ssdoffload
ni2026topas minicpm4model openbmb2025minicpm41 openbmb2026sala pagonas2025cortex
pan2025kvflow qin2025mooncake qwen2025qwen25oneM schroeder2006failures
semianalysis2026cctraces shou2025infinitehbd strati2024dejavu xie2026strata
xu2026raidserve young2002landlord yu2026pythia zai2026glm5model zai2026glm52
zhang2026heddle zheng2024sglang bian2025tokencake li2025continuum
abhyankar2024infercept luo2025autellix tan2025ayo chaudhry2026murakkab
zhang2026cachescout zheng2026pbkv guo2026saga'''.split()
key_by_old = {str(i+1):k for i,k in enumerate(keys)}
prefix, references = old.split('## 参考文献', 1)
rows = {key_by_old[n]: t.strip() for n,t in re.findall(
    r'^\*\*\[(\d+)\]\*\* (.*?)(?=\n\n\*\*\[|\Z)', references, re.M|re.S)}
assert len(rows) == 50
prefix = re.sub(r'\[\[(\d+)\]\]\(#ref-\1\)',
                lambda m:'{{cite:'+key_by_old[m[1]]+'}}', prefix)
start, end = prefix.index('## 2　背景'), prefix.index('## 3　动机与挑战')
prefix = prefix[:start] + (OUT/'background.zh.md').read_text() + prefix[end:]
needle = '### 3.1　现有方法的局限'
assert prefix.count(needle) == 1
prefix = prefix.replace(needle,
    '本文以**工作流完成时间**（WCT）衡量应用级结果：$\\mathrm{WCT}_w=c_w-a_w$，'
    '其中 $a_w$ 是工作流到达时间，$c_w$ 是全部必要输出就绪的时间。它包含模型执行、'
    '工具执行、排队和依赖等待。\n\n'+needle)
needle = '其中的工作流与[图 1(a)](#fig-agent-workflow-examples)所示结构十分相似。'
assert prefix.count(needle) == 1
prefix = prefix.replace(needle, '它具有[图 1](#fig-serving-model)所示的 fork/join 结构。')
moved = json.loads((OUT/'moved-chinese-figures.json').read_text())
for name, anchor, needle in [
    ('gpu-server-availability','fig-gpu-server-availability','但正如[图 2](#fig-gpu-server-availability)所示'),
    ('recovery-cost','fig-motivation-recompute','**挑战 2：'),
]:
    block = re.sub(r'\[\[(\d+)\]\]\(#ref-\1\)',
                   lambda m:'{{cite:'+key_by_old[m[1]]+'}}', moved[name])
    assert prefix.count(needle) == 1, needle
    prefix = prefix.replace(needle, '<a id="'+anchor+'"></a>\n\n'+block+'\n\n'+needle)
prefix = prefix.replace('但正如[图 2](#fig-gpu-server-availability)所示，真实集群中故障并不罕见：',
    '生产训练集群的记录提供了背景：[图 2](#fig-gpu-server-availability)中，')

# Only the first five figure numbers change. Later manuscript figures retain
# their values; figure links keep their semantic targets.
figmap = {'2':'3','3':'5','4':'2','5':'4'}
prefix = re.sub(r'图 ([2-5])(?!\d)', lambda m:'图 '+figmap[m[1]], prefix)
for anchor, needle in [
    ('fig-motivation', '**图 2**'),
    ('fig-motivation-workflow', '![图 2(a)：'),
    ('fig-motivation-branch-gap', '![图 2(b)：'),
    ('fig-motivation-recovery-exposure', '![图 2(c)：'),
    ('fig-agent-prefix-reuse', '![图 4'),
]:
    assert prefix.count(needle) == 1, (anchor, prefix.count(needle))
    prefix = prefix.replace(needle, '<a id="'+anchor+'"></a>\n\n'+needle)

rows['shoeybi2019megatron'] = ('Mohammad Shoeybi, Mostofa Patwary, Raul Puri, Patrick LeGresley, '
    'Jared Casper, and Bryan Catanzaro. 2019. Megatron-LM: Training Multi-Billion Parameter '
    'Language Models Using Model Parallelism. arXiv:1909.08053. Version 4, revised March 2020. '
    '[来源](https://arxiv.org/abs/1909.08053)')
rows['kwon2023vllm'] = ('Woosuk Kwon, Zhuohan Li, Siyuan Zhuang, Ying Sheng, Lianmin Zheng, '
    'Cody Hao Yu, Joseph E. Gonzalez, Hao Zhang, and Ion Stoica. 2023. Efficient Memory Management '
    'for Large Language Model Serving with PagedAttention. In *Proceedings of the 29th Symposium '
    'on Operating Systems Principles*, 611–626. '
    '[doi:10.1145/3600006.3613165](https://doi.org/10.1145/3600006.3613165)')
used = set(re.findall(r'\{\{cite:([^}]+)\}\}', prefix))
assert used <= numbers.keys(), used - numbers.keys()
assert numbers.keys() <= rows.keys(), numbers.keys() - rows.keys()
prefix = re.sub(r'\{\{cite:([^}]+)\}\}',
    lambda m:'[['+numbers[m[1]]+']](#ref-'+numbers[m[1]]+')', prefix)
tail = '## 参考文献\n\n' + '\n\n'.join(
    f'<a id="ref-{n}"></a>\n\n**[{n}]** {rows[k]}'
    for k,n in sorted(numbers.items(), key=lambda kv:int(kv[1])))+'\n'
(PAPER/'paper_draft.md').write_text(prefix + tail)
(OUT/'companion-reference-map.json').write_text(json.dumps(
    {'old_to_key':key_by_old,'key_to_current':numbers,'figure_numbers':figmap},
    indent=2, ensure_ascii=False)+'\n')
print('Companion synchronized:', len(numbers), 'references, first five figure numbers.')
