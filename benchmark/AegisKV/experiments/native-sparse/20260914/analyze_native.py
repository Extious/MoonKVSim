"""Recompute all statistics from completed native-model traces only."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
BUDGETS = [0.05, 0.10, 0.20, 0.25, 0.50]


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def count_window(selected, start, end, history_blocks, remote_only=False):
    x = selected[:, start:end]
    good = (x >= 0) & (x < history_blocks)
    if remote_only:
        qblock = np.arange(start, end)[None, :, None] // 64
        forced = (x < 1) | ((x <= qblock) & (qblock <= x + 16))
        good &= ~forced
    return np.stack([np.bincount(x[g][good[g]], minlength=history_blocks) for g in range(2)])


def order_by_value(values):
    # Deterministic original-address tie breaking, fixed before observing outcomes.
    return np.argsort(-values.ravel(), kind='stable')


def granularity_summary(current, past, bytes_per_unit):
    values, previous = current.ravel(), past.ravel()
    order = order_by_value(values)
    old_order = order_by_value(previous)
    total = int(values.sum())
    cdf = np.r_[0, np.cumsum(values[order], dtype=np.int64)] / total
    result = {'units': len(values), 'unit_bytes': bytes_per_unit,
              'total_main_kv_bytes': int(len(values) * bytes_per_unit),
              'access_events': total, 'accessed_units': int(np.count_nonzero(values)),
              'accessed_unit_fraction': float(np.count_nonzero(values) / len(values)),
              'budgets': {}, 'coverage_targets': {}}
    for frac in BUDGETS:
        k = int(np.floor(frac * len(values)))
        result['budgets'][str(frac)] = {
            'units': k, 'bytes': int(k * bytes_per_unit),
            'actual_byte_fraction': k / len(values),
            'offline_access_coverage': float(cdf[k]),
            'past_window_rank_access_coverage': float(values[old_order[:k]].sum() / total),
            'uniform_random_expected_coverage': k / len(values),
        }
    for target in [0.8, 0.9, 0.95]:
        k = int(np.searchsorted(cdf, target))
        result['coverage_targets'][str(target)] = {
            'units': k, 'bytes': int(k * bytes_per_unit), 'byte_fraction': k / len(values)}
    return result


def main():
    plan = json.loads((OUT / 'PLAN.json').read_text())
    results, csv_rows, layer_rows = [], [], []
    for m in plan['histories_M']:
        for book in plan['book_ids']:
            n = plan['suffix_N']
            directory = OUT / 'traces' / f'pg19-{book}-M{m}-N{n}'
            run = json.loads((directory / 'run.json').read_text())
            assert run['status'] == 'complete' and run['logits_finite']
            assert len(run['layers']) == 28
            b = m // 64
            current, previous, remote = [], [], []
            for row in run['layers']:
                path = OUT / row['trace_file']
                assert sha(path) == row['trace_sha256']
                assert row['native_mask_equals_selected_blocks'] and row['output_finite']
                with np.load(path) as f:
                    selected = f['selected_blocks'].astype(np.int32)
                counts = count_window(selected, m, m+n, b)
                prior = count_window(selected, m-n, m, b)
                distant = count_window(selected, m, m+n, b, remote_only=True)
                assert counts.max() <= n
                assert counts.sum() == row['cached_history_selections_in_suffix']
                current.append(counts)
                previous.append(prior)
                remote.append(distant)
                layer = row['layer_zero_based'] + 1
                layer_stats = granularity_summary(counts.sum(axis=0), prior.sum(axis=0), 65536)
                layer_rows.append({'book_id': book, 'M': m, 'layer': layer,
                                   'coverage_top_10_percent': layer_stats['budgets']['0.1']['offline_access_coverage'],
                                   'coverage_top_20_percent': layer_stats['budgets']['0.2']['offline_access_coverage'],
                                   'fraction_bytes_for_80_percent': layer_stats['coverage_targets']['0.8']['byte_fraction'],
                                   'union_fraction': layer_stats['accessed_unit_fraction']})
            current, previous, remote = map(np.stack, [current, previous, remote])
            np.savez_compressed(directory / 'counts.npz', current=current,
                                previous=previous, nonlocal_counts=remote)
            stats = {
                'book_id': book, 'M': m, 'N': n,
                'counts_shape': list(current.shape),
                'main_history_kv_bytes': int(28 * 2 * b * 32768),
                'query_kv_group_events': int(current.sum()),
                'nonlocal_event_fraction': float(remote.sum() / current.sum()),
                'granularities': {},
            }
            groups = [
                ('layer_group_block', current, previous, 32768),
                ('layer_block', current.sum(axis=1), previous.sum(axis=1), 65536),
                ('token_span_all_layers', current.sum(axis=(0, 1)), previous.sum(axis=(0, 1)), 28*65536),
            ]
            for name, c, p, unit_bytes in groups:
                summary = granularity_summary(c, p, unit_bytes)
                stats['granularities'][name] = summary
                for budget, values in summary['budgets'].items():
                    csv_rows.append({'book_id': book, 'M': m, 'N': n,
                                     'granularity': name, 'nominal_budget_fraction': budget, **values})
            stats['nonlocal_layer_block'] = granularity_summary(
                remote.sum(axis=1), previous.sum(axis=1), 65536)
            # Descriptive layer differences; 28 layers are not 28 independent requests.
            x = current.sum(axis=1)
            per_layer_cover = []
            for layer in range(28):
                order = order_by_value(x[layer])
                k = int(0.2 * b)
                per_layer_cover.append(float(x[layer][order[:k]].sum() / x[layer].sum()))
            stats['per_layer_top_20_percent_coverage'] = per_layer_cover
            result_path = directory / 'statistics.json'
            result_path.write_text(json.dumps(stats, indent=2) + '\n')
            results.append(stats)
            layer_chunk = stats['granularities']['layer_block']
            token_span = stats['granularities']['token_span_all_layers']
            print(book, m, 'layerblock10/20',
                  *[round(layer_chunk['budgets'][f]['offline_access_coverage'], 4) for f in ['0.1', '0.2']],
                  'token-span20', round(token_span['budgets']['0.2']['offline_access_coverage'], 4),
                  'nonlocal_fraction', round(stats['nonlocal_event_fraction'], 4))
    summary = {'independent_documents': 3, 'completed_input_length_runs': len(results),
               'repeat_count_per_input_length': 1,
               'observation': 'native main-KV selected-block events; no latency measurements',
               'results': results}
    (OUT / 'SUMMARY.json').write_text(json.dumps(summary, indent=2) + '\n')
    for name, rows in [('budget_coverage.csv', csv_rows), ('per_layer_statistics.csv', layer_rows)]:
        with (OUT / name).open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == '__main__':
    main()
