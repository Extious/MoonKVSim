from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from moonkvsim.aegiskv.formal_algorithm_audit import FormalAlgorithmAuditError

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_RUNNER_PATH = (
    _REPOSITORY_ROOT / "benchmark/AegisKV/experiments/scripts/run_aegiskv_paper_sweeps.py"
)
_FROZEN_MANIFEST = (
    _REPOSITORY_ROOT
    / "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160-manifest.json"
)


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_test_aegiskv_paper_sweeps", _RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_schedule(
    runner: ModuleType,
    *,
    seed: int = 7,
    focus_prefix: str = "span",
    failure_count: int = 8,
) -> Any:
    targets = runner.failure_workload_progress_targets_per_mille(failure_count)
    return runner.FailureSchedule(
        tuple(
            runner.FailureEventSchedule(
                failure_id=f"gpu-failure:96k:seed-{seed}:event-{index}",
                event_index=index,
                bucket="96k",
                seed=seed,
                focus_span_id=f"{focus_prefix}-{index}",
                target_gpu_id=f"gpu-{index % 8}",
                reference_at_ns=(index + 1) * 1_000,
                target_workload_progress_per_mille=target,
                reference_completed_workflow_count=index + 1,
                reference_workflow_count=160,
                detection_delay_ns=1,
                trigger_progress_per_mille=600,
                gpu_recovery_time_ns=2,
            )
            for index, target in enumerate(targets)
        )
    )


def _compact_system(
    runner: ModuleType,
    *,
    schedule: Any,
    variant_id: str,
    variant_fingerprint: str,
) -> dict[str, Any]:
    failure_count = len(schedule.events)
    report_body = {
        "schema": runner.FORMAL_ALGORITHM_AUDIT_SCHEMA,
        "status": "PASS",
    }
    formal_report = (
        {**report_body, "fingerprint": runner.sha256_json(report_body)}
        if variant_id == runner.AEGISKV_VARIANT_ID
        else None
    )
    scheduler_report_body = {
        "schema": runner.CONTINUOUS_SCHEDULER_AUDIT_SCHEMA,
        "status": "PASS",
    }
    scheduler_report = {
        **scheduler_report_body,
        "fingerprint": runner.sha256_json(scheduler_report_body),
    }
    return {
        "variant_id": variant_id,
        "variant_fingerprint": variant_fingerprint,
        "failure_schedule": schedule.to_dict(),
        "failure_schedule_fingerprint": schedule.fingerprint,
        "run": {
            "repetition": "A",
            "payload_sha256": "a" * 64,
            "journal_sha256": "b" * 64,
            "span_details_sha256": "c" * 64,
            "representative_sha256": "d" * 64,
            "workload": {"workflow_count": 160},
            "metrics": {
                "workflow_completion_time_ns": {
                    "by_workflow_id": {
                        f"workflow-{index}": index + 1 for index in range(160)
                    }
                },
                "failure_impact": {
                    "failure_event_count": failure_count,
                    "active_requests": failure_count,
                },
                "gpu_capacity_recovery": {
                    "scheduled_count": failure_count,
                    "completed_count": failure_count,
                },
                "policy_effects": {
                    "continuous_batch_residency_modeled": True,
                    "compute_scheduler_model": "VLLM_CONTINUOUS_BATCH_SCHEDULER_STEP",
                    "algorithm1": {
                        "algorithm": "ideal_trace_exact_dag_cpm_v1",
                        "duration_source": "trace.recorded_api_time_ns",
                        "predictor_used": False,
                        "prediction_error_modeled": False,
                        "absolute_observed_finish_used": False,
                        "failure_location_used": False,
                    },
                },
            },
            "failure_focus_spans": [
                {
                    "span_id": event.focus_span_id,
                    "available_peer_tokens_at_failure": 64,
                }
                for event in schedule.events
            ],
            "continuous_scheduler_audit": scheduler_report,
            "formal_algorithm_audit": formal_report,
        },
    }
def test_aegiskv_run_requires_and_returns_formal_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    calls: list[tuple[object, object]] = []

    class _Report:
        def to_dict(self) -> dict[str, object]:
            return {"schema": "formal", "status": "PASS", "fingerprint": "f" * 64}

    def audit(payload: object, representative: object) -> _Report:
        calls.append((payload, representative))
        return _Report()

    monkeypatch.setattr(runner, "audit_formal_algorithm_run", audit)
    payload = {"status": "PASS"}
    representative: dict[str, object] = {"formal_algorithm2_events": []}

    report = runner._formal_algorithm_report(
        SimpleNamespace(variant_id=runner.AEGISKV_VARIANT_ID),
        payload=payload,
        representative=representative,
        failure_count=2,
        concurrency=16,
        repetition="A",
    )

    assert calls == [(payload, representative)]
    assert report == {"schema": "formal", "status": "PASS", "fingerprint": "f" * 64}


def test_mooncake_run_does_not_claim_formal_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()

    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Mooncake must not be passed through the AegisKV formal gate")

    monkeypatch.setattr(runner, "audit_formal_algorithm_run", unexpected)

    assert (
        runner._formal_algorithm_report(
            SimpleNamespace(variant_id="vanilla_mooncake_dram"),
            payload={},
            representative={},
            failure_count=2,
            concurrency=16,
            repetition="A",
        )
        is None
    )


