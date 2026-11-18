"""Only plot newly completed physical observations; no illustrative arrays."""
from pathlib import Path
import csv
import hashlib
import json
import os
import shutil
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parent/'mpl-cache'))
import fitz
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D

ROOT=Path(__file__).resolve().parent
AEGIS=ROOT.parents[1]
PAPER=AEGIS/'paper'
RUNS=AEGIS/'experiments/workflow-motivation-20261005/runs'
CAPTURE=RUNS/'capture-163125'
NATIVE=RUNS/'native-163127'
REPLAY=RUNS/'capture-163126'
MM=(505.89-24)/2*25.4/72.27
INK,BLUE,ORANGE,GREEN,RED,EDGE='#243746','#23688D','#9B6428','#39756A','#B83C46','#70808A'
DATA=ROOT/'data';DATA.mkdir(exist_ok=True)
SOURCES=set()


def read(p):
    SOURCES.add(p)
    return json.loads(p.read_text())


def table(name,rows):
    with (DATA/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def save(fig,name):
    out=ROOT/'figures';out.mkdir(exist_ok=True)
    review=ROOT/'review';review.mkdir(exist_ok=True)
    fig.savefig(out/f'{name}.pdf');fig.savefig(out/f'{name}.svg');plt.close(fig)
    with fitz.open(out/f'{name}.pdf') as doc:
        page=doc[0]
        spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
        assert min(s['size'] for s in spans)>=10
        for s in spans:
            r=fitz.Rect(s['bbox'])
            assert r.x0>=-.2 and r.y0>=-.2 and r.x1<=page.rect.width+.2 and r.y1<=page.rect.height+.2,(name,s)
        for style,colors in [('color',fitz.csRGB),('gray',fitz.csGRAY)]:
            page.get_pixmap(matrix=fitz.Matrix(3,3),colorspace=colors,alpha=False).save(review/f'{name}-{style}.png')
        page.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False).save(out/f'{name}.png')
    shutil.copy2(out/f'{name}.pdf',PAPER/f'figures/{name}.pdf')
    shutil.copy2(out/f'{name}.png',PAPER/f'figures/preview/{name}.png')


def typography():
    font_manager.fontManager.addfont('/home/comp/zhanzhao/miniforge3/envs/latex/tinytex/texmf-dist/fonts/opentype/public/libertine/LinLibertine_R.otf')
    plt.rcParams.update({'font.family':'Linux Libertine O','font.size':10.5,'axes.labelsize':10.5,
        'xtick.labelsize':10.5,'ytick.labelsize':10.5,'legend.fontsize':10.5,
        'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7,
        'text.color':INK,'axes.labelcolor':INK,'axes.edgecolor':INK,'xtick.color':INK,'ytick.color':INK,
        'pdf.fonttype':42,'svg.fonttype':'none','legend.frameon':False,'hatch.linewidth':.6})


