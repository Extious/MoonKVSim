#!/usr/bin/env python3
"""Render result claims from bound statistics; preview output stays separate."""
import argparse,hashlib,json
from pathlib import Path
from statistics import mean
from paper_paths import PAPER, ROOT, DATA, TOOLS, DOCS, BUILD, DELIVERY, TEMPLATE
HERE=PAPER

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def interval(x):return f"{x['mean']:+.3f} s (95\\% CI [{x['low']:+.3f}, {x['high']:+.3f}] s)"
def main():
 p=argparse.ArgumentParser();p.add_argument('--paper',type=Path,default=HERE);p.add_argument('--preview',action='store_true');a=p.parse_args();out=a.paper.resolve()
 data=DATA if out==PAPER else out/'data'
 d=json.loads((data/'aligned-statistics.json').read_text())
 if a.preview:assert out!=HERE and d['status']=='PREVIEW_UNVERIFIED_RAW'
 else:assert d['status']=='PASS' and d['acceptance_sha256']
 ep=d['endpoints'];primary=d['primary'];traffic={k:mean(v['F0']['protection_GiB']) for k,v in ep.items()}
 increase=(traffic['full']/traffic['dram']-1)*100
 sections={}
 rows=[]
 for name,k in [('Unprotected','unprotected'),('DRAM-only','dram'),('Full AegisKV','full')]:
  rows.append(f"{name} & {mean(ep[k]['F0']['mean_wct_s']):.3f} & {mean(ep[k]['F1']['mean_wct_s']):.3f} & {mean(ep[k]['F1']['batch_s']):.3f} \\\\")
 sections['TABLE']=r'''\begin{table}[t]
\centering
\caption{Base-setting absolute endpoints (seconds), averaged over five seeds.
These descriptive means do not replace paired penalty contrasts.}
\label{tab:endpoints}
\setlength{\tabcolsep}{3pt}
\begin{tabular}{@{}lrrr@{}}
\toprule
Arm & F0 WCT & F1 WCT & F1 batch \\
\midrule
'''+ '\n'.join(rows)+r'''
\bottomrule
\end{tabular}
\end{table}
'''
 sections['HEALTHY']=f'''Figure~\\ref{{fig:healthy}} shows substantial copying with little resolved
WCT change. Full transfers {traffic['full']:,.0f} GiB per workload, versus
{traffic['dram']:,.0f} GiB for DRAM-only ({increase:.1f}\\% more). Its paired mean
WCT difference is {interval(d['healthy']['dram'])};
unprotected has the same healthy control times. The interval includes zero.
Background copies can overlap compute, while memory and closed-loop batching
change schedules. These modeled timings exclude real controller/kernel costs.
'''
 sections['FAILURE']=f'''The raw ECDFs largely overlap (Figure~\\ref{{fig:failure}} and
Table~\\ref{{tab:endpoints}}). Relative to DRAM-only, full's mean failure-penalty
contrast is {interval(primary['dram']['all'])};
the focus contrast is {interval(primary['dram']['focus'])}.
Against unprotected recomputation, the whole-workload contrast is
{interval(primary['unprotected']['all'])}.
None establishes a stable advantage across these admission orders.
'''
 recovery=d['focus_recovery'];first={x['arm']:x for x in recovery if x['seed']==0}
 delta=first['dram']['materialization_s']-first['full']['materialization_s']
 largest=max(range(5),key=lambda s:primary['dram']['focus']['samples'][s]);assert largest==4
 sections['RECOVERY']=f'''Full copies HBM for four of five focus requests; one uses DRAM alone
(Figure~\\ref{{fig:recovery}}). In seed 0, both arms restore 36,864 prompt tokens,
but full reaches prefix-ready {delta:.3f} s sooner. The corresponding workflow
penalty contrast is still +{primary['dram']['focus']['samples'][0]:.3f} s.
In the largest adverse focus contrast (seed 4), full's workflow penalty
exceeds DRAM-only by {primary['dram']['focus']['samples'][4]:.3f} s despite faster
focus-request recovery. The trace shows a different branch sharing the
recovery worker becoming the last branch before the join; the final request
also waits longer. This post-hoc example explains why a restored prefix or
faster preparation cannot establish workflow-level benefit.
'''
 sections['ABLATIONS']=f'''Every whole-workload and focus interval in Figure~\\ref{{fig:ablations}}
includes zero; the zero-Slack focus contrast is exactly zero in all five
seeds. There is no resolved latency benefit for an individual mechanism here.
Retention nevertheless changes healthy traffic: removing Slack raises it to
{traffic['no_slack']:,.0f} GiB and LRU to {traffic['lru_eviction']:,.0f} GiB, versus
{traffic['full']:,.0f} GiB for full. Fixing the initial quota uses
{traffic['no_aimd']:,.0f} GiB. These byte costs are mechanism observations,
not evidence of a failure-latency or hardware-throughput improvement.
'''
 sections['SENSITIVITY']=f'''All fourteen whole-workload/focus intervals across the seven settings
include zero (Figure~\\ref{{fig:sensitivity}}). At 5 GB/s, the focus estimate is
{interval(d['sensitivity']['bandwidth5']['focus'])},
showing substantial uncertainty. With two sequential faults, the whole-workload
contrast is {interval(d['sensitivity']['failures2']['all'])}.
Service composition and admission order can change signs and dispersion;
these experiments support a conditional mechanism study, not a universal
performance ranking.
'''
 text=(TEMPLATE).read_text()
 for k,v in sections.items():text=text.replace('%RESULT_'+k+'%',v)
 assert '%RESULT_' not in text
 if a.preview:text=text.replace('independent raw-evidence audit','run-time audit (independent raw verification pending)')
 (out/'sections/results.tex').write_text(text)
 abstract=f"Full adds {increase:.1f}\\% protection traffic relative to DRAM-only, while the whole-workload failure-penalty contrast is {interval(primary['dram']['all'])}. Ablations and sensitivity do not resolve a stable WCT advantage."
 if a.preview:abstract='PREVIEW: independent raw verification is pending. '+abstract
 (out/'sections/result-values.tex').write_text('\\newcommand{\\MeasuredRuns}{170}\n\\newcommand{\\AbstractResults}{'+abstract+'}\n')
 conclusion=f'''\\section{{Conclusion}}
AegisKV connects workflow Slack with independent HBM/DRAM protection.
The earlier prototype validates functional recovery; full protection adds
{increase:.1f}\\% healthy traffic without a resolved workflow-latency advantage.
Revision 3 defines shared-prefix group replacement, acknowledged reclamation
and foreground constraints, with executable boundary checks. Its local
invariants are narrower than performance guarantees. Native allocator
integration, physical interference certification and new frozen experiments
remain necessary to evaluate the revised design.
'''
 (out/'sections/conclusion.tex').write_text(conclusion)
 bindings={'status':'PREVIEW' if a.preview else 'PASS','statistics_sha256':sha(data/'aligned-statistics.json'),'generator_sha256':sha(Path(__file__)),'template_sha256':sha(TEMPLATE),'healthy_traffic_increase_percent':increase,'output_sha256':{n:sha(out/'sections'/n) for n in ('results.tex','result-values.tex','conclusion.tex')}}
 (data/'claim-bindings.json').write_text(json.dumps(bindings,indent=2,sort_keys=True)+'\n');print(bindings['status'])
if __name__=='__main__':main()
