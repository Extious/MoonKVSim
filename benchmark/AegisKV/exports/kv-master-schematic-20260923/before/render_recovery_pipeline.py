"""Layer-ordered readiness under partial backup (calibrated analytical model).

MiniCPM4-8B, 32 layers, 32K-token history. Readiness follows the Motivation
measurement: restore the historical KV and process one additional token.
Per-layer computation is the measured A100 forward of one token over the
resident history; per-layer transfer divides the backed-up bytes by the
effective host-to-device bandwidth available to one recovery, which lies below
the link peak. Every panel backs up the same partial state: the blocks that
one token's native selections read (retrospective). Unselected blocks have no
backup in either tier and are not read before readiness, so reconstruction
lies outside the timeline.

Writes two figures: `recovery-pipeline` (timelines at two bandwidths) and
`depth-bandwidth` (required HBM depth and exposed waiting over bandwidth).
"""
from pathlib import Path
import hashlib
import json

import fitz
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.text import Text
from matplotlib.ticker import FixedLocator, NullLocator
import numpy as np

import render_draft_20260915 as src
from design_plot_typography import configure

MODEL, HISTORY, QUERY_TOKENS, BLOCK = 'MiniCPM4-8B', 32768, 1, 64
BOOKS = ('10146', '10321', '10356')
TIMELINE_BPS = (6e9, 3e9)       # effective H2D bandwidth per recovery
SWEEP_BPS = np.geomspace(.25e9, 32e9, 481)
AEGIS = Path(__file__).resolve().parents[3]
PAPER = AEGIS / 'paper'
REVIEW = AEGIS / 'exports/system-design-current'
COLUMN_PT = (505.89 - 24) / 2 * 72 / 72.27
LOAD, COMPUTE, WAIT, WAIT_EDGE = '#6BA394', '#4F5965', '#F1CDD2', '#A23B48'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def token_reads():
    """Per-layer fraction of history blocks read by one query token's native
    selections (distinct over KV heads), averaged over the query positions
    after the history and over texts."""
    blocks, per_book, traces = HISTORY // BLOCK, {}, {}
    for book in BOOKS:
        directory = src.SPARSE / f'traces/pg19-{book}-M{HISTORY}-N512'
        run = json.loads((directory / 'run.json').read_text())
        assert run['status'] == 'complete' and run['M'] == HISTORY, directory
        fractions = []
        for row in sorted(run['layers'], key=lambda r: r['layer_zero_based']):
            path = src.SPARSE / row['trace_file']
            assert sha(path) == row['trace_sha256'], path
            traces[str(path.relative_to(AEGIS))] = row['trace_sha256']
            with np.load(path) as f:
                selected = f['selected_blocks'].astype(np.int32)[:, HISTORY:HISTORY + run['N']]
            valid = (selected >= 0) & (selected < blocks)
            reads = [np.unique(selected[:, q][valid[:, q]]).size
                     for q in range(selected.shape[1])]
            fractions.append(float(np.mean(reads)) / blocks)
        per_book[book] = fractions
    return np.mean(list(per_book.values()), axis=0), per_book, traces


def schedule(transfer, compute, resident=0, bulk=False):
    """Layer l starts after layer l-1 and after its DRAM regions arrive.
    Regions of the first `resident` layers are in HBM; the others load in
    layer order on one link. `bulk` waits for all loads before layer 1."""
    loads, ready, clock = [], np.zeros(len(transfer)), 0.0
    for layer, duration in enumerate(transfer):
        if layer < resident or duration <= 0:
            continue
        loads.append((layer, clock, float(duration)))
        clock += duration
        ready[layer] = clock
    if bulk:
        ready[:] = clock
    start, previous = np.zeros(len(transfer)), 0.0
    for layer in range(len(transfer)):
        start[layer] = max(previous, ready[layer])
        previous = start[layer] + compute
    return loads, start, start + compute


def exposed(finish, compute):
    return float(finish[-1] - len(finish) * compute)


