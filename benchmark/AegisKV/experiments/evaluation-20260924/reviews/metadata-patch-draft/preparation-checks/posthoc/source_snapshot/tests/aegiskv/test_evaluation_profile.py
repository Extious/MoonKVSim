import json
from dataclasses import replace

import pytest

from moonkvsim.aegiskv.current.model import Config, Invocation
from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile


@pytest.fixture
def profile(tmp_path):
    data = dict(
        schema="aegiskv.duration-grid.v1",
        model="test",
        tp=2,
        config=dict(num_hidden_layers=32, num_key_value_heads=8, head_dim=128),
        context_grid=[0, 1024],
        prefill_extend_grid=[1, 64, 256],
        rows=[],
    )
    for context in data["context_grid"]:
        for stage, extend in [("prefill", 1), ("prefill", 64), ("prefill", 256), ("decode", 1)]:
            data["rows"].append(
                dict(
                    stage=stage,
                    context=context,
                    extend=extend,
                    latency_ns=1000 + context + 10 * extend,
                )
            )
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(data))
    return GridDurationProfile(path)


def test_interpolation_has_known_affine_solution(profile):
    assert profile.shape("prefill", 512, 32) == 1832
    assert profile.shape("decode", 300, 1) == 1310


def test_reconstruction_matches_executed_chunks(profile):
    chunks = [(0, 256), (256, 512), (512, 533)]
    assert profile.duration(0, 533, "prefill", 256) == sum(
        profile.duration(start, end, "prefill", 256) for start, end in chunks
    )


def test_decode_event_batching_preserves_sequential_work(profile):
    assert profile.duration(512, 544, "decode", 256) == sum(
        profile.duration(t, t + 1, "decode", 256) for t in range(512, 544)
    )


def test_profile_refuses_extrapolation_and_geometry_mismatch(profile):
    inv = Invocation((1,), (2,), model="test")
    profile.validate(Config(), inv)
    with pytest.raises(ValueError, match="geometry"):
        profile.validate(replace(Config(), tp=4), inv)
    with pytest.raises(ValueError, match="model differs"):
        profile.validate(Config(), replace(inv, model="unknown"))
    with pytest.raises(ValueError, match="bounds"):
        profile.duration(1024, 1025, "decode", 256)
    with pytest.raises(ValueError, match="outside"):
        profile.shape("prefill", 1025, 256)
