#!/usr/bin/env python3
"""Check historical model identities, trace cleaning and frozen provenance.

The 34 model/trace views and their former eight-figure selection are historical
artifacts. This checker does not impose their old section/figure counts on the
current manuscript. Use check_evaluation.py for the current paper.
"""
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
    for source,label in [('eval-ablation-fault','Failure penalty'),('eval-ablation-reuse','Normal next-use')]:
        old={r['category']:r['y'] for r in tables[source]}
        combined={r['category']:r['y'] for r in tables['eval-value-ablation'] if r['series']==label}
        assert old==combined
    checks.append('Combined value-ablation figure preserves both source aggregates exactly')
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
    selection=json.loads((e.DOC/'legacy-main-figures.json').read_text())
    assert set(specs)==set(selection['main']) | set(selection['supplementary'])
    assert len(specs)==34 and len(selection['main'])==8
    checks.append('Historical 34-view catalog and former 8/26 selection retained; no current-paper count requirement')
    report=dict(scope='Historical analytical arithmetic, trace processing and plotting provenance; no current-controller or hardware validation',
      checks=checks,historical_main_figure_count=len(selection['main']),available_figure_count=len(specs),
      selection_file='legacy-main-figures.json',current_manuscript_checked=False,physical_runs=0)
    (out/'CHECKS-expanded.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='fonts'},indent=2))

if __name__=='__main__':main()