def depth(transfer, compute):
    """Smallest HBM depth L for which later DRAM loads never delay a layer."""
    for resident in range(len(transfer) + 1):
        if exposed(schedule(transfer, compute, resident)[2], compute) <= 1e-9:
            return resident
    raise AssertionError('full HBM residency must remove all waiting')


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


def pipeline_figure(reads, compute, transfer, backup_mib, total_mib, layer_mib):
    light, heavy = TIMELINE_BPS
    deep = depth(transfer(heavy), compute)
    panels = [
        ('DRAM, bulk load', light, 0, True),
        ('DRAM, layer order', light, 0, False),
        ('DRAM, layer order', heavy, 0, False),
        (f'L1–{deep} in HBM', heavy, deep, False),
    ]
    fig = plt.figure(figsize=(3.34, 3.02))
    fig.legend(handles=[Patch(color=LOAD, label='H2D load'),
                        Patch(color=COMPUTE, label='Compute'),
                        Patch(facecolor=WAIT, edgecolor=WAIT_EDGE, lw=.6, label='Wait')],
               loc='upper center', bbox_to_anchor=(.5, 1.01), ncol=3,
               handlelength=1.1, handletextpad=.4, columnspacing=1.1)
    fig.text(.012, .872, f'Backup: {backup_mib:.0f} of {total_mib:.0f} MiB', color=COMPUTE)
    fig.text(.985, .872, 'Total / wait (ms)', ha='right', color=COMPUTE)
    left, width, records = .17, .80, []
    for index, (title, bps, resident, bulk) in enumerate(panels):
        loads, start, finish = schedule(transfer(bps), compute, resident, bulk)
        wait = exposed(finish, compute)
        y = .665 - index * .172
        ax = fig.add_axes([left, y, width, .098])
        for _, begin, duration in loads:
            ax.barh(1, duration, left=begin, height=.7, color=LOAD,
                    edgecolor='white', lw=.15)
        previous = 0.0
        for layer in range(len(reads)):
            if start[layer] > previous + 1e-9:
                ax.barh(0, start[layer] - previous, left=previous, height=.7,
                        color=WAIT, edgecolor=WAIT_EDGE, lw=.5)
            ax.barh(0, compute, left=start[layer], height=.7, color=COMPUTE,
                    edgecolor='white', lw=.15)
            previous = finish[layer]
        label = f'({chr(97 + index)}) {title}, {bps / 1e9:g} GB/s'
        fig.text(.012, y + .118, label)
        fig.text(.985, y + .118, f'{finish[-1]:.0f} / {wait:.0f}', ha='right')
        ax.set(xlim=(0, 125), ylim=(-.5, 1.5), yticks=[0, 1],
               yticklabels=['GPU', 'H2D'], xticks=[0, 50, 100])
        ax.tick_params(axis='y', length=0, pad=3)
        for side in ['top', 'right']:
            ax.spines[side].set_visible(False)
        ax.spines['bottom'].set_visible(index == 3)
        ax.tick_params(axis='x', bottom=index == 3, labelbottom=index == 3,
                       length=3, pad=3)
        if index == 3:
            ax.set_xlabel('Time after takeover (ms)', labelpad=3)
        records.append({
            'panel': chr(97 + index), 'label': label, 'h2d_bytes_per_s': bps,
            'hbm_layers': resident, 'bulk_load': bulk,
            'total_ms': float(finish[-1]), 'exposed_wait_ms': wait,
            'hbm_mib': float(reads[:resident].sum() * layer_mib),
            'dram_mib': float(reads[resident:].sum() * layer_mib),
            'layer_start_ms': start.tolist(), 'layer_finish_ms': finish.tolist(),
            'loads': [{'layer': l + 1, 'start_ms': b, 'duration_ms': d} for l, b, d in loads],
        })
    return export(fig, 'recovery-pipeline'), records


