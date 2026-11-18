#!/usr/bin/env python3
"""Reconstruct paired contrasts and color figures from fully accepted fresh runs."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
from statistics import mean,stdev
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
BLUE,ORANGE,GREEN,PURPLE,RED,GRAY='#0072B2','#C77700','#008568','#7651A8','#C44747','#59636F'
COLORS={'unprotected':GRAY,'dram':ORANGE,'full':BLUE,'no_slack':PURPLE,'no_aimd':GREEN,'lru_eviction':RED}
LABELS={'unprotected':'Unprotected','dram':'DRAM-only','full':'Full AegisKV','no_slack':'No Slack','no_aimd':'No AIMD','lru_eviction':'LRU'}
POINTS=('base','concurrency8','concurrency32','serial500','serial1000','bandwidth5','failures2')
POINT_LABELS=('Base: C=16','C=8','C=32',r'$\beta=0.5$',r'$\beta=1$','5 GB/s','Two faults')
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10.5,'axes.labelsize':10.5,'axes.titlesize':10.5,
 'xtick.labelsize':10.5,'ytick.labelsize':10.5,'legend.fontsize':10.5,'svg.fonttype':'none','svg.hashsalt':'aegiskv-aligned-20260906','pdf.fonttype':42,
 'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7})

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ci(values):
 values=list(map(float,values));assert len(values)==5
 center=mean(values);half=2.7764451051977987*stdev(values)/math.sqrt(5)
 return {'samples':values,'mean':center,'low':center-half,'high':center+half,'unit':'seconds','n':5}
def save(fig,out,name):
 fig.canvas.draw();renderer=fig.canvas.get_renderer();bounds=fig.bbox
 hidden=set()
 for ax in fig.axes:
  for axis in (ax.xaxis,ax.yaxis):
   lo,hi=sorted(axis.get_view_interval())
   for tick in [*axis.get_major_ticks(),*axis.get_minor_ticks()]:
    if not lo<=tick.get_loc()<=hi:hidden.update((id(tick.label1),id(tick.label2)))
 for text in fig.findobj(match=matplotlib.text.Text):
  if id(text) not in hidden and text.get_visible() and text.get_text().strip():
   b=text.get_window_extent(renderer)
   assert b.x0>=-.5 and b.y0>=-.5 and b.x1<=bounds.width+.5 and b.y1<=bounds.height+.5,(name,text.get_text(),tuple(b.extents),tuple(bounds.extents))
 for ext in ('pdf','svg','png'):fig.savefig(out/f'{name}.{ext}',dpi=220,facecolor='white')
 plt.close(fig)
def points(ax,values,x,color,label=None):
 summary=ci(values)
 ax.scatter(x+np.linspace(-.10,.10,5),values,s=23,color=color,alpha=.72,marker='o',label=label,zorder=3)
 ax.errorbar([x],[summary['mean']],yerr=[[summary['mean']-summary['low']],[summary['high']-summary['mean']]],
             color=color,fmt='D',ms=5,capsize=5,lw=1.6,zorder=4)
 return summary

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--campaign',type=Path,required=True)
 parser.add_argument('--paper',type=Path,required=True);parser.add_argument('--preview',action='store_true',help='all executed cells; separate directory only; no raw-acceptance claim');args=parser.parse_args()
 campaign=args.campaign.resolve();paper=args.paper.resolve();out=paper/'figures';data=paper/'data';data.mkdir(exist_ok=True)
 protocol=json.loads((campaign/'PROTOCOL.json').read_text());assert protocol['expected_measured_runs']==170
 if args.preview:
  assert paper!=Path(__file__).resolve().parents[4]/'benchmark/AegisKV/paper/simulation-8b'
  execution=json.loads((campaign/'EXECUTION.json').read_text());assert execution['status']=='PASS' and execution['measured_runs']==170
  acceptance=None;accepted=None;out.mkdir(exist_ok=True)
 else:
  acceptance=json.loads((campaign/'ACCEPTANCE.json').read_text())
  assert acceptance['status']=='PASS' and acceptance['measured_runs']==170
  accepted={tuple(x['job']):x['raw_sha256'] for x in acceptance['accepted_runs']};assert len(accepted)==170
 runs={};bindings={}
 for job in protocol['jobs']:
  p,s,f,a=job;path=campaign/'runs'/p/f'seed{s}'/f'{f}-{a}.json';d=json.loads(path.read_text())
  assert d['identity']['job']==job
  if not args.preview:assert d['raw_evidence']['sha256']==accepted[tuple(job)]
  assert d['identity']['contract']==protocol['fingerprint']
  if not args.preview:assert protocol['fingerprint']==acceptance['contract']
  runs[tuple(job)]=d['summary'];bindings[str(path.relative_to(campaign))]=digest(path)
 plans={}
 for p in ('base','concurrency8','concurrency32','failures2'):
  for s in range(5):
   path=campaign/'plans'/f'{p}-seed{s}.json';d=json.loads(path.read_text());assert d['contract']==protocol['fingerprint'];plans[p,s]=d['schedule']['events'];bindings[str(path.relative_to(campaign))]=digest(path)
 def get(p,s,f,a):return runs[('base' if p=='failures2' and f=='F0' else p,s,f,a)]
 def focuses(p,s):
  q=p if p in ('base','concurrency8','concurrency32','failures2') else 'base'
  ids={e['focus_span_id'] for e in plans[q,s]};d=get(p,s,'F1','full')['span_details']
  return {x['workflow_id'] for x in d if x['span_id'] in ids}
 def score(p,s,f,a,cohort='all'):
  r=get(p,s,f,a);values=r['wct_ns'];selected=values if cohort=='all' else {w:values[w] for w in focuses(p,s)}
  return mean(selected.values())/1e9
 def penalty(p,s,a,cohort='all'):return score(p,s,'F1',a,cohort)-score(p,s,'F0',a,cohort)
 def gamma(p,a='full',b='dram',cohort='all'):
  return [penalty(p,s,a,cohort)-penalty(p,s,b,cohort) for s in range(5)]
 for p in POINTS:
  for s in range(5):
   arms=protocol['points'][p]['arms'];orders=[get(p,s,'F1',a)['workflow_admission']['realized_workflow_order_sha256'] for a in arms]
   orders +=[get(p,s,'F0',a)['workflow_admission']['realized_workflow_order_sha256'] for a in arms]
   assert len(set(orders))==1
 stats={'schema':'moonkvsim.aligned_paper_analysis.v1','status':'PREVIEW_UNVERIFIED_RAW' if args.preview else 'PASS','measured_runs':170,
        'protocol_fingerprint':protocol['fingerprint'],'acceptance_sha256':None if args.preview else digest(campaign/'ACCEPTANCE.json'),
        'input_bindings':bindings,'generator_sha256':digest(Path(__file__)),
        'primary':{},'healthy':{},'ablations':{},'sensitivity':{}}
 for control in ('dram','unprotected'):
  stats['primary'][control]={cohort:ci(gamma('base',b=control,cohort=cohort)) for cohort in ('all','focus')}
  stats['healthy'][control]=ci([score('base',s,'F0','full')-score('base',s,'F0',control) for s in range(5)])
 for a in ('no_slack','no_aimd','lru_eviction'):
  stats['ablations'][a]={cohort:ci(gamma('base',a=a,b='full',cohort=cohort)) for cohort in ('all','focus')}
 for p in POINTS:stats['sensitivity'][p]={cohort:ci(gamma(p,cohort=cohort)) for cohort in ('all','focus')}
 # Complete finite-workload descriptive endpoints, not 800 independent replicates.
 stats['endpoints']={}
 for a in ('unprotected','dram','full','no_slack','no_aimd','lru_eviction'):
  stats['endpoints'][a]={}
  for f in ('F0','F1'):
   stats['endpoints'][a][f]={
    'mean_wct_s':[score('base',s,f,a) for s in range(5)],
    'p95_wct_s':[sorted(get('base',s,f,a)['wct_ns'].values())[math.ceil(.95*160)-1]/1e9 for s in range(5)],
    'batch_s':[get('base',s,f,a)['metrics']['workload_end_ns']/1e9 for s in range(5)],
    'protection_GiB':[sum(v for k,v in get('base',s,f,a)['metrics']['resource_cost']['cause_bytes'].items() if k.endswith('_PROTECTION'))/2**30 for s in range(5)]}
 # Healthy cost.
 fig,axs=plt.subplots(1,2,figsize=(7.05,2.65));fig.subplots_adjust(left=.11,right=.985,bottom=.20,top=.84,wspace=.47)
 for i,b in enumerate(('unprotected','dram')):points(axs[0],stats['healthy'][b]['samples'],i,COLORS[b])
 axs[0].axhline(0,color=GRAY,lw=.8,ls=':');axs[0].set_xticks([0,1],['vs unprotected','vs DRAM']);axs[0].set(title='(a) Healthy WCT difference',ylabel='Full minus control (s)')
 for i,a in enumerate(('unprotected','dram','full')):points(axs[1],stats['endpoints'][a]['F0']['protection_GiB'],i,COLORS[a])
 axs[1].set_xticks([0,1,2],['None','DRAM','Full']);axs[1].set(title='(b) Protection traffic',ylabel='Transferred GiB / workload',ylim=(0,None))
 axs[1].set_ylim(bottom=-.04*max(stats['endpoints']['full']['F0']['protection_GiB']))
 save(fig,out,'aligned-healthy')
 # Failure effects and descriptive CDF.
 fig,axs=plt.subplots(1,3,figsize=(7.05,2.65));fig.subplots_adjust(left=.105,right=.98,bottom=.25,top=.84,wspace=.55)
 for a,style in zip(('unprotected','dram','full'),(':','--','-')):
  values=sorted(v/1e9 for s in range(5) for v in get('base',s,'F1',a)['wct_ns'].values())
  axs[0].step(values,np.arange(1,len(values)+1)/len(values),where='post',color=COLORS[a],ls=style,label=LABELS[a],lw=1.3)
 axs[0].set(title='(a) WCT distribution',xlabel='WCT (s)',ylabel='Cumulative fraction',ylim=(0,1.02));axs[0].set_yticks([0,.5,1])
 axs[0].legend(frameon=False,fontsize=10.5,loc='lower right',handlelength=1.3)
 for ax,cohort,title in [(axs[1],'all','(b) Mean penalty'),(axs[2],'focus','(c) Focus penalty')]:
  for i,b in enumerate(('unprotected','dram')):points(ax,stats['primary'][b][cohort]['samples'],i,COLORS[b])
  ax.axhline(0,color=GRAY,lw=.8,ls=':');ax.set_xticks([0,1],['None','DRAM']);ax.set_xlim(-.5,1.5);ax.set(title=title,ylabel='Full minus control (s)')
 save(fig,out,'aligned-failure')
 # Direct focus recovery, exactly one primary focus per seed.
 focus_rows=[]
 for s in range(5):
  fid=plans['base',s][0]['focus_span_id']
  for a in ('dram','full'):
   r=get('base',s,'F1',a);d=next(x for x in r['span_details'] if x['span_id']==fid)
   tokens=[d['restored_peer_tokens'],d['restored_store_tokens'],d['recompute_tokens']]
   assert d['recovery_normal_hbm_local_tokens']==0 and sum(tokens)>0
   focus_rows.append(dict(seed=s,arm=a,span_id=fid,workflow_id=d['workflow_id'],tokens=tokens,
      materialization_s=(d['recovery_ready_ns']-d['failure_at_ns'])/1e9,
      failure_s=d['failure_at_ns']/1e9,gpu_id=d['gpu_id']))
 stats['focus_recovery']=focus_rows
 stats['base_interventions']=[]
 stats['focus_workflow_traces']=[]
 for s in range(5):
  selected=focuses('base',s)
  for a in ('unprotected','dram','full'):
   r=get('base',s,'F1',a)
   for e in r['failure_events']:
    stats['base_interventions'].append(dict(seed=s,arm=a,timestamp_ns=e['timestamp_ns'],
     gpu_id=e['target_gpu_id'],focus_span_id=e['logical_trigger']['focus_span_id'],
     active_victims=e['impacted_active_span_ids'],queued_victims=e['impacted_queued_span_ids'],
     trigger=e['logical_trigger']['continuous_progress_evidence']))
   for f in ('F0','F1'):
    r=get('base',s,f,a)
    stats['focus_workflow_traces'].append(dict(seed=s,arm=a,condition=f,
     workflows={w:r['wct_ns'][w] for w in selected},
     spans=[d for d in r['span_details'] if d['workflow_id'] in selected]))
 fig,axs=plt.subplots(1,2,figsize=(7.05,2.9));fig.subplots_adjust(left=.09,right=.985,bottom=.20,top=.76,wspace=.45)
 for j,a in enumerate(('dram','full')):
  rows=[x for x in focus_rows if x['arm']==a];matrix=np.array([x['tokens'] for x in rows]);matrix=matrix/matrix.sum(axis=1)[:,None]*100
  x=np.arange(5)+(j-.5)*.35;bottom=np.zeros(5)
  for k,(name,color) in enumerate(zip(('HBM copy','DRAM load','Recompute'),(BLUE,ORANGE,RED))):
   axs[0].bar(x,matrix[:,k],bottom=bottom,width=.32,color=color,edgecolor='white',lw=.3,hatch=('..','//','')[k],label=name if j==1 else None);bottom+=matrix[:,k]
  axs[1].bar(x,[r['materialization_s'] for r in rows],width=.32,color=COLORS[a],label=LABELS[a])
 axs[0].set(title='(a) Prompt recovery sources',ylabel='Focus prompt tokens (%)',ylim=(0,100));axs[1].set(title='(b) Recovery preparation',ylabel='Fault to prefix ready (s)')
 for ax in axs:ax.set_xticks(range(5),range(5));ax.set_xlabel('Admission seed (DRAM / Full)')
 axs[0].legend(loc='upper center',bbox_to_anchor=(.5,1.46),ncol=3,frameon=False,handlelength=1,columnspacing=.8)
 axs[1].legend(frameon=False,loc='upper left',bbox_to_anchor=(.0,1.46),ncol=2,handlelength=1,columnspacing=.8)
 save(fig,out,'aligned-recovery')
 # Mechanism ablations.
 fig,axs=plt.subplots(1,2,figsize=(7.05,2.65));fig.subplots_adjust(left=.105,right=.985,bottom=.20,top=.84,wspace=.43)
 for ax,cohort,title in [(axs[0],'all','(a) Whole-workload mean'),(axs[1],'focus','(b) Focus workflow')]:
  for i,a in enumerate(('no_slack','no_aimd','lru_eviction')):points(ax,stats['ablations'][a][cohort]['samples'],i,COLORS[a])
  ax.axhline(0,color=GRAY,lw=.8,ls=':');ax.set_xticks(range(3),['No Slack','No AIMD','LRU']);ax.set(title=title,ylabel='Ablation minus full penalty (s)')
 save(fig,out,'aligned-ablations')
 # Sensitivity; source settings and focus plans are explicit in PROTOCOL.
 fig,axs=plt.subplots(1,2,figsize=(7.05,3.3));fig.subplots_adjust(left=.17,right=.985,bottom=.19,top=.90,wspace=.38)
 for ax,cohort,title in [(axs[0],'all','(a) Whole-workload mean'),(axs[1],'focus','(b) Focus workflow')]:
  for i,p in enumerate(POINTS):
   x=stats['sensitivity'][p][cohort];ax.scatter(x['samples'],i+np.linspace(-.12,.12,5),s=17,color=BLUE,alpha=.5)
   ax.errorbar(x['mean'],i,xerr=[[x['mean']-x['low']],[x['high']-x['mean']]],fmt='D',color=BLUE,ms=4,capsize=4,lw=1.3)
  ax.axvline(0,color=GRAY,lw=.8,ls=':');ax.set_yticks(range(7),POINT_LABELS if ax is axs[0] else ['']*7)
  ax.invert_yaxis();ax.set(title=title,xlabel='Full minus DRAM penalty (s)')
 save(fig,out,'aligned-sensitivity')
 # One transparent table of absolute endpoints and one source-to-claim record.
 (data/'aligned-statistics.json').write_text(json.dumps(stats,indent=2,sort_keys=True)+'\n')
 lines=['# '+('Preview; raw verification pending' if args.preview else 'Accepted revised simulation results'),'',f"170 complete runs; protocol {protocol['fingerprint']}",'']
 for group in ('primary','healthy','ablations','sensitivity'):
  lines += [f'## {group}','',json.dumps(stats[group],indent=2),'']
 (data/'aligned-statistics.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps({k:stats[k] for k in ('primary','healthy','ablations','sensitivity','endpoints')},indent=2))
if __name__=='__main__':main()
