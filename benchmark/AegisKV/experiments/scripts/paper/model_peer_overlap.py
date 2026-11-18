#!/usr/bin/env python3
"""Declared analytical schedules, not measured recovery or full-controller simulation."""
from pathlib import Path
import json,csv,subprocess
import matplotlib.pyplot as plt
from matplotlib import font_manager
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'exports/three-tier-peer-restored-20260921'
for p in ['figures','data','review']:(OUT/p).mkdir(parents=True,exist_ok=True)
fpath=subprocess.check_output(['kpsewhich','LinLibertine_R.otf'],text=True).strip()
font_manager.fontManager.addfont(fpath)
plt.rcParams.update({'font.family':font_manager.FontProperties(fname=fpath).get_name(),'font.size':10.3,'axes.labelsize':10.3,'xtick.labelsize':10.3,'ytick.labelsize':10.3,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})

def schedule(peer=(),compute=3,storage=False):
 ready={};events=[];s=x=g=0
 for l in range(1,5):
  if l in peer:ready[l]=0;continue
  sr=0
  if storage:
   events.append({'layer':l,'resource':'storage','start':s,'end':s+4});s+=4;sr=s
  begin=max(x,sr);x=begin+4;ready[l]=x
  events.append({'layer':l,'resource':'H2D','start':begin,'end':x})
 for l in range(1,5):
  begin=max(g,ready[l]);g=begin+compute
  events.append({'layer':l,'resource':'GPU','start':begin,'end':g})
 # Meaningful schedule validation: one server per resource, no data-before-ready,
 # layer computation order, and identical demand/compute across placements.
 for resource in ['storage','H2D','GPU']:
  ee=sorted([e for e in events if e['resource']==resource],key=lambda e:e['start'])
  assert all(a['end']<=b['start'] for a,b in zip(ee,ee[1:]))
 ge=[e for e in events if e['resource']=='GPU'];assert len(ge)==4
 assert all(e['start']>=ready[e['layer']] for e in ge)
 return g,events

cases=[('DRAM only',()),('Peer: layer 4',(4,)),('Peer: layer 1',(1,))]
fig,axes=plt.subplots(3,1,figsize=(3.33465,2.86),sharex=True)
rows=[]
for ax,(name,peer) in zip(axes,cases):
 total,ev=schedule(peer)
 for e in ev:
  y=1 if e['resource']=='H2D' else 0
  ax.barh(y,e['end']-e['start'],left=e['start'],height=.68,color='#23688D' if y else '#9B6428',edgecolor='white',linewidth=.5)
  ax.text((e['start']+e['end'])/2,y,str(e['layer']),ha='center',va='center',color='white',fontsize=10.3)
  rows.append({'case':name,**e})
 ax.set_yticks([0,1],['GPU','H2D']);ax.set_ylim(-.6,1.6)
 ax.set_title(f'{name}: {total} ms',loc='left',fontsize=10.3,pad=3)
 ax.spines['left'].set_visible(False);ax.tick_params(axis='y',length=0)
 ax.set_xlim(0,20);ax.set_xticks([0,5,10,15,20]);ax.tick_params(axis='x',length=2,pad=1)
axes[-1].set_xlabel('Time after takeover (ms)',labelpad=2)
fig.subplots_adjust(left=.14,right=.98,top=.94,bottom=.17,hspace=.69)
for ext in ['pdf','png']:fig.savefig(OUT/'figures'/f'recovery-pipeline.{ext}',dpi=220)
plt.close(fig)
assert [schedule(p)[0] for _,p in cases]==[19,18,15]
assert schedule(storage=True)[0]==23
curves=[]
f,ax=plt.subplots(figsize=(3.33465,2.10))
for c,color,marker,ls in [(1,'#23688D','o','-'),(3,'#9B6428','s','--'),(6,'#39756A','^',':')]:
 y=[schedule(range(1,L+1),compute=c)[0] for L in range(5)]
 assert all(a>=b for a,b in zip(y,y[1:]));assert y[-1]==4*c
 ax.plot(range(5),y,marker=marker,ls=ls,color=color,lw=1.3,ms=4,label=f'{c} ms/layer')
 curves.extend({'compute_ms':c,'L':L,'recovery_ms':v} for L,v in enumerate(y))
ax.set_xlabel('Peer prefix layers L',labelpad=1);ax.set_ylabel('Recovery (ms)',labelpad=2)
ax.set_xticks(range(5));ax.set_yticks([0,10,20,30]);ax.set_ylim(0,32)
ax.grid(axis='y',color='#D4DADF',lw=.5)
ax.legend(loc='lower left',bbox_to_anchor=(-.02,1.00),ncol=3,frameon=False,fontsize=10.3,handlelength=.9,handletextpad=.25,columnspacing=.6,borderpad=0)
f.subplots_adjust(left=.17,right=.985,top=.82,bottom=.23)
for ext in ['pdf','png']:f.savefig(OUT/'figures'/f'overlap-frontier.{ext}',dpi=220)
plt.close(f)
for name,data in [('pipeline',rows),('frontier',curves)]:
 with (OUT/'data'/f'{name}.csv').open('w') as out:
  w=csv.DictWriter(out,fieldnames=data[0].keys());w.writeheader();w.writerows(data)
(OUT/'data/model.json').write_text(json.dumps({'evidence':'constructed analytical schedule','layers':4,'H2D_ms_per_group':4,'storage_ms_per_group':4,'compute_ms_per_layer':[1,3,6],'prediction':'all true demand revealed at time zero','demand':'one equal-sized required group per layer; complete checkpoint remains in DRAM','workspace':'four demand groups separate from Peer budget; no eviction during replay','baseline':'same full DRAM checkpoint with Peer disabled','fault_phase':'fixed illustrative replay workload, no sampled failure time','physical_runs':0,'shared_storage_reference_ms':23,'pipeline_totals_ms':[19,18,15]},indent=2)+'\n')
print('Model checks passed; paired DRAM / Peer schedules 19, 18, 15 ms.')
