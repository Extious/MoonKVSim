"""Re-layout the two retained Insight panels for a single manuscript column.

Reads unchanged survey and native-capture tables; no new fit or experiment.
Only compilation PDFs are published in paper/; editable exports stay outside.
"""
from pathlib import Path
from datetime import date
import csv
import hashlib
import json
import os
import shutil

os.environ.setdefault('MPLCONFIGDIR', '/tmp/aegiskv-insights-single-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
import numpy as np
import fitz
from design_plot_typography import configure

BASE = Path(__file__).resolve().parents[3]
DATA = BASE / 'experiments/data/design-insights'
OUT = BASE / 'exports/insights-single-column'
PAPER = BASE / 'paper/figures'
WIDTH = 3.34
HEIGHT = 1.72
MODELS = ['NOSA-3B', 'MiniCPM4-8B', 'SeerAttention-Qwen3-8B']


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def style(ax):
    ax.spines[['top','right']].set_visible(False)
    ax.tick_params(length=2.5,pad=2.5)
    ax.grid(axis='y',color='#E1E6E9',lw=.6)
    ax.set_axisbelow(True)


def save(fig,name):
    for ext in ['pdf','svg']:
        fig.savefig(OUT/f'{name}.{ext}',facecolor='white')
    plt.close(fig)
    with fitz.open(OUT/f'{name}.pdf') as doc:
        p=doc[0]
        p.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False).save(OUT/f'{name}.png')
        p.get_pixmap(matrix=fitz.Matrix(3,3),colorspace=fitz.csGRAY,alpha=False).save(OUT/f'{name}-gray.png')
    shutil.copy2(OUT/f'{name}.pdf',PAPER/f'{name}.pdf')


def survey():
    models=json.loads((DATA/'sparse-releases.json').read_text())['models']
    assert len(models)==10
    fig=plt.figure(figsize=(WIDTH,HEIGHT))
    ax=fig.add_axes([.195,.27,.785,.54])
    styles={'block':('o','#B55B25','Block'),'token':('s','#246B94','Token'),
            'entry':('D','#826593','Compressed')}
    xx=[]; yy=[]; best=0
    for m in sorted(models,key=lambda r:r['date']):
        if m['context_k']>best:
            best=m['context_k'];xx.append(date.fromisoformat(m['date']));yy.append(best)
    xx.append(date(2026,10,1));yy.append(best)
    ax.step(xx,yy,where='post',color='#C9CED4',lw=1,zorder=1)
    offsets=[(7,-1),(-5,5),(0,5),(0,-15),(7,-7),(-5,6),(-3,6),(-4,-16),(4,6),(2,-16)]
    for m,offset in zip(models,offsets):
        marker,color,_=styles[m['granularity']]
        x,y=date.fromisoformat(m['date']),m['context_k']
        ax.plot(x,y,marker=marker,ms=4.8,color=color,mec='white',mew=.5,zorder=3)
        ax.annotate(str(m['id']),(x,y),xytext=offset,textcoords='offset points',
                    ha='center',va='bottom',color=color,
                    arrowprops=dict(arrowstyle='-',lw=.45,color=color,shrinkA=0,shrinkB=3))
    ax.set_yscale('log',base=2);ax.set_ylim(20,4096)
    ax.set_xlim(date(2025,5,15),date(2026,10,1))
    ax.set_yticks([32,128,1024],['32K','128K','1M'])
    ax.set_xticks([date(2025,6,1),date(2026,1,1),date(2026,8,1)])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%y'))
    ax.minorticks_off();ax.set_xlabel('Release date',labelpad=2);ax.set_ylabel('Native context',labelpad=3)
    handles=[Line2D([],[],marker=m,color=c,ls='none',ms=5,label=n) for m,c,n in styles.values()]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.56,1.025),frameon=False,ncol=3,
               handlelength=.8,handletextpad=.35,columnspacing=.7)
    style(ax);save(fig,'sparse-models')
    return models


def retry():
    rows=list(csv.DictReader((DATA/'retry-kv-documents.csv').open()))
    fig=plt.figure(figsize=(WIDTH,HEIGHT))
    ax=fig.add_axes([.195,.28,.785,.53]);width=.31;stats=[]
    for j,(key,label,color,hatch) in enumerate([
        ('past_frequency','Past frequency','#246B94',None),
        ('recent_first','Recent first','#E6B896','//')]):
        means=[];lows=[];highs=[]
        for model in MODELS:
            values=np.array([100*float(r[key]) for r in rows if r['model']==model and float(r['budget_fraction'])==.4])
            assert len(values)==3
            means.append(values.mean());lows.append(values.mean()-values.min());highs.append(values.max()-values.mean())
            stats.append(dict(model=model,method=key,mean_pct=float(values.mean()),min_pct=float(values.min()),max_pct=float(values.max()),documents=3))
        ax.bar(np.arange(3)+(j-.5)*width,means,width,label=label,color=color,hatch=hatch,
               edgecolor='#344957',linewidth=.5,yerr=[lows,highs],capsize=2,
               error_kw=dict(ecolor='#243A46',lw=.8,capthick=.8))
    ax.set_xlim(-.55,2.55);ax.set_ylim(0,100);ax.set_yticks([0,50,100])
    ax.set_xticks(np.arange(3),['NOSA\n3B','MiniCPM\n4-8B','Seer\nQwen3-8B'])
    ax.set_ylabel('KV coverage (%)',labelpad=3)
    fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.56,1.025),
               frameon=False,ncol=2,handlelength=1.15,handletextpad=.4,columnspacing=.8)
    style(ax);save(fig,'retry-kv-prediction')
    return stats


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    typography=configure()
    plt.rcParams.update({'axes.linewidth':.7,'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none'})
    models=survey();stats=retry()
    manifest=dict(generator=str(Path(__file__).resolve()),generator_sha256=sha(__file__),
                  input_hashes={str(DATA/n):sha(DATA/n) for n in ['sparse-releases.json','retry-kv-documents.csv','retry-kv-summary.json']},
                  panel_inches=[WIDTH,HEIGHT],layout='Two full-column subfigures stacked in one figure environment',
                  typography=typography,source_models=models,retry_statistics=stats,
                  evidence='Unchanged literature survey and offline native selector captures; no new runtime measurement',
                  outputs={name:sha(OUT/name) for name in ['sparse-models.pdf','retry-kv-prediction.pdf']})
    (OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(panel_inches=[WIDTH,HEIGHT],retry_statistics=stats),indent=2))


if __name__=='__main__':
    main()