def test_aegiskv_formal_failure_rejects_runner_without_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()

    def reject(*_args: object, **_kwargs: object) -> None:
        raise FormalAlgorithmAuditError(["pressure did not trigger immediate MD"])

    monkeypatch.setattr(runner, "audit_formal_algorithm_run", reject)

    with pytest.raises(
        runner.ExperimentError,
        match=(
            "formal Algorithm 2/3 paper gate rejected failure_count=4, concurrency=24, repetition=A"
        ),
    ):
        runner._formal_algorithm_report(
            SimpleNamespace(variant_id=runner.AEGISKV_VARIANT_ID),
            payload={},
            representative={},
            failure_count=4,
            concurrency=24,
            repetition="A",
        )


def test_continuous_scheduler_failure_rejects_both_systems_without_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()

    def reject(*_args: object, **_kwargs: object) -> None:
        raise FormalAlgorithmAuditError(["scheduler participant is unknown"])

    monkeypatch.setattr(runner, "audit_continuous_scheduler_evidence", reject)

    with pytest.raises(
        runner.ExperimentError,
        match="continuous scheduler paper gate rejected variant=vanilla_mooncake_dram",
    ):
        runner._continuous_scheduler_report(
            payload={},
            representative={},
            variant_id="vanilla_mooncake_dram",
            failure_count=2,
            concurrency=16,
            repetition="A",
        )


def test_runner_persists_audit_and_binds_all_formal_sources() -> None:
    runner = _load_runner()
    source = inspect.getsource(runner._run_variant)

    assert '"formal_algorithm_audit": formal_algorithm_audit' in source
    assert "_formal_algorithm_report(" in source
    assert '"continuous_scheduler_audit": continuous_scheduler_audit' in source
    assert "_continuous_scheduler_report(" in source
    assert "retain_exact_token_ids=True" in _RUNNER_PATH.read_text(encoding="utf-8")
    assert {
        "python/moonkvsim/aegiskv/continuous_batch_des.py",
        "python/moonkvsim/aegiskv/experiment_hbm_authority.py",
        "python/moonkvsim/aegiskv/formal_algorithm_audit.py",
        "python/moonkvsim/aegiskv/hbm_quota_aimd.py",
        "python/moonkvsim/aegiskv/lazy_refresh.py",
        "python/moonkvsim/aegiskv/recovery_harm.py",
        "python/moonkvsim/aegiskv/rental_value.py",
        "python/moonkvsim/aegiskv/slack_landlord.py",
        "python/moonkvsim/aegiskv/scheduler_step_bridge.py",
        "python/moonkvsim/aegiskv/types.py",
        "python/moonkvsim/integration/vllm/hbm_block_ledger.py",
        "python/moonkvsim/integration/vllm/scheduler.py",
    }.issubset(set(runner.SOURCE_RELATIVE_PATHS))


def test_runner_requires_exact_frozen_seed_vector() -> None:
    runner = _load_runner()

    assert runner._parse_seeds("0,1,2,3,4") == (0, 1, 2, 3, 4)
    with pytest.raises(ValueError, match="exactly 0,1,2,3,4"):
        runner._parse_seeds("0,1,2,3")
    with pytest.raises(ValueError, match="exactly 0,1,2,3,4"):
        runner._parse_seeds("0,1,2,3,3")
    with pytest.raises(ValueError, match="exactly 0,1,2,3,4"):
        runner._parse_seeds("1,0,2,3,4")
    with pytest.raises(ValueError, match="exactly 0,1,2,3,4"):
        runner._parse_seeds("0,1,2,3,4,5")


def test_frozen_manifest_records_96k_focus_and_no_observed_128k() -> None:
    runner = _load_runner()
    manifest = json.loads(_FROZEN_MANIFEST.read_text(encoding="utf-8"))

    coverage = runner._context_coverage(
        manifest,
        claimed_observed_128k_coverage=False,
    )

    assert coverage["context_bucket_counts"]["128k"] == 0
    assert coverage["max_observed_context_tokens"] == 86_214
    assert coverage["observed_128k_coverage"] is False
    assert coverage["highest_nonempty_context_bucket"] == "96k"


def test_false_128k_paper_claim_fails_closed() -> None:
    runner = _load_runner()
    manifest = json.loads(_FROZEN_MANIFEST.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="128K paper claim rejected"):
        runner._context_coverage(
            manifest,
            claimed_observed_128k_coverage=True,
        )


def test_runner_v4_binds_per_concurrency_plans_and_preserves_raw_cells() -> None:
    runner = _load_runner()
    source = inspect.getsource(runner.main)

    assert runner.SCHEMA == "moonkvsim.aegiskv.paper_sweeps.v4"
    assert runner.DEFAULT_SEEDS == (0, 1, 2, 3, 4)
    assert "build_paper_sweep_statistics(seed_cells)" in source
    assert '"raw_seed_cells": raw_seed_cells' in source
    assert '"cells": aggregate_cells' in source
    assert '"checkpoint_evidence"' in source
    assert '"canonical_failure_plans"' in source
    assert '"cross_concurrency_focus_identity_required": False' in source
    assert "canonical_plan_tasks" in source
    assert "shutil.copytree(checkpoint_dir" in source
    assert '"observed_128k_coverage"' in inspect.getsource(runner._context_coverage)


