#!/usr/bin/env python3
"""Apply the declared figure selection without shortening the experiment plan.

Used after the historical expanded authoring snapshot, not during data refresh.
The source manuscript is read immediately before editing; unrelated chapters
are preserved. Reapplying this selection is idempotent.
"""
import json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
CAPTION=(r'Static value ablations over the same 12 size/slack scenarios at '
    r'4\,GiB/s storage bandwidth. Each policy has a failure-penalty bar and a '
    r'normal next-use-cost bar; these are distinct costs, not additive phases. '
    r'The six policies use identical weights, capacity, and candidate groups. '
    r'Keeping both outcomes visible exposes the normal-reuse cost of recovery '
    r'prioritization. This is a static placement model, not the full online system.')

def figure():
    return ('\\begin{figure}[!htbp]\n \\centering\n'
        ' \\includegraphics[width=\\columnwidth]{figures/eval-value-ablation.pdf}\n'
        ' \\caption{'+CAPTION+'}\n \\label{fig:eval-value-ablation}\n'
        ' \\Description{'+CAPTION+'}\n\\end{figure}')

REPLACEMENTS=[
    (r'Figures~\ref{fig:eval-workflow-outcomes} and~\ref{fig:eval-paired-benefit} show both distributions and matched differences.',
     r'Figure~\ref{fig:eval-workflow-outcomes} shows the distributions. We also compute matched differences for every configuration.'),
    (r'Figure~\ref{fig:eval-recovery-attribution} attributes the final join penalty using ordered interventions.',
     r'An ordered counterfactual attributes the final join penalty using controlled interventions.'),
    ('then restore each cost in a specified order.',
     'then restore detection-floor, read, network, H2D, and replay costs in that order.'),
    (r'Figure~\ref{fig:eval-storage-traffic} supplies a necessary counterpoint.',
     'Resource accounting shows the cost of prioritization.'),
    (r'Figure~\ref{fig:eval-background-backlog} similarly exposes the larger I/O drain interval under a fixed foreground arrival rate.',
     r'With normal I/O using 70\% of the 4\,GiB/s reader, a fluid backlog model exposes a longer drain interval for the larger recovery byte volume. This calculation concerns I/O backlog, not measured TTFT or collateral WCT.'),
    (r'Figure~\ref{fig:eval-logical-fault-phase} isolates growing historical state under fixed remaining-work assumptions.',
     'An analytical sweep scales checkpoint bytes with logical progress while holding remaining work fixed.'),
    (r'Figure~\ref{fig:eval-modern-trace-labels} characterizes the labels.',
     'We audit these labels separately from outage calendars.'),
    (r'Figure~\ref{fig:eval-trace-system-benefit} keeps per-system losses visible.',
     'Per-system aggregation also retains losses, including the negative mean benefit for System 2.'),
    (r'Figures~\ref{fig:eval-layer-factorial}--\ref{fig:eval-sparse-misses} test placement, overlap, and prediction errors separately.',
     r'Figure~\ref{fig:eval-layer-factorial} isolates the placement/scheduling interaction. A separate prefetch-correctness sweep holds required demand fixed to isolate prediction errors.'),
    (r'Figures~\ref{fig:eval-capacity-frontier} and~\ref{fig:eval-storage-bottleneck} cover the static capacity and bandwidth components; the base model assumes sufficient backing and therefore does not validate final-copy eviction performance.',
     r'Figure~\ref{fig:eval-capacity-frontier} shows capacity sensitivity; the experiment package also retains bandwidth sweeps. The base model assumes sufficient backing and therefore does not validate final-copy eviction performance.'),
    (r'Figure~\ref{fig:eval-healthy-io} supplies an I/O queueing mechanism, not a TTFT result.',
     'A separate M/D/1 calculation with constant service time models I/O queueing only; it does not measure TTFT or GPU interference.'),
    (r'Figure~\ref{fig:eval-rate-break-even} shows that a fixed cost of 0.05\,s',
     r'Under this model, a fixed cost of 0.05\,s'),
    ('The two static ablation panels report fault and normal-use costs together',
     r'Figure~\ref{fig:eval-value-ablation} reports failure and normal next-use costs together for the same six policies'),
    ('The current curve multiplies an assumed node-visit cost by declared passes/episodes.',
     'The analytical operation-cost projection multiplies an assumed node-visit cost by declared passes/episodes.'),
]

def select_main_figures():
    config=json.loads((ROOT/'experiments/eurosys27/legacy-main-figures.json').read_text())
    keep=set(config['main']);path=ROOT/'paper/main.tex';current=path.read_text()
    if r'\input{evaluation}' in current:
        raise SystemExit('Historical authoring utility: current Evaluation is independently authored in paper/evaluation.tex; use render_evaluation.py and check_evaluation.py.')
    start=current.index(r'\section{Evaluation}');end=current.index(r'\section{Related Work}')
    text=current[start:end]
    def choose(m):
        match=re.search(r'figures/(eval-[^}]+)\.pdf',m.group())
        if not match:return m.group()
        name=match[1]
        if name=='eval-ablation-fault':return figure()
        return m.group() if name in keep else ''
    text=re.sub(r'\\begin\{figure\}.*?\\end\{figure\}',choose,text,flags=re.S)
    for old,new in REPLACEMENTS:
        pattern=r'\s+'.join(re.escape(token) for token in old.split())
        text=re.sub(pattern,lambda m:new,text)
    if r'Figure~\ref{fig:eval-trace-penalty}' not in text:
        text=text.replace('At original spacing, mean modeled penalty',
            r'Figure~\ref{fig:eval-trace-penalty} reports the conditional recovery distribution.'+'\nAt original spacing, mean modeled penalty')
    if r'Figure~\ref{fig:eval-rental-cost}' not in text:
        text=text.replace('Direct revaluation makes 108 migrations',
            r'Figure~\ref{fig:eval-rental-cost} reports miss and migration cost together.'+'\nDirect revaluation makes 108 migrations')
    if r'\label{sec:eval-rental}' not in text:
        heading=r'\subsection{Online Rent, Renewal, and Migration Hysteresis}'
        text=text.replace(heading,heading+'\n'+r'\label{sec:eval-rental}')
    # Figure-count decisions belong in the authoring notes, not the paper's
    # scientific argument. Remove the temporary integration note if present.
    text=re.sub(r'Eight core figures carry.*?retained in the experiment package\.\s*','',text,flags=re.S)
    text=re.sub(r'\n{3,}','\n\n',text)
    labels=set(re.findall(r'\\label\{(fig:eval-[^}]+)\}',text))
    refs=set(re.findall(r'\\ref\{(fig:eval-[^}]+)\}',text))
    assert refs==labels,{ 'missing_refs':sorted(labels-refs),'dangling_refs':sorted(refs-labels)}
    assets=re.findall(r'figures/(eval-[^}]+)\.pdf',text)
    assert assets==config['main'],assets
    assert text.count(r'\subsection')==config['subsection_count']
    path.write_text(current[:start]+text.rstrip()+'\n\n'+current[end:])
    print('Selected',len(assets),'main figures; retained',config['subsection_count'],'experiment subsections')

if __name__=='__main__':select_main_figures()
