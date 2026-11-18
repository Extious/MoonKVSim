"""Publication-size plotting primitives; every exported label is >= 10 pt."""
from pathlib import Path
import hashlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.text import Text

from paper_paths import PAPER, ROOT, DATA, TOOLS, DOCS, BUILD, DELIVERY, TEMPLATE
OUT = PAPER / 'figures'
BLUE, ORANGE, GREEN, PURPLE, RED, GRAY = (
    '#0072B2', '#B86B00', '#007D60', '#7952A2', '#B83C46', '#59636F')
COLORS = dict(unprotected=GRAY, dram=ORANGE, full=BLUE,
              no_slack=PURPLE, no_aimd=GREEN, lru_eviction=RED)
MARKERS = ('o', 's', '^', 'v', 'P')
plt.rcParams.update({
    'font.family': 'DejaVu Sans', 'font.size': 10.5,
    'axes.labelsize': 10.5, 'axes.titlesize': 11, 'axes.titleweight': 'bold',
    'xtick.labelsize': 10.5, 'ytick.labelsize': 10.5, 'legend.fontsize': 10.5,
    'axes.spines.top': False, 'axes.spines.right': False, 'axes.linewidth': .7,
    'pdf.fonttype': 42, 'ps.fonttype': 42, 'svg.fonttype': 'none',
    'svg.hashsalt': 'aegiskv-publication-20260906',
    'hatch.linewidth': .6, 'savefig.facecolor': 'white',
})

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(fig, name, directory=OUT):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    hidden = set()
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            lo, hi = sorted(axis.get_view_interval())
            for tick in [*axis.get_major_ticks(), *axis.get_minor_ticks()]:
                if not lo <= tick.get_loc() <= hi:
                    hidden.update((id(tick.label1), id(tick.label2)))
    for obj in fig.findobj(match=Text):
        if id(obj) in hidden or not obj.get_visible() or not obj.get_text().strip():
            continue
        b = obj.get_window_extent(renderer)
        assert b.x0 >= -.7 and b.y0 >= -.7 and b.x1 <= fig.bbox.width+.7 and b.y1 <= fig.bbox.height+.7, (name, obj.get_text(), tuple(b.extents))
        assert obj.get_fontsize() >= 10.0, (name, obj.get_text(), obj.get_fontsize())
    directory.mkdir(parents=True, exist_ok=True)
    for suffix in ('pdf', 'svg', 'png'):
        fig.savefig(directory / f'{name}.{suffix}', dpi=240)
    plt.close(fig)

def baseline(ax, horizontal=True):
    (ax.axhline if horizontal else ax.axvline)(0, color=GRAY, lw=.8, ls=(0, (2, 2)), zorder=1)

def observations(ax, values, position, color, horizontal=False, summary=None):
    """All five paired order observations; no workflow pseudoreplication."""
    values = np.asarray(values, dtype=float)
    assert len(values) == 5
    for seed, (value, offset) in enumerate(zip(values, np.linspace(-.13, .13, 5))):
        x, y = (value, position+offset) if horizontal else (position+offset, value)
        ax.scatter(x, y, marker=MARKERS[seed], s=25, facecolor='white',
                   edgecolor=color, linewidth=.8, zorder=3)
    if summary is None:
        avg = values.mean()
        half = 2.7764451051977987 * values.std(ddof=1) / np.sqrt(5)
        summary = dict(mean=avg, low=avg-half, high=avg+half)
    errors = [[summary['mean']-summary['low']], [summary['high']-summary['mean']]]
    if horizontal:
        ax.errorbar(summary['mean'], position, xerr=errors, fmt='D', color=color,
                    ms=4, capsize=3, lw=1.2, zorder=4)
    else:
        ax.errorbar(position, summary['mean'], yerr=errors, fmt='D', color=color,
                    ms=4, capsize=3, lw=1.2, zorder=4)

def panels(n, height=2.8, left=.10, right=.985, bottom=.24, top=.82, gap=.52):
    fig, axes = plt.subplots(1, n, figsize=(7, height))
    fig.subplots_adjust(left=left, right=right, bottom=bottom, top=top, wspace=gap)
    return fig, np.atleast_1d(axes)

def seed_note(fig, y=.98):
    fig.text(.99, y, '5 paired admission orders; mean and 95% t interval',
             ha='right', va='top', color=GRAY)
