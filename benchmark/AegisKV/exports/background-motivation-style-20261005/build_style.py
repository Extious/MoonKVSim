#!/usr/bin/env python3
"""Restore the established paper style without reading historical experiments.

The application DAG, authored normalized example, and symbolic resource states
are retained. Style references are serving_model.pdf and agent_value_b.pdf.
"""
from pathlib import Path
import json
import shutil
import os
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
AEGIS = ROOT.parents[1]
PAPER = AEGIS / 'paper'
PREVIOUS = AEGIS / 'exports/workflow-paper-revision-20261005'
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'mpl-cache'))
import fitz
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle, Patch

INK, EDGE, TEAL, MINT = '#243746', '#70808A', '#39756A', '#E1EEE8'
BLUE, PALE_BLUE, AMBER, WARM = '#23688D', '#DDEBF3', '#9B6428', '#F3E5D1'
GRAY, RED, PALE_RED = '#F1F3F4', '#B83C46', '#F6DADD'
COL_MM = (505.89 - 24) / 2 * 25.4 / 72.27


def workflows():
    out = ROOT / 'sources'
    out.mkdir(exist_ok=True)
    src = ET.parse(PREVIOUS / 'sources/application-workflows.drawio')
    contract = json.loads((PREVIOUS / 'sources/figure-contract.json').read_text())
    for diagram in src.getroot().findall('diagram'):
        model = diagram.find('mxGraphModel')
        model.set('pageHeight', '392')
        cells = {c.get('id'): c for c in model.find('root').findall('mxCell')}
        cells['canvas'].find('mxGeometry').set('height', '392')
        title = cells['title']
        title.set('style', f'html=0;whiteSpace=wrap;fontFamily=Linux Libertine O;'
                  f'fontSize=22;fontColor={INK};fontStyle=0;align=left;'
                  'verticalAlign=middle;fillColor=none;strokeColor=none;spacing=0;')
        tg = title.find('mxGeometry')
        tg.set('y', '10'); tg.set('height', '30')
        positions = {}
        for ident, cell in cells.items():
            if not ident.startswith('agent-'):
                continue
            g = cell.find('mxGeometry')
            y = 64 + (float(g.get('y')) - 80) * 108 / 136
            g.set('y', str(y)); g.set('height', '84')
            positions[ident] = (float(g.get('x')), y)
            cell.set('style', f'rounded=0;whiteSpace=wrap;html=0;'
                     f'fontFamily=Linux Libertine O;fontSize=22;fontColor={INK};'
                     f'align=center;verticalAlign=middle;fillColor={MINT};'
                     f'strokeColor={TEAL};strokeWidth=1.2;spacing=2;')
        for ident, cell in cells.items():
            if cell.get('edge') != '1':
                continue
            old = dict(item.split('=', 1) for item in cell.get('style').split(';') if '=' in item)
            sy = positions[cell.get('source')][1] + 84 * float(old['exitY'])
            ty = positions[cell.get('target')][1] + 84 * float(old['entryY'])
            old.update(strokeColor=EDGE, strokeWidth='1.4', endSize='5', jumpSize='8')
            cell.set('style', ';'.join(f'{k}={v}' for k, v in old.items()) + ';')
            arr = cell.find('mxGeometry/Array')
            if arr is not None:
                pts = arr.findall('mxPoint')
                # Align bend ordinates with actual ports after reducing node height.
                for i, pt in enumerate(pts):
                    y = sy if i == 0 else ty if i == len(pts) - 1 else 376
                    pt.set('y', str(y))
        # Straight horizontal connections retain center ports; long cross-level
        # connections use explicit paths and a bridge where necessary.
    ET.indent(src.getroot())
    src.write(out / 'application-workflows.drawio', encoding='utf-8', xml_declaration=True)
    contract['style_reference'] = 'paper/figures/serving_model.pdf'
    contract['style_changes'] = 'Uniform pale-green Agent rectangles, fine gray connectors, compact spacing, Libertine 10.365 pt at 168 mm.'
    (out / 'figure-contract.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2) + '\n')


def typography():
    font = Path('/home/comp/zhanzhao/miniforge3/envs/latex/tinytex/texmf-dist/fonts/opentype/public/libertine/LinLibertine_R.otf')
    font_manager.fontManager.addfont(str(font))
    plt.rcParams.update({'font.family': 'Linux Libertine O', 'font.size': 10.5,
        'axes.labelsize': 10.5, 'xtick.labelsize': 10.5, 'ytick.labelsize': 10.5,
        'legend.fontsize': 10.5, 'text.color': INK, 'axes.labelcolor': INK,
        'axes.edgecolor': INK, 'xtick.color': INK, 'ytick.color': INK,
        'axes.linewidth': .7, 'axes.spines.top': False, 'axes.spines.right': False,
        'hatch.linewidth': .6, 'pdf.fonttype': 42, 'svg.fonttype': 'none',
        'legend.frameon': False, 'savefig.facecolor': 'white'})


def save(fig, name):
    out = ROOT / 'schematics'; out.mkdir(exist_ok=True)
    review = ROOT / 'review'; review.mkdir(exist_ok=True)
    fig.savefig(out / f'{name}.pdf')
    fig.savefig(out / f'{name}.svg')
    plt.close(fig)
    with fitz.open(out / f'{name}.pdf') as doc:
        page = doc[0]
        assert abs(page.rect.width / 72 * 25.4 - COL_MM) < .01
        page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).save(out / f'{name}.png')
        page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(review / f'{name}-color.png')
        page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY, alpha=False).save(review / f'{name}-gray.png')
        spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
        assert min(s['size'] for s in spans) >= 10
        for s in spans:
            r = fitz.Rect(s['bbox'])
            assert r.x0 >= 0 and r.y0 >= 0 and r.x1 <= page.rect.width + .1 and r.y1 <= page.rect.height + .1, (name, s)
    shutil.copy2(out / f'{name}.pdf', PAPER / f'figures/{name}.pdf')
    preview = PAPER / 'figures/preview'; preview.mkdir(exist_ok=True)
    shutil.copy2(out / f'{name}.png', preview / f'{name}.png')