def test_available_peer_prefix_is_bound_to_selected_recovery_gpu() -> None:
    runner = _load_runner()
    route = {
        "selected_gpu_id": "gpu-3",
        "peer_prefix_tokens_by_gpu": {"gpu-2": 4096, "gpu-3": 64},
    }

    assert (
        runner._selected_route_prefix_tokens(
            route,
            field="peer_prefix_tokens_by_gpu",
        )
        == 64
    )


def test_canonical_plan_worker_derives_once_and_writes_bound_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    mooncake = SimpleNamespace(
        variant_id="vanilla_mooncake_dram",
        parameters="mooncake-parameters",
        profile="mooncake-profile",
    )
    aegiskv = SimpleNamespace(
        variant_id=runner.AEGISKV_VARIANT_ID,
        parameters="mooncake-parameters",
        profile="aegiskv-profile",
    )
    token_ids = list(range(64))
    records = (
        {
            "span_id": "span-0",
            "messages_or_token_ids": {"kind": "token_ids", "value": token_ids},
            "prompt_token_ids_hash": runner.sha256_json(token_ids),
            "token_count_mode": "qwen3_token_ids",
        },
    )
    canonical_schedule = _canonical_schedule(runner, failure_count=2)
    derive_calls: list[dict[str, object]] = []

    monkeypatch.setattr(runner, "_WORKER_RECORDS", records)
    monkeypatch.setattr(runner, "_WORKER_VARIANTS", (mooncake, aegiskv))
    monkeypatch.setattr(runner, "_WORKER_BUCKET", "96k")

    def derive(
        actual_records: object,
        **kwargs: object,
    ) -> object:
        assert actual_records is records
        derive_calls.append(kwargs)
        return canonical_schedule

    monkeypatch.setattr(runner, "derive_failure_schedule", derive)

    document = runner._worker_canonical_plan(
        7,
        24,
        checkpoint_dir=tmp_path,
        contract_fingerprint="c" * 64,
        source_contract_sha256="s" * 64,
    )

    assert len(derive_calls) == 1
    assert derive_calls[0]["workflow_concurrency"] == 24
    assert derive_calls[0]["workflow_admission_seed"] == 7
    assert derive_calls[0]["peer_binding_seed"] == 0
    assert derive_calls[0]["freeze_post_treatment_impact_contracts"] is False
    assert derive_calls[0]["failure_count"] == 2
    assert derive_calls[0]["compared_profiles"] == (
        "mooncake-profile",
        "aegiskv-profile",
    )
    schedule, binding, _content = runner._validated_canonical_plan_checkpoint(
        document,
        seed=7,
        concurrency=24,
        contract_fingerprint="c" * 64,
        source_contract_sha256="s" * 64,
    )
    assert schedule.fingerprint == canonical_schedule.fingerprint
    assert binding["content_sha256"] == document["content_sha256"]
    assert document["content"]["workflow_concurrency"] == 24
    assert document["content"]["canonical_failure_count"] == 2
    assert document["content"]["focus_span_ids_by_failure_count"] == {
        "2": ["span-0", "span-1"]
    }
    assert json.loads(
        runner._canonical_plan_checkpoint_path(tmp_path, 7, 24).read_text(
            encoding="utf-8"
        )
    ) == document
    with pytest.raises(ValueError, match="checkpoint task binding mismatch"):
        runner._validated_canonical_plan_checkpoint(
            document,
            seed=7,
            concurrency=16,
            contract_fingerprint="c" * 64,
            source_contract_sha256="s" * 64,
        )


