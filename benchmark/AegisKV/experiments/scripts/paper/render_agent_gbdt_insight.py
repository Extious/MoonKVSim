"""Render the held-out remaining-time diagnostic without inventing accuracy.

Reuses saved predictions; never retrains to improve the appearance of a plot.
The candidate stays outside the manuscript because early accuracy is weak.
"""
from pathlib import Path
import csv
import hashlib
import json
import os

os.environ.setdefault('MPLCONFIGDIR', '/tmp/aegiskv-gbdt-insight-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FixedFormatter
import numpy as np
import pymupdf as fitz
from design_plot_typography import configure

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / 'benchmark/AegisKV'
DATA = BASE / 'experiments/data/agent-gbdt-steps'
OUT = BASE / 'exports/agent-gbdt-insight'
STYLES = {'median': ('Median', '#747474', '--'),
          'gbdt_basic': ('GBDT basic', '#AD6A22', ':'),
          'gbdt_history': ('GBDT + history', '#216A9D', '-')}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frame(ax):
    ax.spines[['top','right']].set_visible(False)
    ax.grid(axis='y', color='#E2E2E2', linewidth=.55, zorder=0)
    ax.tick_params(length=2.5, width=.65, pad=2)
    for side in ['bottom','left']:
        ax.spines[side].set_linewidth(.65)


def cdf(ax, rows, compact=False):
    max_error=0
    for method,(label,color,ls) in STYLES.items():
        x=np.sort([float(r[method+'_ape_pct']) for r in rows])
        # Empirical CDF: every held-out Agent exactly once, including tails.
        y=np.arange(1,len(x)+1)/len(x)
        ax.step(np.r_[0.,x], np.r_[0.,y], where='post', color=color,
                linestyle=ls, linewidth=1.4, label=label, zorder=3)
        max_error=max(max_error,float(x[-1]))
    ax.set_xscale('symlog',linthresh=100,linscale=1)
    ax.set_xlim(0,max_error*1.13); ax.set_ylim(0,1.015)
    ticks=[0,100,1000,10000]
    if not compact:
        ticks=[0,50,100,1000,10000]
    ticks=[v for v in ticks if v<=max_error*1.13]
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_major_formatter(FixedFormatter([f'{v:,}' if v<1000 else f'{v//1000}k' for v in ticks]))
    ax.xaxis.set_minor_locator(FixedLocator([]))
    ax.set_yticks([0,.25,.5,.75,1], ['0','.25','.50','.75','1'])
    ax.set_xlabel('Relative error (%)',labelpad=2)
    ax.set_ylabel('Fraction of Agents',labelpad=3)
    ax.legend(loc='lower right',bbox_to_anchor=(1.,.045),frameon=False,
              handlelength=1.5,labelspacing=.2,handletextpad=.5,borderaxespad=.1)
    frame(ax)
    return max_error


def save(fig, stem, width):
    pdf=OUT/(stem+'.pdf'); png=OUT/(stem+'.png')
    fig.savefig(pdf); fig.savefig(OUT/(stem+'.svg')); plt.close(fig)
    with fitz.open(pdf) as doc:
        p=doc[0]
        p.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False).save(png)
        p.get_pixmap(matrix=fitz.Matrix(3,3),colorspace=fitz.csGRAY,alpha=False).save(OUT/(stem+'-gray.png'))
        spans=[s for b in p.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans']]
        outside=[s['text'] for s in spans if not p.rect.contains(fitz.Rect(s['bbox']))]
        return dict(path=str(pdf),sha256=sha(pdf),png_sha256=sha(png),
                    page_inches=[p.rect.width/72,p.rect.height/72],
                    placed_width_inches=width,minimum_text_pt=min(s['size'] for s in spans)*width/(p.rect.width/72),
                    out_of_page_text=outside)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    typography=configure()
    plt.rcParams.update({'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none',
                         'axes.unicode_minus':False})
    rows=list(csv.DictReader((DATA/'primary-landmark.csv').open()))
    summary=json.loads((DATA/'summary.json').read_text())
    assert len({(r['workflow_id'],r['agent_id']) for r in rows})==len(rows)==1443
    assert {int(r['step']) for r in rows}=={2}
    reviews=[]
    for stem,width,height,compact in [('agent-remaining-error',3.34,2.55,False),
                                      ('agent-remaining-error-compact',2.24,2.1,True)]:
        fig,ax=plt.subplots(figsize=(width,height))
        fig.subplots_adjust(left=.17 if not compact else .23,right=.98,bottom=.20 if not compact else .24,top=.975)
        max_error=cdf(ax,rows,compact)
        reviews.append(save(fig,stem,width))
    # Secondary landmarks must remain visible even if they do not improve.
    # They are different eligible cohorts, NOT a controlled within-Agent trend.
    fig,axs=plt.subplots(1,2,figsize=(7.,2.65))
    fig.subplots_adjust(left=.072,right=.98,bottom=.225,top=.85,wspace=.35)
    steps=[1,2,5,10,20]; xs=np.arange(len(steps))
    for method,(_,color,ls) in STYLES.items():
        label=STYLES[method][0]
        for ax,metric in zip(axs,['median_ape_pct','within20_pct']):
            vals=[summary[str(s)][method][metric] for s in steps]
            ax.plot(xs,vals,color=color,ls=ls,lw=1.3,marker={'median':'s','gbdt_basic':'^','gbdt_history':'o'}[method],ms=4,label=label)
    for ax in axs:
        frame(ax); ax.set_xticks(xs,[str(s) for s in steps]); ax.set_xlim(-.2,4.2)
        ax.set_xlabel('Current request index',labelpad=3)
    axs[0].set_ylabel('Median relative error (%)',labelpad=3); axs[0].set_ylim(0,85)
    axs[1].set_ylabel('Error within 20% (%)',labelpad=3); axs[1].set_ylim(0,25)
    handles,labels=axs[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='upper center',ncol=3,frameon=False,bbox_to_anchor=(.53,1.02))
    reviews.append(save(fig,'agent-remaining-by-step',7.))
    manifest=dict(evidence='Offline fitting and evaluation on observed CC traces; not synthetic predictions or hardware AegisKV execution',
                  status='Diagnostic candidate: does not establish accurate early whole-Agent runtime prediction',
                  primary_landmark='Second request arrival, after first request completion',
                  agents=len(rows),workflows=len({r['workflow_id'] for r in rows}),
                  error='100 * abs(predicted_remaining_seconds - actual_remaining_seconds) / actual_remaining_seconds',
                  x_axis='Linear from 0 to 100 percent, log above 100 percent; all observations retained',
                  max_primary_ape_pct=max_error,
                  secondary_cohorts={str(s):summary[str(s)]['median']['n_agents'] for s in steps},
                  secondary_warning='Eligibility differs across landmarks; curves do not establish within-Agent accuracy improvement',
                  typography=typography,exports=reviews,
                  sources={str(p):sha(p) for p in [DATA/'protocol.json',DATA/'summary.json',DATA/'predictions.csv',DATA/'primary-landmark.csv',Path(__file__)]},
                  visual_review='Pending inspection of these final exported PNGs and grayscale; see REVIEW.json')
    (OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(exports=reviews,primary=summary['2']),indent=2))


if __name__=='__main__':
    main()