def exposure():
    fig = plt.figure(figsize=(COL_MM / 25.4, 51 / 25.4))
    ax = fig.add_axes([.13, .28, .66, .54])
    labels, absorbed, exposed = ['A', 'B', 'C'], [3, 0, 4], [1, 4, 0]
    ax.barh(labels, absorbed, height=.58, color=MINT, edgecolor=TEAL, hatch='////', lw=.65)
    ax.barh(labels, exposed, left=absorbed, height=.58, color=RED, edgecolor=RED, lw=.65)
    ax.invert_yaxis()
    for y in range(3):
        ax.text(4.15, y, '4', va='center')
        yf = fig.transFigure.inverted().transform(ax.transData.transform((0, y)))[1]
        fig.text(.923, yf, str(exposed[y]), va='center', ha='center')
    ax.set(xlim=(0, 5.5), xticks=[0, 2, 4], xlabel='Reconstruction time (u)')
    ax.tick_params(axis='y', length=0)
    fig.legend(handles=[Patch(facecolor=MINT, edgecolor=TEAL, hatch='////', label='Absorbed'),
                        Patch(facecolor=RED, edgecolor=RED, label='Added WCT')],
               loc='upper left', bbox_to_anchor=(.09, 1), ncol=2,
               handlelength=1.1, handletextpad=.5, columnspacing=.8, borderaxespad=0)
    fig.text(.923, .928, 'ΔW (u)', ha='center')
    save(fig, 'workflow-recovery-exposure')


