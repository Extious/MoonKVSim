"""Run the local SGLang top-k reference on explicitly constructed scores.

This does not load a trained model or execute a CUDA kernel. The selected AST
functions are executed unchanged on CPU, without importing the GPU test module.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Optional

import torch

OUT = Path(__file__).resolve().parent
SGLANG = Path('/home/comp/zhanzhao/sglang')
SOURCE = SGLANG / 'sgl-kernel/tests/test_topk.py'
M, N, TOPK = 16, 8, 4
torch.set_num_threads(1)


def extract_functions():
    content = SOURCE.read_text()
    tree = ast.parse(content)
    names = ('_ref_torch_impl', '_ref_torch_transform_decode_impl')
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {'torch': torch, 'Optional': Optional}
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), 'exec'), namespace)
    extracted = '\n\n'.join(ast.get_source_segment(content, n) for n in nodes)
    (OUT / 'sglang_reference_excerpt.py.txt').write_text(extracted + '\n')
    return namespace, [
        {'name': n.name, 'start': n.lineno, 'end': n.end_lineno} for n in nodes
    ]


def main():
    reference, functions = extract_functions()
    # This fixture deliberately creates persistence and different layer choices.
    # The reference computes the outputs; persistence is an input assumption.
    histories = [
        [(0, 3, j) for j in (8, 10, 8, 12, 8, 10, 8, 14)],
        [(5, 11, j) for j in (1, 7, 9, 13, 1, 7, 9, 13)],
    ]
    results = []
    rows = []
    page_table = torch.tensor([(5 * j + 7) % (M + N) for j in range(M + N)])
    assert page_table.unique().numel() == M + N
    for layer_id, fixture in enumerate(histories):
        layer_scores, selected, mapped = [], [], []
        counts = torch.zeros(M + N, dtype=torch.int64)
        for query_offset, history in enumerate(fixture):
            query_position = M + query_offset
            # Baseline entries are unique, and the four fixture winners outrank
            # them. Future entries receive large values to check causal slicing.
            scores = torch.arange(M + N, dtype=torch.float32) / 100
            winners = (*history, query_position)
            for rank, token in enumerate(winners):
                scores[token] = 10 - rank
            scores[query_position + 1:] = 1000 + torch.arange(
                M + N - query_position - 1, dtype=torch.float32
            )
            raw = reference['_ref_torch_impl'](
                scores.unsqueeze(0), query_position + 1, TOPK
            )[0]
            assert set(raw.tolist()) == set(winners)
            assert bool((raw <= query_position).all())
            assert raw.unique().numel() == TOPK
            physical = reference['_ref_torch_transform_decode_impl'](
                scores.unsqueeze(0), query_position + 1, page_table.unsqueeze(0), TOPK
            )[0]
            assert set(physical.tolist()) == set(page_table[raw].tolist())
            # Keep actual top-k order as well as a sorted copy for display.
            selected.append(raw.tolist())
            mapped.append(physical.tolist())
            layer_scores.append(scores.tolist())
            counts[raw] += 1
            for token in raw.tolist():
                rows.append({
                    'evidence': 'constructed_scores_local_sglang_CPU_reference',
                    'layer_id_zero_based': layer_id,
                    'query_position_zero_based': query_position,
                    'key_position_zero_based': token,
                    'is_backed_up_history': token < M,
                    'is_replayed_suffix': token >= M,
                    'score': scores[token].item(),
                    'ordinary_paged_physical_location': page_table[token].item(),
                })
        assert int(counts.sum()) == N * TOPK
        assert int(counts[:M].sum()) == 3 * N
        results.append({
            'layer_id_zero_based': layer_id,
            'fixture_scores': layer_scores,
            'logical_selected_indices': selected,
            'ordinary_paged_locations': mapped,
            'selection_count_by_position': counts.tolist(),
        })

    first_history = {j for j in results[0]['logical_selected_indices'][0] if j < M}
    physical_rows = []
    for block_tokens in (1, 4, 8):
        running_union = set()
        union_tokens_by_query = []
        for selection in results[0]['logical_selected_indices']:
            blocks = {j // block_tokens for j in selection if j < M}
            running_union |= blocks
            union_tokens_by_query.append(len(running_union) * block_tokens)
        first_blocks = sorted({j // block_tokens for j in first_history})
        first_materialized = sorted({
            j for block in first_blocks
            for j in range(block * block_tokens, (block + 1) * block_tokens)
        })
        assert first_history <= set(first_materialized)
        physical_rows.append({
            'transport_block_tokens_ASSUMED': block_tokens,
            'first_query_blocks': first_blocks,
            'first_query_materialized_history_positions': first_materialized,
            'first_query_transfer_tokens': len(first_materialized),
            'window_union_tokens_by_query': union_tokens_by_query,
        })

    initial_resident = {0, 3, 5, 6}
    first_selection = set(results[0]['logical_selected_indices'][0])
    classification = {
        'initial_hbm_history_tokens': sorted(initial_resident),
        'selected_hbm_history_hits': sorted(first_selection & initial_resident),
        'selected_host_history_misses': sorted(first_history - initial_resident),
        'selected_current_local_token': sorted(first_selection - first_history),
        'classification_is_set_arithmetic_not_CUDA_execution': True,
    }
    assert len(classification['selected_hbm_history_hits']) == 2
    assert len(classification['selected_host_history_misses']) == 1
    assert classification['selected_current_local_token'] == [M]

    source_paths = [
        'sgl-kernel/tests/test_topk.py',
        'python/sglang/srt/layers/attention/nsa/nsa_indexer.py',
        'python/sglang/srt/layers/attention/nsa_backend.py',
        'python/sglang/srt/managers/hisparse_coordinator.py',
        'python/sglang/jit_kernel/hisparse.py',
        'python/sglang/jit_kernel/csrc/hisparse.cuh',
        'python/sglang/srt/models/deepseek_v2.py',
    ]
    artifact = {
        'evidence': 'constructed_input_executed_local_SGLang_torch_reference',
        'trained_model_runs': 0,
        'cuda_kernel_runs': 0,
        'source_checkout': str(SGLANG),
        'source_commit': subprocess.check_output(
            ['git', '-C', str(SGLANG), 'rev-parse', 'HEAD'], text=True
        ).strip(),
        'source_branch': subprocess.check_output(
            ['git', '-C', str(SGLANG), 'branch', '--show-current'], text=True
        ).strip(),
        'source_functions_executed_unchanged': functions,
        'torch_version': torch.__version__,
        'device': 'cpu',
        'config': {
            'M_history_tokens': M, 'N_replayed_tokens': N,
            'independent_layer_input_fixtures': 2,
            'topk_reference_example': TOPK,
            'topk_is_scaled_for_readability_not_a_supported_CUDA_launch_claim': True,
            'display_positions_are_one_based': True,
            'reference_positions_are_zero_based': True,
            'index_scores_are_not_main_attention_probabilities': True,
            'block_amplification_is_full_block_transfer_assumption': True,
        },
        'ordinary_paged_location_map': page_table.tolist(),
        'layers': results,
        'physical_block_assumption_examples': physical_rows,
        'first_query_residency_example': classification,
        'source_sha256': {
            relative: hashlib.sha256((SGLANG / relative).read_bytes()).hexdigest()
            for relative in source_paths
        },
        'checks': {
            'selected_rows_and_causal_masks': 2 * N,
            'ordinary_paged_mapping_rows': 2 * N,
            'no_future_selection': True,
            'equal_topk_per_query': True,
            'history_selection_events_per_layer': 3 * N,
            'suffix_selection_events_per_layer': N,
            'status': 'PASS',
        },
    }
    (OUT / 'reference_trace.json').write_text(json.dumps(artifact, indent=2) + '\n')
    with (OUT / 'selected_entries.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({
        'checks': artifact['checks'],
        'source_commit': artifact['source_commit'],
        'evidence': artifact['evidence'],
        'history_unions_per_layer': [sum(x > 0 for x in v['selection_count_by_position'][:M]) for v in results],
        'first_query_residency_example': classification,
    }, indent=2))


if __name__ == '__main__':
    main()
