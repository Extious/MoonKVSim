"""Schematic KV Master figures (constructed examples, not measurements).

master-selection
    (a) Agent selection: unhidden retry delay [T - s]^+ of the Motivation
        Agents A1-A4 against a threshold lambda.
    (b) One protected Agent: per-layer access counts; the Top-K blocks of the
        first L layers are also in HBM; the uncheckpointed tail is rebuilt.
recovery-pipeline
    Layer-ordered recovery trend in units of one layer's rebuild time. The
    rebuild of a layer starts once its Top-K blocks are resident; its misses are
    then fetched ahead of the stream while it computes on hits; the rest of the
    KV loads after the Top-K blocks of all remaining layers.
depth-bandwidth
    Required depth L versus effective H2D bandwidth, normalized to B*, the
    bandwidth at which one layer's Top-K blocks load in one layer's rebuild.
"""
from pathlib import Path
import hashlib
import json
import subprocess

import fitz
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch, Rectangle
from matplotlib.text import Text
import numpy as np

from design_plot_typography import configure

AEGIS = Path(__file__).resolve().parents[3]
PAPER = AEGIS / 'paper'
REVIEW = AEGIS / 'exports/system-design-current'
COLUMN_PT = (505.89 - 24) / 2 * 72 / 72.27
HOT, COLD, COMPUTE, WAIT, WAIT_EDGE = '#6BA394', '#D3E6DF', '#4F5965', '#F1CDD2', '#A23B48'
MUTED, GRID, DRAM = '#8A939B', '#E1E5E8', '#DDE2E6'

AGENTS = {'A1': 0.0, 'A2': 32.6, 'A3': 16.3, 'A4': 18.0}   # Figure 2(b), seconds
LAMBDA = 17.0
PIPE_LAYERS, HOT_LOAD, HOT_SHARE = 8, 1.2, .5              # Top-K load per layer, share of bytes
MISS_LOAD, STEP = .3, 1e-3                                  # misses per rebuilt layer; simulation step
MISS = '#C3792F'
DEPTH_LAYERS = 32
SWEEP = np.linspace(.05, 2, 391)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def italic_math(family):
    path = subprocess.check_output(['kpsewhich', 'LinLibertine_RI.otf'], text=True).strip()
    font_manager.fontManager.addfont(path)
    plt.rcParams.update({'mathtext.fontset': 'custom', 'mathtext.rm': family,
                         'mathtext.it': f'{family}:italic', 'mathtext.cal': family,
                         'mathtext.sf': family, 'mathtext.bf': f'{family}:bold'})
    return {'italic_path': path, 'italic_sha256': sha(path)}


def check_text(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for text in fig.findobj(match=Text):
        if not text.get_visible() or not text.get_text().strip():
            continue
        box = text.get_window_extent(renderer)
        assert box.x0 >= -.7 and box.y0 >= -.7, text.get_text()
        assert box.x1 <= fig.bbox.width + .7 and box.y1 <= fig.bbox.height + .7, text.get_text()
        assert text.get_fontsize() >= 10.0, (text.get_text(), text.get_fontsize())


def export(fig, name):
    """Scale to the text column, then write the paper PDF, preview and reviews."""
    check_text(fig)
    for subdir in ['figures', 'data', 'review']:
        (REVIEW / subdir).mkdir(parents=True, exist_ok=True)
    native = REVIEW / f'figures/{name}.native.pdf'
    fig.savefig(native)
    plt.close(fig)
    source = fitz.open(native)
    doc = fitz.open()
    page = doc.new_page(width=COLUMN_PT,
                        height=source[0].rect.height * COLUMN_PT / source[0].rect.width)
    page.show_pdf_page(page.rect, source, 0)
    doc.save(PAPER / f'figures/{name}.pdf', garbage=4, deflate=True)
    page.get_pixmap(matrix=fitz.Matrix(3, 3)).save(PAPER / f'figures/preview/{name}.png')
    page.get_pixmap(matrix=fitz.Matrix(2, 2)).save(REVIEW / f'review/{name}.column.png')
    page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY).save(
        REVIEW / f'review/{name}.gray.png')
    spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b
             for line in b['lines'] for s in line['spans'] if s['text'].strip()]
    minimum_font = min(s['size'] for s in spans)
    assert minimum_font >= 10, (name, minimum_font)
    return {'width_mm': page.rect.width / 72 * 25.4,
            'height_mm': page.rect.height / 72 * 25.4,
            'minimum_font_pt': minimum_font, 'embedded_rasters': len(page.get_images())}


