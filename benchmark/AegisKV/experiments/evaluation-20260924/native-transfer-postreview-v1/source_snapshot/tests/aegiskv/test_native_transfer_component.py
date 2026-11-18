import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "native_transfer_component_tested",
    ROOT / "python/moonkvsim/aegiskv/evaluation_native_transfer.py",
)
component = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(component)


def test_head_union_retains_query_order_and_rejects_noncausal_selection():
    selected = np.full((2, 128, 2), -1, dtype=np.int16)
    selected[:, :, 0] = np.arange(128) // 64
    selected[:, 64:, 1] = 0
    incidence = component.incidence_from_selected(selected, 128)
    assert incidence[0].tolist() == [True, False]
    assert incidence[64].tolist() == [True, True]
    assert incidence.sum() == 64 + 64 * 2  # Repeated heads are not double charged.
    selected[0, 0, 1] = 1
    with pytest.raises(ValueError, match="future"):
        component.incidence_from_selected(selected, 128)


def test_partial_prefetch_is_not_retransmitted_after_demand_preemption():
    pipe = component.SerialTransfer([(0, 0), (0, 1)], set(), 1, block_bytes=10)
    pipe.advance(3)
    assert pipe.remaining[(0, 0)] == 7
    pipe.require({(0, 1)})
    assert pipe.ready_at[(0, 1)] == 13
    pipe.advance(20)
    assert pipe.ready_at[(0, 0)] == 20
    assert pipe.transferred == 20 and pipe.preemptions == 1
    assert [row[4] for row in pipe.segments] == [3, 10, 7]


def test_zero_compute_is_exact_unique_demand_bytes_not_event_frequency():
    future = np.zeros((2, 4, 5), dtype=bool)
    future[:, :, :2] = True
    future[:, :, 4] = True  # Local rebuilt tail is causal and free of H2D.
    background = [(layer, b) for layer in range(2) for b in range(4)]
    initial = {(0, 0)}
    summary, queries, layers, segments = component.simulate(
        future, 256, initial, background, 2, 0, block_bytes=16
    )
    assert summary["demanded_unique_bytes"] == 4 * 16
    assert summary["transferred_bytes"] == 3 * 16
    assert summary["raw_component_finish_ns"] == 3 * 16 // 2
    assert summary["local_tail_query_block_events"] == 8
    assert queries.shape == (2, 4, 7)
    assert (queries[:, :, 2] >= 0).all()
    assert int(segments[:, 4].sum()) == summary["transferred_bytes"]
    assert int(layers[:, 4].sum()) == summary["exposed_wait_ns"]


def test_prepared_layer_hides_later_layer_transfer_without_batch_barrier():
    future = np.ones((2, 1, 1), dtype=bool)
    result, query, layers, _ = component.simulate(
        future, 64, {(0, 0)}, [(0, 0), (1, 0)], 1, 10, block_bytes=10
    )
    assert result["raw_component_finish_ns"] == 20
    assert result["exposed_wait_ns"] == 0
    assert layers[1, 0] == 10 and query[1, 0, 1] == 10


def test_local_tail_only_needs_no_transfer_and_future_tail_is_rejected():
    future = np.zeros((1, 2, 6), dtype=bool)
    future[:, :, 4] = True
    result, *_ = component.simulate(future, 256, set(), [(0, b) for b in range(4)], 1, 0)
    assert result["transferred_bytes"] == 0
    assert result["raw_component_finish_ns"] == 0
    future[0, 0, 5] = True
    with pytest.raises(ValueError, match="future local-tail"):
        component.simulate(future, 256, set(), [(0, b) for b in range(4)], 1, 0)


def test_stop_accounts_unused_partial_background_bytes():
    future = np.zeros((1, 1, 2), dtype=bool)
    future[0, 0, 0] = True
    result, *_ = component.simulate(future, 128, {(0, 0)}, [(0, 0), (0, 1)], 1, 3, block_bytes=10)
    assert result["transferred_bytes"] == 3
    assert result["transferred_but_not_demanded_bytes"] == 3
    assert result["partial_transfer_bytes_at_stop"] == 3
    assert result["canceled_unfinished_object_remaining_bytes"] == 7


def test_current_is_past_only_and_oracle_does_not_change_common_prefetch_order():
    chunks = np.zeros((5, 3, 12), dtype=np.uint16)
    chunks[:, 0, 0] = 256
    chunks[:, 1, 1] = 200
    future = np.zeros((5, 256, 12), dtype=bool)
    future[:, :, 7] = True
    residents, background, _ = component.placements(chunks, future, 512, k=1, depth=4)
    changed = chunks.copy()
    changed[:, 2, 11] = 65535  # No reading future completed chunks.
    other = future.copy()
    other[:] = False
    other[:, :, 6] = True
    revised, order, _ = component.placements(changed, other, 512, k=1, depth=4)
    assert residents["Current"] == revised["Current"]
    assert residents["Oracle"] != revised["Oracle"]
    assert background == order
    assert all(layer < 4 for layer, _ in residents["Current"])


def test_current_ranking_strict_hysteresis_and_earlier_ties():
    assert component.topk([10, 11], {0}, 1, 2, 0.1) == (0,)
    assert component.topk([10, 11.01], {0}, 1, 2, 0.1) == (1,)
    assert component.topk([1, 1, 1], (), 2, 3, 0.1) == (0, 1)
