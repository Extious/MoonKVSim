#!/usr/bin/env python3
"""Deterministic illustrative SSD/H2D/compute timelines, not measurements.

One serial resource per stage. Every needed group is correctly predicted at
time zero. All selected KV fit the declared transient recovery workspace.
The model excludes rate interference, control delay and contention with other
requests; those limits are explicit in the paper, data and review record.
"""
from pathlib import Path
import csv, json, itertools, os
os.environ.setdefault('MPLCONFIGDIR','/tmp/aegiskv-storage-design-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BASE=Path(__file__).resolve().parents[3]
OUT=BASE/'exports/system-design-dram-ssd-20260920'
DATA=OUT/'data'; FIG=OUT/'figures'


def schedule(resident, compute=3., ssd=4., h2d=1., layers=4):
    resident=set(resident); jobs=[]; ready={}; st=0.
    for l in range(1,layers+1):
        if l in resident:ready[l]=0.
        else:
            jobs.append(dict(stage='SSD',layer=l,start=st,end=st+ssd))
            st+=ssd;ready[l]=st
    pending=set(ready); t=0.; gpu_ready={}
    while pending:
        available=[l for l in pending if ready[l]<=t]
        if not available:
            t=min(ready[l] for l in pending)
            available=[l for l in pending if ready[l]<=t]
        l=min(available)
        jobs.append(dict(stage='H2D',layer=l,start=t,end=t+h2d))
        t+=h2d;gpu_ready[l]=t;pending.remove(l)
    t=0.
    for l in range(1,layers+1):
        start=max(t,gpu_ready[l]);t=start+compute
        jobs.append(dict(stage='GPU',layer=l,start=start,end=t))
    return jobs,t


def validate():
    count=0
    for c in [1.,3.,6.]:
        for mask in itertools.product([False,True],repeat=4):
            resident={i+1 for i,x in enumerate(mask) if x}
            jobs,total=schedule(resident,c)
            for stage in ['SSD','H2D','GPU']:
                tasks=sorted([j for j in jobs if j['stage']==stage],key=lambda j:j['start'])
                assert all(a['end']<=b['start'] for a,b in zip(tasks,tasks[1:]))
            for l in range(1,5):
                h=next(j for j in jobs if j['stage']=='H2D' and j['layer']==l)
                g=next(j for j in jobs if j['stage']=='GPU' and j['layer']==l)
                if l not in resident:
                    s=next(j for j in jobs if j['stage']=='SSD' and j['layer']==l)
                    assert s['end']<=h['start']
                assert h['end']<=g['start']
            assert total==max(j['end'] for j in jobs)
            count+=1
    assert schedule(set())[1]==20
    assert schedule({1})[1]==16
    assert schedule({4})[1]==19
    return count


def main():
    for p in [DATA,FIG]:p.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10.5,'axes.labelsize':10.5,
                         'xtick.labelsize':10.05,'ytick.labelsize':10.5,'legend.fontsize':10.05,
                         'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none'})
    colors={'SSD':'#E7CDAA','H2D':'#A5C8DE','GPU':'#A8CEC0'}
    cases=[('All groups on SSD',set()),('Keep layer 4 in DRAM',{4}),('Keep layer 1 in DRAM',{1})]
    fig,axes=plt.subplots(3,1,figsize=(7.,3.65),sharex=True)
    fig.subplots_adjust(left=.115,right=.945,top=.84,bottom=.13,hspace=.76)
    rows=[]
    for ax,(label,resident) in zip(axes,cases):
        jobs,total=schedule(resident)
        for j in jobs:
            y={'SSD':2,'H2D':1,'GPU':0}[j['stage']]
            ax.barh(y,j['end']-j['start'],left=j['start'],height=.72,
                    color=colors[j['stage']],edgecolor='#36444C',lw=.6,
                    hatch='//' if j['stage']=='SSD' else None)
            ax.text((j['start']+j['end'])/2,y,str(j['layer']),ha='center',va='center',fontsize=10.05)
            rows.append(dict(case=label,**j))
        ax.set_yticks([2,1,0],['SSD','H2D','GPU']);ax.set_ylim(-.6,2.6)
        ax.set_title(label,loc='left',fontsize=10.5,pad=5)
        ax.axvline(total,color='#263C49',lw=.9,ls=':')
        ax.text(total+.22,.0,f'{total:g} ms',ha='left',va='center',fontsize=10.05)
        ax.spines[['top','right','left']].set_visible(False)
        ax.tick_params(axis='y',length=0,pad=6)
        ax.grid(axis='x',color='#E6E9EB',lw=.6);ax.set_axisbelow(True)
    axes[-1].set_xlabel('Time since restore begins (ms)')
    axes[-1].set_xlim(0,23);axes[-1].set_xticks(range(0,21,4))
    fig.text(.115,.967,'Illustrative model  |  numbers in bars denote layers',fontsize=10.5,va='top')
    for ext in ['pdf','svg','png']:fig.savefig(FIG/f'recovery-pipeline.{ext}',dpi=180,facecolor='white')
    plt.close(fig)
    with (DATA/'pipeline-events.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    fig,ax=plt.subplots(figsize=(3.34,2.35))
    fig.subplots_adjust(left=.21,right=.97,top=.73,bottom=.25)
    sweep=[]
    for c,color,marker,ls in [(1.,'#23688D','o','-'),(3.,'#9B6428','s','--'),(6.,'#39756A','^',':')]:
        yy=[]
        for d in range(5):
            total=schedule(range(1,d+1),c)[1];yy.append(total)
            sweep.append(dict(compute_ms=c,dram_groups=d,total_ms=total))
        ax.plot(range(5),yy,color=color,marker=marker,ls=ls,lw=1.2,ms=4,label=f'C = {c:g} ms')
    ax.set(xlabel='Early-layer groups in DRAM',ylabel='Restore time (ms)',xticks=range(5),ylim=(0,32))
    ax.spines[['top','right']].set_visible(False);ax.grid(color='#E6E9EB',lw=.6)
    fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.59,.99),frameon=False,
               ncol=1,labelspacing=.15,handlelength=1.6)
    for ext in ['pdf','svg','png']:fig.savefig(FIG/f'overlap-frontier.{ext}',dpi=200,facecolor='white')
    plt.close(fig)
    with (DATA/'overlap-frontier.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(sweep[0]));w.writeheader();w.writerows(sweep)
    manifest={'evidence':'deterministic illustrative model; no physical measurement',
              'layers':4,'ssd_ms_per_group':4,'h2d_ms_per_group':1,'compute_ms_default':3,
              'group_bytes':'equal normalized payloads; no hardware bandwidth claim',
              'prediction':'all needed groups correctly predicted and available as prefetch targets at time zero',
              'workspace':'holds four selected groups; separate from persistent DRAM retention budget',
              'resources':'independent serial SSD, H2D and GPU resources; no bandwidth interference',
              'schedule':'SSD in layer order; ready H2D jobs in layer order; GPU strictly layer order',
              'validated_cases':validate(),'pipeline_totals_ms':{name:schedule(r)[1] for name,r in cases},
              'limitations':['No foreground competition','No sparse predictor miss','No control latency',
                             'No SSD queue jitter','No distributed TP overhead']}
    (DATA/'MODEL.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
