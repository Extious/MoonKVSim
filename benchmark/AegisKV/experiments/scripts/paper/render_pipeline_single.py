"""Single-column layout of the unchanged calibrated layer recovery pipeline."""
from pathlib import Path
import json
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import render_draft_20260915 as src
from design_plot_typography import configure


def main():
    typography=configure()
    src.OUT=src.OUT/'design-single'
    h=src.u_profile('MiniCPM4-8B',quantity='preload')
    k,floor,scan=src.topk_peer_frontier(h,src.U_REQ,src.C_MS,src.D_MS)
    history=float(next(r for r in src.LAT_META_M['rows'] if r['context']==src.CTX_REF)['prefill_median_s'])
    tail=src.LAYERS*src.C_MS/1000
    fig=plt.figure(figsize=(3.34,3.05))
    legend=[Patch(color=src.BLUE,label='Preload'),
            Patch(facecolor=src.ORANGE,edgecolor='white',hatch='///',label='Demand'),
            Patch(color=src.PALE_BLUE,label='Cold KV'),Patch(color=src.GRAY,label='Compute'),
            Patch(color=src.RED,label='KV wait')]
    fig.legend(handles=legend,loc='upper center',bbox_to_anchor=(.50,1.01),ncol=3,
               handlelength=1,handletextpad=.4,columnspacing=.6,labelspacing=.35)
    # Use the empty last legend cell as the heading for the aligned time column.
    fig.text(.98,.866,'Total/wait (ms)',ha='right',color=src.GRAY)
    left,width=.23,.74
    titles=['Token-block order','Layer-major, full KV','Preload + demand',f'Peer: first {k} layers']
    waits=[];totals=[];transfers_summary=[]
    for i,title in enumerate(titles):
        y=.655-i*.170
        ax=fig.add_axes([left,y,width,.10])
        if i<2:
            _,start,finish=src.pipeline(0,src.D_MS,src.C_MS,layer_major=i==1)
            transfers=[('preload',l,l*src.D_MS,src.D_MS) for l in range(src.LAYERS)]
        else:
            start,finish,transfers=src.sparse_pipeline(0 if i==2 else k,h,src.U_REQ,src.C_MS,src.D_MS)
        for kind,_,t,duration in transfers:
            ax.barh(1,duration,left=t,height=.70,
                    color={'preload':src.BLUE,'demand':src.ORANGE,'cold':src.PALE_BLUE}[kind],
                    edgecolor='white',lw=.15,hatch='///' if kind=='demand' else None)
        for l in range(src.LAYERS):
            prev=finish[l-1] if l else 0
            if start[l]>prev:ax.barh(0,start[l]-prev,left=prev,height=.70,color=src.RED)
            ax.barh(0,src.C_MS,left=start[l],height=.70,color=src.GRAY,edgecolor='white',lw=.15)
        wait=float(finish[-1]-src.LAYERS*src.C_MS)
        waits.append(wait);totals.append(float(finish[-1]))
        transfers_summary.append({kind:sum(d for t,_,_,d in transfers if t==kind) for kind in ['preload','demand','cold']})
        fig.text(.01,y+.12,f'({chr(97+i)})',weight='bold')
        fig.text(.08,y+.12,title)
        fig.text(.98,y+.12,f'{finish[-1]:.0f} / {wait:.0f}',ha='right')
        ax.set(xlim=(0,310),ylim=(-.5,1.5),yticks=[0,1],yticklabels=['Compute','H2D'],xticks=[0,100,200,300])
        ax.tick_params(axis='y',length=0,pad=3)
        ax.spines['bottom'].set_visible(i==3)
        ax.tick_params(axis='x',bottom=i==3,labelbottom=i==3,length=3,pad=3)
        if i==3:ax.set_xlabel('Time after takeover (ms)',labelpad=3)
    old=json.loads((src.OUT.parent/'design-paper/MANIFEST.json').read_text())
    assert np.allclose(waits,old['waits_ms'],rtol=0,atol=1e-9)
    assert np.allclose(totals,old['totals_ms'],rtol=0,atol=1e-9)
    assert k==old['peer_layers'] and abs(k*h*32-old['peer_mib'])<1e-9
    src.save(fig,'design-layer-pipeline',evidence='calibrated analytic illustration',width_in=3.34,
             note='Four restore-and-replay schedules, relabeled (a)-(d). Full-recompute reference removed; history prefill is covered by the Motivation figure. Same inputs, waits, and completion times as design-paper.',
             sources=old['sources'])
    record=src.MANIFEST['design-layer-pipeline']
    record.update(generator=str(Path(__file__).relative_to(src.ROOT)),generator_sha256=src.sha(Path(__file__)),
                  typography=typography,
                  source_hashes={p:src.sha(src.ROOT/p) for p in old['sources']},
                  h=h,effective_fraction=src.U_REQ,C_ms=src.C_MS,D_ms=src.D_MS,peer_layers=k,peer_mib=k*h*32,
                  demand_floor_ms=floor,waits_ms=waits,totals_ms=totals,transfers_ms=transfers_summary,
                  full_recompute_s=history+tail,frontier_scan=scan,
                  previous_manifest_sha256=src.sha(src.OUT.parent/'design-paper/MANIFEST.json'))
    (src.OUT/'MANIFEST.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({n:record[n] for n in ['size_in','waits_ms','totals_ms','peer_mib']}))


if __name__=='__main__':main()
