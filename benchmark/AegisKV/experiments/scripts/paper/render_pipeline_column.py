#!/usr/bin/env python3
"""Re-layout the unchanged analytical SSD/H2D/replay model for one column."""
from pathlib import Path
import csv,json
import model_storage_overlap as model
import matplotlib.pyplot as plt
BASE=Path(__file__).resolve().parents[3];OUT=BASE/'exports/design-figure-revision-20260920'
FIG=OUT/'figures';DATA=OUT/'data'

def main():
 for p in [FIG,DATA]:p.mkdir(parents=True,exist_ok=True)
 plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10.1,'axes.labelsize':10.1,
   'xtick.labelsize':10.1,'ytick.labelsize':10.1,'pdf.fonttype':42,'svg.fonttype':'none'})
 cases=[('All groups on SSD',set()),('Layer 4 in DRAM',{4}),('Layer 1 in DRAM',{1})]
 fig,axes=plt.subplots(3,1,figsize=(3.34,3.65),sharex=True)
 fig.subplots_adjust(left=.165,right=.98,top=.94,bottom=.14,hspace=.90)
 colors={'SSD':'#E7CDAA','H2D':'#A5C8DE','GPU':'#A8CEC0'};rows=[]
 for ax,(label,resident) in zip(axes,cases):
  jobs,total=model.schedule(resident)
  for j in jobs:
   y={'SSD':2,'H2D':1,'GPU':0}[j['stage']]
   ax.barh(y,j['end']-j['start'],left=j['start'],height=.88,color=colors[j['stage']],
           edgecolor='#36444C',lw=.6,hatch='//' if j['stage']=='SSD' else None)
   ax.text((j['start']+j['end'])/2,y,str(j['layer']),ha='center',va='center',fontsize=10.1)
   rows.append(dict(case=label,**j))
  ax.set_yticks([2,1,0],['SSD','H2D','GPU']);ax.set_ylim(-.6,2.6)
  ax.set_title(f'{label} · {total:g} ms',loc='left',fontsize=10.1,pad=4)
  ax.axvline(total,color='#263C49',lw=.8,ls=':')
  ax.spines[['top','right','left']].set_visible(False);ax.tick_params(axis='y',length=0,pad=4)
  ax.grid(axis='x',color='#E6E9EB',lw=.6);ax.set_axisbelow(True)
 axes[-1].set(xlabel='Recovery time (ms)',xlim=(0,21),xticks=[0,5,10,15,20])
 for ext in ['pdf','svg','png']:fig.savefig(FIG/f'recovery-pipeline.{ext}',dpi=220,facecolor='white')
 plt.close(fig)
 with (DATA/'pipeline-events.csv').open('w') as f:
  wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)
 (DATA/'PIPELINE_CHECKS.json').write_text(json.dumps({'cases_checked':model.validate(),
   'semantics':'unchanged from preceding analytical model; only rendering changed',
   'totals_ms':{name:model.schedule(r)[1] for name,r in cases},
   'assumptions_source':'exports/system-design-dram-ssd-20260920/data/MODEL.json'},indent=2)+'\n')
 print('Re-rendered unchanged 20/19/16 ms pipeline in one column')
if __name__=='__main__':main()