def schedule(layers, hot, cold, resident=0, bulk=False):
    """One H2D stream. Without `bulk`, Top-K blocks of layers beyond `resident`
    load in layer order, then the other KV of every layer. A layer rebuilds
    (one time unit) after the previous layer and once its Top-K blocks are
    resident. With `bulk`, every layer's full KV loads before layer 1."""
    loads, ready, clock = [], np.zeros(layers), 0.0
    if bulk:
        for kind, duration in [('hot', hot), ('cold', cold)]:
            for layer in range(layers):
                loads.append((kind, layer, clock, duration))
                clock += duration
        ready[:] = clock
    else:
        for layer in range(resident, layers):
            loads.append(('hot', layer, clock, hot))
            clock += hot
            ready[layer] = clock
        for layer in range(layers):
            loads.append(('cold', layer, clock, cold))
            clock += cold
    start, previous = np.zeros(layers), 0.0
    for layer in range(layers):
        start[layer] = max(previous, ready[layer])
        previous = start[layer] + 1
    return loads, start, start + 1


def wait(finish):
    return float(finish[-1] - len(finish))


def depth(layers, hot):
    for resident in range(layers + 1):
        if wait(schedule(layers, hot, 0, resident)[2]) <= 1e-9:
            return resident
    raise AssertionError('full residency removes all waiting')


def style(ax):
    for side in ['top', 'right']:
        ax.spines[side].set_visible(False)


COUNTS = [[9, 2, 3, 7, 1, 2],      # access counts at checkpoint c, rows L1-L4
          [2, 8, 1, 6, 3, 1],
          [5, 1, 2, 1, 6, 2],
          [1, 4, 1, 2, 1, 7]]
K_EX, L_EX = 2, 2


def top_k(row, k=K_EX):
    return set(sorted(range(len(row)), key=lambda b: -row[b])[:k])


def cell(ax, x, y, face, edge, lw=.6, text=None, color=COMPUTE, hatch=None, width=.92):
    ax.add_patch(Rectangle((x, y), width, .84, facecolor=face, edgecolor=edge, lw=lw, hatch=hatch))
    if text is not None:
        ax.text(x + width / 2, y + .42, text, ha='center', va='center', color=color)


def selection_figure():
    fig = plt.figure(figsize=(3.34, 3.12))
    top = fig.add_axes([.14, .70, .83, .22])
    names = list(AGENTS)[::-1]
    values = [AGENTS[n] for n in names]
    colors = [DRAM if v > LAMBDA else 'white' for v in values]
    top.barh(names, values, height=.62, color=colors,
             edgecolor=[COMPUTE if v > LAMBDA else MUTED for v in values], lw=.6)
    top.text(.6, names.index('A1'), '0: hidden by slack', va='center', color=MUTED)
    top.axvline(LAMBDA, color=WAIT_EDGE, lw=1, ls=(0, (3, 2)))
    top.text(LAMBDA + .6, 3.28, r'$\lambda$', color=WAIT_EDGE)
    top.set(xlim=(0, 36), xticks=[0, 10, 20, 30])
    top.set_xlabel('Retry delay not hidden by slack (s)', labelpad=2)
    top.tick_params(length=3, pad=2)
    top.tick_params(axis='y', length=0)
    style(top)
    fig.text(.012, .955, r'(a) Agents above $\lambda$ get a DRAM checkpoint')

    grid = fig.add_axes([.14, .085, .83, .39])
    fig.text(.012, .5, f'(b) Access counts of one Agent, $K={K_EX}$, $L={L_EX}$')
    rows, blocks = len(COUNTS), len(COUNTS[0])
    for row, counts in enumerate(COUNTS):
        y = rows - 1 - row
        hot = top_k(counts) if row < L_EX else set()
        for block, count in enumerate(counts):
            h = block in hot
            cell(grid, block, y, HOT if h else DRAM, COMPUTE if h else MUTED,
                 text=str(count), color='white' if h else COMPUTE)
        cell(grid, blocks + .15, y, 'white', WAIT_EDGE, hatch='////', width=1.25)
        grid.text(-.2, y + .42, f'L{row + 1}', ha='right', va='center')
    for block in range(blocks):
        grid.text(block + .46, rows + .12, f'B{block}', ha='center', va='bottom')
    grid.text(blocks + .78, rows + .12, 'Tail', ha='center', va='bottom', color=WAIT_EDGE)
    grid.plot([-.1, blocks + 1.5], [1.96, 1.96], color=COMPUTE, lw=.9, ls=(0, (3, 2)))
    grid.set(xlim=(-1.25, blocks + 1.55), ylim=(-.1, rows + .75))
    grid.axis('off')
    fig.legend(handles=[Patch(facecolor=HOT, edgecolor=COMPUTE, lw=.6, label='HBM + DRAM'),
                        Patch(facecolor=DRAM, edgecolor=MUTED, lw=.6, label='DRAM'),
                        Patch(facecolor='white', edgecolor=WAIT_EDGE, lw=.6, hatch='////',
                              label='Rebuilt')],
               loc='lower center', bbox_to_anchor=(.55, -.015), ncol=3, frameon=False,
               handlelength=1.0, handletextpad=.35, columnspacing=.8)
    return export(fig, 'master-selection'), {
        'agents_unhidden_delay_s': AGENTS, 'lambda_s': LAMBDA,
        'protected': [n for n, v in AGENTS.items() if v > LAMBDA],
        'example_grid': {'K': K_EX, 'L': L_EX, 'access_counts': COUNTS,
                         'hbm_blocks': {f'L{r + 1}': sorted(top_k(COUNTS[r])) for r in range(L_EX)},
                         'tail': 'at most Z = 256 accepted tokens after the last checkpoint'}}