def test_worker_cell_projects_both_variants_from_one_fixed_logical_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    mooncake = SimpleNamespace(
        variant_id="vanilla_mooncake_dram",
        parameters="mooncake-parameters",
        profile="mooncake-profile",
        fingerprint="m" * 64,
    )
    aegiskv = SimpleNamespace(
        variant_id=runner.AEGISKV_VARIANT_ID,
        parameters="aegiskv-parameters",
        profile="aegiskv-profile",
        fingerprint="a" * 64,
    )
    token_ids = list(range(64))
    records = (
        {
            "span_id": "span-0",
            "messages_or_token_ids": {"kind": "token_ids", "value": token_ids},
            "prompt_token_ids_hash": runner.sha256_json(token_ids),
            "token_count_mode": "qwen3_token_ids",
        },
    )
    logical_by_concurrency = {
        concurrency: runner._canonical_schedule_for_failure_count(
            _canonical_schedule(
                runner,
                focus_prefix=f"c{concurrency}",
                failure_count=(8 if concurrency == runner.BASE_CONCURRENCY else 2),
            ),
            2,
        )
        for concurrency in runner.WORKFLOW_CONCURRENCIES
    }
    assert tuple(
        event.focus_span_id for event in logical_by_concurrency[8].events
    ) == ("c8-0", "c8-1")
    assert tuple(
        event.focus_span_id for event in logical_by_concurrency[16].events
    ) == ("c16-2", "c16-5")
    project_calls: list[dict[str, object]] = []
    run_calls: list[tuple[str, object]] = []
    gate_calls: list[tuple[object, dict[str, object]]] = []

    monkeypatch.setattr(runner, "_WORKER_RECORDS", records)
    monkeypatch.setattr(runner, "_WORKER_VARIANTS", (mooncake, aegiskv))
    monkeypatch.setattr(runner, "_WORKER_BUCKET", "96k")

    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("cell workers must never outcome-select a new schedule")

    def project(actual_records: object, **kwargs: object) -> object:
        assert actual_records is records
        project_calls.append(kwargs)
        concurrency = kwargs["workflow_concurrency"]
        assert type(concurrency) is int
        return logical_by_concurrency[concurrency]

    def run_variant(
        variant: SimpleNamespace,
        *,
        schedule: object,
        **_kwargs: object,
    ) -> dict[str, object]:
        run_calls.append((str(variant.variant_id), schedule))
        return {"variant": str(variant.variant_id)}

    def validate(system: object, **kwargs: object) -> None:
        gate_calls.append((system, kwargs))

    monkeypatch.setattr(runner, "derive_failure_schedule", unexpected)
    monkeypatch.setattr(runner, "project_failure_schedule_to_profile", project)
    monkeypatch.setattr(runner, "_run_variant", run_variant)
    monkeypatch.setattr(runner, "_validate_compact_system", validate)

    documents_by_concurrency = {
        concurrency: runner._worker_cell(
            (
                2,
                concurrency,
                7,
                ("vanilla_mooncake_dram", runner.AEGISKV_VARIANT_ID),
            ),
            logical_by_concurrency[concurrency],
            tmp_path,
            "c" * 64,
            "s" * 64,
        )
        for concurrency in runner.WORKFLOW_CONCURRENCIES
    }

    assert len(project_calls) == 8
    for call in project_calls:
        concurrency = call["workflow_concurrency"]
        assert type(concurrency) is int
        assert call["reference"] is logical_by_concurrency[concurrency]
    assert {call["workflow_concurrency"] for call in project_calls} == {8, 16, 24, 32}
    assert run_calls == [
        (variant_id, logical_by_concurrency[concurrency])
        for concurrency in runner.WORKFLOW_CONCURRENCIES
        for variant_id in ("vanilla_mooncake_dram", runner.AEGISKV_VARIANT_ID)
    ]
    assert len(gate_calls) == 8
    for concurrency, documents in documents_by_concurrency.items():
        for variant_id, document in zip(
            ("vanilla_mooncake_dram", runner.AEGISKV_VARIANT_ID),
            documents,
            strict=True,
        ):
            checkpoint_path = runner._checkpoint_path(
                tmp_path,
                (2, concurrency, 7, variant_id),
            )
            assert json.loads(checkpoint_path.read_text(encoding="utf-8")) == document
            assert (
                document["task"]["logical_plan_fingerprint"]
                == logical_by_concurrency[concurrency].fingerprint
            )


def test_pending_variant_checkpoints_group_into_one_worker_per_cell() -> None:
    runner = _load_runner()

    grouped = runner._group_variant_tasks_by_cell(
        [
            (2, 16, 0, "vanilla_mooncake_dram"),
            (2, 16, 0, runner.AEGISKV_VARIANT_ID),
            (4, 16, 0, runner.AEGISKV_VARIANT_ID),
        ]
    )

    assert grouped == [
        (2, 16, 0, ("vanilla_mooncake_dram", runner.AEGISKV_VARIANT_ID)),
        (4, 16, 0, (runner.AEGISKV_VARIANT_ID,)),
    ]
    assert runner._checkpoint_path(
        Path("checkpoints"),
        (2, 16, 0, runner.AEGISKV_VARIANT_ID),
    ) == Path("checkpoints/failure-2_concurrency-16_seed-0_aegiskv_unified.json")


def test_process_pool_abort_cancels_and_kills_without_waiting() -> None:
    runner = _load_runner()
    events: list[tuple[object, ...]] = []

    class _Future:
        def __init__(self, name: str) -> None:
            self.name = name

        def cancel(self) -> bool:
            events.append(("cancel", self.name))
            return True

    class _Process:
        def __init__(self, name: str) -> None:
            self.name = name
            self.alive = True

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            events.append(("terminate", self.name))

        def join(self, *, timeout: float) -> None:
            events.append(("join", self.name, timeout))

        def kill(self) -> None:
            events.append(("kill", self.name))
            self.alive = False

    class _Executor:
        def __init__(self) -> None:
            self._processes = {0: _Process("p0"), 1: _Process("p1")}

        def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
            events.append(("shutdown", wait, cancel_futures))

    runner._abort_process_pool(
        _Executor(),
        (_Future("f0"), _Future("f1")),
    )

    assert events[:2] == [("cancel", "f0"), ("cancel", "f1")]
    assert ("terminate", "p0") in events
    assert ("terminate", "p1") in events
    assert ("kill", "p0") in events
    assert ("kill", "p1") in events
    assert events[-1] == ("shutdown", False, True)


