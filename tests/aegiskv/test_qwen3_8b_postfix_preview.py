from __future__ import annotations

import gzip
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from moonkvsim.aegiskv.experiment import (
    ExperimentVariant,
    FailureEventSchedule,
    FailureImpactContract,
    FailureSchedule,
    core_variants,
)
from moonkvsim.common.hash import sha256_json


def _runner_module() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "benchmark"
        / "AegisKV"
        / "experiments"
        / "scripts"
        / "run_qwen3_8b_postfix_preview.py"
    )
    spec = importlib.util.spec_from_file_location("run_qwen3_8b_postfix_preview", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schedule() -> FailureSchedule:
    return FailureSchedule(
        (
            FailureEventSchedule(
                failure_id="failure-0",
                event_index=0,
                bucket="96k",
                seed=0,
                focus_span_id="workflow-0:span-0",
                target_gpu_id="gpu-0",
                reference_at_ns=10,
                target_workload_progress_per_mille=500,
                reference_completed_workflow_count=0,
                reference_workflow_count=1,
                detection_delay_ns=0,
                trigger_progress_per_mille=600,
                gpu_recovery_time_ns=120_000_000_000,
                selection_scope="test",
                physical_target_frozen=True,
            ),
        )
    )


def test_run_binding_fingerprint_covers_protocol_inputs() -> None:
    runner = _runner_module()
    variant = core_variants()[0]
    records = ({"workflow_id": "workflow-0", "span_id": "workflow-0:span-0"},)
    schedule = _schedule()

    baseline = runner._run_binding_fingerprint(
        records,
        variant,
        scenario_id="gpu_failure",
        schedule=schedule,
        bucket="96k",
        seed=0,
        peer_binding_seed=0,
    )

    assert baseline != runner._run_binding_fingerprint(
        ({"workflow_id": "workflow-0", "span_id": "workflow-0:span-1"},),
        variant,
        scenario_id="gpu_failure",
        schedule=schedule,
        bucket="96k",
        seed=0,
        peer_binding_seed=0,
    )
    assert baseline != runner._run_binding_fingerprint(
        records,
        variant,
        scenario_id="no_failure",
        schedule=None,
        bucket="96k",
        seed=0,
        peer_binding_seed=0,
    )
    assert baseline != runner._run_binding_fingerprint(
        records,
        variant,
        scenario_id="gpu_failure",
        schedule=schedule,
        bucket="64k",
        seed=0,
        peer_binding_seed=0,
    )
    assert baseline != runner._run_binding_fingerprint(
        records,
        variant,
        scenario_id="gpu_failure",
        schedule=schedule,
        bucket="96k",
        seed=1,
        peer_binding_seed=0,
    )
    assert baseline != runner._run_binding_fingerprint(
        records,
        variant,
        scenario_id="gpu_failure",
        schedule=schedule,
        bucket="96k",
        seed=0,
        peer_binding_seed=1,
    )
    assert baseline != runner._run_binding_fingerprint(
        records,
        variant,
        scenario_id="gpu_failure",
        schedule=schedule,
        bucket="96k",
        seed=0,
        peer_binding_seed=0,
        workflow_concurrency=8,
    )
    assert baseline != runner._run_binding_fingerprint(
        records,
        variant,
        scenario_id="gpu_failure",
        schedule=schedule,
        bucket="96k",
        seed=0,
        peer_binding_seed=0,
        paper_causal_mode=True,
    )


def test_run_binding_fingerprint_covers_variant_identity() -> None:
    runner = _runner_module()
    variants: tuple[ExperimentVariant, ...] = core_variants()
    records = ({"workflow_id": "workflow-0", "span_id": "workflow-0:span-0"},)
    schedule = _schedule()

    fingerprints = {
        runner._run_binding_fingerprint(
            records,
            variant,
            scenario_id="gpu_failure",
            schedule=schedule,
            bucket="96k",
            seed=0,
            peer_binding_seed=0,
        )
        for variant in variants
    }

    assert len(fingerprints) == len(variants)


def test_compact_hashes_bind_embedded_content() -> None:
    runner = _runner_module()
    full_payload = {
        "schema": "payload",
        "metrics": {"wct": 1},
        "journal": [1, 2, 3],
    }
    compact_payload = {"schema": "payload", "metrics": {"wct": 1}}
    metadata = runner._compact_hash_metadata(full_payload, compact_payload)

    assert metadata == {
        "compact_sha256": sha256_json(compact_payload),
        "omitted_fields": ["journal"],
    }
    changed = dict(compact_payload)
    changed["metrics"] = {"wct": 2}
    assert runner._compact_hash_metadata(full_payload, changed)["compact_sha256"] != (
        metadata["compact_sha256"]
    )


def test_compact_representative_retains_route_and_peer_binding_audit() -> None:
    runner = _runner_module()

    assert "route_events" in runner.COMPACT_REPRESENTATIVE_FIELDS
    assert "peer_target_binding_events" in runner.COMPACT_REPRESENTATIVE_FIELDS


def test_read_checkpoint_detects_gzip_independent_of_suffix(tmp_path: Path) -> None:
    runner = _runner_module()
    document = {"schedule": {"events": []}}
    gzip_path = tmp_path / "logical-failure-plan.json"
    with gzip.open(gzip_path, "wt", encoding="utf-8") as stream:
        json.dump(document, stream)
    plain_path = tmp_path / "legacy-checkpoint.json"
    plain_path.write_text(json.dumps(document), encoding="utf-8")

    assert runner._read_checkpoint(gzip_path) == document
    assert runner._read_checkpoint(plain_path) == document


def test_implementation_fingerprint_covers_declared_sources() -> None:
    runner = _runner_module()
    root = Path(__file__).parents[2]

    assert runner._implementation_fingerprint(root) == (
        runner._implementation_fingerprint(root)
    )
    assert {
        "python/moonkvsim/aegiskv/experiment.py",
        "python/moonkvsim/aegiskv/experiment_hbm_authority.py",
        "python/moonkvsim/aegiskv/continuous_batch_des.py",
        "python/moonkvsim/integration/vllm/scheduler.py",
    }.issubset(set(runner.IMPLEMENTATION_PATHS))


def test_paper_causal_mode_requires_full_workload_and_fresh_single_failure() -> None:
    runner = _runner_module()

    runner._validate_paper_causal_inputs(
        historical_aggregate=None,
        failure_count=1,
        workflow_limit=160,
        source_workflow_count=160,
    )
    for kwargs, message in (
        (
            {
                "historical_aggregate": Path("legacy.json"),
                "failure_count": 1,
                "workflow_limit": 160,
                "source_workflow_count": 160,
            },
            "rejects historical",
        ),
        (
            {
                "historical_aggregate": None,
                "failure_count": 3,
                "workflow_limit": 160,
                "source_workflow_count": 160,
            },
            "exactly one failure",
        ),
        (
            {
                "historical_aggregate": None,
                "failure_count": 1,
                "workflow_limit": 60,
                "source_workflow_count": 160,
            },
            "complete frozen workload",
        ),
    ):
        try:
            runner._validate_paper_causal_inputs(**kwargs)
        except ValueError as error:
            assert message in str(error)
        else:
            raise AssertionError("paper causal validation accepted an invalid input")


def test_paper_failure_schedule_rejects_frozen_impact_contracts() -> None:
    runner = _runner_module()
    valid = _schedule()
    runner._validate_paper_failure_schedule(valid)
    event = valid.events[0]

    shared_contract = FailureImpactContract(
        active_span_ids=("workflow-0:span-0",),
        queued_span_ids=(),
        reroute_only_queued_span_ids=(),
    )
    with pytest.raises(ValueError, match="post-treatment"):
        runner._validate_paper_failure_schedule(
            FailureSchedule((replace(event, impact_contract=shared_contract),))
        )
    with pytest.raises(ValueError, match="post-treatment"):
        runner._validate_paper_failure_schedule(
            FailureSchedule(
                (
                    replace(
                        event,
                        profile_impact_contracts={"profile": shared_contract},
                    ),
                )
            )
        )


def test_worker_checkpoint_binding_uses_effective_workflow_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    records = ({"workflow_id": "workflow-0", "span_id": "workflow-0:span-0"},)
    variant = core_variants()[0]
    schedule = _schedule()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        runner,
        "run_study_cell",
        lambda *_args, **_kwargs: type(
            "Result",
            (),
            {
                "payload": {},
                "representative": {},
                "payload_sha256": "payload",
                "journal_sha256": "journal",
                "span_details": (),
            },
        )(),
    )
    monkeypatch.setattr(runner, "_write_checkpoint", lambda *_args: None)

    original_binding = runner._run_binding_fingerprint

    def capture_binding(*args: object, **kwargs: object) -> str:
        captured.update(kwargs)
        return original_binding(*args, **kwargs)

    monkeypatch.setattr(runner, "_run_binding_fingerprint", capture_binding)
    runner._init_worker(
        records,
        {variant.variant_id: variant},
        {variant.variant_id: schedule},
        "96k",
        tmp_path,
        0,
        0,
        True,
        1,
    )

    runner._run_one(variant.variant_id, "gpu_failure")

    assert captured["workflow_concurrency"] == 1
    assert captured["paper_causal_mode"] is True


@pytest.mark.parametrize("value", (0, 1_000))
def test_failure_progress_cli_rejects_request_boundaries(
    tmp_path: Path,
    value: int,
) -> None:
    runner = _runner_module()

    with pytest.raises(
        ValueError,
        match="failure-progress-per-mille must be strictly between",
    ):
        runner.main(
            [
                "--output",
                str(tmp_path / "unused.json.gz"),
                "--failure-progress-per-mille",
                str(value),
            ]
        )
