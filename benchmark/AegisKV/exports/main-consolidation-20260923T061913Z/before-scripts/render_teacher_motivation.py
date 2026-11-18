#!/usr/bin/env python3
"""Single-column O1/O2 figures for the teacher's revised Motivation.

O1 combines trace geometry, measured reconstruction, and conditional WCT.
O2 combines existing native selector traces with a constructed schedule.
Neither panel adds a new physical measurement or a policy result.
"""
from pathlib import Path
import csv
import hashlib
import json
import statistics
import os
os.environ.setdefault('MPLCONFIGDIR', '/tmp/aegiskv-teacher-motivation-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch
from matplotlib.lines import Line2D
import numpy as np
import fitz
from design_plot_typography import configure

BASE = Path(__file__).resolve().parents[3]
REPO = BASE.parents[1]
OUT = BASE/'exports/motivation-teacher-20260923'
DATA = BASE/'experiments/data'
WIDTH = (505.89-24)/2/72.27
HEIGHT = 3.65
INK, BLUE, TEAL = '#243746', '#23688D', '#39756A'
RED, PALE, MINT = '#AC4251', '#DDEBF3', '#E1EEE8'
GRAY, EDGE = '#F1F3F4', '#70808A'
SAND, AMBER = '#F3E5D1', '#9B6428'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def output(fig, name):
    for extension in ['pdf','svg']:
        fig.savefig(OUT/f'figures/{name}.{extension}', facecolor='white')
    plt.close(fig)
    d = fitz.open(OUT/f'figures/{name}.pdf')
    p = d[0]
    spans = [s for b in p.get_text('dict')['blocks'] if b['type']==0
             for l in b['lines'] for s in l['spans'] if s['text'].strip()]
    assert min(s['size'] for s in spans) >= 10
    assert all(p.rect.contains(fitz.Rect(s['bbox'])) for s in spans)
    p.get_pixmap(matrix=fitz.Matrix(3,3)).save(OUT/f'figures/{name}.png')
    p.get_pixmap(matrix=fitz.Matrix(2,2)).save(OUT/f'review/{name}.column.png')
    p.get_pixmap(matrix=fitz.Matrix(2,2),colorspace=fitz.csGRAY).save(OUT/f'review/{name}.gray.png')
    return {'width_mm':p.rect.width*25.4/72,'height_mm':p.rect.height*25.4/72,
            'min_font_pt':min(s['size'] for s in spans),
            'embedded_rasters':len(p.get_images()),'sha256':sha(OUT/f'figures/{name}.pdf')}


def agent_value():
    folder = DATA/'motivation-compact-cc'
    with (folder/'compact-example-failure-position.csv').open() as f:
        rows = sorted(csv.DictReader(f),key=lambda r:int(r['branch_index']))
    costs = json.loads((folder/'recovery-costs-measured.json').read_text())
    assert costs['wct_evidence']=='calculated_not_fault_injected'
    assert costs['cost_evidence']=='physical_worker_microbenchmark'
    for rel,digest in costs['source_sha256'].items():
        assert sha(REPO/rel)==digest,rel
    records=costs['workflow_costs']
    assert len(rows)==len(records)==4
    origin=min(float(r['branch_start_s']) for r in rows)
    join=max(float(r['branch_end_s']) for r in rows)-origin
    for row,cost in zip(rows,records):
        assert int(row['prefix_tokens'])==cost['prefix_tokens']
        assert statistics.median(cost['trials_s'])==cost['recompute_s']
        assert abs(join-(float(row['branch_end_s'])-origin)-float(row['slack_s']))<1e-8
        changed=max(float(r['branch_end_s'])+(cost['recompute_s'] if r is row else 0)
                    for r in rows)
        assert abs(changed-(origin+join)-cost['wct_increase_s'])<1e-8

    fig=plt.figure(figsize=(WIDTH,HEIGHT))
    fig.text(.5,.976,'(a) Four-branch workflow',ha='center',va='top')
    ax=fig.add_axes([.015,.55,.97,.37])
    ax.set_xlim(-39,194);ax.set_ylim(3.6,-.95);ax.set_axis_off()
    ax.plot([-6,-6],[0,3],color=EDGE,lw=.8,zorder=1)
    ax.plot([join,join],[0,3],color=EDGE,lw=.8,zorder=1)
    for name,x in [('A0',-37),('A5',166)]:
        ax.add_patch(Rectangle((x,1.15),25,.70,fc='#F7E6E9',ec=RED,lw=.8))
        ax.text(x+12.5,1.50,name,ha='center',va='center',color=INK)
    ax.plot([-12,-6],[1.5,1.5],color=EDGE,lw=.8)
    ax.annotate('',xy=(166,1.5),xytext=(join,1.5),
                arrowprops={'arrowstyle':'->','lw':.8,'color':EDGE,'mutation_scale':6})
    for i,row in enumerate(rows):
        start=float(row['branch_start_s'])-origin
        end=float(row['branch_end_s'])-origin
        duration=float(row['duration_s'])
        critical=float(row['slack_s'])==0
        ax.plot([-6,start],[i,i],color=EDGE,lw=.8,zorder=1)
        ax.add_patch(Rectangle((start,i-.30),duration,.60,
                              fc='#F7E6E9' if critical else PALE,
                              ec=RED if critical else BLUE,lw=.8,zorder=2))
        ax.text((start+end)/2,i,f'A{i+1} {duration:.1f}s',ha='center',va='center')
        if not critical:
            ax.plot([end,join],[i,i],color=EDGE,lw=.85,ls=(0,(3,2)),zorder=1)
        if i==0:
            ax.text((end+join)/2,i-.40,'91.2 s slack',ha='center',va='bottom',color=INK)
    fig.legend(handles=[Patch(fc='#F7E6E9',ec=RED,label='Critical path'),
                        Line2D([0],[0],color=EDGE,ls=(0,(3,2)),label='Join slack')],
               loc='center',bbox_to_anchor=(.5,.505),ncol=2,frameon=False,
               handlelength=1.1,columnspacing=.9,handletextpad=.4)

    fig.text(.5,.465,'(b) Reconstruction and workflow delay',ha='center',va='top')
    ax=fig.add_axes([.13,.135,.665,.245])
    stat=fig.add_axes([.835,.135,.15,.245],sharey=ax)
    t=np.array([r['recompute_s'] for r in records])
    lo=np.array([r['trial_min_s'] for r in records]);hi=np.array([r['trial_max_s'] for r in records])
    added=np.array([r['wct_increase_s'] for r in records]);absorbed=t-added
    y=np.arange(4)
    ax.barh(y,absorbed,height=.60,fc=MINT,ec=TEAL,hatch='///',lw=.55,label='Absorbed')
    ax.barh(y,added,left=absorbed,height=.60,fc=RED,ec=RED,lw=.55,label='Added WCT')
    ax.errorbar(t,y,xerr=[t-lo,hi-t],fmt='none',ecolor=INK,elinewidth=.7,capsize=2,capthick=.6)
    for i,cost in enumerate(records):
        ax.text(hi[i]+.6,i,f'{t[i]:.1f}',va='center',ha='left')
        stat.text(.5,i,f'{added[i]:.1f}',va='center',ha='center')
    ax.set_xlim(0,53);ax.set_ylim(3.55,-.55)
    ax.set_yticks(y,['A1','A2','A3','A4']);ax.set_xticks([0,20,40])
    ax.set_xlabel('Reconstruction time (s)',labelpad=2)
    ax.spines[['top','right','left']].set_visible(False)
    ax.tick_params(axis='y',length=0,pad=3);ax.tick_params(axis='x',length=2,pad=2)
    ax.grid(axis='x',lw=.5,color='#E1E5E8');ax.set_axisbelow(True)
    stat.set_xlim(0,1);stat.set_axis_off()
    stat.text(.5,1.04,'ΔW (s)',transform=stat.transAxes,ha='center',va='bottom')
    fig.legend(*ax.get_legend_handles_labels(),loc='center',bbox_to_anchor=(.44,.396),
               ncol=2,frameon=False,handlelength=1.0,handletextpad=.4,columnspacing=1)
    geometry=output(fig,'agent_value')
    return {'geometry':geometry,'workflow_id':costs['workflow_id'],
            'costs':records,'counterfactual':costs['counterfactual'],
            'evidence':costs['evidence'],
            'inputs':{str(p.relative_to(BASE)):sha(p) for p in
                      [folder/'compact-example-failure-position.csv',folder/'recovery-costs-measured.json']}}


def kv_value():
    folder=DATA/'kv-access-concentration-8b-20260921'
    with (folder/'curves.csv').open() as f:curves=list(csv.DictReader(f))
    summaries=json.loads((folder/'summary.json').read_text())
    styles=[('NOSA-8B',BLUE,'o','-'),('NSA-8B',AMBER,'s','--'),
            ('MiniCPM4.1-8B',TEAL,'^','-.')]
    fig=plt.figure(figsize=(WIDTH,HEIGHT))
    fig.text(.5,.976,'(a) Historical KV access concentration',ha='center',va='top')
    ax=fig.add_axes([.18,.515,.78,.29])
    selected=[]
    for model,color,marker,style in styles:
        rows=sorted([r for r in curves if r['model']==model and r['metric']=='query_block'
                     and int(r['window_queries'])==512],key=lambda r:int(r['K']))
        assert [int(r['K']) for r in rows]==list(range(504))
        x=np.array([float(r['block_fraction'])*100 for r in rows])
        mean,low,high=[np.array([float(r[k])*100 for r in rows]) for k in ['mean','min','max']]
        summary=next(r for r in summaries if r['model']==model and r['metric']=='query_block'
                     and r['window_queries']==512)
        assert abs(mean[101]/100-summary['top20']['mean'])<1e-12
        ax.fill_between(x,low,high,color=color,alpha=.13,lw=0)
        ax.plot(x,mean,color=color,ls=style,lw=1.15,marker=marker,
                markevery=[51,101,202,302,403],ms=3.2,mfc='white',mew=.8,label=model)
        selected.append(summary)
    ax.plot([0,100],[0,100],color=EDGE,ls=':',lw=.85,label='Uniform')
    ax.set_xlim(0,100);ax.set_ylim(0,103)
    ax.set_xticks([0,20,40,60,80,100]);ax.set_yticks([0,25,50,75,100])
    ax.set_xlabel('Hot historical blocks (%)',labelpad=2)
    ax.set_ylabel('Access share (%)',labelpad=2)
    ax.tick_params(length=2,pad=2);ax.spines[['top','right']].set_visible(False)
    ax.grid(axis='y',lw=.5,color='#E1E5E8');ax.set_axisbelow(True)
    handles,labels=ax.get_legend_handles_labels()
    order=[0,2,1,3]  # Read NOSA, NSA, MiniCPM in row order, matching the prose.
    fig.legend([handles[i] for i in order],[labels[i] for i in order],loc='upper center',bbox_to_anchor=(.53,.93),
               ncol=2,frameon=False,handlelength=1.45,handletextpad=.35,
               columnspacing=.7,labelspacing=.25,borderaxespad=0)

    fig.text(.5,.392,'(b) Recovery overlap (schematic)',ha='center',va='top')
    ax=fig.add_axes([.24,.095,.735,.225])
    ax.set_xlim(0,10.2);ax.set_ylim(2.05,-.65);ax.set_axis_off()
    schedule={'evidence':'constructed schedule, arbitrary time units; not measured',
              'initial_state':'Layer 1 KV resident; future layer demand known',
              'compute':[['L1',0,3],['L2',3,5],['L3',7,10]],
              'transfers':[['L2',0,2],['L3',2,7]],'exposed_wait':[5,7]}
    # One serialized transfer stream. A layer starts only after both its
    # previous layer and its own KV are ready. Layer 3 exposes a two-unit wait.
    assert schedule['transfers'][0][2]<=schedule['compute'][1][1]
    assert schedule['compute'][2][1]==max(schedule['compute'][1][2],schedule['transfers'][1][2])
    for label,start,end in schedule['compute']:
        ax.add_patch(Rectangle((start,-.27),end-start,.54,fc=GRAY,ec=EDGE,lw=.65))
        ax.text((start+end)/2,0,label,ha='center',va='center')
    ax.add_patch(Rectangle((5,-.27),2,.54,fc='#F7E6E9',ec=RED,hatch='///',lw=.65))
    ax.text(6,0,'Wait',ha='center',va='center',color=RED,
            bbox={'facecolor':'#F7E6E9','edgecolor':'none','pad':.2})
    for label,start,end in schedule['transfers']:
        ax.add_patch(Rectangle((start,.73),end-start,.54,fc=PALE,ec=BLUE,lw=.65))
        ax.text((start+end)/2,1,label,ha='center',va='center')
    for x in [5,7]:ax.plot([x,x],[.30,1.40],color=RED,lw=.65,ls=(0,(2,2)))
    ax.text(-.4,0,'Compute',ha='right',va='center')
    ax.text(-.4,1,'KV load',ha='right',va='center')
    ax.annotate('',xy=(10.1,1.80),xytext=(0,1.80),
                arrowprops={'arrowstyle':'->','lw':.7,'color':INK,'mutation_scale':6})
    ax.text(5.1,2.01,'Time (schematic)',ha='center',va='top')
    geometry=output(fig,'kv_value')
    (OUT/'data/overlap-schedule.json').write_text(json.dumps(schedule,indent=2)+'\n')
    return {'geometry':geometry,'native_concentration':selected,'schedule':schedule,
            'inputs':{str(p.relative_to(BASE)):sha(p) for p in
                      [folder/'curves.csv',folder/'summary.json',folder/'protocol.json']}}


def main():
    for folder in ['figures','review','data']:(OUT/folder).mkdir(parents=True,exist_ok=True)
    typography=configure()
    plt.rcParams.update({'font.size':10.25,'axes.labelsize':10.25,'axes.titlesize':10.25,
                         'xtick.labelsize':10.25,'ytick.labelsize':10.25,'legend.fontsize':10.25,
                         'text.color':INK,'axes.labelcolor':INK,'xtick.color':INK,'ytick.color':INK,
                         'axes.linewidth':.65,'pdf.fonttype':42,'svg.fonttype':'none'})
    report={'generator':str(Path(__file__).resolve()),'generator_sha256':sha(__file__),
            'typography':typography,'figure_font_pt':10.25,
            'agent_value':agent_value(),'kv_value':kv_value(),'new_gpu_runs':0}
    (OUT/'figure-manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({name:report[name]['geometry'] for name in ['agent_value','kv_value']},indent=2))


if __name__=='__main__':main()
