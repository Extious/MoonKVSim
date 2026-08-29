from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from moonkvsim.baseline.e2_harness import load_harness_config
from moonkvsim.baseline.trace_runner import TraceSelection, load_trace_run_input
from moonkvsim.common.hash import canonical_json_bytes

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SMOKE_CONFIG = REPOSITORY_ROOT / "configs/experiments/vanilla-weka-e2-smoke.json"
NEAR128_CONFIG = REPOSITORY_ROOT / "configs/experiments/vanilla-weka-near128-e2.json"
HARNESS_SCHEMA = REPOSITORY_ROOT / "schemas/vanilla-trace-e2-harness.schema.json"
WORKFLOW_ID = "0e4206535a79f980e2b1091181202ea987fe"
TRACE_SHA256 = "0a1c37deea32f2c393ba7d8d2d9a7c5629854b874b01ace8953140ad889f6d54"
MAX_SPAN_ID = f"weka:{WORKFLOW_ID}:main:000006"


def _load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_bytes())
    assert isinstance(document, dict)
    return document


def test_near128_config_is_a_strict_selection_only_smoke_derivative() -> None:
    smoke = _load_json(SMOKE_CONFIG)
    near128 = _load_json(NEAR128_CONFIG)
    schema = _load_json(HARNESS_SCHEMA)

    Draft202012Validator(schema).validate(near128)

    expected = copy.deepcopy(smoke)
    expected["trace"]["selection"]["workflow_ids"] = [WORKFLOW_ID]
    assert near128 == expected
    assert near128["trace"] == {
        **smoke["trace"],
        "selection": {
            "workflow_ids": [WORKFLOW_ID],
            "whole_workflow_closure": True,
        },
    }
    assert near128["trace"]["token_count_mode"] == "source_hash_blocks_64"
    assert near128["target"]["context_configuration_status"] == "proposed_unvalidated"
    assert near128["evidence"] == {
        "class": "E2",
        "boundary": "E2_real_trace_shape_vanilla_baseline_uncalibrated",
        "formal_use_allowed": False,
        "physical_timing_claim_allowed": False,
        "calibration_status": "not_calibrated",
    }

    predictor = near128["predictor"]
    hardware_shape = {
        "schema": "moonkvsim.assumed-hardware-shape-profile.v1",
        "parameter_source": "assumed",
        "hardware_profile_id": predictor["hardware_profile_id"],
        "gpus": near128["deployment"]["gpus"],
        "store": near128["store"],
        "network": near128["network"],
    }
    assert (
        predictor["hardware_profile_fingerprint"]
        == hashlib.sha256(canonical_json_bytes(hardware_shape)).hexdigest()
    )
    assert (
        predictor["hardware_profile_fingerprint"]
        == smoke["predictor"]["hardware_profile_fingerprint"]
    )


def test_near128_external_trace_shape_when_locked_input_is_available() -> None:
    document = _load_json(NEAR128_CONFIG)
    trace_path = Path(document["trace"]["path"])
    if not trace_path.is_file():
        pytest.skip("locked external normalized Weka trace is not present")

    config = load_harness_config(NEAR128_CONFIG)
    run_input = load_trace_run_input(
        config.trace_path,
        selection=TraceSelection(workflow_ids=config.workflow_ids),
    )

    assert run_input.source_sha256 == TRACE_SHA256
    assert run_input.total_valid_span_count == 46_142
    assert run_input.selected_workflow_ids == (WORKFLOW_ID,)
    assert len(run_input.spans) == 8
    assert sum(item.metadata.prompt_tokens for item in run_input.spans) == 590_080
    assert all(
        item.metadata.prompt_tokens + item.metadata.output_tokens <= 131_072
        for item in run_input.spans
    )

    largest = max(
        run_input.spans,
        key=lambda item: item.metadata.prompt_tokens + item.metadata.output_tokens,
    )
    assert largest.span_id == MAX_SPAN_ID
    assert largest.metadata.prompt_tokens == 130_176
    assert largest.metadata.output_tokens == 619
    assert largest.metadata.prompt_tokens + largest.metadata.output_tokens == 130_795