def test_both_runner_pools_use_fail_fast_abort_and_normal_wait() -> None:
    runner = _load_runner()
    source = inspect.getsource(runner.main)

    assert source.count("_abort_process_pool(") == 2
    assert source.count("shutdown(wait=True)") == 2
    assert "with ProcessPoolExecutor" not in source


@pytest.mark.parametrize(
    ("task_context", "expected_label"),
    (
        (
            {
                "kind": "canonical_failure_plan",
                "failure_count": 2,
                "workflow_concurrency": 32,
                "seed": 3,
                "variant_id": "vanilla_mooncake_dram",
            },
            "canonical-plan seed=3 concurrency=32",
        ),
        (
            {
                "kind": "variant_cell",
                "failure_count": 2,
                "workflow_concurrency": 32,
                "seed": 3,
                "variant_ids": ["vanilla_mooncake_dram", "aegiskv_unified"],
            },
            (
                "cell F=2 C=32 seed=3 "
                "variants=vanilla_mooncake_dram,aegiskv_unified"
            ),
        ),
    ),
)
def test_future_failure_keeps_worker_error_and_adds_task_context(
    task_context: dict[str, object],
    expected_label: str,
) -> None:
    runner = _load_runner()

    class _Future:
        def result(self) -> None:
            raise RuntimeError("future logical failure focus completed before its ordered trigger")

    with pytest.raises(runner.PaperSweepWorkerError, match=expected_label) as captured:
        runner._future_result_with_context(
            _Future(),
            task_context=task_context,
        )

    assert isinstance(captured.value.__cause__, RuntimeError)
    assert captured.value.task_context == task_context
    assert "future logical failure focus" in str(captured.value.__cause__)


