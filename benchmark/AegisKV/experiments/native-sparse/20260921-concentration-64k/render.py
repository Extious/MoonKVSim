"""Standalone scientific plots; all layer blocks, no head-level budget selection."""
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
os.environ.setdefault('MPLCONFIGDIR', '/tmp/aegiskv-concentration-64k-20260921')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import fitz

BASE = Path('/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV')
DATA = BASE/'experiments/data/kv-access-concentration-64k-20260921'
OUT = BASE/'exports/kv-access-concentration-64k-20260921'
sys.path.insert(0,str(BASE/'experiments/scripts/paper'))
from design_plot_typography import configure
STYLES = [('NOSA-8B','NOSA-8B*','#246B94','o','-'),
          ('NSA-8B','NSA-8B*','#B65D24','s','--'),
          ('MiniCPM4.1-8B','MiniCPM4.1-8B','#447B56','^','-.'),
          ('Qwen2.5-7B-Instruct-1M','Qwen2.5-7B-1M†','#885B97','D',':')]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export(fig,stem):
    for ext in ('pdf','svg'):
        fig.savefig(OUT/f'{stem}.{ext}',facecolor='white')
    plt.close(fig)
    with fitz.open(OUT/f'{stem}.pdf') as doc:
        page=doc[0]
        page.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False).save(OUT/f'{stem}.png')
        page.get_pixmap(matrix=fitz.Matrix(3,3),colorspace=fitz.csGRAY,alpha=False).save(OUT/f'{stem}-gray.png')
        page.get_pixmap(matrix=fitz.Matrix(4/3,4/3),alpha=False).save(OUT/f'{stem}-reading-size.png')
        spans=[s for block in page.get_text('dict')['blocks'] if 'lines' in block
               for line in block['lines'] for s in line['spans'] if s['text'].strip()]
        assert all(page.rect.contains(fitz.Rect(s['bbox'])) for s in spans)
        assert min(s['size'] for s in spans)>=10
        return dict(width_inches=page.rect.width/72,height_inches=page.rect.height/72,
                    minimum_font_pt=min(s['size'] for s in spans))