def history_and_recovery(calls):
    fig=plt.figure(figsize=(MM/25.4,85/25.4))
    ax=fig.add_axes([.19,.62,.77,.24]);handles=[];rows=[]
    for app,ls,prefix in [('research','-', 'R'),('review','--','S')]:
        for letter,color,marker in [('A',BLUE,'o'),('B',ORANGE,'s'),('C',GREEN,'^')]:
            selected=sorted([r for r in calls if r['agent_key']==f'F0/{app}/{letter}'],key=lambda r:r['round_index'])
            xs=[r['round_index'] for r in selected];ys=[r['kv_tensor_bytes']/2**30 for r in selected]
            ax.plot(xs,ys,color=color,ls=ls,marker=marker,mfc='white',ms=4,lw=1.05,label=f'{prefix}-{letter}')
            for r in selected:rows.append({'call_id':r['id'],'application':app,'agent':letter,'round':r['round_index'],'input_tokens':r['input_tokens'],'cache_tokens':r['cache_tokens'],'kv_tensor_bytes':r['kv_tensor_bytes']})
    ax.set(xticks=[0,1,2,3],xlabel='Invocation index',ylabel='KV tensors (GiB)',ylim=(0,2.5))
    ax.grid(axis='y',color='#DEE4E8',lw=.5);fig.text(.035,.865,'(a)')
    fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.54,1),ncol=3,
               handlelength=1.2,handletextpad=.4,columnspacing=.7,borderaxespad=0)
    table('agent-history-growth.csv',rows)
    ax=fig.add_axes([.19,.13,.77,.25]);fig.text(.035,.40,'(b)')
    profiles=read(CAPTURE/'recovery-profile.json')
    x=[];full=[];dram=[];full_err=[];dram_err=[];rows=[]
    for p in profiles:
        m=p['measurements'];x.append(m[0]['context_tokens']/1000)
        for metric,values,errors in [('full_prefill_cuda_ms',full,full_err),('dram_to_gpu_cuda_ms',dram,dram_err)]:
            a=np.array([v[metric] for v in m])/1000;mean=a.mean();values.append(mean);errors.append([mean-a.min(),a.max()-mean])
        for v in m:rows.append({'source_call_id':p['source_call_id'],'workflow_id':p['workflow_id'],**v})
    ax.errorbar(x,full,yerr=np.array(full_err).T,color=BLUE,marker='o',mfc='white',ms=4,lw=1.1,capsize=2,label='Full prefill')
    ax.errorbar(x,dram,yerr=np.array(dram_err).T,color=GREEN,marker='s',mfc='white',ms=4,lw=1.1,capsize=2,label='DRAM H2D')
    ax.set(xlabel='Input context (k tokens)',ylabel='Time (s)',xlim=(0,16.8),ylim=(0,1.55),xticks=[0,4,8,12,16])
    ax.grid(axis='y',color='#DEE4E8',lw=.5)
    ax.legend(loc='upper left',handlelength=1.1,handletextpad=.5)
    table('physical-recovery-profile.csv',rows)
    save(fig,'agent-state-and-recovery')


def native_concentration():
    summary=read(NATIVE/'SUMMARY.json');rows=[]
    fig=plt.figure(figsize=(MM/25.4,60/25.4));ax=fig.add_axes([.16,.24,.79,.58])
    for request,color,marker,label in zip(summary['requests'],[BLUE,ORANGE,GREEN],['o','s','^'],['Research A','Review A','Review B']):
        folder=NATIVE/f"call-{request['source_call_id']:04}"
        M=request['history_tokens'];B=M//64
        heat=[]
        for layer in request['layers']:
            path=NATIVE/layer['trace_file'];SOURCES.add(path)
            with np.load(path) as v:arr=v['selected_blocks']
            suffix=arr[:,M:]
            valid=suffix[(suffix>=0)&(suffix<B)]
            heat.append(np.bincount(valid,minlength=B))
        heat=np.array(heat)
        # Each budget fraction is charged equally in every layer. Physical
        # candidates are (layer,64-token block), summed across KV-head events.
        ordered=np.sort(heat,axis=1)[:,::-1]
        total=heat.sum();assert total>0
        x=[0];y=[0]
        for fraction in [1,5,10,20,40,60,80,100]:
            k=max(1,int(np.ceil(B*fraction/100)))
            covered=int(ordered[:,:k].sum())
            actual=100*k/B
            x.append(actual);y.append(100*covered/total)
            rows.append({'source_call_id':request['source_call_id'],'model':'NOSA-8B','historical_full_blocks_per_layer':B,
                'budget_blocks_per_layer':k,'budget_percent':actual,'covered_selection_events':covered,
                'total_historical_selection_events':int(total),'coverage_percent':100*covered/total,
                'scope':'Retrospective concentration from measured native events; not causal placement or latency.'})
        ax.plot(x,y,color=color,marker=marker,mfc='white',ms=4,lw=1.1,label=label)
    ax.plot([0,100],[0,100],color=EDGE,ls=':',lw=1,label='Uniform ref.')
    ax.set(xlim=(0,100),ylim=(0,102),xticks=[0,20,40,60,80,100],yticks=[0,25,50,75,100],
           xlabel='Hot historical blocks (%)',ylabel='Selection events (%)')
    ax.grid(axis='y',color='#DEE4E8',lw=.5)
    fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.53,1),ncol=2,
               handlelength=1.35,handletextpad=.4,columnspacing=.75,borderaxespad=0)
    table('native-selection-concentration.csv',rows)
    save(fig,'native-recovery-demand')