def depth_figure(reads, compute, transfer, layer_mib):
    rows = []
    for bps in SWEEP_BPS:
        t = transfer(bps)
        hbm_layers = depth(t, compute)
        rows.append({'h2d_bytes_per_s': float(bps), 'hbm_depth_L': hbm_layers,
                     'hbm_mib': float(reads[:hbm_layers].sum() * layer_mib),
                     'all_dram_exposed_wait_ms': exposed(schedule(t, compute)[2], compute)})
    low, high = 1e9, 10e9
    for _ in range(60):
        middle = (low + high) / 2
        low, high = (middle, high) if depth(transfer(middle), compute) > 1 else (low, middle)
    knee = high
    gbps = np.array([r['h2d_bytes_per_s'] for r in rows]) / 1e9
    depths = np.array([r['hbm_depth_L'] for r in rows])
    waits = np.array([r['all_dram_exposed_wait_ms'] for r in rows])

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(3.34, 2.72), sharex=True,
                                      gridspec_kw={'hspace': .16})
    fig.subplots_adjust(left=.17, right=.97, top=.97, bottom=.17)
    top.plot(gbps, depths, color=COMPUTE, lw=1.3, drawstyle='steps-post')
    bottom.plot(gbps, waits, color=WAIT_EDGE, lw=1.3)
    for bps in TIMELINE_BPS:
        t = transfer(bps)
        top.plot(bps / 1e9, depth(t, compute), 'o', ms=4.5, mfc='white',
                 mec=COMPUTE, mew=1.1, zorder=3)
        bottom.plot(bps / 1e9, exposed(schedule(t, compute)[2], compute), 'o', ms=4.5,
                    mfc='white', mec=WAIT_EDGE, mew=1.1, zorder=3)
    for ax in (top, bottom):
        ax.axvline(knee / 1e9, color=COMPUTE, lw=.8, ls=(0, (3, 2)))
        ax.set_xscale('log')
        ax.xaxis.set_major_locator(FixedLocator([.25, .5, 1, 2, 4, 8, 16, 32]))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.set_xticklabels(['0.25', '0.5', '1', '2', '4', '8', '16', '32'])
        for side in ['top', 'right']:
            ax.spines[side].set_visible(False)
        ax.tick_params(length=3, pad=3)
    top.set(xlim=(.25, 32), ylim=(0, 32), yticks=[0, 8, 16, 24, 32])
    top.set_ylabel('Depth $L$', labelpad=3)
    top.text(knee / 1e9 * 1.12, 13, 'load ≈ compute', color=COMPUTE)
    top.text(.98, .86, '(a)', transform=top.transAxes, ha='right')
    bottom.set_yscale('log')
    bottom.set(ylim=(.1, 2000), yticks=[.1, 1, 10, 100, 1000])
    bottom.set_yticklabels(['0.1', '1', '10', '100', '1000'])
    bottom.yaxis.set_minor_locator(NullLocator())
    bottom.set_ylabel('Wait (ms)', labelpad=3)
    bottom.text(.98, .86, '(b)', transform=bottom.transAxes, ha='right')
    bottom.set_xlabel('Effective H2D bandwidth per recovery (GB/s)', labelpad=3)
    fig.align_ylabels([top, bottom])
    return export(fig, 'depth-bandwidth'), rows, knee


def italic_math(family):
    """Typeset math symbols such as L in the manuscript's Libertine italic."""
    import subprocess
    from matplotlib import font_manager
    path = subprocess.check_output(['kpsewhich', 'LinLibertine_RI.otf'], text=True).strip()
    font_manager.fontManager.addfont(path)
    plt.rcParams.update({'mathtext.fontset': 'custom', 'mathtext.rm': family,
                         'mathtext.it': f'{family}:italic'})
    return {'italic_path': path, 'italic_sha256': sha(path)}


