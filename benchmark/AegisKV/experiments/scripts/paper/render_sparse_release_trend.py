"""Selected sparse/hybrid model releases: literature survey, not adoption rate.

The input is the preserved September 18 survey. Plot reported context classes,
not an exact common token limit. Dates may be announcements or repository dates.
Only this figure is published; no native-selector results are regenerated.
"""
from datetime import date
from pathlib import Path
import hashlib
import json
import os
import shutil

os.environ.setdefault('MPLCONFIGDIR', '/tmp/aegiskv-sparse-release-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
import fitz
from design_plot_typography import configure

BASE = Path(__file__).resolve().parents[3]
DATA = BASE / 'experiments/data/design-insights/sparse-releases.json'
OUT = BASE / 'exports/insights-trend-tracker-algorithm-20260921'
PAPER = BASE / 'paper/figures'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    survey = json.loads(DATA.read_text())
    models = survey['models']
    assert [m['id'] for m in models] == list(range(1, 11))
    typography = configure()
    plt.rcParams.update({
        'font.size': 10.3, 'axes.labelsize': 10.3, 'xtick.labelsize': 10.3,
        'ytick.labelsize': 10.3, 'legend.fontsize': 10.3,
        'axes.linewidth': .7, 'pdf.fonttype': 42, 'svg.fonttype': 'none',
    })
    typography['font_pt'] = 10.3
    fig = plt.figure(figsize=(3.33465, 1.85))
    ax = fig.add_axes([.205, .28, .775, .52])
    styles = {'block': ('o', '#B55B25', 'Block'),
              'token': ('s', '#246B94', 'Token'),
              'entry': ('D', '#826593', 'Compressed')}
    offsets = [(7, -1), (-6, 6), (3, 6), (0, -16), (7, -6),
               (-5, 7), (-3, 7), (-5, -17), (4, 7), (1, -17)]
    for model, offset in zip(models, offsets):
        marker, color, _ = styles[model['granularity']]
        x, y = date.fromisoformat(model['date']), model['context_k']
        ax.plot(x, y, marker=marker, ms=5.4, color=color,
                mec='white', mew=.45, zorder=3)
        ax.annotate(str(model['id']), (x, y), xytext=offset,
                    textcoords='offset points', ha='center', va='bottom',
                    color='#222222',
                    arrowprops=dict(arrowstyle='-', lw=.45,
                                    color='#555555', shrinkA=0, shrinkB=3))
    ax.set_yscale('log', base=2)
    ax.set_ylim(20, 4096)
    ax.set_xlim(date(2025, 5, 15), date(2026, 8, 25))
    ax.set_yticks([32, 128, 1024], ['32K', '128K', '1M'])
    ax.set_xticks([date(2025, 6, 1), date(2026, 1, 1), date(2026, 8, 1)])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%y'))
    ax.minorticks_off()
    ax.set_xlabel('Release / repository date', labelpad=2)
    ax.set_ylabel('Reported context', labelpad=3)
    ax.spines[['top', 'right']].set_visible(False)
    ax.tick_params(length=2.5, pad=2.5)
    ax.grid(axis='y', color='#E1E6E9', lw=.6)
    ax.set_axisbelow(True)
    handles = [Line2D([], [], marker=m, color=c, ls='none', ms=5.4, label=n)
               for m, c, n in styles.values()]
    fig.legend(handles=handles, loc='upper center', bbox_to_anchor=(.56, 1.01),
               frameon=False, ncol=3, handlelength=.8, handletextpad=.35,
               columnspacing=.7)
    for ext in ['pdf', 'svg']:
        fig.savefig(OUT / f'sparse-models.{ext}', facecolor='white')
    plt.close(fig)
    with fitz.open(OUT / 'sparse-models.pdf') as doc:
        doc[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).save(OUT / 'sparse-models.png')
        doc[0].get_pixmap(matrix=fitz.Matrix(3, 3), colorspace=fitz.csGRAY,
                          alpha=False).save(OUT / 'sparse-models-gray.png')
    shutil.copy2(OUT / 'sparse-models.pdf', PAPER / 'sparse-models.pdf')
    shutil.copy2(OUT / 'sparse-models.png', PAPER / 'preview/sparse-models.png')
    manifest = dict(
        generator=str(Path(__file__).resolve()), generator_sha256=sha(__file__),
        input=str(DATA), input_sha256=sha(DATA), models=models,
        typography=typography, panel_inches=[3.33465, 1.85],
        evidence='Selected literature survey; no new experiment, census, or sparsity-rate measurement.',
        encodings='Date vs reported context class; shape/color denote selection unit in the sparse branch.',
        limitations='Hybrid branches differ; release/repository dates are distinguished in the source data. No fitted or cumulative trend line.',
        outputs={f'sparse-models.{ext}': sha(OUT / f'sparse-models.{ext}')
                 for ext in ['pdf', 'svg', 'png']})
    (OUT / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'models': len(models), 'output': str(PAPER / 'sparse-models.pdf')}))


if __name__ == '__main__':
    main()
