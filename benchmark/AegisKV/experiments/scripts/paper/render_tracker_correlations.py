#!/usr/bin/env python3
"""Observed causal feature associations; no GBDT refit or hardware execution."""
from pathlib import Path
from collections import defaultdict
import csv,json,hashlib,os
os.environ.setdefault('MPLCONFIGDIR','/tmp/aegiskv-tracker-correlation-mpl')
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE=Path(__file__).resolve().parents[3]
OUT=BASE/'exports/design-figure-revision-20260920'
SOURCE=BASE/'experiments/data/agent-time-early/landmarks.csv'
FEATURES=[('elapsed_s','Elapsed time'),('current_prompt_tokens','Current input\nlength proxy'),
 ('context_growth','Context growth\nproxy'),('first_output_tokens','Previous output\ntokens'),
 ('first_api_s','Previous API\nduration'),('since_first_completion_s','Gap after\nprevious API')]

def rank(x):
    _,inv,count=np.unique(x,return_inverse=True,return_counts=True)
    return (np.cumsum(count)-count+(count+1)/2)[inv]

def rho(x,y):
    a,b=rank(x),rank(y)
    return float(np.corrcoef(a,b)[0,1]) if a.std()>0 and b.std()>0 else float('nan')

def main():
    figdir=OUT/'figures';data=OUT/'data'
    for p in [figdir,data]:p.mkdir(parents=True,exist_ok=True)
    rows=list(csv.DictReader(SOURCE.open()))
    assert len(rows)==1443 and len({r['workflow_id'] for r in rows})==170
    assert len({(r['workflow_id'],r['agent_id']) for r in rows})==len(rows)
    for r in rows:
        assert float(r['first_completion_s'])<=float(r['landmark_s'])
        assert float(r['actual_remaining_s'])>0
    # Cohort and labels match the previously evaluated workflow-disjoint GBDT study.
    prev=list(csv.DictReader((BASE/'experiments/data/agent-gbdt-steps/primary-landmark.csv').open()))
    labels={(r['workflow_id'],r['agent_id']):float(r['actual_remaining_s']) for r in prev}
    assert len(labels)==len(rows)
    assert all(abs(float(r['actual_remaining_s'])-labels[(r['workflow_id'],r['agent_id'])])<1e-7 for r in rows)
    y=np.array([float(r['actual_remaining_s']) for r in rows])
    arrays=[]
    for key,_ in FEATURES:
        arrays.append(np.array([float(r['current_prompt_tokens'])-float(r['first_prompt_tokens'])
          if key=='context_growth' else float(r[key]) for r in rows]))
    clusters=defaultdict(list)
    for i,r in enumerate(rows):clusters[r['workflow_id']].append(i)
    groups=list(clusters.values());rng=np.random.default_rng(20260921)
    draws=[]
    for _ in range(2000):
        idx=np.concatenate([groups[j] for j in rng.integers(0,len(groups),len(groups))])
        draws.append([rho(x[idx],y[idx]) for x in arrays])
    ci=np.nanpercentile(np.array(draws),[2.5,97.5],axis=0);summary=[]
    for j,((key,label),x) in enumerate(zip(FEATURES,arrays)):
        summary.append(dict(feature=key,label=label.replace('\n',' '),spearman_rho=rho(x,y),
                            lower95=float(ci[0,j]),upper95=float(ci[1,j])))
    with (data/'tracker-correlations.csv').open('w') as f:
        wr=csv.DictWriter(f,fieldnames=list(summary[0]));wr.writeheader();wr.writerows(summary)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10.1,'axes.labelsize':10.1,
      'xtick.labelsize':10.1,'ytick.labelsize':10.1,'pdf.fonttype':42,'svg.fonttype':'none'})
    fig,ax=plt.subplots(figsize=(3.34,3.35));fig.subplots_adjust(left=.54,right=.93,top=.87,bottom=.16)
    xx=np.array([r['spearman_rho'] for r in summary]);yy=np.arange(len(summary))
    ax.errorbar(xx,yy,xerr=np.vstack([xx-ci[0],ci[1]-xx]),fmt='o',color='#23688D',
                ecolor='#6E7C85',capsize=3,markersize=4.5,lw=1)
    ax.axvline(0,color='#8A9298',ls=':',lw=.8)
    ax.set(yticks=yy,yticklabels=[x[1] for x in FEATURES],ylim=(5.6,-.6),
           xlim=(-.4,.4),xticks=[-.4,0,.4],xlabel='Spearman ρ')
    ax.tick_params(axis='y',length=0,pad=8);ax.grid(axis='x',color='#E7EAED',lw=.6)
    ax.spines[['top','right','left']].set_visible(False)
    fig.text(.04,.97,'Observed signals at request 2',fontsize=10.3,fontweight='bold',va='top')
    assert np.min(ci) > -.4 and np.max(ci) < .4, 'Display must contain complete intervals'
    for ext in ['pdf','png','svg']:fig.savefig(figdir/f'tracker-correlations.{ext}',dpi=210,facecolor='white')
    plt.close(fig)
    manifest={'evidence':'observational offline analysis of existing recorded traces; no predictor refit',
      'target':'whole-Agent remaining seconds at second LLM request arrival, after the first call completes',
      'source':str(SOURCE.relative_to(BASE)),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
      'cohort_match':'All IDs and remaining-second labels match agent-gbdt-steps/primary-landmark.csv',
      'agents':1443,'workflow_clusters':170,'agent_samples_each':1,'correlation':'Spearman with average ranks for ties',
      'interval':'2000 complete-workflow bootstrap resamples; equal contribution per eligible Agent in a resample',
      'bootstrap_seed':20260921,'selection':'All eligible request-2 Agents; no outcome or correlation filtering',
      'limitations':['Association is not causality, GBDT importance or held-out prediction accuracy',
       'All roles are Subagent; categorical model effects not coded as ordinal correlation',
       'Input lengths are 64-token hash-prefix proxies; no exact tokenizer lengths',
       'No explicit tool results, task semantics, future steps or current output/latency used',
       'Conditional intervals do not establish unseen-workflow/time generalization',
       'Whole-Agent label is not validation of residual-segment runtime predictions'],
      'features':summary}
    (data/'TRACKER_PROVENANCE.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
