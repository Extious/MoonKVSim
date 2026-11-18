"""Editable standalone plots of measured native selection-frequency concentration."""
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
os.environ.setdefault('MPLCONFIGDIR', '/tmp/aegiskv-kv-concentration-20260921')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import fitz

BASE = Path('/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV')
DATA = BASE / 'experiments/data/kv-access-concentration-three-models-20260921'
OUT = BASE / 'exports/kv-access-concentration-three-models-20260921'
sys.path.insert(0, str(BASE / 'experiments/scripts/paper'))
from design_plot_typography import configure
STYLES = [
    ('NOSA-3B', '#246B94', 'o', '-'),
    ('NSA-8B', '#B65D24', 's', '--'),
    ('MiniCPM4.1-8B', '#447B56', '^', '-.'),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export(fig, stem):
    for ext in ('pdf', 'svg'):
        fig.savefig(OUT / f'{stem}.{ext}', facecolor='white')
    plt.close(fig)
    with fitz.open(OUT / f'{stem}.pdf') as doc:
        page = doc[0]
        page.get_pixmap(matrix=fitz.Matrix(3,3), alpha=False).save(OUT / f'{stem}.png')
        page.get_pixmap(matrix=fitz.Matrix(3,3), colorspace=fitz.csGRAY,
                        alpha=False).save(OUT / f'{stem}-gray.png')
        page.get_pixmap(matrix=fitz.Matrix(4/3,4/3), alpha=False).save(OUT / f'{stem}-reading-size.png')
        spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b
                 for line in b['lines'] for s in line['spans'] if s['text'].strip()]
        assert all(page.rect.contains(fitz.Rect(s['bbox'])) for s in spans)
        smallest = min(s['size'] for s in spans)
        assert smallest >= 10, smallest
        return dict(width_inches=page.rect.width/72, height_inches=page.rect.height/72,
                    minimum_font_pt=smallest)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    typography = configure()
    plt.rcParams.update({'axes.linewidth':.65, 'pdf.fonttype':42, 'svg.fonttype':'none'})
    with (DATA / 'curves.csv').open() as f:
        curves = list(csv.DictReader(f))
    with (DATA / 'layers.csv').open() as f:
        layers = list(csv.DictReader(f))
    summary = json.loads((DATA / 'summary.json').read_text())
    exports = {}
    for metric, stem, description in [
            ('query_block', 'access-concentration', 'All KV heads merged within each query'),
            ('selector_event', 'selector-event-concentration', 'Native group-selection events (secondary metric)')]:
        fig, axes = plt.subplots(1, 2, figsize=(7., 3.5), sharey=True)
        fig.subplots_adjust(left=.095, right=.985, top=.71, bottom=.255, wspace=.18)
        for ax, n in zip(axes, (256,512)):
            for model, color, marker, style in STYLES:
                rows = sorted([r for r in curves if r['model'] == model and r['metric'] == metric
                               and int(r['window_queries']) == n], key=lambda r:int(r['K']))
                assert [int(r['K']) for r in rows] == list(range(505))
                x = np.array([float(r['block_fraction'])*100 for r in rows])
                y, low, high = [np.array([float(r[k])*100 for r in rows]) for k in ('mean','min','max')]
                ax.fill_between(x, low, high, color=color, alpha=.12, linewidth=0)
                ax.plot(x, y, label=model, color=color, linestyle=style, linewidth=1.3,
                        marker=marker, markersize=3.5, markevery=[51,101,202,302,403],
                        markerfacecolor='white', markeredgewidth=.8)
            ax.plot([0,100],[0,100], color='#72787B', linestyle=':', linewidth=.9, label='Uniform')
            ax.set_title(f'{n}-query window', pad=5)
            ax.set_xlim(0,100)
            ax.set_ylim(0,103)
            ax.set_xticks([0,20,40,60,80,100])
            ax.set_yticks([0,20,40,60,80,100])
            ax.tick_params(length=2.5, pad=2)
            ax.spines[['top','right']].set_visible(False)
            ax.grid(axis='y', color='#E2E6E9', linewidth=.5)
            ax.set_axisbelow(True)
        fig.text(.54,.978,'Native sparse KV access concentration',ha='center',va='top')
        fig.text(.54,.913,description,ha='center',va='top')
        fig.legend(*axes[0].get_legend_handles_labels(),loc='upper center',
                   bbox_to_anchor=(.54,.852),ncol=4,frameon=False,handlelength=1.75,
                   handletextpad=.4,columnspacing=.9,borderaxespad=0)
        fig.text(.017,.5,'Cumulative reference share (%)',rotation=90,ha='left',va='center')
        fig.text(.54,.149,'Hottest historical blocks per layer (%)',ha='center',va='center')
        fig.text(.54,.077,'32 layers; 3 PG19 documents; shade: document min–max.',ha='center',va='center')
        fig.text(.54,.023,'Same-window ranking; 504 historical blocks/layer; not prediction accuracy.',ha='center',va='center')
        exports[stem] = export(fig, stem)

    fig, axes = plt.subplots(3,1,figsize=(7.,6.2))
    fig.subplots_adjust(left=.097,right=.985,top=.78,bottom=.12,hspace=.38)
    layer_points = []
    for ax, (model,_,_,_) in zip(axes, STYLES):
        for n,budget,color,style,marker in [
                (256,'20','#246B94','-','o'),(512,'20','#246B94','--','s'),
                (256,'40','#B65D24','-','^'),(512,'40','#B65D24','--','v')]:
            values=[]
            for layer in range(1,33):
                rows=[r for r in layers if r['model']==model and r['metric']=='query_block'
                      and int(r['layer'])==layer and int(r['window_queries'])==n]
                assert len(rows)==3
                v=np.array([float(r[f'top{budget}_share'])*100 for r in rows])
                values.append(v.mean())
                layer_points.append(dict(model=model,layer=layer,window_queries=n,budget=budget,
                                         mean_pct=float(v.mean()),min_pct=float(v.min()),max_pct=float(v.max())))
            expected=next(r for r in summary if r['model']==model and r['window_queries']==n
                          and r['metric']=='query_block')[f'top{budget}']['mean']
            assert abs(np.mean(values)/100-expected)<1e-12
            ax.plot(range(1,33),values,color=color,linestyle=style,linewidth=1.1,marker=marker,
                    markevery=4,markersize=3,markerfacecolor='white',markeredgewidth=.8,
                    label=f'Top {budget}%, {n} queries')
        ax.set_title(model,pad=5)
        ax.set_xlim(.5,32.5)
        ax.set_ylim(0,103)
        ax.set_xticks([1,8,16,24,32])
        ax.set_yticks([0,20,40,60,80,100])
        ax.tick_params(length=2.5,pad=2)
        ax.spines[['top','right']].set_visible(False)
        ax.grid(axis='y',color='#E2E6E9',linewidth=.5)
        ax.set_axisbelow(True)
    fig.text(.54,.98,'Concentration across all 32 layers',ha='center',va='top')
    fig.text(.54,.936,'One reference per query/block; all KV heads merged',ha='center',va='top')
    fig.legend(*axes[0].get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.54,.895),
               ncol=2,frameon=False,handlelength=2.,columnspacing=1.3,borderaxespad=0)
    fig.text(.017,.46,'Share of query–block references (%)',rotation=90,ha='left',va='center')
    fig.text(.54,.071,'Layer ID',ha='center',va='center')
    fig.text(.54,.025,'Mean over 3 documents; retrospective ranking separately in each layer.',ha='center',va='center')
    exports['concentration-by-layer']=export(fig,'concentration-by-layer')
    output_paths=[OUT/f'{stem}.{ext}' for stem in exports for ext in ('pdf','svg','png')]
    output_paths += [OUT/f'{stem}-{suffix}.png' for stem in exports for suffix in ('gray','reading-size')]
    manifest=dict(evidence='Observed native selections; same-window ranking, no online prediction claim',
        generator=str(Path(__file__).resolve()),generator_sha256=sha(__file__),typography=typography,
        inputs={name:sha(DATA/name) for name in ('protocol.json','curves.csv','layers.csv','summary.json')},
        exports=exports,layer_points=layer_points,
        outputs={p.name:sha(p) for p in output_paths})
    (OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(exports,indent=2))


if __name__=='__main__':
    main()
