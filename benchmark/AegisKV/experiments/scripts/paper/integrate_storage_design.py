#!/usr/bin/env python3
"""Merge reviewed System Design with freshly read concurrent paper chapters.

No experiments are run. Back up all changed inputs before publishing. The
full model-only Evaluation is preserved, with explicit scope/ablation updates.
"""
from pathlib import Path
from datetime import datetime,timezone
import shutil,hashlib,json,re

ROOT=Path(__file__).resolve().parents[3]
WORK=ROOT/'exports/system-design-dram-ssd-20260920'
PAPER=ROOT/'paper'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive=ROOT/'Archived'/('before-storage-design-integration-'+stamp)
    archive.mkdir(parents=True,exist_ok=False)
    shutil.copytree(PAPER,archive/'paper');shutil.copy2(ROOT/'AGENTS.md',archive/'AGENTS.md')
    baseline={str(p.relative_to(ROOT)):digest(p) for p in PAPER.rglob('*') if p.is_file()}
    main_path=PAPER/'main.tex';main=main_path.read_text()
    old='''The design currently uses direct marginal revaluation; rental credit is
an optional maintenance alternative whose incremental value must be
isolated under the same score and migration rules.'''
    new='''The revised online controller uses tier-local trial rent followed by
joint marginal revaluation. Required ablations compare direct revaluation,
rent without renewal, rent without aging, and full rent under the same
score and migration rules. Sparse retention and layer overlap are ablated
separately: recency versus causal access ranking, and serial loading versus
bounded pipelining, with equal committed coverage and transient workspace.
Online runs also fill storage and force last-copy fallback. The static
placement model in these plots does not validate those mechanisms.'''
    if old not in main:raise RuntimeError('Concurrent Evaluation changed; inspect before adapting the exact merge')
    main=main.replace(old,new)
    main=main.replace('static value component, not the full asynchronous online algorithm.',
                      'static value component, not tier-local rent, sparse demand prediction,\nlayer-wise replay, or the full asynchronous online algorithm.')
    main=main.replace('specify a bounded online controller and an asynchronous checkpoint protocol',
                      'specify a bounded online controller combining sparse/layer candidates,\ntrial rent, and an asynchronous checkpoint protocol')
    # Routine line breaking preserves the evaluation meaning.
    main=main.replace('workflow IDs, prompt/tool','workflow IDs, prompt and tool')
    abstract_path=PAPER/'abstract.tex';abstract=abstract_path.read_text()
    abstract=abstract.replace('common failure together and preserves checkpoint validity during asynchronous\nmigration.',
                            'common failure together, uses sparse demand and layer overlap to value\nfast-tier residency, and screens online competitors using tier-local rent.\nVersioned transitions preserve recovery validity during migration and\nexplicit fallback.')
    draft_path=PAPER/'paper_draft.md';draft=draft_path.read_text()
    a=draft.index('## 3. AegisKV Design');b=draft.index('## 4. Evaluation',a)
    draft=draft[:a]+(WORK/'system-design-draft.md.txt').read_text()+draft[b:]
    draft=draft.replace('### 4.4 消融与安全迁移',
        '### 4.4 消融与安全迁移\n\n新增设计机制需要独立消融：同价值模型下的直接重估、完整租金、无续费和无老化；稀疏访问排名对比 recency；相同完整 checkpoint 和临时工作区下的串行读取与层间流水；SSD 满时的显式回退。当前四分支静态放置曲线不验证这些在线机制，须与本轮层流水线的分析模型分开。')
    # Protect against silent replacement of chapters updated since our initial read.
    for p in [main_path,abstract_path,draft_path]:
        if digest(p)!=baseline[str(p.relative_to(ROOT))]:raise RuntimeError(f'Concurrent change: {p}')
    for p,text in [(main_path,main),(abstract_path,abstract),(draft_path,draft)]:p.write_text(text)
    shutil.copy2(WORK/'paper/system_design.tex',PAPER/'system_design.tex')
    for ext,folder in [('pdf','figures'),('png','figures/preview')]:
        for p in (WORK/'figures').glob('*.'+ext):shutil.copy2(p,PAPER/folder/p.name)
    # Keep prior raw trace evidence/assets that the full-paper task had removed.
    for stem in ['sparse-models','retry-kv-prediction']:
        for ext,folder in [('pdf','figures'),('png','figures/preview')]:
            src=WORK/'paper'/folder/f'{stem}.{ext}'
            if src.exists() and not (PAPER/folder/src.name).exists():shutil.copy2(src,PAPER/folder/src.name)
    (WORK/'INTEGRATION.json').write_text(json.dumps({'archive':str(archive.relative_to(ROOT)),
        'timestamp':stamp,'baseline':baseline,'owned_design':str((PAPER/'system_design.tex').relative_to(ROOT)),
        'new_figures':['system-overview','sparse-recovery','recovery-pipeline','overlap-frontier','rental-competition','checkpoint-lifecycle'],
        'preserved':'Fresh Introduction, Background, Evaluation, Related Work, Conclusion and unrelated assets',
        'narrow_other_chapter_edits':'Contribution wording, analytical scope, requested mechanism ablations, one line break'},indent=2)+'\n')
    print('Merged System Design; archived all previous inputs at',archive)

if __name__=='__main__':main()
