"""Cross-model access-concentration statistics from completed native sparse-attention traces only.

Inputs (immutable trace directories written by the capture scripts):
  benchmark/AegisKV/experiments/native-sparse/20260914/traces/*          NOSA-1B      (28 layers, 2 KV heads, block 64)
  benchmark/AegisKV/experiments/native-sparse/20260915/traces/*          MiniCPM4-8B  (32 layers, 2 KV heads, block 64)
  benchmark/AegisKV/experiments/native-sparse/20260915-nosa-3b/traces/*  NOSA-3B      (32 layers, 2 KV heads, block 64; 32K only)

For every (model, document, M) the script counts, per layer and history block, how many of the first
256 or 512 subsequent queries selected the block (summed over the KV heads), then reports the fraction
of selected-block accesses covered by the hottest x% of history-KV bytes under two management units.
The 256-query window is nested within the same causal 512-query capture, not an independent GPU run:

  layer_block             one 64-token block of one layer (all KV heads)   -> 64 KiB for both models
  token_span_all_layers   one 64-token span across all layers               -> layers x 64 KiB

Both rankings are offline (frequency in the same 256/512-query window) and, for the budget table, also
online (rank taken from the previous same-length window, applied to the current one).  Also emits the
per-layer union fraction (blocks touched at least once by the 512 queries) that the design section
uses as u_l, and the needed fraction of a layer for a replay of the next n queries (n = 32..512), i.e. the
union of the blocks those queries select, which is what must be resident before the layer's replay can finish.

needed_fraction_models.csv additionally reports what an online loader that does not know the future selection
moves before the layer's replay can finish (fraction of the layer):
  gating_fraction_*            how far down a hot-first / most-recent-first order the last needed block sits
  effective_fraction_*         speculate-then-demand: preload the hottest blocks (previous 512-query rank) up to the
                               previous window's union size (or, *_matched, the previous n-query union), then fetch
                               the still-missing needed blocks on demand; effective = preloaded + missed
needed_coverage_models.csv gives, for n = 64 and 256, the share of the needed set that is resident after preloading
the hottest / most recent h fraction of the layer (h = 0, 0.05, ..., 1).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

PROJECT = Path('/home/comp/zhanzhao/MoonKVSim')
OUT = Path(__file__).resolve().parent
MODELS = {
    'NOSA-1B': dict(root=PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260914', layers=28, kv_heads=2,
                    block_bytes_layer=65536, algorithm='NOSA (InfLLM-v2 selector + trained locality gate)'),
    'MiniCPM4-8B': dict(root=PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260915', layers=32, kv_heads=2,
                        block_bytes_layer=65536, algorithm='InfLLM-v2 (compressed-key block selection)'),
}
BOOKS = ['10146', '10321', '10356']
HISTORIES = [16384, 32768]
N = 512                              # captured suffix, not the concentration window length
CONCENTRATION_QUERIES = [256, 512]
BUDGETS = [0.05, 0.10, 0.20, 0.30, 0.50]
TAILS = [32, 64, 128, 256, 512]          # replay lengths for the needed-fraction table


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def count_window(selected, start, end, history_blocks):
    x = selected[:, start:end]
    good = (x >= 0) & (x < history_blocks)
    return np.stack([np.bincount(x[g][good[g]], minlength=history_blocks) for g in range(x.shape[0])])


def curve(values):
    order = np.argsort(-values.ravel(), kind='stable')
    total = values.sum()
    return np.r_[0, np.cumsum(values.ravel()[order], dtype=np.int64)] / total, order


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extra-model', action='append', default=None, choices=['NOSA-3B', 'MiniCPM4.1-8B'],
                        help='Validated 32K captures added to the two base models (default: NOSA-3B, whose three '
                             'documents completed and passed observer validation in job 151771). Pinned NOSA-8B '
                             'cannot run 32K plus suffix unchanged.')
    parser.add_argument('--out-dir', type=Path, default=OUT,
                        help='Stage new tables separately; defaults to the existing paper data directory')
    args = parser.parse_args()
    if args.extra_model is None:
        args.extra_model = ['NOSA-3B']
    output = args.out_dir.resolve()
    models = dict(MODELS)
    for model in args.extra_model:
        root = PROJECT / 'benchmark/AegisKV/experiments/native-sparse' / f'20260915-{model.lower()}'
        env = json.loads((root / 'measured-environment.json').read_text())
        assert env['model'] == 'openbmb/' + model
        expected_revision = {'NOSA-3B': 'c5a4d505d5811f7555d786a031a4623787da7fb0',
                             'MiniCPM4.1-8B': '3a8dfed9c79a45e07dbff95bcd49d792343fa1a3'}[model]
        assert env['revision'] == expected_revision, env['revision']
        layout = env['kv_layout']
        assert layout == dict(layers=32, kv_heads=2, head_dim=128, block_tokens=64, block_bytes_layer=65536), layout
        assert env['checkpoint_weights'], 'Additional checkpoints require hashed weight provenance'
        assert env['args']['suffix'] == N and 32768 in env['args']['histories'], env['args']
        validation = json.loads((root / 'measured-observer-validation.json').read_text())
        assert validation['paired_forward_max_abs_logit_diff'] == 0
        assert len(validation['layers']) == layout['layers']
        kernel_check = ('native_mask_equals_selected_blocks' if model.startswith('NOSA-') else
                        'native_kernel_indices_equal_selected_blocks')
        assert all(row['output_finite'] and row[kernel_check]
                   for row in validation['layers']), 'Additional model observer failed validation'
        algorithm = ('NOSA (InfLLM-v2 selector + trained locality gate)' if model.startswith('NOSA-') else
                     'InfLLM-v2 (compressed-key block selection)')
        models[model] = dict(root=root, layers=layout['layers'], kv_heads=layout['kv_heads'],
                             block_bytes_layer=layout['block_bytes_layer'],
                             algorithm=algorithm, histories=[32768])
    curve_rows, budget_rows, layer_rows, needed_rows, coverage_rows, summary = [], [], [], [], [], {}
    grid = np.linspace(0, 1, 401)
    for model, spec in models.items():
        for m in spec.get('histories', HISTORIES):
            for book in BOOKS:
                directory = spec['root'] / 'traces' / f'pg19-{book}-M{m}-N{N}'
                run = json.loads((directory / 'run.json').read_text())
                assert run['status'] == 'complete' and run['logits_finite'], directory
                environment = json.loads((spec['root'] / run['environment_file']).read_text())
                assert environment['model'] == 'openbmb/' + model, directory
                assert run.get('model', environment['model']) == environment['model'], directory
                assert (run['M'], run['N']) == (m, N), directory
                assert sorted(row['layer_zero_based'] for row in run['layers']) == list(range(spec['layers'])), directory
                assert len(run['layers']) == spec['layers'], (model, len(run['layers']))
                b = m // 64
                current = {q: [] for q in CONCENTRATION_QUERIES}
                previous = {q: [] for q in CONCENTRATION_QUERIES}
                for row in run['layers']:
                    if model in args.extra_model:
                        key = ('native_mask_equals_selected_blocks' if model.startswith('NOSA-') else
                               'native_kernel_indices_equal_selected_blocks')
                        assert row['output_finite'] and row['causal_and_unique'] and row[key], (directory, row)
                    path = spec['root'] / row['trace_file']
                    assert sha(path) == row['trace_sha256'], path
                    with np.load(path) as f:
                        selected = f['selected_blocks'].astype(np.int32)
                    assert selected.shape[0] == spec['kv_heads'], selected.shape
                    counts = count_window(selected, m, m + N, b)
                    assert counts.sum() == row['cached_history_selections_in_suffix'], (path, counts.sum())
                    for q in CONCENTRATION_QUERIES:
                        assert 0 < q <= N
                        current[q].append(count_window(selected, m, m + q, b).sum(axis=0))
                        previous[q].append(count_window(selected, m - q, m, b).sum(axis=0))
                    prev_counts = previous[N][-1]
                    # Online load orders a recovery loader can use without knowing the future: hottest block of the
                    # previous 512-query window first (ties: most recent first), or plain most-recent-first.
                    hot_order = np.lexsort((-np.arange(b), -prev_counts))         # primary: count desc, secondary: newest first
                    rec_order = np.arange(b)[::-1]                                # newest block first
                    hot_rank = np.empty(b, dtype=np.int64)
                    hot_rank[hot_order] = np.arange(b)
                    rec_rank = np.empty(b, dtype=np.int64)
                    rec_rank[rec_order] = np.arange(b)
                    prev_union = float(np.count_nonzero(prev_counts) / b)          # what the loader knows online: h = u_prev
                    for n_tail in TAILS:                                # blocks a replay of the next n_tail queries touches
                        needed = count_window(selected, m, m + n_tail, b).sum(axis=0) > 0
                        # gating fraction: how far down an online order the loader must get before every needed block
                        # of this layer is resident (= bytes that must arrive before the layer's replay can finish)
                        gate_hot = float((hot_rank[needed].max() + 1) / b) if needed.any() else 0.0
                        gate_rec = float((rec_rank[needed].max() + 1) / b) if needed.any() else 0.0
                        # speculate-then-demand: preload the hottest h = u_prev fraction (previous-window order), then fetch
                        # the needed blocks that are still missing on demand.  Path bytes before this layer's replay can
                        # finish = preloaded + missed; recorded as a fraction of the layer (effective needed fraction).
                        k_pre = int(round(prev_union * b))
                        pre_hot = hot_rank < k_pre
                        pre_rec = rec_rank < k_pre
                        miss_hot = float(np.count_nonzero(needed & ~pre_hot) / b)
                        miss_rec = float(np.count_nonzero(needed & ~pre_rec) / b)
                        # matched estimator: preload as many blocks as the previous n_tail queries touched (known online)
                        prev_union_n = float(np.count_nonzero(count_window(selected, m - n_tail, m, b).sum(axis=0)) / b)
                        k_match = int(round(prev_union_n * b))
                        miss_match = float(np.count_nonzero(needed & ~(hot_rank < k_match)) / b)
                        needed_rows.append(dict(model=model, book_id=book, M=m, replay_queries=n_tail,
                                                layer=row['layer_zero_based'] + 1, needed_fraction=float(needed.mean()),
                                                gating_fraction_hot_first=gate_hot, gating_fraction_recency_first=gate_rec,
                                                preload_fraction=k_pre / b,
                                                effective_fraction_hot_first=k_pre / b + miss_hot,
                                                effective_fraction_recency_first=k_pre / b + miss_rec,
                                                preload_fraction_matched=k_match / b,
                                                effective_fraction_hot_first_matched=k_match / b + miss_match))
                        if n_tail in (64, 256):                         # coverage of the needed set vs. preloaded fraction
                            n_need = int(needed.sum())
                            for h in np.linspace(0, 1, 21):
                                k = int(round(h * b))
                                coverage_rows.append(dict(model=model, book_id=book, M=m, replay_queries=n_tail,
                                                          layer=row['layer_zero_based'] + 1, preloaded_fraction=float(h),
                                                          needed_covered_hot_first=float(np.count_nonzero(needed & (hot_rank < k)) / max(n_need, 1)),
                                                          needed_covered_recency_first=float(np.count_nonzero(needed & (rec_rank < k)) / max(n_need, 1))))
                    layer_rows.append(dict(model=model, book_id=book, M=m, layer=row['layer_zero_based'] + 1,
                                           union_fraction=float(np.count_nonzero(counts.sum(axis=0)) / b),
                                           top20_coverage=float(curve(counts.sum(axis=0))[0][int(0.2 * b)])))
                for q in CONCENTRATION_QUERIES:
                    cur_window, prev_window = np.stack(current[q]), np.stack(previous[q])
                    units = {
                        'layer_block': (cur_window, prev_window, spec['block_bytes_layer']),
                        'token_span_all_layers': (cur_window.sum(axis=0), prev_window.sum(axis=0),
                                                  spec['layers'] * spec['block_bytes_layer']),
                    }
                    stats = dict(model=model, book_id=book, M=m, N=q, captured_suffix_queries=N,
                                 query_window_zero_based_half_open=[m, m + q], layers=spec['layers'],
                                 run_file=str((directory / 'run.json').relative_to(PROJECT)),
                                 run_sha256=sha(directory / 'run.json'),
                                 history_kv_bytes=int(spec['layers'] * b * spec['block_bytes_layer']),
                                 access_events=int(cur_window.sum()), granularities={})
                    for name, (cur, prev, unit_bytes) in units.items():
                        cdf, order = curve(cur)
                        assert np.isclose(cdf[0], 0) and np.isclose(cdf[-1], 1)
                        assert np.all(np.diff(cdf) >= 0)
                        xs = np.arange(len(cdf)) / (len(cdf) - 1)
                        for xx, yy in zip(grid, np.interp(grid, xs, cdf)):
                            curve_rows.append(dict(model=model, book_id=book, M=m, N=q, granularity=name,
                                                   byte_fraction=float(xx), access_coverage=float(yy)))
                        _, old_order = curve(prev)
                        flat, total = cur.ravel(), cur.sum()
                        entry = dict(units=int(flat.size), unit_bytes=int(unit_bytes),
                                     accessed_unit_fraction=float(np.count_nonzero(flat) / flat.size), budgets={})
                        for frac in BUDGETS:
                            k = int(np.floor(frac * flat.size))
                            rec = dict(units=k, bytes=int(k * unit_bytes), actual_byte_fraction=k / flat.size,
                                       offline_access_coverage=float(cdf[k]),
                                       past_window_rank_access_coverage=float(flat[old_order[:k]].sum() / total))
                            entry['budgets'][str(frac)] = rec
                            budget_rows.append(dict(model=model, book_id=book, M=m, N=q, granularity=name,
                                                    nominal_budget_fraction=frac, **rec))
                        for target in (0.8, 0.9):
                            entry[f'byte_fraction_for_{int(target * 100)}_percent'] = float(np.searchsorted(cdf, target) / flat.size)
                        stats['granularities'][name] = entry
                    # Preserve the old 512-query keys for consumers; new windows are explicit.
                    key = f'{model}/{book}/M{m}' + (f'/N{q}' if q != N else '')
                    summary[key] = stats
                    lb, ts = stats['granularities']['layer_block'], stats['granularities']['token_span_all_layers']
                    print(model, book, m, f'N{q}', 'layer_block top20', round(lb['budgets']['0.2']['offline_access_coverage'], 4),
                          'online', round(lb['budgets']['0.2']['past_window_rank_access_coverage'], 4),
                          'token_span top20', round(ts['budgets']['0.2']['offline_access_coverage'], 4),
                          'union(layer_block)', round(lb['accessed_unit_fraction'], 4), flush=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'SUMMARY_MODELS.json').write_text(json.dumps(dict(
        models={k: dict(algorithm=v['algorithm'], layers=v['layers'], kv_heads=v['kv_heads'],
                        histories=v.get('histories', HISTORIES)) for k, v in models.items()},
        documents=BOOKS, histories=HISTORIES, suffix_queries=N, concentration_queries=CONCENTRATION_QUERIES,
        repeat_count_per_input_length=1,
        window_dependency='256-query observations are nested in the same 512-query causal capture; not independent runs',
        observation='native selected-block events of the first 256/512 queries after the history; offline and matched previous-window ranks',
        results=summary), indent=2) + '\n')
    for name, rows in [('concentration_curves_models.csv', curve_rows), ('budget_coverage_models.csv', budget_rows),
                       ('per_layer_union_models.csv', layer_rows), ('needed_fraction_models.csv', needed_rows),
                       ('needed_coverage_models.csv', coverage_rows)]:
        with (output / name).open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print('WROTE', output)


if __name__ == '__main__':
    main()