def simulate(layers, hot, cold, miss, resident=0):
    """One H2D stream, simulated in steps of STEP. Top-K blocks of layers beyond
    `resident` load in layer order, then the other KV. A layer starts after the
    previous one once its Top-K blocks are resident; at that moment its misses
    (blocks the tail selects outside GPU memory) are fetched ahead of the stream.
    The layer computes on hits meanwhile and ends once both its unit of compute
    and its misses are done."""
    queue = [['hot', l, hot] for l in range(resident, layers)] + \
            [['cold', l, cold] for l in range(layers)]
    ready = {l: 0.0 for l in range(resident)}
    pending, missed = [], {}
    start, finish = [None] * layers, [None] * layers
    segments, t, layer, previous = [], 0.0, 0, 0.0
    while layer < layers or queue or pending:
        if layer < layers and start[layer] is None and t >= previous - 1e-9 and layer in ready:
            start[layer] = t
            pending.append(['miss', layer, miss])
        if layer < layers and start[layer] is not None and layer in missed \
                and t >= start[layer] + 1 - 1e-9:
            finish[layer] = previous = t
            layer += 1
            continue
        job = pending[0] if pending else (queue[0] if queue else None)
        if job is not None:
            kind, which = job[0], job[1]
            if segments and segments[-1][:2] == (kind, which) and abs(segments[-1][3] - t) < 1e-9:
                segments[-1] = (kind, which, segments[-1][2], t + STEP)
            else:
                segments.append((kind, which, t, t + STEP))
            job[2] -= STEP
            if job[2] <= 1e-9:
                (pending if pending else queue).pop(0)
                if kind == 'hot':
                    ready[which] = t + STEP
                elif kind == 'miss':
                    missed[which] = t + STEP
        t += STEP
    return segments, np.array(start), np.array(finish)


def pipeline_figure():
    cold = HOT_LOAD * (1 - HOT_SHARE) / HOT_SHARE
    loads, bulk_start, bulk_finish = schedule(PIPE_LAYERS, HOT_LOAD, cold, 0, True)
    bulk = ([(k, l, b, b + d) for k, l, b, d in loads], bulk_start, bulk_finish)
    runs = {r: simulate(PIPE_LAYERS, HOT_LOAD, cold, MISS_LOAD, r) for r in range(PIPE_LAYERS + 1)}
    deep = next(r for r in range(PIPE_LAYERS + 1) if wait(runs[r][2]) <= .01)
    panels = [('(a) DRAM only, full KV first', 0, bulk),
              ('(b) DRAM only, layer order', 0, runs[0]),
              (f'(c) Top-$K$ of L1–L{deep} in HBM', deep, runs[deep])]
    fig = plt.figure(figsize=(3.34, 2.62))
    fig.legend(handles=[Patch(color=HOT, label='Top-$K$ load'),
                        Patch(color=MISS, label='Miss fetch'),
                        Patch(color=COLD, label='Other KV load'),
                        Patch(color=COMPUTE, label='Rebuild'),
                        Patch(facecolor=WAIT, edgecolor=WAIT_EDGE, lw=.6, label='Wait')],
               loc='upper center', bbox_to_anchor=(.54, 1.01), ncol=3, frameon=False,
               handlelength=1.1, handletextpad=.35, columnspacing=.8)
    records = []
    xmax = max(max(max(e for *_, e in segs), fin[-1]) for segs, _, fin in [bulk, runs[0]]) + .4
    for index, (title, resident, (segments, start, finish)) in enumerate(panels):
        y = .585 - index * .225
        ax = fig.add_axes([.14, y, .83, .12])
        colors = {'hot': HOT, 'cold': COLD, 'miss': MISS}
        for kind, _, begin, end in segments:
            ax.barh(1, end - begin, left=begin, height=.7, color=colors[kind],
                    edgecolor='white', lw=.4)
        previous = 0.0
        for layer in range(PIPE_LAYERS):
            if start[layer] > previous + 1e-6:
                ax.barh(0, start[layer] - previous, left=previous, height=.7,
                        color=WAIT, edgecolor=WAIT_EDGE, lw=.5)
            ax.barh(0, 1, left=start[layer], height=.7, color=COMPUTE, edgecolor='white', lw=.4)
            if finish[layer] > start[layer] + 1 + 1e-6:
                ax.barh(0, finish[layer] - start[layer] - 1, left=start[layer] + 1, height=.7,
                        color=WAIT, edgecolor=WAIT_EDGE, lw=.5)
            previous = finish[layer]
        fig.text(.012, y + .14, title)
        ax.set(xlim=(0, xmax), ylim=(-.5, 1.5), yticks=[0, 1], yticklabels=['GPU', 'H2D'])
        ax.tick_params(axis='y', length=0, pad=3)
        ax.tick_params(axis='x', bottom=False, labelbottom=False)
        style(ax)
        ax.spines['bottom'].set_visible(index == 2)
        records.append({'panel': title, 'hbm_layers': resident,
                        'ready': round(float(finish[-1]), 3), 'wait': round(wait(finish), 3),
                        'miss_fetch_total': round(sum(e - b for k, _, b, e in segments
                                                      if k == 'miss'), 3),
                        'h2d_end': round(float(max(e for *_, e in segments)), 3)})
    fig.text(.555, .02, 'Time after takeover', ha='center')
    return export(fig, 'recovery-pipeline'), {
        'units': "one layer's rebuild time", 'layers': PIPE_LAYERS,
        'topk_load_per_layer': HOT_LOAD, 'other_kv_load_per_layer': cold,
        'miss_fetch_per_layer': MISS_LOAD, 'topk_share_of_layer_bytes': HOT_SHARE,
        'depth_L': deep, 'panels': records}