def foreground(calls):
    summary=read(CAPTURE/'SUMMARY.json');arrival=min(w['arrival_ns'] for w in summary['workflows'] if w['run_id']=='F0')
    fig=plt.figure(figsize=(MM/25.4,57/25.4));ax=fig.add_axes([.17,.25,.79,.56]);rows=[]
    for index,color in [(0,BLUE),(1,ORANGE)]:
        selected=sorted([r for r in calls if r['worker']==index],key=lambda r:r['finish_ns'])
        x=[(r['finish_ns']-arrival)/1e9 for r in selected]
        for field,ls in [('cuda_allocated_bytes','-'),('cuda_reserved_bytes','--')]:
            ax.step(x,[r[field]/2**30 for r in selected],where='post',color=color,ls=ls,lw=1.15)
        for r,t in zip(selected,x):rows.append({'call_id':r['id'],'worker':index,'time_s':t,
            'cuda_allocated_bytes':r['cuda_allocated_bytes'],'cuda_reserved_bytes':r['cuda_reserved_bytes'],
            'cuda_peak_allocated_bytes':r['cuda_peak_allocated_bytes'],'resident_agent_kv_bytes':r['resident_agent_kv_bytes']})
    ax.set(xlabel='Elapsed time (s)',ylabel='PyTorch memory (GiB)',ylim=(0,20),xlim=(0,105),xticks=[0,25,50,75,100])
    ax.grid(axis='y',color='#DEE4E8',lw=.5)
    handles=[Line2D([],[],color=BLUE,lw=1.1,label='GPU 0'),Line2D([],[],color=ORANGE,lw=1.1,label='GPU 1'),
             Line2D([],[],color=INK,lw=1.1,label='Allocated'),Line2D([],[],color=INK,lw=1.1,ls='--',label='Reserved')]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.54,1),ncol=2,handlelength=1.4,columnspacing=1,borderaxespad=0)
    table('foreground-hbm-observations.csv',rows)
    save(fig,'foreground-hbm-measured')


def exposure():
    summary=read(REPLAY/'SUMMARY.json')
    assert summary['input_equal_all'] and summary['output_equal_all']
    table_rows=[]
    fig=plt.figure(figsize=(MM/25.4,51/25.4));ax=fig.add_axes([.20,.27,.75,.66])
    for index,app in enumerate(['research','review']):
        values=[]
        for trial in range(3):
            a=next(w for w in summary['workflows'] if w['application']==app and w['run_id']==f'P{trial}_F0')
            b=next(w for w in summary['workflows'] if w['application']==app and w['run_id']==f'P{trial}_F1')
            delta=(b['wct_ms']-a['wct_ms'])/1000;values.append(delta)
            table_rows.append({'application':app,'trial':trial,'healthy_wct_s':a['wct_ms']/1000,'kv_loss_wct_s':b['wct_ms']/1000,'delta_wct_s':delta})
        ax.scatter(index+np.array([-.12,0,.12]),values,facecolor='white',edgecolor=BLUE,s=23,zorder=3)
        ax.plot([index-.23,index+.23],[np.mean(values)]*2,color=RED,lw=1.7)
    ax.axhline(0,color=EDGE,ls=':',lw=.75)
    ax.set(xticks=[0,1],xticklabels=['Research','Review'],ylabel='WCT change (s)',xlim=(-.5,1.5))
    ax.grid(axis='y',color='#DEE4E8',lw=.5)
    fig.legend(handles=[Line2D([],[],ls='none',marker='o',mfc='white',mec=BLUE,label='Paired run'),Line2D([],[],color=RED,lw=1.7,label='Mean')],
               loc='lower center',bbox_to_anchor=(.56,.01),ncol=2,handlelength=1.1,columnspacing=1,borderaxespad=0)
    table('paired-kv-loss-wct.csv',table_rows)
    save(fig,'workflow-kv-loss-measured')


def main():
    typography()
    calls=[read(p) for p in sorted((CAPTURE/'calls').glob('*.json'))]
    calls=[r for r in calls if r['run_id']=='F0']
    assert len(calls)==36
    history_and_recovery(calls)
    if (NATIVE/'SUMMARY.json').exists():native_concentration()
    foreground(calls)
    if (REPLAY/'SUMMARY.json').exists():exposure()
    (ROOT/'MEASUREMENT_SOURCES.json').write_text(json.dumps([{'path':str(p.relative_to(AEGIS)),
      'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(SOURCES)],indent=2)+'\n')


if __name__=='__main__':main()