def main():
    typography = configure()
    typography.update(italic_math(typography['family']))
    layers = src.LAYERS
    compute = src.replay_ms_per_layer(HISTORY, tail=QUERY_TOKENS)
    layer_bytes = HISTORY * src.KV_PER_TOKEN_LAYER
    layer_mib = layer_bytes / 2**20
    reads, reads_by_book, traces = token_reads()
    backup_mib = float(reads.sum() * layer_mib)

    def transfer(bps):
        return reads * layer_bytes / bps * 1e3

    pipeline_pdf, panels = pipeline_figure(reads, compute, transfer, backup_mib,
                                           layers * layer_mib, layer_mib)
    depth_pdf, sweep, knee = depth_figure(reads, compute, transfer, layer_mib)
    prefill_s = float(next(r for r in src.LAT_META_M['rows']
                           if r['context'] == HISTORY)['prefill_median_s'])
    sources = [src.REPLAY_JSON, src.LATENCY[MODEL]]
    common = {
        'evidence': 'calibrated analytical model, not a hardware trace; excludes failure '
                    'detection, queueing, launch overhead and interference',
        'model': MODEL, 'layers': layers, 'history_tokens': HISTORY,
        'readiness': f'restore historical KV and process {QUERY_TOKENS} additional token, '
                     'as in the Motivation recovery-cost measurement',
        'compute_ms_per_layer': compute,
        'compute_source': f'measured forward of {QUERY_TOKENS} token over a resident '
                          f'{HISTORY}-token history on {src.GPU_NAME}, split evenly across layers',
        'bandwidth': 'effective host-to-device bandwidth available to one recovery, below '
                     'the link peak; transfers of one recovery are serialized in layer order',
        'full_layer_mib': layer_mib,
        'backup': 'blocks read by one query token (distinct over KV heads), per-layer '
                  'mean over the 512 query positions after the history and three PG19 '
                  'texts; retrospective; unselected blocks have no backup in HBM or DRAM',
        'backup_fraction_per_layer': reads.tolist(),
        'backup_fraction_by_text': reads_by_book,
        'backup_fraction_mean': float(reads.mean()),
        'backup_mib': backup_mib,
        'hbm_depth_rule': 'smallest L with zero exposed wait',
        'full_reconstruction_prefill_s': prefill_s,
        'typography': typography,
        'generator': str(Path(__file__).relative_to(AEGIS)),
        'generator_sha256': sha(__file__),
        'sources': {str(p.relative_to(AEGIS)): sha(p) for p in sources},
        'trace_sources': traces,
    }
    (REVIEW / 'data/recovery-pipeline.json').write_text(json.dumps(
        {**common, 'timeline_h2d_bytes_per_s': list(TIMELINE_BPS), 'panels': panels,
         'paper_pdf': pipeline_pdf}, indent=2) + '\n')
    (REVIEW / 'data/depth-bandwidth.json').write_text(json.dumps(
        {**common, 'depth_above_one_below_bytes_per_s': knee,
         'mean_layer_load_equals_compute_bytes_per_s':
             float(reads.mean() * layer_bytes / (compute / 1e3)),
         'sweep': sweep, 'paper_pdf': depth_pdf}, indent=2) + '\n')
    print(json.dumps({'compute_ms_per_layer': compute, 'backup_mib': backup_mib,
                      'knee_GBps': knee / 1e9, 'prefill_s': prefill_s,
                      'pipeline_pdf': pipeline_pdf, 'depth_pdf': depth_pdf}, indent=2))
    for r in panels:
        print(r['label'], round(r['total_ms'], 1), round(r['exposed_wait_ms'], 2),
              round(r['hbm_mib'], 1))
    for gb in [.5, 1, 2, 3, 4, 6, 16]:
        r = min(sweep, key=lambda row: abs(row['h2d_bytes_per_s'] / 1e9 - gb))
        print(round(r['h2d_bytes_per_s'] / 1e9, 2), r['hbm_depth_L'], round(r['hbm_mib'], 1),
              round(r['all_dram_exposed_wait_ms'], 2))


if __name__ == '__main__':
    main()