def demand():
    fig = plt.figure(figsize=(COL_MM / 25.4, 59 / 25.4))
    ax = fig.add_axes([.02, .01, .96, .98]); ax.axis('off')
    ax.set(xlim=(0, 10), ylim=(0, 9.5))
    ax.text(.08, 8.95, '(a) Complete DRAM coverage', va='center')
    for row in range(3):
        ax.text(.35, 8 - row * .83, f'L{row+1}', va='center', ha='center')
        for block in range(6):
            selected = row < 2 and block in ({0, 3} if row == 0 else {1, 4})
            ax.add_patch(Rectangle((1.1 + block * 1.4, 7.70 - row * .83), 1.25, .60,
                         facecolor=MINT if selected else GRAY, edgecolor=TEAL if selected else EDGE,
                         hatch='////' if selected else None, lw=.55))
    ax.add_patch(Rectangle((1.1, 5.32), .6, .4, facecolor=MINT, edgecolor=TEAL, hatch='////', lw=.55))
    ax.text(1.93, 5.52, 'Additional HBM copy', va='center')
    ax.text(.08, 4.57, '(b) Transfer relative to demand', va='center')
    # Symbolic before/after-demand ordering, not a physical latency trace.
    for y, start, end, label in [(3.30, 2.25, 4.15, 'Hidden'), (1.70, 4.0, 7.0, 'Exposed')]:
        ax.text(.08, y, label, va='center')
        ax.plot([2.1, 9.55], [y, y], color=EDGE, lw=.55)
        ax.add_patch(Rectangle((start, y-.16), end-start, .32, facecolor=PALE_BLUE, edgecolor=BLUE, lw=.55))
        ax.plot([5.4, 5.4], [y-.35, y+.35], color=INK, lw=.75)
        if end > 5.4:
            ax.add_patch(Rectangle((5.4, y-.16), end-5.4, .32, facecolor=PALE_RED, edgecolor=RED, hatch='////', lw=.55))
    ax.text(5.4, .83, 'KV needed', va='center', ha='center')
    ax.annotate('time', xy=(9.7, .83), xytext=(8.4, .83), ha='right', va='center',
                arrowprops={'arrowstyle': '->', 'color': EDGE, 'lw': .65})
    ax.add_patch(Rectangle((2.25, .07), .6, .40, facecolor=PALE_BLUE, edgecolor=BLUE, lw=.55))
    ax.text(3.04, .27, 'H2D', va='center')
    ax.add_patch(Rectangle((5.3, .07), .6, .40, facecolor=PALE_RED, edgecolor=RED, hatch='////', lw=.55))
    ax.text(6.10, .27, 'Stall', va='center')
    save(fig, 'recovery-demand-placement')


def capacity():
    fig = plt.figure(figsize=(COL_MM / 25.4, 52 / 25.4))
    ax = fig.add_axes([.14, .22, .82, .57])
    for x, serving, replica in [(0, 2, 4), (1, 5, 1), (2, 3, 3)]:
        ax.bar(x, 1, width=.57, color=GRAY, edgecolor=EDGE, lw=.65)
        ax.bar(x, serving, bottom=1, width=.57, color=BLUE, edgecolor=BLUE, lw=.65)
        ax.bar(x, replica, bottom=1+serving, width=.57, color=MINT, edgecolor=TEAL, hatch='////', lw=.65)
    ax.set(xticks=[0, 1, 2], xticklabels=['Low load', 'High load', 'Load falls'],
           yticks=[], ylabel='HBM allocation', ylim=(0, 7.2), xlim=(-.55, 2.55))
    fig.legend(handles=[Patch(facecolor=GRAY, edgecolor=EDGE, label='Fixed'),
        Patch(facecolor=BLUE, edgecolor=BLUE, label='Serving'),
        Patch(facecolor=MINT, edgecolor=TEAL, hatch='////', label='Replica space')],
        loc='upper center', bbox_to_anchor=(.54, .96), ncol=3,
        handlelength=.9, handletextpad=.45, columnspacing=.8, borderaxespad=0)
    save(fig, 'foreground-replica-capacity')


if __name__ == '__main__':
    workflows()
    typography()
    exposure()
    demand()
    capacity()
