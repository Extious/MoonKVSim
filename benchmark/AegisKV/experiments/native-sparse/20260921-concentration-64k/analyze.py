"""64K / 512-Query native access concentration, layer blocks across all heads.

Same-window frequency ranking is an oracle description of access concentration,
not a prefetch predictor. Each Query contributes at most once to a layer block.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import numpy as np

ROOT = Path('/home/comp/zhanzhao/MoonKVSim')
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'benchmark/AegisKV/experiments/data/kv-access-concentration-64k-20260921'
M, N, B, BLOCKS = 65024, 512, 64, 1016
BOOKS = ('10321', '10356', '10762')
BUDGETS = {'10': 102, '20': 204, '40': 407}


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def csv_out(path, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def selected_counts(selected):
    selected = selected[:, M:M+N].astype(np.int32)
    assert selected.shape[:2] == (2, N)
    assert np.all((selected < 0) | (selected <= (M + np.arange(N))[None, :, None] // B))
    sorted_ids = np.sort(np.where(selected < 0, 2**30, selected), axis=-1)
    assert not np.any((np.diff(sorted_ids, axis=-1) == 0) & (sorted_ids[:, :, 1:] < 2**30))
    good = (selected >= 0) & (selected < BLOCKS)
    query = np.broadcast_to(np.arange(N)[None, :, None], selected.shape)
    incidence = np.zeros((N, BLOCKS), dtype=bool)
    incidence[query[good], selected[good]] = True
    counts = incidence.sum(axis=0, dtype=np.int64)
    check = np.zeros(BLOCKS, dtype=np.int64)
    for q in range(N):
        ids = selected[:, q].ravel()
        check[np.unique(ids[(ids >= 0) & (ids < BLOCKS)])] += 1
    assert np.array_equal(counts, check)
    return counts, int(good.sum())


def qwen_counts(arrays):
    # Actual native packed ranges may be unaligned to physical 64-token blocks.
    # Each historical key is earlier than every Query in the observed tile.
    incidence = np.zeros((N // B, BLOCKS), dtype=bool)
    independent = [set() for _ in range(N // B)]
    for h in range(28):
        bc, bo, cc, ci = [arrays[f'h{h:02d}_{k}'] for k in ('bc', 'bo', 'cc', 'ci')]
        assert bc.shape == cc.shape == (8,)
        assert bo.shape[0] == ci.shape[0] == 8
        for tile in range(8):
            assert 0 <= bc[tile] <= bo.shape[1] and 0 <= cc[tile] <= ci.shape[1]
            starts = bo[tile, :int(bc[tile])].astype(np.int64)
            cols = ci[tile, :int(cc[tile])].astype(np.int64)
            assert np.all((starts >= 0) & (starts < M+(tile+1)*B))
            assert np.all((cols >= 0) & (cols < M+tile*B))
            for start in starts:
                stop = min(int(start)+B, M)
                if start < stop:
                    incidence[tile, start//B:(stop-1)//B+1] = True
                    # Independent token enumeration, not the interval formula.
                    independent[tile].update(token//B for token in range(int(start), stop))
            cols = cols[cols < M]
            incidence[tile, cols//B] = True
            independent[tile].update(int(token)//B for token in cols)
    for tile, ref in enumerate(independent):
        assert ref == set(np.flatnonzero(incidence[tile]))
    return incidence.sum(axis=0, dtype=np.int64) * B


def curve(counts):
    assert counts.shape == (BLOCKS,) and np.all((0 <= counts) & (counts <= N))
    cs = np.r_[0, np.cumsum(np.sort(counts)[::-1], dtype=np.int64)]
    assert cs[-1] > 0
    result = cs / cs[-1]
    assert np.all(np.diff(result) >= 0)
    assert np.all(result + 1e-12 >= np.arange(BLOCKS+1)/BLOCKS)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--qwen-dir', type=Path, required=True)
    args = parser.parse_args()
    models = {'NOSA-8B': HERE/'nosa8b-153960', 'NSA-8B': HERE/'nsa8b-153963',
              'MiniCPM4.1-8B': HERE/'minicpm41-153961',
              'Qwen2.5-7B-Instruct-1M': args.qwen_dir.resolve()}
    OUT.mkdir(parents=True, exist_ok=True)
    sources, metadata, count_archive, matched_ids = {}, {}, {}, {}
    layers, docs, curves, summary, input_checks = [], [], [], [], []
    checks = dict(nosa_packed_masks=0, native_layer_records=0, qwen_packed_layers=0,
                  independent_layer_count_checks=0, topk_sum_checks=0)

    def read(path):
        raw = path.read_bytes()
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    protocol = read(HERE/'protocol.json')
    assert protocol['total_tokens'] == M+N and protocol['historical_blocks_per_layer'] == BLOCKS
    for model, folder in models.items():
        qwen = model.startswith('Qwen')
        env = read(folder/'measured-environment.json')
        validation = read(folder/'measured-observer-validation.json')
        assert validation['paired_forward_max_abs_logit_diff'] == 0
        nlayers = env['kv_layout']['layers']
        assert nlayers == (28 if qwen else 32)
        assert env['kv_layout']['block_tokens'] == B
        assert env['capture_sha256' if qwen else 'script_sha256'] == sha(HERE/('capture_qwen.py' if qwen else
                                                'capture_nosa8b.py' if model=='NOSA-8B' else
                                                'capture_nsa.py' if model=='NSA-8B' else 'capture_minicpm41_dual.py'))
        metadata[model] = dict(capture_folder=str(folder), environment=env,
            validation={k:v for k,v in validation.items() if k!='layers'})
        model_curves = []
        for book in BOOKS:
            run_dir = folder/'traces'/f'pg19-{book}-M{M}-N{N}'
            run = read(run_dir/'run.json')
            assert run['status'] == 'complete' and run['logits_finite']
            assert (run['M'], run['N']) == (M,N)
            assert sorted(r['layer_zero_based'] for r in run['layers']) == list(range(nlayers))
            ids_path = run_dir/'input_ids.npy'
            assert sha(ids_path) == run['input_ids_sha256']
            assert sha(HERE/'texts'/f'{book}.txt') == run['input_text_sha256']
            sources[str(ids_path.relative_to(ROOT))] = sha(ids_path)
            ids = np.load(ids_path).reshape(-1)
            assert len(ids) == M+N
            if book not in matched_ids:
                matched_ids[book] = ids.copy()
            same = np.array_equal(ids, matched_ids[book])
            if not qwen:
                assert same
            input_checks.append(dict(model=model,book_id=book,tokens=len(ids),same_ids_as_nosa=bool(same)))
            doc_curves = []
            for rec in run['layers']:
                path = folder/rec['trace_file']
                raw = path.read_bytes()
                assert hashlib.sha256(raw).hexdigest() == rec['trace_sha256']
                sources[str(path.relative_to(ROOT))] = rec['trace_sha256']
                assert rec['output_finite']
                layer = rec['layer_zero_based'] + 1
                with np.load(io.BytesIO(raw)) as archive:
                    if qwen:
                        assert rec['native_sparse_calls'] == 28 and rec['native_packed_indices_observed']
                        counts = qwen_counts(archive)
                        checks['qwen_packed_layers'] += 1
                    else:
                        selected = archive['selected_blocks']
                        assert list(selected.shape) == rec['selection_shape']
                        assert selected.shape == (2, M+N, env['native_layer_config']['topk'])
                        assert rec['causal_and_unique']
                        counts, events = selected_counts(selected)
                        assert events == rec['cached_history_selections_in_suffix']
                if model == 'NOSA-8B':
                    assert rec['native_mask_equals_selected_blocks']
                    mp = run_dir/f'layer-{layer:02d}-mask.npz'
                    sources[str(mp.relative_to(ROOT))] = sha(mp)
                    with np.load(mp) as packed:
                        offset = int(packed['query_start'])
                        actual = packed['packed_mask'][:, M-offset:M+N-offset]
                    idx = selected[:, M:M+N]
                    expected = np.zeros_like(actual)
                    h,q,r = np.nonzero(idx >= 0)
                    block = idx[h,q,r].astype(np.int64)
                    np.bitwise_or.at(expected,(h,q,block//64),np.left_shift(np.uint64(1),(block%64).astype(np.uint64)))
                    assert np.array_equal(expected, actual)
                    checks['nosa_packed_masks'] += 1
                elif not qwen:
                    assert rec['native_kernel_indices_equal_selected_blocks']
                    assert rec['native_sparse_calls'] == rec['select_calls'] == 1
                if model == 'NSA-8B':
                    assert rec['compressed_branch_executed'] and rec['compressed_output_finite']
                    assert rec['compressed_key_shape'] == rec['compressed_value_shape'] == [4095,2,128]
                    metadata[model]['compressed_prefix_vectors'] = 4063
                    metadata[model]['compressed_prefix_bytes_per_layer'] = 4063*1024
                cs = curve(counts)
                key = f'{model}_{book}_l{layer:02d}'
                count_archive[key] = counts.astype(np.int32)
                row = dict(model=model,book_id=book,layer=layer,counts_key=key,
                    query_block_references=int(counts.sum()),mean_blocks_per_query=float(counts.sum()/N),
                    distinct_blocks=int(np.count_nonzero(counts)),k90=int(np.searchsorted(cs,.9)),
                    k90_fraction=float(np.searchsorted(cs,.9)/BLOCKS))
                for pct,k in BUDGETS.items():
                    row[f'top{pct}'] = float(cs[k])
                    # Independent partition-based top-K sum.
                    assert np.isclose(cs[k],np.partition(counts,-k)[-k:].sum()/counts.sum(),rtol=0,atol=1e-12)
                    checks['topk_sum_checks'] += 1
                layers.append(row)
                doc_curves.append(cs)
                checks['native_layer_records'] += 1
                checks['independent_layer_count_checks'] += 1
            avg = np.mean(doc_curves,axis=0)
            model_curves.append(avg)
            docs.append(dict(model=model,book_id=book,layers=nlayers,
                **{f'top{pct}':float(avg[k]) for pct,k in BUDGETS.items()},
                k90_for_mean_curve=int(np.searchsorted(avg,.9))))
        model_curves = np.asarray(model_curves)
        avg, low, high = np.mean(model_curves,axis=0),np.min(model_curves,axis=0),np.max(model_curves,axis=0)
        for k in range(BLOCKS+1):
            curves.append(dict(model=model,k=k,stored_fraction=k/BLOCKS,
                               coverage_mean=float(avg[k]),coverage_min=float(low[k]),coverage_max=float(high[k])))
        summary.append(dict(model=model,layers=nlayers,documents=3,
            **{f'top{pct}_{s}':float(fn(model_curves[:,k]))
               for pct,k in BUDGETS.items() for s,fn in [('mean',np.mean),('min',np.min),('max',np.max)]},
            k90_for_mean_curve=int(np.searchsorted(avg,.9)),
            k90_fraction_for_mean_curve=float(np.searchsorted(avg,.9)/BLOCKS)))
        print(model,summary[-1],flush=True)
    assert len(layers) == 372 and len(docs) == 12 and checks['nosa_packed_masks'] == 96
    for name,rows in [('layers.csv',layers),('documents.csv',docs),('curves.csv',curves)]:
        csv_out(OUT/name,rows)
    np.savez_compressed(OUT/'counts.npz',**count_archive)
    save(OUT/'summary.json',summary)
    save(OUT/'protocol.json',protocol)
    save(OUT/'model-provenance.json',metadata)
    save(OUT/'input-checks.json',input_checks)
    sources[str(Path(__file__).relative_to(ROOT))] = sha(__file__)
    save(OUT/'source-sha256.json',sources)
    checks['status'] = 'passed'
    save(OUT/'analysis-checks.json',checks)


if __name__ == '__main__':
    main()
