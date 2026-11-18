"""Audited layer-level, same-window concentration from native sparse traces."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import numpy as np

ROOT = Path('/home/comp/zhanzhao/MoonKVSim')
BASE = ROOT / 'benchmark/AegisKV/experiments/native-sparse'
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'benchmark/AegisKV/experiments/data/kv-access-concentration-three-models-20260921'
M, B, BLOCKS = 32256, 64, 504
BOOKS = ('10146', '10321', '10356')
WINDOWS = (256, 512)
BUDGETS = {'10': 51, '20': 101, '40': 202}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def csv_out(path, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def statistics(v):
    return dict(mean=float(np.mean(v)), min=float(np.min(v)), max=float(np.max(v)))


def incidence_and_events(selected, n):
    selected = selected[:, M:M+n].astype(np.int32)
    assert selected.shape[:2] == (2, n)
    assert np.all((selected < 0) | (selected <= (M + np.arange(n))[None, :, None] // B))
    sorted_ids = np.sort(np.where(selected < 0, 2**30, selected), axis=-1)
    assert not np.any((np.diff(sorted_ids, axis=-1) == 0) & (sorted_ids[:, :, 1:] < 2**30))
    good = (selected >= 0) & (selected < BLOCKS)
    query = np.broadcast_to(np.arange(n)[None, :, None], selected.shape)
    incidence = np.zeros((n, BLOCKS), dtype=bool)
    incidence[query[good], selected[good]] = True
    merged = incidence.sum(axis=0, dtype=np.int64)
    event = np.bincount(selected[good], minlength=BLOCKS)
    # Independent set-per-query reference, including cross-head deduplication.
    check = np.zeros(BLOCKS, dtype=np.int64)
    for q in range(n):
        ids = selected[:, q].ravel()
        check[np.unique(ids[(ids >= 0) & (ids < BLOCKS)])] += 1
    assert np.array_equal(check, merged)
    assert np.all(merged <= n) and np.all(merged <= event)
    assert np.array_equal(merged > 0, event > 0)
    return merged, event


def cumulative(counts):
    result = np.r_[0, np.cumsum(np.sort(counts)[::-1], dtype=np.int64)]
    assert result[-1] > 0 and result.shape == (BLOCKS + 1,)
    assert np.all(np.diff(result) >= 0)
    assert np.all(result / result[-1] + 1e-12 >= np.arange(BLOCKS + 1) / BLOCKS)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--nsa-dir', type=Path, required=True)
    args = parser.parse_args()
    models = {
        'NOSA-3B': BASE / '20260915-nosa-3b',
        'NSA-8B': args.nsa_dir.resolve(),
        'MiniCPM4.1-8B': HERE / 'minicpm41',
    }
    protocol = json.loads((HERE / 'protocol.json').read_text())
    assert protocol['history_tokens'] == M and protocol['historical_blocks_per_layer'] == BLOCKS
    OUT.mkdir(parents=True, exist_ok=True)
    sources, counts_archive = {}, {}
    layer_rows, doc_rows, curve_rows, summaries, metadata = [], [], [], [], {}
    mask_checks = 0

    def read(path):
        raw = path.read_bytes()
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    for model, folder in models.items():
        env = read(folder / 'measured-environment.json')
        validation = read(folder / 'measured-observer-validation.json')
        assert validation['paired_forward_max_abs_logit_diff'] == 0
        cfg = env['native_layer_config']
        assert cfg['block_size'] == B
        assert env['kv_layout'] == dict(layers=32, kv_heads=2, head_dim=128,
                                        block_tokens=64, block_bytes_layer=65536)
        metadata[model] = dict(revision=env['revision'], gpu_job=env['slurm_job_id'],
                               capture_folder=str(folder), native_config=cfg,
                               kv_layout=env['kv_layout'], gpu=env['gpu'])
        doc_curves = {}
        for book in BOOKS:
            capture_m = 32768 if model == 'NOSA-3B' else M
            run_dir = folder / 'traces' / f'pg19-{book}-M{capture_m}-N512'
            run = read(run_dir / 'run.json')
            assert run['status'] == 'complete' and run['logits_finite']
            assert run['M'] == capture_m and run['N'] == 512
            assert sorted(r['layer_zero_based'] for r in run['layers']) == list(range(32))
            input_path = run_dir / 'input_ids.npy'
            assert sha(input_path) == run['input_ids_sha256']
            sources[str(input_path.relative_to(ROOT))] = sha(input_path)
            per_window = {(n, metric): [] for n in WINDOWS for metric in ('query_block', 'selector_event')}
            for record in run['layers']:
                path = folder / record['trace_file']
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                assert digest == record['trace_sha256']
                sources[str(path.relative_to(ROOT))] = digest
                assert record['causal_and_unique'] and record['output_finite']
                with np.load(io.BytesIO(raw)) as archive:
                    selected = archive['selected_blocks']
                assert list(selected.shape) == record['selection_shape']
                assert selected.shape == (2, capture_m + 512, cfg['topk'])
                layer = record['layer_zero_based'] + 1
                if model == 'NOSA-3B':
                    assert record['native_mask_equals_selected_blocks']
                    lo, hi = record['native_mask_checked_query_range']
                    assert lo <= M and hi >= M + 512
                    # Independently reconstruct the actual packed kernel mask for the crop.
                    mask_path = run_dir / f'layer-{layer:02d}-mask.npz'
                    sources[str(mask_path.relative_to(ROOT))] = sha(mask_path)
                    with np.load(mask_path) as archive:
                        offset = int(archive['query_start'])
                        actual = archive['packed_mask'][:, M-offset:M+512-offset]
                    idx = selected[:, M:M+512]
                    expected = np.zeros_like(actual)
                    head, query, rank = np.nonzero(idx >= 0)
                    block = idx[head, query, rank].astype(np.int64)
                    np.bitwise_or.at(expected, (head, query, block // 64),
                                     np.left_shift(np.uint64(1), (block % 64).astype(np.uint64)))
                    assert np.array_equal(actual, expected)
                    mask_checks += 1
                else:
                    assert record['native_kernel_indices_equal_selected_blocks']
                    assert record['native_sparse_calls'] == record['select_calls'] == 1
                if model == 'NSA-8B':
                    assert record['compressed_branch_executed'] and record['compressed_output_finite']
                    assert record['compressed_key_shape'] == [2047, 2, 128]
                    assert record['compressed_value_shape'] == [2047, 2, 128]
                    metadata[model]['compressed_kv_bytes_full_sequence_per_layer'] = record['compressed_kv_bytes_full_sequence']
                    metadata[model]['compressed_prefix_vectors'] = (M - cfg['kernel_size']) // cfg['kernel_stride'] + 1
                    metadata[model]['compressed_prefix_bytes_per_layer'] = ((M - cfg['kernel_size']) // cfg['kernel_stride'] + 1) * 2 * 2 * 128 * 2
                for n in WINDOWS:
                    merged, events = incidence_and_events(selected, n)
                    if n == 512 and capture_m == M:
                        assert events.sum() == record['cached_history_selections_in_suffix']
                    for metric, counts in (('query_block', merged), ('selector_event', events)):
                        key = f'{model}_{book}_l{layer}_n{n}_{metric}'
                        counts_archive[key] = counts.astype(np.int32)
                        cs = cumulative(counts)
                        share = cs / cs[-1]
                        per_window[n, metric].append(cs)
                        layer_rows.append(dict(model=model, book_id=book, layer=layer,
                            window_queries=n, metric=metric, counts_key=key,
                            references=int(cs[-1]), mean_references_per_query=float(cs[-1]/n),
                            distinct_blocks=int(np.count_nonzero(counts)),
                            blocks_for_80pct=int(np.searchsorted(share, .8)),
                            blocks_for_90pct=int(np.searchsorted(share, .9)),
                            **{f'top{label}_share': float(share[k]) for label, k in BUDGETS.items()}))
            for (n, metric), vals in per_window.items():
                cs = np.stack(vals)
                assert cs.shape == (32, BLOCKS + 1)
                macro = (cs / cs[:, -1:]).mean(axis=0)
                weighted = cs.sum(axis=0) / cs[:, -1].sum()
                doc_curves[book, n, metric] = (macro, weighted)
                doc_rows.append(dict(model=model, book_id=book, window_queries=n, metric=metric,
                    **{f'top{label}_macro': float(macro[k]) for label, k in BUDGETS.items()},
                    **{f'top{label}_weighted': float(weighted[k]) for label, k in BUDGETS.items()}))
            print('ANALYZED', model, book, flush=True)
        for n in WINDOWS:
            for metric in ('query_block', 'selector_event'):
                curves = np.stack([doc_curves[book, n, metric][0] for book in BOOKS])
                weighted = np.stack([doc_curves[book, n, metric][1] for book in BOOKS])
                for k in range(BLOCKS + 1):
                    curve_rows.append(dict(model=model, window_queries=n, metric=metric, K=k,
                        block_fraction=k / BLOCKS, **statistics(curves[:, k]),
                        weighted_mean=float(weighted[:, k].mean())))
                rows = [r for r in layer_rows if r['model'] == model and r['window_queries'] == n and r['metric'] == metric]
                summaries.append(dict(model=model, window_queries=n, metric=metric,
                    **{f'top{label}': statistics(curves[:, k]) for label, k in BUDGETS.items()},
                    K_for_90pct_on_mean_curve=int(np.searchsorted(curves.mean(axis=0), .9)),
                    mean_fraction_for_90pct=float(np.mean([r['blocks_for_90pct'] / BLOCKS for r in rows])),
                    mean_distinct_fraction=float(np.mean([r['distinct_blocks'] / BLOCKS for r in rows])),
                    mean_references_per_query=float(np.mean([r['mean_references_per_query'] for r in rows])),
                    layers_mean_top20_at_least_80pct=int(sum(np.mean([r['top20_share'] for r in rows if r['layer'] == l]) >= .8 for l in range(1,33)))))
    write_json(OUT / 'protocol.json', protocol)
    csv_out(OUT / 'layers.csv', layer_rows)
    csv_out(OUT / 'documents.csv', doc_rows)
    csv_out(OUT / 'curves.csv', curve_rows)
    np.savez_compressed(OUT / 'counts.npz', **counts_archive)
    write_json(OUT / 'summary.json', summaries)
    write_json(OUT / 'model-provenance.json', metadata)
    sources[str(Path(__file__).resolve().relative_to(ROOT))] = sha(__file__)
    sources[str((HERE / 'protocol.json').relative_to(ROOT))] = sha(HERE / 'protocol.json')
    write_json(OUT / 'source-sha256.json', sources)
    write_json(OUT / 'analysis-checks.json', dict(
        documents_per_model=3, layers_per_model=32, source_traces=288,
        crop_native_mask_rechecks=mask_checks, per_query_set_count_checks=576,
        observed_new_forwards=6, reused_causal_forwards=3,
        rows=len(layer_rows), curves=len(curve_rows), counts_vectors=len(counts_archive),
        all_observer_logit_differences_zero=True, all_native_index_identity_checks=True))
    for row in summaries:
        if row['metric'] == 'query_block':
            print(json.dumps(row))


if __name__ == '__main__':
    main()
