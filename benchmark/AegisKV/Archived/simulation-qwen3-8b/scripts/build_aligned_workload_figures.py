#!/usr/bin/env python3
"""Descriptive workload and labeled motivation evidence, without treatment outcomes."""
import json,hashlib
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'benchmark/AegisKV/experiments/results/paper/legacy-rendered-figures'
WORK=ROOT/'benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl'
BLUE,ORANGE,GREEN,PURPLE,RED='#0072B2','#C77700','#008568','#7651A8','#C44747'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10.5,'axes.labelsize':10.5,'axes.titlesize':10.5,
 'xtick.labelsize':10.5,'ytick.labelsize':10.5,'legend.fontsize':10.5,'svg.fonttype':'none','svg.hashsalt':'aegiskv-aligned-20260906','pdf.fonttype':42,'ps.fonttype':42,
 'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7})
def save(fig,name):
 OUT.mkdir(parents=True,exist_ok=True)
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
 for suffix in ['pdf','svg','png']:
  fig.savefig(OUT/f'{name}.{suffix}',dpi=220,facecolor='white')
 plt.close(fig)
def main():
 records=[json.loads(line) for line in WORK.open() if line.strip()]
 prompt=np.array([r['prompt_tokens'] for r in records]);context=np.array([r['prompt_tokens']+r['output_tokens'] for r in records])
 workflows={w:sum(r['workflow_id']==w for r in records) for w in {r['workflow_id'] for r in records}}
 fig,axes=plt.subplots(1,3,figsize=(7.05,2.6));fig.subplots_adjust(left=.09,right=.98,bottom=.33,top=.82,wspace=.56)
 for ax,values,title,xlabel,color in [(axes[0],prompt/1024,'(a) Prompt length','Prompt tokens (Ki)',BLUE),
         (axes[1],list(workflows.values()),'(b) Workflow size','Calls per workflow',GREEN)]:
  x=np.sort(values);ax.step(x,np.arange(1,len(x)+1)/len(x),where='post',color=color,lw=1.6)
  ax.set(title=title,xlabel=xlabel,ylabel='Cumulative fraction',ylim=(0,1.04));ax.set_yticks([0,.5,1]);ax.grid(alpha=.18)
 axes[0].set_xticks([0,40,80]);axes[1].set_xticks([5,10,15])
 bounds=np.array([8,16,32,64,96,128]);counts=np.histogram(context,bins=np.r_[0,bounds*1024])[0]
 ax=axes[2];bars=ax.bar(np.arange(6),counts,color=[GREEN]*5+['#B8BEC5'],width=.7)
 for b,n in zip(bars,counts):
  if n==0:ax.text(b.get_x()+b.get_width()/2,max(counts)*.03,'0',ha='center',va='bottom')
 ax.set_xticks(range(6),[str(x) for x in bounds],rotation=45,ha='right');ax.set(title='(c) Context coverage',xlabel='Context upper bound\n(Ki tokens)',ylabel='Calls',ylim=(0,max(counts)*1.24))
 save(fig,'aligned-workload')
 fig,axes=plt.subplots(1,2,figsize=(7.05,3.1));fig.subplots_adjust(left=.085,right=.985,bottom=.23,top=.73,wspace=.43)
 x=np.linspace(0,96,97);one=x*1024*147456/2**30
 ax=axes[0];ax.plot(x,one,label='One KV copy',color=BLUE,lw=1.7);ax.plot(x,2*one,label='Two KV copies',color=ORANGE,lw=1.7,ls='--')
 available=(40*2**30-16381470720-2*2**30)/2**30
 ax.axhline(available,color=RED,ls=':',lw=1.5,label='Post-reserve capacity')
 ax.set(title='(a) Declared Qwen3-8B KV layout',xlabel='Prompt length (Ki tokens)',ylabel='HBM footprint (GiB)',xlim=(0,96),ylim=(0,29))
 ax.set_xticks([0,32,64,96]);fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.27,.995),ncol=2,frameon=False,fontsize=10.5,handlelength=1.3,columnspacing=.8)
 profile_path=OUT.parent/'data/physical-pilot/pilot-cost-profile.json'
 profile=json.loads(profile_path.read_text()); rates=profile['values']
 assert profile['status']=='PASS'
 ax=axes[1];v=np.array([[rates['hbm_protection_bandwidth_bytes_per_ms'],rates['dram_protection_bandwidth_bytes_per_ms']],
                       [rates['hbm_recovery_bandwidth_bytes_per_ms'],rates['dram_recovery_bandwidth_bytes_per_ms']]])/1e6
 for j,(name,color) in enumerate([('HBM path',BLUE),('DRAM path',ORANGE)]):
  b=ax.bar(np.arange(2)+(j-.5)*.31,v[:,j],width=.3,label=name,color=color)
  for rect,n in zip(b,v[:,j]):ax.text(rect.get_x()+rect.get_width()/2,n+.07,f'{n:.2f}',ha='center')
 ax.set(title='(b) Measured RTX4090 pilot rates',ylabel='Effective service (GB/s)',ylim=(0,3.35))
 ax.set_xticks([0,1],['Protection','Recovery']);fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.775,.995),frameon=False,ncol=1,handlelength=1)
 save(fig,'aligned-motivation-cost')
 data={'workload_sha256':hashlib.sha256(WORK.read_bytes()).hexdigest(),'requests':len(records),'workflows':len(workflows),
  'maximum_prompt':int(max(prompt)),'maximum_context':int(max(context)), 'context_bins_Ki':bounds.tolist(),'context_counts':counts.tolist(),
  'kv_bytes_per_token':147456,'post_reserve_GiB':available,
  'rate_profile_sha256':hashlib.sha256(profile_path.read_bytes()).hexdigest(),
  'rates_scope':'same-allocation physical-pilot-146426/pilot-cost-profile.json; effective host-staged rates; not A100 calibration'}
 (OUT/'descriptive-data.json').write_text(json.dumps(data,indent=2)+'\n')
 print(data)
if __name__=='__main__':main()