def test_failure_artifact_is_atomic_and_retains_complete_exception_chain(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    output_dir = tmp_path / "failed-cell"
    task_context = runner._cell_task_binding(
        2,
        32,
        2,
        ("vanilla_mooncake_dram", runner.AEGISKV_VARIANT_ID),
    )
    captured_error: BaseException | None = None
    try:
        try:
            raise ValueError("foreground scheduler pages cannot fit physical HBM")
        except ValueError as leaf_error:
            raise runner.PaperSweepWorkerError(
                task_context=task_context,
                error=leaf_error,
            ) from leaf_error
    except runner.PaperSweepWorkerError as error:
        captured_error = error
        failure_path = runner._write_failure_artifact(
            output_dir=output_dir,
            error=error,
            task_context=error.task_context,
            source_contract_sha256="s" * 64,
            checkpoint_contract_fingerprint="c" * 64,
        )

    assert failure_path == output_dir / "FAILURE.json"
    assert failure_path.is_file()
    assert not list(output_dir.rglob("*.tmp"))
    assert not (output_dir / "paper-sweeps.json").exists()
    document = json.loads(failure_path.read_text(encoding="utf-8"))
    assert document["schema"] == runner.FAILURE_SCHEMA
    assert document["status"] == "FAIL"
    assert document["paper_ready"] is False
    assert document["task_context"] == task_context
    assert document["source_contract_sha256"] == "s" * 64
    assert document["checkpoint_contract_fingerprint"] == "c" * 64
    assert captured_error is not None
    assert [item["message"] for item in document["exception"]["chain"]] == [
        str(captured_error),
        "foreground scheduler pages cannot fit physical HBM",
    ]
    assert "ValueError: foreground scheduler pages" in document["exception"][
        "traceback"
    ]
    body = {key: value for key, value in document.items() if key != "fingerprint"}
    assert document["fingerprint"] == runner.sha256_json(body)


def test_main_canonical_worker_failure_writes_failure_artifact_and_no_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _load_runner()
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    requests_path = config_dir / "requests.json"
    failure_path = config_dir / "failure.json"
    engine_path = config_dir / "engine.json"
    workload_path = tmp_path / "workload.jsonl"
    manifest_path = tmp_path / "manifest.json"
    for path in (
        requests_path,
        failure_path,
        engine_path,
        workload_path,
        manifest_path,
    ):
        path.write_text("{}\n", encoding="utf-8")
    configs = SimpleNamespace(
        requests_path=requests_path,
        failure_path=failure_path,
        engine_path=engine_path,
        requests={"seeds": [0, 1, 2, 3, 4]},
    )
    selected_variants = tuple(
        variant
        for variant in runner.core_variants()
        if variant.variant_id in {"vanilla_mooncake_dram", runner.AEGISKV_VARIANT_ID}
    )
    parameters = selected_variants[0].parameters
    workload_manifest = {
        "selection": {
            "audit": {
                "task_count": 160,
                "context_bucket_counts": {
                    "8k": 1,
                    "32k": 0,
                    "64k": 0,
                    "96k": 0,
                    "128k": 0,
                },
                "max_observed_context_tokens": 1,
            }
        }
    }
    source_bindings = {
        "runner.py": {"path": "/source/runner.py", "sha256": "a" * 64}
    }

    def load_configs(*_args: object, **_kwargs: object) -> object:
        return configs

    def workload_paths(*_args: object, **_kwargs: object) -> tuple[Path, Path]:
        return workload_path, manifest_path

    def load_workload(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        return (), {"fingerprint": "w" * 64}, workload_manifest

    def variants(_parameters: object) -> tuple[object, ...]:
        return selected_variants

    class _FailureFuture:
        def result(self) -> None:
            raise RuntimeError("oracle exploded before checkpoint commit")

        def cancel(self) -> bool:
            return True

    class _Executor:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self._processes: dict[object, object] = {}

        def submit(self, *_args: object, **_kwargs: object) -> _FailureFuture:
            return _FailureFuture()

        def shutdown(self, *, wait: bool, cancel_futures: bool = False) -> None:
            del wait, cancel_futures

    monkeypatch.setattr(runner, "load_experiment_configs", load_configs)
    monkeypatch.setattr(
        runner,
        "model_parameters_from_configs",
        lambda _configs: parameters,
    )
    monkeypatch.setattr(runner, "workload_paths", workload_paths)
    monkeypatch.setattr(runner, "load_frozen_workload", load_workload)
    monkeypatch.setattr(runner, "core_variants", variants)
    monkeypatch.setattr(runner, "_source_bindings", lambda _root: source_bindings)
    monkeypatch.setattr(runner, "ProcessPoolExecutor", _Executor)
    monkeypatch.setattr(runner, "as_completed", lambda futures: iter(futures))

    output_dir = tmp_path / "failed-run"
    status = runner.main(
        (
            "--config-dir",
            config_dir.as_posix(),
            "--output-dir",
            output_dir.as_posix(),
            "--jobs",
            "2",
        )
    )

    assert status == 2
    failure_artifact = output_dir / "FAILURE.json"
    assert failure_artifact.is_file()
    assert failure_artifact.as_posix() in capsys.readouterr().err
    assert not list(output_dir.rglob("*.tmp"))
    assert not (output_dir / "paper-sweeps.json").exists()
    document = json.loads(failure_artifact.read_text(encoding="utf-8"))
    assert document["status"] == "FAIL"
    assert document["task_context"] == {
        "kind": "canonical_failure_plan",
        "failure_count": 2,
        "workflow_concurrency": 8,
        "seed": 0,
        "variant_id": "vanilla_mooncake_dram",
    }
    assert document["source_contract_sha256"] == runner.sha256_json(source_bindings)
    assert len(document["checkpoint_contract_fingerprint"]) == 64
    assert [entry["type"] for entry in document["exception"]["chain"]] == [
        f"{runner.PaperSweepWorkerError.__module__}.PaperSweepWorkerError",
        "builtins.RuntimeError",
    ]
    assert "oracle exploded before checkpoint commit" in document["exception"][
        "traceback"
    ]


def test_worker_cell_fails_closed_when_fixed_focus_cannot_be_projected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    variant = SimpleNamespace(
        variant_id="vanilla_mooncake_dram",
        parameters="parameters",
        profile="profile",
        fingerprint="m" * 64,
    )
    logical_schedule = runner._canonical_schedule_for_failure_count(
        _canonical_schedule(runner), 2
    )
    monkeypatch.setattr(runner, "_WORKER_RECORDS", ({"span_id": "span-0"},))
    monkeypatch.setattr(runner, "_WORKER_VARIANTS", (variant,))
    monkeypatch.setattr(runner, "_WORKER_BUCKET", "96k")

    def reject(*_args: object, **_kwargs: object) -> None:
        raise runner.ExperimentError("fixed logical focus is absent at C=24")

    monkeypatch.setattr(runner, "project_failure_schedule_to_profile", reject)

    with pytest.raises(runner.ExperimentError, match="fixed logical focus"):
        runner._worker_cell(
            (2, 24, 7, ("vanilla_mooncake_dram",)),
            logical_schedule,
            tmp_path,
            "c" * 64,
            "s" * 64,
        )
    assert not runner._checkpoint_path(
        tmp_path,
        (2, 24, 7, "vanilla_mooncake_dram"),
    ).exists()


def test_canonical_failure_subsets_are_nested_and_keep_f2_targets() -> None:
    runner = _load_runner()
    canonical = _canonical_schedule(runner)

    schedules = {
        failure_count: runner._canonical_schedule_for_failure_count(
            canonical, failure_count
        )
        for failure_count in runner.FAILURE_COUNTS
    }
    focus_sets = {
        failure_count: {event.focus_span_id for event in schedule.events}
        for failure_count, schedule in schedules.items()
    }

    assert focus_sets[1] < focus_sets[2] < focus_sets[4] < focus_sets[8]
    assert tuple(
        event.target_workload_progress_per_mille for event in schedules[2].events
    ) == (333, 667)
    assert tuple(event.focus_span_id for event in schedules[2].events) == (
        "span-2",
        "span-5",
    )


def test_only_c16_uses_f8_and_nonbase_concurrency_uses_direct_f2() -> None:
    runner = _load_runner()

    assert {
        concurrency: runner._canonical_plan_failure_count(concurrency)
        for concurrency in runner.WORKFLOW_CONCURRENCIES
    } == {8: 2, 16: 8, 24: 2, 32: 2}
    direct_f2 = _canonical_schedule(
        runner,
        focus_prefix="direct",
        failure_count=2,
    )
    assert runner._canonical_schedule_for_failure_count(direct_f2, 2) is direct_f2
    with pytest.raises(ValueError, match="only supports failure_count=2"):
        runner._canonical_schedule_for_failure_count(direct_f2, 1)


def test_bound_checkpoint_rejects_content_and_source_contract_tampering() -> None:
    runner = _load_runner()
    task = {"kind": "test", "seed": 0}
    document = runner._bound_checkpoint_document(
        schema="checkpoint.test.v1",
        task=task,
        content={"value": 1},
        contract_fingerprint="c" * 64,
        source_contract_sha256="s" * 64,
    )

    content, binding = runner._validated_checkpoint_content(
        document,
        schema="checkpoint.test.v1",
        task=task,
        contract_fingerprint="c" * 64,
        source_contract_sha256="s" * 64,
    )
    assert content == {"value": 1}
    assert binding["content_sha256"] == document["content_sha256"]

    tampered = json.loads(json.dumps(document))
    tampered["content"]["value"] = 2
    with pytest.raises(ValueError, match="content hash mismatch"):
        runner._validated_checkpoint_content(
            tampered,
            schema="checkpoint.test.v1",
            task=task,
            contract_fingerprint="c" * 64,
            source_contract_sha256="s" * 64,
        )
    with pytest.raises(ValueError, match="source contract mismatch"):
        runner._validated_checkpoint_content(
            document,
            schema="checkpoint.test.v1",
            task=task,
            contract_fingerprint="c" * 64,
            source_contract_sha256="x" * 64,
        )


def test_v4_checkpoint_resume_replays_compact_paper_gates() -> None:
    runner = _load_runner()
    logical_schedule = runner._canonical_schedule_for_failure_count(
        _canonical_schedule(runner), 2
    )
    task = (2, 16, 7, runner.AEGISKV_VARIANT_ID)
    system = _compact_system(
        runner,
        schedule=logical_schedule,
        variant_id=runner.AEGISKV_VARIANT_ID,
        variant_fingerprint="a" * 64,
    )
    content = {
        "failure_count": 2,
        "workflow_concurrency": 16,
        "seed": 7,
        "variant_id": runner.AEGISKV_VARIANT_ID,
        "system": system,
    }
    document = runner._bound_checkpoint_document(
        schema=runner.RUN_CHECKPOINT_SCHEMA,
        task=runner._variant_task_binding(
            task,
            logical_plan_fingerprint=logical_schedule.fingerprint,
        ),
        content=content,
        contract_fingerprint="c" * 64,
        source_contract_sha256="s" * 64,
    )

    restored, binding = runner._validated_run_checkpoint(
        document,
        task=task,
        contract_fingerprint="c" * 64,
        source_contract_sha256="s" * 64,
        expected_variant_fingerprint="a" * 64,
        logical_schedule=logical_schedule,
    )
    assert restored == content
    assert binding["content_sha256"] == document["content_sha256"]

    invalid_content = json.loads(json.dumps(content))
    invalid_content["system"]["run"]["workload"]["workflow_count"] = 159
    invalid_document = runner._bound_checkpoint_document(
        schema=runner.RUN_CHECKPOINT_SCHEMA,
        task=runner._variant_task_binding(
            task,
            logical_plan_fingerprint=logical_schedule.fingerprint,
        ),
        content=invalid_content,
        contract_fingerprint="c" * 64,
        source_contract_sha256="s" * 64,
    )
    with pytest.raises(runner.ExperimentError, match="exactly 160 workflows"):
        runner._validated_run_checkpoint(
            invalid_document,
            task=task,
            contract_fingerprint="c" * 64,
            source_contract_sha256="s" * 64,
            expected_variant_fingerprint="a" * 64,
            logical_schedule=logical_schedule,
        )

    invalid_content = json.loads(json.dumps(content))
    invalid_content["system"]["run"]["metrics"]["workflow_completion_time_ns"][
        "by_workflow_id"
    ].pop("workflow-159")
    invalid_document = runner._bound_checkpoint_document(
        schema=runner.RUN_CHECKPOINT_SCHEMA,
        task=runner._variant_task_binding(
            task,
            logical_plan_fingerprint=logical_schedule.fingerprint,
        ),
        content=invalid_content,
        contract_fingerprint="c" * 64,
        source_contract_sha256="s" * 64,
    )
    with pytest.raises(runner.ExperimentError, match=r"WCT map.*exactly 160"):
        runner._validated_run_checkpoint(
            invalid_document,
            task=task,
            contract_fingerprint="c" * 64,
            source_contract_sha256="s" * 64,
            expected_variant_fingerprint="a" * 64,
            logical_schedule=logical_schedule,
        )

    invalid_content = json.loads(json.dumps(content))
    invalid_content["system"]["run"]["formal_algorithm_audit"]["status"] = "BLOCKED"
    invalid_document = runner._bound_checkpoint_document(
        schema=runner.RUN_CHECKPOINT_SCHEMA,
        task=runner._variant_task_binding(
            task,
            logical_plan_fingerprint=logical_schedule.fingerprint,
        ),
        content=invalid_content,
        contract_fingerprint="c" * 64,
        source_contract_sha256="s" * 64,
    )
    with pytest.raises(runner.ExperimentError, match="report did not pass"):
        runner._validated_run_checkpoint(
            invalid_document,
            task=task,
            contract_fingerprint="c" * 64,
            source_contract_sha256="s" * 64,
            expected_variant_fingerprint="a" * 64,
            logical_schedule=logical_schedule,
        )


def test_cross_scale_alignment_allows_per_concurrency_focus_ids() -> None:
    runner = _load_runner()
    canonical_by_concurrency = {
        concurrency: _canonical_schedule(
            runner,
            focus_prefix=f"c{concurrency}",
            failure_count=(8 if concurrency == runner.BASE_CONCURRENCY else 2),
        )
        for concurrency in runner.WORKFLOW_CONCURRENCIES
    }
    cells = []
    dimensions = [
        *((failure_count, 16) for failure_count in runner.FAILURE_COUNTS),
        *((2, concurrency) for concurrency in runner.WORKFLOW_CONCURRENCIES if concurrency != 16),
    ]
    for failure_count, concurrency in dimensions:
        canonical = canonical_by_concurrency[concurrency]
        schedule = runner._canonical_schedule_for_failure_count(canonical, failure_count)
        focus_ids = [event.focus_span_id for event in schedule.events]
        cells.append(
            {
                "failure_count": failure_count,
                "workflow_concurrency": concurrency,
                "seed": 7,
                "workload_fingerprint": "w" * 64,
                "canonical_plan_fingerprint": canonical.fingerprint,
                "failure_focus_span_ids_by_system": {
                    "vanilla_mooncake_dram": focus_ids,
                    runner.AEGISKV_VARIANT_ID: focus_ids,
                },
                "failure_target_workload_progress_per_mille": [
                    event.target_workload_progress_per_mille
                    for event in schedule.events
                ],
            }
        )

    runner._validate_cross_scale_alignment(cells, seeds=(7,))

    concurrency_focuses = {
        tuple(
            cell["failure_focus_span_ids_by_system"]["vanilla_mooncake_dram"]
        )
        for cell in cells
        if cell["failure_count"] == 2
    }
    assert len(concurrency_focuses) == len(runner.WORKFLOW_CONCURRENCIES)

    drifted = json.loads(json.dumps(cells))
    concurrency_24 = next(
        cell
        for cell in drifted
        if cell["failure_count"] == 2 and cell["workflow_concurrency"] == 24
    )
    concurrency_24["failure_focus_span_ids_by_system"]["vanilla_mooncake_dram"] = [
        "drift-0",
        "drift-1",
    ]
    with pytest.raises(runner.ExperimentError, match="systems diverged"):
        runner._validate_cross_scale_alignment(drifted, seeds=(7,))

    workload_drifted = json.loads(json.dumps(cells))
    concurrency_32 = next(
        cell
        for cell in workload_drifted
        if cell["failure_count"] == 2 and cell["workflow_concurrency"] == 32
    )
    concurrency_32["workload_fingerprint"] = "x" * 64
    with pytest.raises(runner.ExperimentError, match="changed the frozen workload"):
        runner._validate_cross_scale_alignment(workload_drifted, seeds=(7,))


@pytest.mark.parametrize('failure_count', [2, 8])
def test_frozen_oracle_plan_roundtrips_but_sensitivity_drops_post_treatment_contracts(
    failure_count: int,
) -> None:
    runner = _load_runner()
    original = _canonical_schedule(runner, failure_count=failure_count)
    frozen = runner.FailureSchedule(tuple(
        runner.replace(
            event,
            physical_target_frozen=True,
            impact_contract=runner.FailureImpactContract(
                active_span_ids=(event.focus_span_id,),
                queued_span_ids=(),
                reroute_only_queued_span_ids=(),
            ),
        )
        for event in original.events
    ))
    assert runner._failure_schedule_from_dict(frozen.to_dict()) == frozen
    reduced = runner._canonical_schedule_for_failure_count(frozen, 2)
    assert len(reduced.events) == 2
    assert all(not event.physical_target_frozen for event in reduced.events)
    assert all(event.impact_contract is None for event in reduced.events)
    assert all(event.profile_impact_contracts is None for event in reduced.events)
    assert [event.target_workload_progress_per_mille for event in reduced.events] == [333, 667]


def test_zero_peer_focus_is_not_excluded_from_valid_checkpoint() -> None:
    runner = _load_runner()
    schedule = _canonical_schedule(runner, seed=0, failure_count=2)
    system = _compact_system(
        runner, schedule=schedule,
        variant_id=runner.AEGISKV_VARIANT_ID, variant_fingerprint='f' * 64,
    )
    for focus in system['run']['failure_focus_spans']:
        focus['available_peer_tokens_at_failure'] = 0
    runner._validate_compact_system(
        system, task=(2, 16, 0, runner.AEGISKV_VARIANT_ID),
        expected_variant_fingerprint='f' * 64, logical_schedule=schedule,
    )