def depth_figure():
    depths = np.array([depth(DEPTH_LAYERS, 1 / b) for b in SWEEP])
    waits = np.array([wait(schedule(DEPTH_LAYERS, 1 / b, 0)[2]) for b in SWEEP])
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(3.34, 2.6), sharex=True,
                                      gridspec_kw={'hspace': .16})
    fig.subplots_adjust(left=.17, right=.97, top=.97, bottom=.18)
    top.plot(SWEEP, depths, color=COMPUTE, lw=1.3, drawstyle='steps-post')
    bottom.plot(SWEEP, waits, color=WAIT_EDGE, lw=1.3)
    for ax in (top, bottom):
        ax.axvline(1, color=COMPUTE, lw=.8, ls=(0, (3, 2)))
        ax.set_xlim(0, 2)
        ax.set_xticks([0, .5, 1, 1.5, 2])
        ax.tick_params(length=3, pad=3)
        style(ax)
    top.set(ylim=(0, 33), yticks=[0, 8, 16, 24, 32])
    top.set_ylabel('Depth $L$', labelpad=3)
    top.text(1.05, 20, 'Top-$K$ + miss\n= rebuild', color=COMPUTE, va='center')
    top.text(.98, .86, '(a)', transform=top.transAxes, ha='right')
    bottom.set_yscale('log')
    bottom.set(ylim=(.3, 1000), yticks=[1, 10, 100, 1000])
    bottom.set_yticklabels(['1', '10', '100', '1000'])
    bottom.minorticks_off()
    bottom.set_ylabel('Wait', labelpad=3)
    bottom.text(.98, .86, '(b)', transform=bottom.transAxes, ha='right')
    bottom.set_xlabel(r'Effective H2D bandwidth ($\times B$*)', labelpad=3)
    fig.align_ylabels([top, bottom])
    rows = [{'bandwidth_over_Bstar': float(b), 'depth_L': int(d), 'wait_without_hbm': float(w)}
            for b, d, w in zip(SWEEP, depths, waits)]
    return export(fig, 'depth-bandwidth'), {'layers': DEPTH_LAYERS, 'sweep': rows}


def main():
    typography = configure()
    typography.update(italic_math(typography['family']))
    outputs = {}
    for name, build in [('master-selection', selection_figure),
                        ('recovery-pipeline', pipeline_figure),
                        ('depth-bandwidth', depth_figure)]:
        pdf, data = build()
        outputs[name] = pdf
        (REVIEW / f'data/{name}.json').write_text(json.dumps({
            'evidence': 'constructed schematic; illustrates trends, not a measurement or a specific model',
            'generator': str(Path(__file__).relative_to(AEGIS)),
            'generator_sha256': sha(__file__), 'typography': typography,
            'paper_pdf': pdf, **data}, indent=2) + '\n')
        print(name, json.dumps(pdf))
        if name == 'recovery-pipeline':
            for r in data['panels']:
                print('  ', r)
        if name == 'depth-bandwidth':
            for b in [.25, .5, .75, 1, 1.5]:
                r = min(data['sweep'], key=lambda row: abs(row['bandwidth_over_Bstar'] - b))
                print('  ', r)


if __name__ == '__main__':
    main()
