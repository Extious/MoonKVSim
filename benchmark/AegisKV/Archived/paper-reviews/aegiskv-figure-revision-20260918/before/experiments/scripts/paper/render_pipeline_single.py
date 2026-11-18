"""Single-column layout of the unchanged calibrated layer recovery pipeline."""
from pathlib import Path
import json
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import render_draft_20260915 as src


def main():
    src.OUT=src.OUT/'design-single'
    h=src.u_profile('MiniCPM4-8B',quantity='preload')
    k,floor,scan=src.topk_peer_frontier(h,src.U_REQ,src.C_MS,src.D_MS)
    history=float(next(r for r in src.LAT_META_M['rows'] if r['context']==src.CTX_REF)['prefill_median_s'])
    tail=src.LAYERS*src.C_MS/1000
    fig=plt.figure(figsize=(3.34,6.3))
    legend=[Patch(color=src.BLUE,label='Preload / full KV'),
            Patch(facecolor=src.ORANGE,edgecolor='white',hatch='///',label='Demand fetch'),
            Patch(color=src.PALE_BLUE,label='Cold KV'),Patch(color=src.GRAY,label='Tail compute'),
            Patch(color=src.RED,label='KV wait'),Patch(color=src.PURPLE,label='History prefill')]
    fig.legend(handles=legend,loc='upper center',bbox_to_anchor=(.50,.995),ncol=2,
               handlelength=1,handletextpad=.4,columnspacing=.6,labelspacing=.35)
    left,width=.23,.74
    full=fig.add_axes([left,.765,width,.06])
    full.barh(0,history,height=.65,color=src.PURPLE)
    full.barh(0,tail,left=history,height=.65,color=src.GRAY)
    full.text(history/2,0,f'{history:.2f} s',color='white',ha='center',va='center')
    full.set(xlim=(0,6),ylim=(-.6,.6),yticks=[0],yticklabels=['Compute'],xticks=[0,2,4,6])
    full.tick_params(axis='y',length=0,pad=3)
    full.set_xlabel('Time (s)',labelpad=3)
    fig.text(left,.848,'(a) Full recompute',weight='bold')
    fig.text(.97,.848,f'{history+tail:.2f} s',ha='right')
    titles=['(b) Token-block order','(c) Layer-major, full KV','(d) Preload + demand',f'(e) Peer: first {k} layers']
    waits=[];totals=[];transfers_summary=[]
    for i,title in enumerate(titles):
        y=.51-i*.14
        ax=fig.add_axes([left,y,width,.055])
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
        fig.text(left,y+.108,title,weight='bold')
        fig.text(left,y+.078,f'{finish[-1]:.0f} ms total; {wait:.0f} ms wait')
        ax.set(xlim=(0,310),ylim=(-.5,1.5),yticks=[0,1],yticklabels=['Compute','H2D'],xticks=[0,100,200,300])
        ax.tick_params(axis='y',length=0,pad=3)
        ax.tick_params(axis='x',labelbottom=i==3,length=3,pad=3)
        if i==3:ax.set_xlabel('Time after takeover (ms)',labelpad=3)
    old=json.loads((src.OUT.parent/'design-paper/MANIFEST.json').read_text())
    assert np.allclose(waits,old['waits_ms'],rtol=0,atol=1e-9)
    assert np.allclose(totals,old['totals_ms'],rtol=0,atol=1e-9)
    assert k==old['peer_layers'] and abs(k*h*32-old['peer_mib'])<1e-9
    src.save(fig,'design-layer-pipeline',evidence='calibrated analytic illustration',width_in=3.34,
             note='Single-column layout only. Same model, inputs, schedule, waits, and tail completion times as design-paper. All transfer and compute segments are retained.',
             sources=old['sources'])
    record=src.MANIFEST['design-layer-pipeline']
    record.update(generator=str(Path(__file__).relative_to(src.ROOT)),generator_sha256=src.sha(Path(__file__)),
                  source_hashes={p:src.sha(src.ROOT/p) for p in old['sources']},
                  h=h,effective_fraction=src.U_REQ,C_ms=src.C_MS,D_ms=src.D_MS,peer_layers=k,peer_mib=k*h*32,
                  demand_floor_ms=floor,waits_ms=waits,totals_ms=totals,transfers_ms=transfers_summary,
                  full_recompute_s=history+tail,frontier_scan=scan,
                  previous_manifest_sha256=src.sha(src.OUT.parent/'design-paper/MANIFEST.json'))
    (src.OUT/'MANIFEST.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({n:record[n] for n in ['size_in','waits_ms','totals_ms','peer_mib']}))


if __name__=='__main__':main()
