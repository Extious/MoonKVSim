#!/usr/bin/env python3
"""Check model identities, trace cleaning, provenance and actual PDF placement."""
import csv,hashlib,json,re,tempfile
from collections import defaultdict
from pathlib import Path
import fitz
import expanded as e
from plot_expanded import verify

def main():
    checks=[];out=e.ROOT/'exports/evaluation-expanded-20260921'
    specs,tables=verify(e.OUT,e.DOC/'figure-specs.json');checks.append('All table/source/spec hashes and evidence labels')
    assert {r['scenario_id'] for r in tables['eval-ablation-fault']}=={'12-scenarios'}
    assert {r['scenario_id'] for r in tables['eval-ablation-reuse']}=={'12-scenarios'}
    checks.append('Static ablation uses 12 size/slack cases, distinguished from the 36-case CDF')
    for policy in e.POLICIES:
        rows=[r for r in tables['eval-recovery-attribution'] if r['category']==policy]
        assert abs(sum(r['y'] for r in rows)-e.loss(policy)[0])<1e-8
    checks.append('Ordered attribution telescopes to the exact final join penalty')
    assert abs(e.loss('LRU')[0]-e.loss('AegisKV model')[0]-2.008333333333333)<1e-8
    assert max(e.loss('AegisKV model')[1])>max(e.loss('LRU')[1])
    checks.append('Base WCT benefit and adverse pool-occupancy effect both retained')
    a=e.loss('Feasible oracle',budget=16);b=e.loss('Feasible oracle',budget=28)
    assert b[0]>a[0] and e.t.objective(e.GROUPS,b[2],e.CFG)<e.t.objective(e.GROUPS,a[2],e.CFG)
    checks.append('Capacity tradeoff distinguishes joint objective from fault-only latency')
    for overlap,hot in [(True,True),(False,True),(True,False),(False,False)]:
        for density in [.125,.5,1]:
            for accuracy in [0,.5,1]:
                total,wait,events=e.layer_model(overlap,hot,density,accuracy=accuracy)
                assert total>=24 and abs(total-wait-24)<1e-9
                for resource in ['ssd','h2d','gpu']:
                    ev=sorted((x for x in events if x[0]==resource or resource=='ssd' and x[0]=='unused'),key=lambda x:x[2])
                    assert all(x[3]<=y[2]+1e-9 for x,y in zip(ev,ev[1:]))
                gpu={x[1]:x[3] for x in events if x[0]=='gpu'}
                for resource,layer,start,end in events:
                    if resource in ['ssd','unused','h2d'] and layer>=2:assert start>=gpu[layer-2]-1e-9
    checks.append('36 layer cases: resource exclusivity, two-layer bound, compute/wait conservation')
    intervals=e.read_lanl();stats=e.SUMMARY['lanl']
    assert stats['raw_rows']==sum(stats.get(k,0) for k in ['non_compute','zero_duration','negative_duration','unparseable','merged_overlapping_or_touching','clean_intervals'])
    by=defaultdict(list)
    for r in intervals:by[(r['system'],r['node'])].append(r)
    for rows in by.values():assert all(a['end']<b['start'] for a,b in zip(rows,rows[1:]))
    checks.append('Trace exclusion arithmetic and per-node disjoint outage intervals')
    miniature=[dict(system=1,node=i,start=float(a),end=float(a+30)) for i,a in enumerate([0,0,20])]
    rs=e.trace_replay(miniature,'LRU');s=max(e.loss('LRU')[1])
    assert abs(rs[1]['wait_s']-s)<1e-9 and rs[2]['wait_s']==0
    assert len(e.trace_replay(miniature,'LRU',workflows=4))==12
    checks.append('Trace FIFO waiting recurrence, idle reset and exposure multiplier')
    for rental,h,renew in [(False,.2,True),(True,.2,True),(True,0,True),(True,.2,False)]:
        rows=e.rental_stream(rental,h,renew)
        assert all(a['rent']<=b['rent'] for a,b in zip(rows,rows[1:]))
        assert abs(rows[-1]['movement']-.1*rows[-1]['migrations'])<1e-9
    checks.append('Rental accounting: monotone committed rent and migration charge')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);manifest=json.loads((e.OUT/'manifest.json').read_text())
        spec=json.loads((e.DOC/'figure-specs.json').read_text());first=next(iter(spec));spec[first]['evidence']='measured'
        (p/'spec.json').write_text(json.dumps(spec));manifest['spec_sha256']=e.sha(p/'spec.json')
        manifest['raw_tables']={};(p/'manifest.json').write_text(json.dumps(manifest))
        try:verify(p,p/'spec.json')
        except ValueError as ex:assert 'Measured input requires' in str(ex)
        else:raise AssertionError('Model relabeling accepted')
    checks.append('Measured relabeling rejected without physical raw provenance')
    paper=e.ROOT/'paper';main=(paper/'main.tex').read_text()
    evaluation=main.split('\\section{Evaluation}',1)[1].split('\\section{Related Work}',1)[0]
    assert '\\begin{figure*}' not in evaluation
    assets=re.findall(r'\\includegraphics\[width=\\columnwidth\]\{(figures/eval-[^}]+)\}',evaluation)
    assert len(assets)==len(specs)==33
    log=(e.ROOT/'exports/latex-build/main.log').read_text()
    problems=[x for x in log.splitlines() if re.search(r'Overfull|undefined|LaTeX Error|Emergency stop',x)]
    assert not problems,problems
    placed={m.group(1):float(m.group(2))*72/72.27 for m in re.finditer(r'Package pdftex.def Info: (figures/\S+\.pdf)\s+used.*?Requested size: ([0-9.]+)pt',log,re.S)}
    fonts=[]
    for asset in assets:
        doc=fitz.open(paper/asset);page=doc[0];scale=placed[asset]/page.rect.width
        spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
        small=min(s['size']*scale for s in spans)
        assert small>=10, (asset,small)
        fonts.append(dict(asset=asset,placed_width_bp=placed[asset],minimum_font_bp=small))
    checks.append('All 33 Evaluation assets single-column; placed figure text >= 10 bp')
    pdf=fitz.open(paper/'main.pdf');references=next(i+1 for i,p in enumerate(pdf) if 'References' in p.get_text().splitlines())
    report=dict(scope='Analytical arithmetic, trace processing, plotting provenance and manuscript; no hardware validation',
      checks=checks,figure_count=len(specs),subsections=evaluation.count('\\subsection'),pdf_pages=len(pdf),references_start_page=references,
      page_limit_enforced=False,reason='User explicitly prioritizes complete content over the 12-page limit at this stage',
      fonts=fonts,paper_sha256=e.sha(paper/'main.pdf'),physical_runs=0)
    (out/'CHECKS-expanded.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='fonts'},indent=2))

if __name__=='__main__':main()
