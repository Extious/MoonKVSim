#!/usr/bin/env python3
"""Replot recorded OOF predictions and an explicit analytical retention example.

No model fitting, new trace collection, or physical serving experiment.
"""
from pathlib import Path
from collections import defaultdict
import csv, json, hashlib, os
os.environ.setdefault('MPLCONFIGDIR', '/tmp/aegiskv-design-evidence-mpl')
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from render_tracker_correlations import rho, FEATURES

BASE = Path(__file__).resolve().parents[3]
OUT = BASE/'exports/design-evidence-review-20260921'
METHODS = [('median', 'Median', '#68747A', ':'),
           ('gbdt_basic', 'GBDT', '#23688D', '-'),
           ('gbdt_history', 'GBDT+history', '#9B6428', '--')]


def save(fig, stem):
    for ext in ['pdf', 'png', 'svg']:
        fig.savefig(OUT/f'figures/{stem}.{ext}', dpi=210, facecolor='white')
    plt.close(fig)


def main():
    for name in ['figures', 'data']:
        (OUT/name).mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10.1,
        'axes.labelsize':10.1, 'xtick.labelsize':10.1, 'ytick.labelsize':10.1,
        'legend.fontsize':10.1, 'pdf.fonttype':42, 'svg.fonttype':'none'})
    primary=BASE/'experiments/data/agent-gbdt-steps/primary-landmark.csv'
    source=BASE/'experiments/data/agent-time-early/landmarks.csv'
    corr_path=BASE/'exports/design-figure-revision-20260920/data/tracker-correlations.csv'
    rows=list(csv.DictReader(primary.open())); features=list(csv.DictReader(source.open()))
    key=lambda r:(r['workflow_id'],r['agent_id'])
    fmap={key(r):r for r in features}; corr=list(csv.DictReader(corr_path.open()))
    assert len(rows)==len(fmap)==1443 and len({key(r) for r in rows})==1443
    assert all(int(r['step'])==2 for r in rows)
    assert all(abs(float(r['actual_remaining_s'])-float(fmap[key(r)]['actual_remaining_s']))<1e-7 for r in rows)
    y=np.array([float(r['actual_remaining_s']) for r in rows]); assert np.all(y>0)
    groups=defaultdict(list); folds=defaultdict(set)
    for i,r in enumerate(rows):
        groups[r['workflow_id']].append(i); folds[r['workflow_id']].add(r['fold'])
    assert len(groups)==170 and all(len(v)==1 for v in folds.values())
    for (name,_),expected in zip(FEATURES,corr):
        x=np.array([float(fmap[key(r)]['current_prompt_tokens'])-float(fmap[key(r)]['first_prompt_tokens'])
            if name=='context_growth' else float(fmap[key(r)][name]) for r in rows])
        assert abs(rho(x,y)-float(expected['spearman_rho']))<1e-10
    stats={}; errors={}; sample_rows=[]
    old=json.loads((BASE/'experiments/data/agent-gbdt-steps/summary.json').read_text())['2']
    for method,*_ in METHODS:
        pred=np.array([float(r[method+'_s']) for r in rows])
        ae=np.abs(pred-y); ape=100*ae/y; errors[method]=ae
        stats[method]={'mae_s':float(ae.mean()),'median_ape_pct':float(np.median(ape)),
          'p90_ape_pct':float(np.percentile(ape,90)), 'within50_pct':float(np.mean(ape<=50)*100),
          'max_ae_s':float(ae.max())}
        for metric in ['mae_s','median_ape_pct','p90_ape_pct','within50_pct']:
            assert abs(stats[method][metric]-old[method][metric])<1e-7
        for r,p,a,b in zip(rows,pred,ae,ape):
            sample_rows.append(dict(workflow_id=r['workflow_id'],agent_id=r['agent_id'],fold=r['fold'],
               method=method,actual_remaining_s=float(r['actual_remaining_s']),prediction_s=p,ae_s=a,ape_pct=b))
    rng=np.random.default_rng(20260921); clusters=list(groups.values()); draws=[]
    for _ in range(2000):
        ids=np.concatenate([clusters[i] for i in rng.integers(0,len(clusters),len(clusters))])
        draws.append([(errors['gbdt_basic'][ids]-errors['median'][ids]).mean(),
                      (errors['gbdt_history'][ids]-errors['gbdt_basic'][ids]).mean()])
    ci=np.percentile(draws,[2.5,97.5],axis=0)
    stats['paired_mae_difference_s_ci95']={'basic_minus_median':ci[:,0].tolist(),'history_minus_basic':ci[:,1].tolist()}
    with (OUT/'data/tracker-oof-errors.csv').open('w') as f:
        wr=csv.DictWriter(f,fieldnames=sample_rows[0].keys());wr.writeheader();wr.writerows(sample_rows)
    fig=plt.figure(figsize=(3.34,4.15))
    ax=fig.add_axes([.50,.62,.46,.30])
    xx=np.array([float(r['spearman_rho']) for r in corr]);lo=np.array([float(r['lower95']) for r in corr]);hi=np.array([float(r['upper95']) for r in corr])
    ax.errorbar(xx,np.arange(6),xerr=[xx-lo,hi-xx],fmt='o',color='#23688D',ecolor='#6E7C85',capsize=3,ms=4,lw=1)
    ax.axvline(0,color='#8A9298',ls=':',lw=.8)
    ax.set(yticks=range(6),yticklabels=['Elapsed time','Input length*','Context growth*','Previous output','Previous API','Previous gap'],
           ylim=(5.5,-.5),xlim=(-.4,.4),xticks=[-.4,0,.4],xlabel='Spearman ρ')
    ax.tick_params(axis='y',length=0,pad=7);ax.grid(axis='x',color='#E7EAED',lw=.6)
    ax.spines[['top','right','left']].set_visible(False)
    fig.text(.02,.98,'(a) Marginal feature associations',weight='bold',va='top')
    ax=fig.add_axes([.18,.11,.78,.275])
    for method,label,color,ls in METHODS:
        vals=np.sort(errors[method]);cdf=np.arange(1,len(vals)+1)/len(vals)
        ax.step(np.r_[0,vals],np.r_[0,cdf],where='post',label=label,color=color,ls=ls,lw=1.2)
    upper=max(v.max() for v in errors.values())*1.05
    ax.set_xscale('symlog',linthresh=1)
    ax.set(xlim=(0,upper),ylim=(0,1),xlabel='Absolute error (s; log above 1 s)',ylabel='Agent fraction',
           xticks=[0,10,100,1000,10000],xticklabels=['0','10','100','1k','10k'],yticks=[0,.5,1])
    ax.spines[['top','right']].set_visible(False);ax.grid(color='#E7EAED',lw=.6)
    fig.legend(ax.get_lines(), ['Median','Basic','History'], loc='upper center',
               bbox_to_anchor=(.56,.455), ncol=3, frameon=False, handlelength=1.1,
               handletextpad=.35, columnspacing=.7, borderaxespad=0)
    fig.text(.02,.50,'(b) Held-out remaining-time errors',weight='bold',va='top')
    save(fig,'tracker-correlations')

    # Conditional on one isolated failure. No normal-use value, prediction error,
    # shared-fault interaction or claim about calibrated hardware parameters.
    slack=np.linspace(0,20,401)
    profiles=[('A',4.,2.,2.,'#9B6428','--'),('B',18.,8.,1.,'#23688D','-')]
    fig,ax=plt.subplots(figsize=(3.34,2.85))
    fig.subplots_adjust(left=.20,right=.97,bottom=.22,top=.87)
    values=[]
    for name,slow,fast,size,color,ls in profiles:
        gain=(np.maximum(0,slow-slack)-np.maximum(0,fast-slack))/size
        ax.plot(slack,gain,color=color,ls=ls,lw=1.4,label=f'{name}: {size:g} units; {slow:g}→{fast:g} s')
        values += [dict(profile=name,slack_s=s,slow_s=slow,fast_s=fast,size_units=size,gain_per_unit=g)
                   for s,g in zip(slack,gain)]
    ax.plot([0],[1],'s',color=profiles[0][4],ms=5,clip_on=False)
    ax.annotate('A: slack 0',xy=(0,1),xytext=(2,3.0),fontsize=10.1,
                arrowprops={'arrowstyle':'-','color':'#9B6428','lw':.8})
    ax.plot([6],[10],'o',color=profiles[1][4],ms=5)
    ax.annotate('B: slack 6',xy=(6,10),xytext=(1,6.8),fontsize=10.1,
                arrowprops={'arrowstyle':'-','color':'#23688D','lw':.8})
    ax.set(xlabel='Slack (s)',ylabel='Saved WCT / unit (s)',xlim=(0,20),ylim=(0,15),xticks=[0,5,10,15,20],yticks=[0,5,10])
    ax.legend(loc='upper right',frameon=False,handlelength=1.5,borderaxespad=.15,labelspacing=.2)
    ax.spines[['top','right']].set_visible(False);ax.grid(color='#E7EAED',lw=.6);ax.set_axisbelow(True)
    fig.text(.02,.985,'Analytical example: slack is insufficient',va='top',weight='bold')
    save(fig,'retention-value')
    with (OUT/'data/retention-value.csv').open('w') as f:
        wr=csv.DictWriter(f,fieldnames=values[0].keys());wr.writeheader();wr.writerows(values)

    # Preserve all published model cohorts and show the identical-budget oracle.
    # This separates a predictor gap from the limited capacity available for the
    # union of KV needed by 64 future queries.
    native_path=BASE/'experiments/data/design-insights/retry-kv-documents.csv'
    native=list(csv.DictReader(native_path.open()))
    native_summary=json.loads((BASE/'experiments/data/design-insights/retry-kv-summary.json').read_text())
    models=['NOSA-3B','MiniCPM4-8B','SeerAttention-Qwen3-8B']; ns=[]
    fig,ax=plt.subplots(figsize=(3.34,2.75))
    fig.subplots_adjust(left=.19,right=.97,top=.69,bottom=.25)
    for j,(method,label,color,hatch) in enumerate([
        ('past_frequency','Past frequency','#23688D',None),
        ('recent_first','Recent first','#E6B896','//')]):
        means=[];low=[];high=[]
        for model in models:
            cohort=[r for r in native if r['model']==model and float(r['budget_fraction'])==.4]
            assert len(cohort)==3 and len({r['book_id'] for r in cohort})==3
            v=np.array([float(r[method]) for r in cohort])*100
            assert abs(v.mean()/100-native_summary['summary'][model][method]['mean'])<1e-10
            assert all(float(r[method])<=float(r['oracle'])+1e-12 for r in cohort)
            means.append(v.mean());low.append(v.mean()-v.min());high.append(v.max()-v.mean())
            ns.append(dict(model=model,method=method,mean_pct=v.mean(),min_pct=v.min(),max_pct=v.max(),n_documents=3))
        ax.bar(np.arange(3)+(j-.5)*.30,means,.30,label=label,color=color,hatch=hatch,
               edgecolor='#344957',lw=.6,yerr=[low,high],capsize=2,error_kw={'lw':.8})
    oracle=[100*native_summary['summary'][m]['oracle']['mean'] for m in models]
    ax.scatter(range(3),oracle,marker='D',s=24,facecolors='white',edgecolors='#253844',label='Oracle budget bound',zorder=5)
    ax.set(ylim=(0,100),yticks=[0,50,100],ylabel='KV coverage (%)',xticks=range(3),
           xticklabels=['NOSA\n3B','MiniCPM\n4-8B','Seer\nQwen3-8B'])
    ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',color='#E7EAED',lw=.6);ax.set_axisbelow(True)
    handles,labels=ax.get_legend_handles_labels()
    order=[labels.index(x) for x in ['Past frequency','Recent first','Oracle budget bound']]
    fig.legend([handles[i] for i in order],[labels[i] for i in order],loc='upper center',
               bbox_to_anchor=(.56,1.02),frameon=False,handlelength=1.4,labelspacing=.25)
    save(fig,'retry-kv-prediction')
    (OUT/'data/native-coverage.json').write_text(json.dumps({'statistics':ns,'oracle_mean_pct':dict(zip(models,oracle)),
      'source':str(native_path.relative_to(BASE)),'source_sha256':hashlib.sha256(native_path.read_bytes()).hexdigest()},indent=2)+'\n')
    manifest={'evidence':'Reanalysis of existing recorded OOF predictions plus a separate constructed analytical example',
      'source_hashes':{str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [primary,source,corr_path]},
      'cohort':{'agents':1443,'workflows':170,'landmark':2,'sample_per_agent':1},
      'target':'whole-agent remaining seconds; not residual DAG segment or Slack accuracy',
      'prediction_protocol':'existing five-fold workflow-disjoint predictions, no new training; all error tails retained',
      'interval':'2000 paired whole-workflow bootstrap samples, predictors fixed; conditional, no retraining uncertainty',
      'tracker':stats,
      'analytical_example':{'gain':'[max(0,Rslow-slack)-max(0,Rfast-slack)]/size',
        'fault':'isolated, conditional on occurrence','normal_reuse_value':0,'hardware_calibration':False,
        'A_at_slack0':{'saved_wct_s':2,'size_units':2,'density':1},
        'B_at_slack6':{'saved_wct_s':10,'size_units':1,'density':10},
        'supports':'Slack-only order is insufficient; size-normalized workflow value matters',
        'does_not_support':'superiority of rental over direct revaluation or general runtime gains'}}
    (OUT/'data/EVIDENCE.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(stats,indent=2))


if __name__=='__main__':main()
