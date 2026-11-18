#!/usr/bin/env python3
"""Reproduce frozen recovery schedules and audit exclusive managed occupancy.

No new physical measurements. Recovery starts after placement is complete;
the figure does not include promotion/demotion or a storage read stage.
"""
from pathlib import Path
import ast, csv, hashlib, json, subprocess
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'exports/exclusive-kv-master-20260921'
LEGACY = ROOT/'experiments/scripts/paper/render_draft_20260915.py'
MANIFEST = ROOT/'Archived/paper-overleaf-20260919/paper/figures/design-single/MANIFEST.json'


def main():
    old = json.loads(MANIFEST.read_text())
    # Load only the two pure scheduling functions, without legacy module side effects.
    nodes = [n for n in ast.parse(LEGACY.read_text()).body
             if isinstance(n, ast.FunctionDef) and n.name in {'pipeline', 'sparse_pipeline'}]
    env = {'np': np, 'LAYERS': 32}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(LEGACY), 'exec'), env)
    h, u, c, d, k = [old[key] for key in ['h','effective_fraction','C_ms','D_ms','peer_layers']]
    font = subprocess.check_output(['kpsewhich','LinLibertine_R.otf'],text=True).strip()
    font_manager.fontManager.addfont(font)
    font_manager.fontManager.addfont(subprocess.check_output(['kpsewhich','LinLibertine_RB.otf'],text=True).strip())
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=font).get_name(),
        'font.size':10.3,'pdf.fonttype':42,'svg.fonttype':'none',
        'axes.spines.top':False,'axes.spines.right':False,'axes.spines.left':False})
    colors = {'preload':'#23688D','demand':'#9B6428','cold':'#C6DDE8',
              'compute':'#566168','wait':'#B55459'}
    fig = plt.figure(figsize=(3.33465,3.5))
    legend = [Patch(color=colors['preload'],label='Preload'),
              Patch(facecolor=colors['demand'],edgecolor='white',hatch='///',label='Demand'),
              Patch(color=colors['cold'],label='Cold KV'),
              Patch(color=colors['compute'],label='Compute'),
              Patch(color=colors['wait'],label='KV wait')]
    fig.legend(handles=legend,loc='upper center',bbox_to_anchor=(.5,1.005),ncol=3,frameon=False,
               handlelength=.9,handletextpad=.35,columnspacing=.55,labelspacing=.3)
    fig.text(.985,.825,'Total/wait (ms)',ha='right',color=colors['compute'])
    titles = ['Token-block order','Layer-major, full KV','Preload + demand','Peer: first 7 layers']
    events, results = [], []
    for i, title in enumerate(titles):
        y = .661 - i*.163
        ax = fig.add_axes([.23,y,.745,.085])
        if i < 2:
            _, start, finish = env['pipeline'](0,d,c,layer_major=i==1)
            transfers = [('preload',l,l*d,d) for l in range(32)]
        else:
            start, finish, transfers = env['sparse_pipeline'](0 if i==2 else k,h,u,c,d)
        for kind, layer, t, duration in transfers:
            ax.barh(1,duration,left=t,height=.7,color=colors[kind],edgecolor='white',
                    lw=.15,hatch='///' if kind=='demand' else None)
            events.append(dict(case=i,kind=kind,layer=layer,start_ms=t,duration_ms=duration))
        for layer in range(32):
            prev = finish[layer-1] if layer else 0
            if start[layer] > prev:
                ax.barh(0,start[layer]-prev,left=prev,height=.7,color=colors['wait'])
            ax.barh(0,c,left=start[layer],height=.7,color=colors['compute'],edgecolor='white',lw=.15)
        wait = float(finish[-1]-32*c)
        peer = 0 if i < 3 else k*h*32
        dram = 1024-peer
        assert np.isclose(sum(x[3] for x in transfers)/d*32,dram)
        assert np.isclose(wait,old['waits_ms'][i])
        assert np.isclose(finish[-1],old['totals_ms'][i])
        results.append(dict(case=i,peer_mib=peer,dram_mib=dram,storage_mib=0,
                            managed_mib=peer+dram,total_ms=float(finish[-1]),wait_ms=wait))
        fig.text(.01,y+.107,f'({chr(97+i)})',weight='bold')
        fig.text(.075,y+.107,title)
        fig.text(.985,y+.107,f'{finish[-1]:.0f}/{wait:.0f}',ha='right')
        ax.set(xlim=(0,310),ylim=(-.5,1.5),yticks=[0,1],yticklabels=['GPU','H2D'],xticks=[0,100,200,300])
        ax.tick_params(axis='y',length=0,pad=3)
        ax.spines['bottom'].set_visible(i==3)
        ax.tick_params(axis='x',bottom=i==3,labelbottom=i==3,length=3,pad=3)
        if i==3:
            ax.set_xlabel('Time after takeover (ms)',labelpad=2)
    fig.text(.5,.008,'(d): Peer 147.5 + DRAM 876.5 MiB',ha='center')
    for ext in ['pdf','png','svg']:
        fig.savefig(OUT/'figures'/f'recovery-pipeline.{ext}',dpi=220,facecolor='white')
    plt.close(fig)
    with (OUT/'data/pipeline-events.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(events[0]));writer.writeheader();writer.writerows(events)
    record={'evidence':'reproduced calibrated analytical schedules with exclusive residency accounting',
        'inputs':{n:old[n] for n in ['h','effective_fraction','C_ms','D_ms','peer_layers','peer_mib']},
        'cases':results,'total_managed_kv_mib':1024,'new_physical_runs':0,
        'scope':'DRAM/Peer slice; storage is inactive. Placement complete before failure. Execution workspace separate.',
        'limitations':['ideal preemptible H2D stream','homogeneous layer means','no finite-workspace pressure',
                       'no foreground queues','no promotion or demotion cost in this static comparison',
                       'cold KV transferred after replay; it does not delay the plotted tail completion'],
        'source_manifest':str(MANIFEST.relative_to(ROOT)),
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in [LEGACY,MANIFEST]},'preserved_source_hashes':old['source_hashes']}
    (OUT/'data/pipeline-provenance.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(results,indent=2))


if __name__=='__main__':
    main()
