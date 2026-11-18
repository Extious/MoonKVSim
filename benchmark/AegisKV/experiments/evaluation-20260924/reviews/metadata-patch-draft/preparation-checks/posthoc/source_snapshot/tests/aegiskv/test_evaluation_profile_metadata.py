import json
from copy import deepcopy

import pytest

from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile, profile_manifest_fields


@pytest.fixture
def profile(tmp_path):
    data = dict(
        schema="aegiskv.duration-grid.v1",
        model="test-model",
        revision="pinned-test-revision",
        tp=1,
        hardware="test-hardware",
        batch_size=1,
        backend="test-backend",
        backend_version="test-version",
        database_mode="test-table",
        calibrated=False,
        physical_execution=False,
        timing_evidence="test-only affine grid; no measurements",
        interpolation={"mode": "linear", "extrapolation": False},
        config=dict(num_hidden_layers=36, num_key_value_heads=8, head_dim=128),
        context_grid=[0, 1024],
        prefill_extend_grid=[1, 256],
        rows=[
            dict(stage=stage, context=context, extend=extend, latency_ns=1000 + context + extend)
            for context in (0, 1024)
            for stage, extend in (("prefill", 1), ("prefill", 256), ("decode", 1))
        ],
    )
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(data))
    return GridDurationProfile(path, scale=2.0)


def test_manifest_identifies_actual_profile_without_promoting_evidence(profile):
    fields = profile_manifest_fields(profile, [{"compute_dma_slowdown": 0}])
    assert fields["duration_profile"] == "GridDurationProfile"
    assert "test-only affine grid" in fields["timing"]
    assert "per-token decode" in fields["timing"]
    assert "AIConfigurator" not in fields["timing"]
    metadata = fields["duration_profile_metadata"]
    assert metadata["model"] == "test-model"
    assert metadata["revision"] == "pinned-test-revision"
    assert metadata["scale"] == 2.0
    assert metadata["calibrated"] is False
    assert metadata["physical_execution"] is False
    assert not {"rows", "config", "context_grid"} & metadata.keys()
    assert not {"source_sha256", "profile_sha256", "evidence_class", "paper_ready"} & fields.keys()
    assert fields["compute_dma_slowdown_values"] == [0.0]
    assert fields["foreground_dma_compute_interference"].startswith("disabled")
    assert "not measured zero overhead" in fields["foreground_dma_compute_interference"]


def test_manifest_inspects_all_configs_and_sorts_unique_dma_levels(profile):
    configs = [{"compute_dma_slowdown": value} for value in (0, 0.1, 0.05, 0.1)]
    fields = profile_manifest_fields(profile, iter(configs))
    assert fields["compute_dma_slowdown_values"] == [0.0, 0.05, 0.1]
    assert "compute-event-start" in fields["foreground_dma_compute_interference"]
    assert "any TP rank of the same worker" in fields["foreground_dma_compute_interference"]
    assert "not calibrated" in fields["foreground_dma_compute_interference"]
    assert json.dumps(fields, sort_keys=True, allow_nan=False) == json.dumps(
        profile_manifest_fields(profile, reversed(configs)), sort_keys=True, allow_nan=False
    )


def test_manifest_is_detached_and_does_not_change_costs_or_inputs(profile):
    configs = [{"compute_dma_slowdown": 0.05, "prediction_multiplier": 2.0}]
    before_configs, before_data = deepcopy(configs), deepcopy(profile.data)
    before_bytes = profile.path.read_bytes()
    before_duration = profile.duration(0, 533, "prefill", 256)
    fields = profile_manifest_fields(profile, configs)
    fields["duration_profile_metadata"]["interpolation"]["mode"] = "changed-return-only"
    fields["compute_dma_slowdown_values"].append(7)
    assert configs == before_configs
    assert profile.data == before_data
    assert profile.path.read_bytes() == before_bytes
    assert profile.duration(0, 533, "prefill", 256) == before_duration
    assert "prediction_multiplier" not in fields
    assert fields["duration_profile_metadata"]["scale"] == 2.0


def test_missing_evidence_tags_stay_unknown(profile):
    for key in ("timing_evidence", "calibrated", "physical_execution"):
        profile.data.pop(key)
    fields = profile_manifest_fields(profile, [{"compute_dma_slowdown": 0}])
    assert fields["timing"].startswith("configured duration grid via GridDurationProfile")
    assert "calibrated" not in fields["duration_profile_metadata"]
    assert "physical_execution" not in fields["duration_profile_metadata"]


@pytest.mark.parametrize("values", [[], [-0.01], [float("nan")], [float("inf")], [0, -1]])
def test_manifest_rejects_invalid_dma_levels(profile, values):
    with pytest.raises(ValueError, match="nonempty, finite and nonnegative"):
        profile_manifest_fields(profile, [{"compute_dma_slowdown": value} for value in values])


def test_missing_dma_config_does_not_silently_default_to_zero(profile):
    with pytest.raises(KeyError, match="compute_dma_slowdown"):
        profile_manifest_fields(profile, [{}])
