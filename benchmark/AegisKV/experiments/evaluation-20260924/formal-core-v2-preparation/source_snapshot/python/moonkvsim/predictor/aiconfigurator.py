"""Explicit, fail-closed AIConfigurator provider binding.

MoonKVSim does not invent a hardware profile, database, calibration, or global
latency scale.  A usable provider therefore needs both an installed package and
an exact support manifest for the selected profile.  This module only bridges a
phase-aware backend once those inputs exist.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from importlib import metadata
from typing import Protocol

from moonkvsim.predictor.schema import PredictionBatch, PredictionPhase, PredictionProfile

AICONFIGURATOR_PROVIDER_NAME = "aiconfigurator"
AICONFIGURATOR_PINNED_VERSION = "0.9.0"
AICONFIGURATOR_PINNED_COMMIT = "4b9d9dc51e02b5e9d4acc3688f3edf41693834c6"
AICONFIGURATOR_BACKEND = "vllm"


class AIConfiguratorUnavailableError(RuntimeError):
    """Raised instead of fabricating a predictor result from missing support."""


@dataclass(frozen=True, slots=True)
class AIConfiguratorDiagnostic:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class AIConfiguratorAvailability:
    diagnostics: tuple[AIConfiguratorDiagnostic, ...]

    @property
    def available(self) -> bool:
        return not self.diagnostics

    def require_available(self) -> None:
        if self.diagnostics:
            detail = "; ".join(f"{item.code}: {item.message}" for item in self.diagnostics)
            raise AIConfiguratorUnavailableError(detail)


@dataclass(frozen=True, slots=True)
class AIConfiguratorSupportManifest:
    """Exact provider coverage; this is capability metadata, not calibration."""

    provider_version: str
    provider_source_revision: str
    profile_fingerprint: str
    backend_name: str
    database_mode: str
    database_sha256: str
    hardware_profile_id: str
    hardware_profile_fingerprint: str
    model_id: str
    model_revision: str
    tensor_parallel_size: int
    pipeline_parallel_size: int
    supported_phases: tuple[PredictionPhase, ...]


class AIConfiguratorPhaseBackend(Protocol):
    """Narrow bridge implemented by a resolved AIConfigurator integration."""

    def predict_prefill_forward_ms(
        self,
        *,
        extend_lengths: tuple[int, ...],
        past_kv_lengths: tuple[int, ...],
    ) -> float: ...

    def predict_decode_forward_ms(
        self,
        *,
        past_kv_lengths: tuple[int, ...],
    ) -> float: ...


def probe_aiconfigurator(
    profile: PredictionProfile | None,
    *,
    support: AIConfiguratorSupportManifest | None,
    installed_version: str | None,
) -> AIConfiguratorAvailability:
    """Check exact model/backend/hardware/database coverage without guessing."""

    diagnostics: list[AIConfiguratorDiagnostic] = []
    if installed_version is None:
        diagnostics.append(
            AIConfiguratorDiagnostic(
                "package_unavailable",
                "the aiconfigurator distribution is not installed in this environment",
            )
        )
    elif installed_version != AICONFIGURATOR_PINNED_VERSION:
        diagnostics.append(
            AIConfiguratorDiagnostic(
                "package_version_mismatch",
                f"installed {installed_version}, pinned {AICONFIGURATOR_PINNED_VERSION}",
            )
        )
    if profile is None:
        diagnostics.append(
            AIConfiguratorDiagnostic(
                "profile_unresolved",
                "no explicit model/hardware/database prediction profile was supplied",
            )
        )
        return AIConfiguratorAvailability(tuple(diagnostics))
    if profile.provider_name != AICONFIGURATOR_PROVIDER_NAME:
        diagnostics.append(
            AIConfiguratorDiagnostic(
                "provider_mismatch",
                f"profile provider is {profile.provider_name!r}, not aiconfigurator",
            )
        )
    if profile.provider_version != AICONFIGURATOR_PINNED_VERSION:
        diagnostics.append(
            AIConfiguratorDiagnostic(
                "profile_version_mismatch",
                "profile does not use the pinned AIConfigurator version",
            )
        )
    if profile.provider_source_revision != AICONFIGURATOR_PINNED_COMMIT:
        diagnostics.append(
            AIConfiguratorDiagnostic(
                "profile_source_mismatch",
                "profile does not use the pinned AIConfigurator commit",
            )
        )
    if support is None:
        diagnostics.append(
            AIConfiguratorDiagnostic(
                "support_manifest_unavailable",
                "no explicit Qwen3/vLLM/target-hardware database support manifest exists",
            )
        )
        return AIConfiguratorAvailability(tuple(diagnostics))

    expected = {
        "provider_version": profile.provider_version,
        "provider_source_revision": profile.provider_source_revision,
        "profile_fingerprint": profile.fingerprint,
        "database_mode": profile.database_mode,
        "database_sha256": profile.database_sha256,
        "hardware_profile_id": profile.hardware_profile_id,
        "hardware_profile_fingerprint": profile.hardware_profile_fingerprint,
        "model_id": profile.model_id,
        "model_revision": profile.model_revision,
        "tensor_parallel_size": profile.tensor_parallel_size,
        "pipeline_parallel_size": profile.pipeline_parallel_size,
    }
    mismatched = tuple(
        field_name
        for field_name, expected_value in expected.items()
        if getattr(support, field_name) != expected_value
    )
    if mismatched:
        diagnostics.append(
            AIConfiguratorDiagnostic(
                "support_manifest_mismatch",
                "support manifest differs in: " + ", ".join(mismatched),
            )
        )
    if support.backend_name != AICONFIGURATOR_BACKEND:
        diagnostics.append(
            AIConfiguratorDiagnostic(
                "backend_unsupported",
                f"support manifest backend is {support.backend_name!r}, not vllm",
            )
        )
    if len(set(support.supported_phases)) != len(support.supported_phases) or set(
        support.supported_phases
    ) != set(PredictionPhase):
        diagnostics.append(
            AIConfiguratorDiagnostic(
                "phase_coverage_incomplete",
                "support manifest must cover prefill and decode separately",
            )
        )
    return AIConfiguratorAvailability(tuple(diagnostics))


def probe_local_aiconfigurator(
    profile: PredictionProfile | None = None,
    *,
    support: AIConfiguratorSupportManifest | None = None,
) -> AIConfiguratorAvailability:
    """Probe the current interpreter; source checkout presence is not installation."""

    try:
        installed_version = metadata.version(AICONFIGURATOR_PROVIDER_NAME)
    except metadata.PackageNotFoundError:
        installed_version = None
    return probe_aiconfigurator(
        profile,
        support=support,
        installed_version=installed_version,
    )


class AIConfiguratorForwardProvider:
    """Forward-only wrapper around an explicitly supported phase backend."""

    provider_name = AICONFIGURATOR_PROVIDER_NAME

    def __init__(
        self,
        *,
        profile: PredictionProfile,
        support: AIConfiguratorSupportManifest,
        backend: AIConfiguratorPhaseBackend,
        installed_version: str,
    ) -> None:
        availability = probe_aiconfigurator(
            profile,
            support=support,
            installed_version=installed_version,
        )
        availability.require_available()
        self._profile = profile
        self._backend = backend

    def predict_forward_duration_ns(self, batch: PredictionBatch) -> int:
        expected_identity = (
            self._profile.model_id,
            self._profile.model_revision,
            self._profile.tensor_parallel_size,
            self._profile.pipeline_parallel_size,
            self._profile.hardware_profile_id,
            self._profile.hardware_profile_fingerprint,
            self._profile.fingerprint,
        )
        actual_identity = (
            batch.model_id,
            batch.model_revision,
            batch.tensor_parallel_size,
            batch.pipeline_parallel_size,
            batch.hardware_profile_id,
            batch.hardware_profile_fingerprint,
            batch.profile_fingerprint,
        )
        if actual_identity != expected_identity:
            raise ValueError("prediction batch does not match the AIConfigurator profile")
        shape = batch.shape
        if batch.phase is PredictionPhase.PREFILL:
            duration_ms = self._backend.predict_prefill_forward_ms(
                extend_lengths=shape.extend_lengths,
                past_kv_lengths=shape.past_kv_lengths,
            )
        else:
            duration_ms = self._backend.predict_decode_forward_ms(
                past_kv_lengths=shape.past_kv_lengths,
            )
        if (
            isinstance(duration_ms, bool)
            or not isinstance(duration_ms, (int, float))
            or not math.isfinite(duration_ms)
            or duration_ms <= 0
        ):
            raise ValueError("AIConfigurator backend must return positive finite milliseconds")
        duration_ns = round(duration_ms * 1_000_000)
        if duration_ns <= 0:
            raise ValueError("AIConfigurator duration rounds to zero nanoseconds")
        return duration_ns
