"""Paper Figure 3: selected native 32K / 512-Query concentration, one column.

Uses the existing validated three-model captures. No GPU execution, policy
prediction, attention-mass weighting, or physical-transfer claim is added.
"""
from pathlib import Path
import csv
import hashlib
import json
import os
os.environ.setdefault('MPLCONFIGDIR', '/tmp/aegiskv-paper-concentration')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pymupdf
from design_plot_typography import configure

BASE = Path(__file__).resolve().parents[3]
DATA = BASE/'experiments/data/kv-access-concentration-8b-20260921'
OUT = BASE/'exports/figure3-three-models-32k-20260921'
STYLES = [('NOSA-8B','#246B94','o','-'),
          ('NSA-8B','#B65D24','s','--'),
          ('MiniCPM4.1-8B','#447B56','^','-.')]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    typography=configure()
    selection=json.loads((BASE/'exports/kv-access-concentration-current.json').read_text())
    assert selection['models']==[x[0] for x in STYLES]
    assert selection['total_comparison_tokens']==32704 and selection['query_window']==512
    assert selection['metric']=='query_block'
    with (DATA/'curves.csv').open() as f: curves=list(csv.DictReader(f))
    summaries=json.loads((DATA/'summary.json').read_text())
    plt.rcParams.update({'axes.linewidth':.65,'pdf.fonttype':42,'svg.fonttype':'none'})
    fig,ax=plt.subplots(figsize=(3.33465,2.45))
    fig.subplots_adjust(left=.181,right=.955,bottom=.219,top=.77)
    selected=[]
    for model,color,marker,style in STYLES:
        rows=sorted([r for r in curves if r['model']==model and r['metric']=='query_block'
                     and int(r['window_queries'])==512],key=lambda r:int(r['K']))
        assert [int(r['K']) for r in rows]==list(range(504))
        x=np.array([float(r['block_fraction'])*100 for r in rows])
        y,low,high=[np.array([float(r[k])*100 for r in rows]) for k in ('mean','min','max')]
        s=next(s for s in summaries if s['model']==model and s['metric']=='query_block'
               and s['window_queries']==512)
        for label,k in [('10',51),('20',101),('40',202)]:
            assert abs(y[k]/100-s[f'top{label}']['mean'])<1e-12
        ax.fill_between(x,low,high,color=color,alpha=.13,linewidth=0)
        ax.plot(x,y,label=model,color=color,linestyle=style,linewidth=1.15,
                marker=marker,markevery=[51,101,202,302,403],markersize=3.3,
                markerfacecolor='white',markeredgewidth=.8)
        selected.append(s)
    ax.plot([0,100],[0,100],color='#777777',linestyle=':',linewidth=.9,label='Uniform')
    ax.set_xlim(0,100);ax.set_ylim(0,103)
    ax.set_xticks([0,20,40,60,80,100]);ax.set_yticks([0,25,50,75,100])
    ax.set_xlabel('Hot historical blocks (%)',labelpad=3)
    ax.set_ylabel('Access share (%)',labelpad=2)
    ax.tick_params(length=2.2,pad=2)
    ax.spines[['top','right']].set_visible(False)
    ax.grid(axis='y',color='#E2E6E9',linewidth=.5)
    ax.set_axisbelow(True)
    fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.54,.985),
               ncol=2,frameon=False,handlelength=1.55,handletextpad=.4,
               columnspacing=.8,borderaxespad=0,labelspacing=.3)
    stem=OUT/'kv-access-concentration'
    for ext in ('pdf','svg'):fig.savefig(stem.with_suffix('.'+ext),facecolor='white')
    plt.close(fig)
    with pymupdf.open(stem.with_suffix('.pdf')) as doc:
        page=doc[0]
        for name,scale,space in [('png',3,pymupdf.csRGB),('gray.png',3,pymupdf.csGRAY),
                                 ('reading-size.png',4/3,pymupdf.csRGB)]:
            target=stem.with_suffix('.png') if name=='png' else OUT/(stem.name+'-'+name)
            page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=space,alpha=False).save(target)
        spans=[s for block in page.get_text('dict')['blocks'] if 'lines' in block
               for line in block['lines'] for s in line['spans'] if s['text'].strip()]
        assert all(page.rect.contains(pymupdf.Rect(s['bbox'])) for s in spans)
        assert min(s['size'] for s in spans)>=10
        geometry=dict(width_pt=page.rect.width,height_pt=page.rect.height,
                      minimum_font_pt=min(s['size'] for s in spans))
    output_paths=[stem.with_suffix('.'+ext) for ext in ('pdf','svg','png')]
    output_paths += [OUT/(stem.name+'-'+n+'.png') for n in ('gray','reading-size')]
    manifest=dict(generator=str(Path(__file__).resolve()),generator_sha256=sha(__file__),
        selection=selection,selected_summary=selected,typography=typography,geometry=geometry,
        evidence='Existing native GPU traces; same-window frequency concentration, not prediction accuracy',
        aggregation='Normalize each layer/document, mean over all32layers, equal mean over3documents',
        interval='document min-max, not CI',new_gpu_runs=0,
        inputs={str(DATA/n):sha(DATA/n) for n in ('protocol.json','curves.csv','summary.json')},
        outputs={p.name:sha(p) for p in output_paths})
    (OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(geometry,indent=2))


if __name__=='__main__':main()
