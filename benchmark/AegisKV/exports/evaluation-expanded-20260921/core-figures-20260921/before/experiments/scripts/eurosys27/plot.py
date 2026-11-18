#!/usr/bin/env python3
"""Plot analytical or measured tables using one stable visual contract.

Measured mode requires a distinct provenance manifest with verified raw-file
hashes; changing a CSV evidence label alone cannot publish a measured figure.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
DEFAULT=ROOT/'experiments/data/eurosys27/theory'
OUT=ROOT/'exports/eurosys-complete-20260920/figures'
WIDTH=3.33465
COLORS=['#2868A5','#CB7A28','#389680','#A64461','#5C538F','#626262']
STYLE={
 'Storage only':(COLORS[0],'--','v'), 'LRU':(COLORS[1],'-','s'),
 'Reuse only':(COLORS[2],':','^'), 'AegisKV model':(COLORS[3],'-','o'),
 'AegisKV':(COLORS[3],'-','o'), 'Feasible oracle':(COLORS[4],'-.','D'),
 'All DRAM':(COLORS[5],':','x'),
}
SPECS={
 'workflow-outcomes':('cdf','Workflow failure penalty (s)','Scenario fraction',2.6),
 'capacity-frontier':('budget','DRAM budget (GiB)','Workflow failure penalty (s)',2.6),
 'storage-bottleneck':('bandwidth','Storage read bandwidth (GiB/s)','Workflow failure penalty (s)',2.6),
 'prediction-robustness':('error','Signed duration perturbation (%)','Workflow failure penalty (s)',2.6),
 'checkpoint-lag':('lag','Commit lag (s)','Workflow failure penalty (s)',2.6),
 'healthy-io':('load','Backup link utilization (%)','Mean I/O response time (ms)',2.6),
 'common-fault':('counterexample','Branches retained in DRAM','Delay (s)',2.5),
 'controller-scaling':('scaling','Live DAG segments','Decision time (ms)',2.6),
}


def setup():
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10.5,
        'axes.labelsize':10.5,'axes.titlesize':10.5,'legend.fontsize':10.3,
        'xtick.labelsize':10.3,'ytick.labelsize':10.3,'pdf.fonttype':42,
        'ps.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,
        'axes.spines.right':False,'axes.linewidth':.7,'lines.linewidth':1.4,
        'savefig.dpi':220,'axes.axisbelow':True})


def read_tables(data,mode):
    manifest=json.loads((data/'manifest.json').read_text())
    if manifest['evidence'] != mode:
        raise ValueError(f'Manifest evidence {manifest["evidence"]} differs from mode {mode}')
    if mode=='analytical':
        sources=manifest.get('source_files',{})
        if not sources:raise ValueError('Analytical mode needs model/config source hashes')
        for src in sources.values():
            if len(src['paths'])!=len(src['sha256']):raise ValueError('Mismatched source hash list')
            for relative,digest in zip(src['paths'],src['sha256']):
                p=ROOT/relative
                if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
                    raise ValueError(f'Changed analytical source; regenerate tables: {p}')
    if mode=='measured':
        sources=manifest.get('raw_sources',[])
        if not sources:
            raise ValueError('Measured mode needs raw_sources with paths and SHA-256 digests')
        for src in sources:
            p=data/src['path']
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=src['sha256']:
                raise ValueError(f'Raw source failed hash check: {p}')
        if not manifest.get('aggregation_command') or not manifest.get('statistical_unit'):
            raise ValueError('Measured mode requires aggregation_command and statistical_unit')
    tables={}
    for path in sorted(data.glob('*.csv')):
        if path.stem=='scenario-results':continue
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if manifest.get('tables',{}).get(path.name)!=digest:
            raise ValueError(f'Changed or unregistered input table: {path.name}')
        rows=list(csv.DictReader(path.open()))
        if not rows:continue
        for r in rows:
            if r['evidence']!=mode:raise ValueError(f'Mixed evidence in {path.name}')
            for k in ['x','y']:
                r[k]=float(r[k])
                if not math.isfinite(r[k]):raise ValueError(f'Non-finite {k} in {path}')
            for k in ['lower','upper']:
                r[k]=float(r[k]) if r[k] else None
            if (r['lower'] is None)!=(r['upper'] is None):raise ValueError('Both interval endpoints required')
            if r['lower'] is not None and (not math.isfinite(r['lower']) or not math.isfinite(r['upper']) or r['lower']>r['upper']):
                raise ValueError('Invalid uncertainty interval')
            expected_unit='fraction' if path.stem=='workflow-outcomes' else 'GiB' if path.stem=='safe-demotion' else 'ms' if path.stem in ['healthy-io','controller-scaling'] else 's'
            if r['unit']!=expected_unit:raise ValueError(f'Wrong unit for {path.stem}: {r["unit"]}')
            if r['figure']!=path.stem:raise ValueError('Row figure does not match table filename')
            allowed_panels=({'fault','reuse'} if path.stem=='policy-ablation' else
                            {'occupancy','copied'} if path.stem=='safe-demotion' else
                            {SPECS[path.stem][0]} if path.stem in SPECS else set())
            if r['panel'] not in allowed_panels:raise ValueError(f'Unknown figure/panel: {path.stem}/{r["panel"]}')
            if mode=='analytical' and r['source_id'] not in manifest['source_files']:
                raise ValueError('Analytical row source_id has no model-source record')
            if mode=='measured' and int(r['independent_runs'])<1:raise ValueError('Measured row has no runs')
            if mode=='measured' and r['source_id'] not in {s.get('id') for s in manifest['raw_sources']}:
                raise ValueError('Measured row source_id has no raw-source record')
            if mode=='analytical' and (int(r['independent_runs'])!=0 or r['lower'] is not None):
                raise ValueError('Analytical scenarios have neither physical runs nor confidence intervals')
        tables[path.stem]=rows
    return tables,manifest


def badge(fig,mode):
    fig.text(.985,.99,'Analytical scenarios' if mode=='analytical' else 'Measured',
             ha='right',va='top',fontsize=10.3,color='#555555')


def save(fig,name,out,mode,publish):
    badge(fig,mode)
    out.mkdir(parents=True,exist_ok=True)
    # Fixed physical canvas: never bbox_inches=tight (changes final font scale).
    for ext in ['pdf','png','svg']:fig.savefig(out/(name+'.'+ext),facecolor='white')
    if publish:
        import shutil
        target=ROOT/'paper/figures';target.mkdir(exist_ok=True)
        shutil.copy2(out/(name+'.pdf'),target/(name+'.pdf'))
        prev=target/'preview';prev.mkdir(exist_ok=True)
        shutil.copy2(out/(name+'.png'),prev/(name+'.png'))
    plt.close(fig)


def lines(ax,rows,step=False):
    series=list(dict.fromkeys(r['series'] for r in rows))
    for index,s in enumerate(series):
        rs=sorted((r for r in rows if r['series']==s),key=lambda r:r['x'])
        x=[r['x'] for r in rs];y=[r['y'] for r in rs]
        if step and rows[0]['panel']=='cdf':
            x=[x[0]]+x;y=[0]+y
        c,ls,m=STYLE.get(s,(COLORS[index%6],['-','--',':','-.'][index%4],['o','s','^','D'][index%4]))
        ax.plot(x,y,label=s,color=c,ls=ls,marker=None if step else m,
                markersize=3.4,markerfacecolor='white',drawstyle='steps-post' if step else 'default')
        bounded=[r for r in rs if r['lower'] is not None]
        if bounded:
            bx=[r['x'] for r in bounded]
            low=[r['lower'] for r in bounded];high=[r['upper'] for r in bounded]
            ax.vlines(bx,low,high,color=c,lw=.8)
            ax.scatter(bx,low,color=c,marker='_',s=15);ax.scatter(bx,high,color=c,marker='_',s=15)
    ax.grid(axis='y',color='#DDDDDD',lw=.6)
    return series


def plot(data,out,mode,publish=False):
    setup();tables,manifest=read_tables(data,mode)
    for name,(panel,xlabel,ylabel,height) in SPECS.items():
        if name not in tables:continue
        rows=[r for r in tables[name] if r['panel']==panel]
        fig,ax=plt.subplots(figsize=(WIDTH,height))
        fig.subplots_adjust(left=.20,right=.985,bottom=.25,top=.67)
        series=lines(ax,rows,step=(name=='workflow-outcomes'))
        if mode=='measured' and name=='workflow-outcomes':ylabel='Workflow fraction'
        ax.set(xlabel=xlabel,ylabel=ylabel)
        if name=='workflow-outcomes':
            ax.set_ylim(0,1.03);ax.set_xlim(left=min(0,min(r['x'] for r in rows)))
        else:
            low=min(min(r['y'],r['lower']) if r['lower'] is not None else r['y'] for r in rows)
            ax.set_ylim(bottom=min(0,low*1.15))
        if name=='storage-bottleneck':
            ax.set_xscale('log',base=2);ax.set_xticks([.5,2,8,20]);ax.set_xticklabels(['0.5','2','8','20'])
        if name=='prediction-robustness':ax.set_xticks([-100,-50,0,50,100])
        if name=='common-fault':ax.set_xticks([0,1,2])
        if name=='controller-scaling':
            if any(r['x']<=0 or r['y']<=0 or (r['lower'] is not None and r['lower']<=0) for r in rows):
                raise ValueError('Controller log axes require positive values and bounds')
            ax.set_xscale('log');ax.set_yscale('log')
            ax.set_xlim(min(8,min(r['x'] for r in rows)/1.1),max(20000,max(r['x'] for r in rows)*1.1))
            ax.set_xticks([10,100,1000,10000]);ax.set_xticklabels(['10','100','1000','10000'])
            extents=[r[k] for r in rows for k in ['y','lower','upper'] if r[k] is not None]
            ax.set_ylim(min(extents)/1.5,max(extents)*1.5)
            ax.set_yticks([.1,1,10,100,1000,10000]);ax.set_yticklabels(['0.1','1','10','100','1000','10000'])
            fig.subplots_adjust(left=.255)
        fig.legend(*ax.get_legend_handles_labels(),loc='upper left',bbox_to_anchor=(.13,.94),
                   ncol=2 if len(series)>3 else 1,frameon=False,columnspacing=.8,
                   handlelength=1.8,handletextpad=.4,borderaxespad=0)
        save(fig,name,out,mode,publish)
    if 'policy-ablation' in tables:
        rows=tables['policy-ablation'];fig,axes=plt.subplots(1,2,figsize=(7.0,2.5))
        fig.subplots_adjust(left=.075,right=.99,top=.84,bottom=.31,wspace=.37)
        labels={'LRU':'LRU','Reuse only':'Reuse','No dependencies':'No DAG',
            'No reuse value':'No reuse','AegisKV model':'AegisKV\nmodel','Feasible oracle':'Oracle'}
        for ax,panel,title in zip(axes,['fault','reuse'],['(a) Failure penalty','(b) Next-use restore']):
            rs=[r for r in rows if r['panel']==panel]
            y=[r['y'] for r in rs];x=np.arange(len(rs))
            ax.bar(x,y,color=[STYLE.get(r['series'],(COLORS[4],))[0] for r in rs],
                   edgecolor='#333333',lw=.5,hatch=['','//','..','xx','','\\\\'])
            ax.set_xticks(x);ax.set_xticklabels([labels.get(r['series'],r['series']) for r in rs],rotation=30,ha='right')
            ax.set_ylabel('Mean delay (s)');ax.set_title(title);ax.grid(axis='y',color='#DDDDDD',lw=.6)
            bounded=[(i,r) for i,r in enumerate(rs) if r['lower'] is not None]
            if bounded:
                ax.vlines([i for i,r in bounded],[r['lower'] for i,r in bounded],
                          [r['upper'] for i,r in bounded],color='black',lw=.8)
            low=min(r[k] for r in rs for k in ['y','lower'] if r[k] is not None)
            ax.set_ylim(bottom=min(0,low*1.15))
        save(fig,'policy-ablation',out,mode,publish)
    if 'safe-demotion' in tables:
        fig,ax=plt.subplots(figsize=(WIDTH,2.6));fig.subplots_adjust(left=.19,right=.985,bottom=.25,top=.70)
        lines(ax,tables['safe-demotion'],step=True)
        extent=[r[k] for r in tables['safe-demotion'] for k in ['y','lower','upper'] if r[k] is not None]
        ax.set(xlabel='Time since capacity event (s)',ylabel='Bytes (GiB)',
               ylim=(min(0,min(extent)*1.1),max(27,max(extent)*1.1)))
        fig.legend(*ax.get_legend_handles_labels(),loc='upper left',bbox_to_anchor=(.13,.94),
                   frameon=False,ncol=2,columnspacing=.8,handlelength=1.8,handletextpad=.4)
        save(fig,'safe-demotion',out,mode,publish)
    record={'evidence':mode,'source_directory':str(data),'input_manifest_sha256':hashlib.sha256((data/'manifest.json').read_bytes()).hexdigest(),
       'renderer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
       'canvas_width_in':WIDTH,'font_pt':10.5,'table_count':len(tables),
       'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.pdf'))}}
    (out/'render-manifest.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=DEFAULT)
    p.add_argument('--output',type=Path,default=OUT)
    p.add_argument('--mode',choices=['analytical','measured'],default='analytical')
    p.add_argument('--publish',action='store_true')
    a=p.parse_args();plot(a.data,a.output,a.mode,a.publish)