def axes_style(ax):
    ax.set_ylim(0,103)
    ax.set_yticks([0,20,40,60,80,100])
    ax.tick_params(length=2.5,pad=2)
    ax.spines[['top','right']].set_visible(False)
    ax.grid(axis='y',color='#E2E6E9',linewidth=.5)
    ax.set_axisbelow(True)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    typography=configure()
    plt.rcParams.update({'axes.linewidth':.65,'pdf.fonttype':42,'svg.fonttype':'none'})
    with (DATA/'curves.csv').open() as f: curves=list(csv.DictReader(f))
    with (DATA/'layers.csv').open() as f: layers=list(csv.DictReader(f))
    summary=json.loads((DATA/'summary.json').read_text())
    exports={}
    fig,ax=plt.subplots(figsize=(7,4.6))
    fig.subplots_adjust(left=.104,right=.978,top=.718,bottom=.228)
    for model,label,color,marker,style in STYLES:
        rows=sorted([r for r in curves if r['model']==model],key=lambda r:int(r['k']))
        assert [int(r['k']) for r in rows]==list(range(1017))
        x=np.array([float(r['stored_fraction'])*100 for r in rows])
        y,lo,hi=[np.array([float(r[k])*100 for r in rows])
                 for k in ('coverage_mean','coverage_min','coverage_max')]
        ax.fill_between(x,lo,hi,color=color,alpha=.13,linewidth=0)
        ax.plot(x,y,label=label,color=color,marker=marker,linestyle=style,linewidth=1.4,
                markevery=[102,204,407,610,813],markersize=4,markerfacecolor='white',markeredgewidth=.9)
    ax.plot([0,100],[0,100],color='#858585',linestyle=(0,(2,3)),linewidth=.9)
    ax.text(80,65,'Qwen ≈ Uniform',color='#656565',ha='center',va='center')
    axes_style(ax)
    ax.set_xlim(0,100)
    ax.set_xticks([0,20,40,60,80,100])
    ax.set_ylabel('Cumulative reference share (%)',labelpad=5)
    ax.set_xlabel('Hottest historical blocks per layer (%)',labelpad=7)
    fig.text(.54,.975,'Sparse KV block access concentration',ha='center',va='top')
    fig.text(.54,.919,'64K total tokens · final 512 Queries · all-layer mean',ha='center',va='top')
    fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.54,.858),
               ncol=2,frameon=False,handlelength=2.4,columnspacing=2.1,borderaxespad=0)
    fig.text(.54,.09,'Same-window ranking; 3 PG19 texts; shade: text min–max.',ha='center',va='center')
    fig.text(.54,.036,'*NOSA/NSA: 64K extrapolation. †Qwen: MInference backend.',ha='center',va='center')
    exports['access-concentration']=export(fig,'access-concentration')

    fig,axes=plt.subplots(4,1,figsize=(7,7.8))
    fig.subplots_adjust(left=.102,right=.978,top=.835,bottom=.119,hspace=.58)
    points=[]
    for ax,(model,label,_,_,_) in zip(axes,STYLES):
        nlayers=next(s['layers'] for s in summary if s['model']==model)
        for pct,color,style,marker in [('20','#246B94','-','o'),('40','#B65D24','--','s')]:
            avg,lo,hi=[],[],[]
            for layer in range(1,nlayers+1):
                rows=[r for r in layers if r['model']==model and int(r['layer'])==layer]
                assert len(rows)==3
                values=np.array([float(r[f'top{pct}'])*100 for r in rows])
                avg.append(values.mean());lo.append(values.min());hi.append(values.max())
                points.append(dict(model=model,layer=layer,budget=pct,
                                   mean_pct=float(values.mean()),min_pct=float(values.min()),max_pct=float(values.max())))
            expected=next(s[f'top{pct}_mean'] for s in summary if s['model']==model)
            assert abs(np.mean(avg)/100-expected)<1e-12
            xs=range(1,nlayers+1)
            ax.fill_between(xs,lo,hi,color=color,alpha=.12,linewidth=0)
            ax.plot(xs,avg,color=color,linestyle=style,marker=marker,linewidth=1.15,
                    markersize=3,markevery=3,markerfacecolor='white',markeredgewidth=.8,label=f'Top {pct}% blocks')
        ax.set_title(label,pad=5)
        ax.set_xlim(.5,nlayers+.5)
        ax.set_xticks([1,8,16,24,nlayers])
        axes_style(ax)
    fig.text(.54,.985,'KV access concentration in every layer',ha='center',va='top')
    fig.text(.54,.95,'64K / 512 Queries; all heads merged within each Query',ha='center',va='top')
    fig.legend(*axes[0].get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.54,.909),
               ncol=2,frameon=False,handlelength=2.2,columnspacing=1.6,borderaxespad=0)
    fig.text(.018,.48,'Share of Query–block references (%)',rotation=90,ha='left',va='center')
    fig.text(.54,.077,'Layer ID',ha='center',va='center')
    fig.text(.54,.044,'Mean over 3 texts; shade: text min–max; same-window ranking.',ha='center',va='center')
    fig.text(.54,.014,'*64K extrapolation. †Official Qwen selector + MInference backend.',ha='center',va='center')
    exports['concentration-by-layer']=export(fig,'concentration-by-layer')
    paths=[OUT/f'{stem}.{ext}' for stem in exports for ext in ('pdf','svg','png')]
    paths += [OUT/f'{stem}-{suffix}.png' for stem in exports for suffix in ('gray','reading-size')]
    manifest=dict(evidence='Native GPU attention indices; retrospective layer concentration, not prediction accuracy',
        generator=str(Path(__file__).resolve()),generator_sha256=sha(__file__),typography=typography,
        inputs={n:sha(DATA/n) for n in ('protocol.json','curves.csv','layers.csv','summary.json')},
        exports=exports,layer_points=points,outputs={p.name:sha(p) for p in paths})
    (OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(exports,indent=2))


if __name__=='__main__':main()
