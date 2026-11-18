#!/usr/bin/env python3
"""Render validated physical KV-recovery measurements; never synthesize points."""
import argparse
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, LogLocator, NullFormatter
from motivation_layout import HEIGHT_IN, FONT_PT, axes_rect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--width', type=float, default=2.24)
    ap.add_argument('--height', type=float, default=2.25)
    ap.add_argument('--layout', choices=('original', 'compact'), default='original')
    ap.add_argument('--paths', nargs='+', help='Explicit measured paths to show; raw input remains unchanged')
    args = ap.parse_args()
    data = json.loads(args.data.read_text())
    assert data['evidence'] == 'physical_worker_microbenchmark'
    for name, digest in data['source_sha256'].items():
        assert hashlib.sha256((args.data.parent/name).read_bytes()).hexdigest() == digest, name
    meta, rows = data['metadata'], data['rows']
    assert meta['model'] == 'Qwen/Qwen2.5-7B-Instruct-1M'
    sparse = meta.get('protocol') in ('sparse_prefill_kv_fill_one_token_v1', 'sparse_prefill_kv_fill_one_token_v2',
                                    'sparse_prefill_kv_fill_one_token_v3_sharedfs')
    one_token = sparse or meta.get('protocol') == 'prefill_kv_fill_one_token_v1'
    assert meta['dtype'] == 'BF16'
    assert meta['activation_backend'] == 'flashinfer.activation.silu_and_mul'
    if one_token:
        assert meta['new_tokens'] == 1 and meta['forward_mode'].startswith('EXTEND')
        if not sparse:
            assert meta['recompute_schedule'] == 'empty-cache Prefill of M in <=8192-token chunks, followed by one-token EXTEND'
        else:
            assert meta['sparse_min_queries'] == 1 and meta['chunk_tokens'] == 8192
        assert all(r['new_tokens'] == 1 and r['history_tokens'] == r['context_tokens']-1 for r in rows)
    else:
        assert meta['tail_tokens'] == 64
        assert meta['recompute_schedule'] == 'rebuild history with 8192-token chunks, then the same separate 64-token tail as reuse'
    assert all(r['status'] == 'measured' for r in rows)
    contexts = sorted(meta['contexts'])
    assert len(rows) == len(contexts) * (len(meta['paths']) if sparse else 3)
    sharedfs = meta.get('protocol') == 'sparse_prefill_kv_fill_one_token_v3_sharedfs'
    compact = args.layout == 'compact'
    assert not compact or sharedfs, 'The compact layout is calibrated for the four-path shared-FS panel.'
    font = FONT_PT if compact else (10.5 if sharedfs else 8)
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':font,
        'axes.labelsize':font if sharedfs else 8.5, 'xtick.labelsize':font, 'ytick.labelsize':font,
        'legend.fontsize':font, 'pdf.fonttype':42, 'ps.fonttype':42,
        'axes.spines.top':False, 'axes.spines.right':False})
    fig, ax = plt.subplots(figsize=(args.width, args.height))
    fig.subplots_adjust(left=.31 if sharedfs else .24, right=.97 if sharedfs else .94,
                        bottom=.315 if sharedfs else .225, top=.755 if sharedfs else .78)
    if compact:
        # Physical bands keep 10.25 pt text readable at the final paper width.
        assert abs(args.height - HEIGHT_IN) < 1e-9
        ax.set_position(axes_rect(args.width, .64, .14))
    full_label = 'Full prefill' if one_token else 'Recompute'
    styles = [('HBM', '#0072B2', '-', 'o', 'HBM reuse'),
              ('DRAM', '#D55E00', '--', 's', 'DRAM reuse'),
              ('Recompute', '#B02532', ':', '^', full_label)]
    if sparse:
        styles = [('HBM', '#0072B2', '-', 'o', 'HBM'),
                  ('DRAM_overlap', '#009E73', '--', 'D', 'DRAM + overlap'),
                  ('DRAM_no_overlap', '#D55E00', '-.', 's', 'DRAM (serial)'),
                  ('FullPrefill', '#B02532', ':', '^', 'Full prefill')]
        if set(args.paths or meta['paths']) == {'HBM', 'DRAM_no_overlap', 'FullPrefill'}:
            styles = [('HBM', '#0072B2', '-', 'o', 'HBM reuse'),
                      ('DRAM_no_overlap', '#D55E00', '--', 's', 'DRAM reuse'),
                      ('FullPrefill', '#B02532', ':', '^', 'Full prefill')]
        if meta.get('protocol') == 'sparse_prefill_kv_fill_one_token_v3_sharedfs':
            styles = [('HBM', '#0072B2', '-', 'o', 'HBM'),
                      ('DRAM_no_overlap', '#D55E00', '--', 's', 'DRAM'),
                      ('SharedFS_no_overlap', '#7A5195', '-.', 'D', 'Shared FS'),
                      ('FullPrefill', '#B02532', ':', '^', 'Full prefill')]
    if args.paths:
        assert len(set(args.paths)) == len(args.paths)
        assert set(args.paths) <= {r['path'] for r in rows}
        styles = [s for s in styles if s[0] in args.paths]
        assert {s[0] for s in styles} == set(args.paths)
    for path, color, linestyle, marker, label in styles:
        selected = sorted((r for r in rows if r['path'] == path), key=lambda r:r['context_tokens'])
        assert [r['context_tokens'] for r in selected] == contexts
        y = [r['latency_ms']/1000 for r in selected]
        lo = [(r['latency_ms']-r['trial_min_ms'])/1000 for r in selected]
        hi = [(r['trial_max_ms']-r['latency_ms'])/1000 for r in selected]
        assert all(v > 0 for v in y)
        if any(r.get('timing_repeats_per_input', meta.get('repeats', 1)) > 1 for r in selected):
            ax.errorbar(contexts, y, yerr=[lo, hi], color=color,
                        linestyle=linestyle, marker=marker, markersize=3.5,
                        linewidth=1.3, elinewidth=.65, capsize=1.8, label=label)
        else:
            ax.plot(contexts, y, color=color, linestyle=linestyle,
                    marker=marker, markersize=3.5, linewidth=1.3, label=label)
    ax.set_xscale('log', base=2)
    ax.set_yscale('log')
    candidates = contexts if len(contexts) <= 4 else [8192,32768,131072,524288,1010000]
    ticks = [c for c in candidates if min(contexts) <= c <= max(contexts)]
    for c in [min(contexts), max(contexts)]:
        if not ticks or all(max(c,t)/min(c,t) > 1.65 for t in ticks):ticks.append(c)
    ax.xaxis.set_major_locator(FixedLocator(sorted(ticks)))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x,pos: '1.01M' if x == 1010000 else f'{x/1024:g}K'))
    ax.xaxis.set_minor_formatter(NullFormatter())
    if compact:
        # Only tick density changes: all four measured context points remain.
        ax.xaxis.set_major_locator(FixedLocator([8192, 65536, 1010000]))
    ax.yaxis.set_major_locator(LogLocator(base=10, numticks=6))
    ax.yaxis.set_minor_formatter(NullFormatter())
    if sharedfs:
        ax.yaxis.set_major_locator(FixedLocator([.1, 1, 10, 100, 1000]))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, pos: f'{y:g}'))
    if sharedfs and not compact:
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right', rotation_mode='anchor')
    ax.set_xlabel('Context (tokens)' if sharedfs else 'Total context (tokens)', labelpad=3)
    ax.set_ylabel('Prefill time (s)' if sharedfs else ('Prefill latency (s)' if one_token else 'Recovery latency (s)'), labelpad=2)
    ax.grid(axis='y',which='major',alpha=.22,linewidth=.6)
    ax.margins(x=.08,y=.14)
    if compact:
        ax.set_ylim(.06, 1000)
        ax.tick_params(which='major', length=2.5, pad=2)
        ax.minorticks_off()
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ordered_labels = ['HBM reuse', full_label, 'DRAM reuse']
    if sparse and len(styles) == 4:
        ordered_labels = ['Full prefill', 'HBM', 'DRAM (serial)', 'DRAM + overlap']
    if meta.get('protocol') == 'sparse_prefill_kv_fill_one_token_v3_sharedfs':
        ordered_labels = ['HBM', 'Shared FS', 'DRAM', 'Full prefill']
    ordered_labels = [label for label in ordered_labels if label in by_label] + [
        label for label in labels if label not in ordered_labels]
    fig.legend([by_label[label] for label in ordered_labels], ordered_labels,
               loc='upper center',bbox_to_anchor=(.5 if sharedfs else .54,.98 if compact else 1.0),
               ncol=2,frameon=False,handlelength=1.8 if sharedfs else 1.5,
               handletextpad=.35 if sharedfs else .4,columnspacing=.5 if sharedfs else .7,
               borderaxespad=0 if compact else .5,
               borderpad=.15 if compact else .4, labelspacing=.25 if compact else .5)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for ext in ['pdf','png','svg']:
        fig.savefig(args.output.with_suffix('.'+ext),dpi=240)
    plt.close(fig)
    manifest = {'data':str(args.data.resolve()),'data_sha256':hashlib.sha256(args.data.read_bytes()).hexdigest(),
                'evidence':data['evidence'],'run_complete':data['run_complete'],
                'contexts':contexts,'omitted_contexts':data['omitted_contexts'],
                'plotted_paths':[s[0] for s in styles],
                'retained_raw_paths_not_plotted':sorted({r['path'] for r in rows}-{s[0] for s in styles}),
                'width_inches':args.width,'height_inches':args.height,
                'layout':args.layout,'font_pt':font,
                'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'layout_sha256':hashlib.sha256(Path(__file__).with_name('motivation_layout.py').read_bytes()).hexdigest(),
                'error_bars':('minimum to maximum where timing repeats exceed one; not confidence intervals'),
                'metadata':meta,
                'exports_sha256':{ext:hashlib.sha256(args.output.with_suffix('.'+ext).read_bytes()).hexdigest()
                                  for ext in ['pdf','png','svg']}}
    args.output.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'output':str(args.output),'contexts':contexts}))

if __name__ == '__main__':main()
