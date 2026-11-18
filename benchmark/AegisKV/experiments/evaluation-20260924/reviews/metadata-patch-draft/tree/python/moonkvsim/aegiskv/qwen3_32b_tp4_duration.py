"""Deterministic scheduler-step duration model for Qwen3-32B TP=4.

This provider is deliberately independent of the Qwen3-8B trace-duration
provider.  It derives one whole scheduler-step duration from the exact phase
and token vectors carried by :class:`AdaptedSchedulerStep`, the pinned
Qwen3-32B architecture, and explicit A100/NVLink analytical ceilings.

The result is a closed-form, uncalibrated roofline estimate.  It is useful for
deterministic simulation only; it is neither a physical measurement nor a
calibrated prediction.  The complete assumptions and formula identities are
fingerprinted and attached to the standard scheduler-step evidence boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from moonkvsim.aegiskv.scheduler_step_bridge import (
    SchedulerStepDurationProvider,
    StepDurationEvidenceClass,
    StepDurationProviderEvidence,
)
from moonkvsim.common.hash import sha256_json
from moonkvsim.predictor.schema import (
    ForwardBoundary,
    PredictionBatch,
    PredictionPhase,
    PredictionProfile,
    PredictionRequest,
)
from moonkvsim.predictor.vllm_adapter import AdaptedPhaseBatch, AdaptedSchedulerStep

MODEL_ID: Final = "Qwen/Qwen3-32B"
MODEL_REVISION: Final = "9216db5781bf21249d130ec9da846c4624c16137"
PROVIDER_NAME: Final = "qwen3-32b-tp4-analytical-roofline"
PROVIDER_VERSION: Final = "v1-modeled-uncalibrated"
DATABASE_MODE: Final = (
    "closed-form-qwen3-32b-proposed-yarn-128k-runtime-validation-pending-no-duration-database"
)
HARDWARE_PROFILE_ID: Final = "nvidia-a100-sxm4-80gb-tp4-one-node-analytical-ceilings-v1"
MODEL_CONFIG_SOURCE: Final = (
    f"https://huggingface.co/Qwen/Qwen3-32B/blob/{MODEL_REVISION}/config.json"
)
MODEL_SAFETENSORS_INDEX_SOURCE: Final = (
    f"https://huggingface.co/Qwen/Qwen3-32B/blob/{MODEL_REVISION}/model.safetensors.index.json"
)
HARDWARE_SPEC_SOURCE: Final = "https://www.nvidia.com/en-gb/data-center/a100/"
COLLECTIVE_COST_SOURCE: Final = (
    "benchmark/AegisKV/experiments/configs/engine/qwen3-32b-dp8-tp4-8node-a100-80gb.json"
)
TIMING_AND_BANDWIDTH: Final = "modeled_uncalibrated"
ALLOWED_CLAIM: Final = "simulation_only"
COLLECTIVE_SCOPE: Final = "two TP=4 ring all-reduces per transformer layer on one inference node"
NATIVE_MAX_CONTEXT_TOKENS: Final = 40_960
MAX_CONTEXT_TOKENS: Final = 131_072
CONTEXT_EXTENSION_PROVENANCE: Final = "proposed_yarn_128k_modeled_not_runtime_validated"
KV_LAYOUT_STATUS: Final = "proposed_yarn_128k_modeled_runtime_validation_pending"
MODEL_SAFETENSORS_TOTAL_BYTES: Final = 65_524_246_528
MODEL_WEIGHTS_PROVENANCE: Final = (
    "locked_revision_safetensors_index_total_size_65524246528_evenly_divided_by_tp4_"
    "runtime_partition_validation_pending"
)
ISOLATED_REQUEST_SCHEDULING_RULE: Final = (
    "chunk_prompt_without_truncation_then_output_tokens_minus_one_single_token_decode_steps"
)


def _positive_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _ceil_div(numerator: int, denominator: int) -> int:
    if numerator < 0 or denominator <= 0:
        raise ValueError("ceil division requires a non-negative numerator and positive divisor")
    return (numerator + denominator - 1) // denominator


@dataclass(frozen=True, slots=True)
class Qwen3TP4AnalyticalParameters:
    """All numerical assumptions used by the analytical duration provider.

    Model dimensions are the fields in the pinned Qwen3-32B ``config.json``.
    The A100 values are published dense BF16 and HBM peak ceilings.  The
    collective bandwidth/setup values are the repository's explicit
    uncalibrated intra-node values, not an NCCL measurement.
    """

    hidden_size: int = 5_120
    intermediate_size: int = 25_600
    num_hidden_layers: int = 64
    num_attention_heads: int = 64
    num_kv_heads: int = 8
    head_dim: int = 128
    vocab_size: int = 151_936
    native_max_context_tokens: int = NATIVE_MAX_CONTEXT_TOKENS
    max_context_tokens: int = MAX_CONTEXT_TOKENS
    model_safetensors_total_bytes: int = MODEL_SAFETENSORS_TOTAL_BYTES
    scalar_bytes: int = 2
    tensor_parallel_size: int = 4
    pipeline_parallel_size: int = 1
    dense_bf16_flops_per_second_per_gpu: int = 312_000_000_000_000
    hbm_bandwidth_bytes_per_second_per_gpu: int = 2_039_000_000_000
    collective_bandwidth_bytes_per_second_per_rank: int = 100_000_000_000
    collective_setup_ns: int = 1_000
    model_all_reduces_per_layer: int = 2

    def __post_init__(self) -> None:
        for field_name in (
            "hidden_size",
            "intermediate_size",
            "num_hidden_layers",
            "num_attention_heads",
            "num_kv_heads",
            "head_dim",
            "vocab_size",
            "native_max_context_tokens",
            "max_context_tokens",
            "model_safetensors_total_bytes",
            "scalar_bytes",
            "tensor_parallel_size",
            "pipeline_parallel_size",
            "dense_bf16_flops_per_second_per_gpu",
            "hbm_bandwidth_bytes_per_second_per_gpu",
            "collective_bandwidth_bytes_per_second_per_rank",
            "collective_setup_ns",
            "model_all_reduces_per_layer",
        ):
            _positive_int(getattr(self, field_name), field_name)
        expected_model = {
            "hidden_size": 5_120,
            "intermediate_size": 25_600,
            "num_hidden_layers": 64,
            "num_attention_heads": 64,
            "num_kv_heads": 8,
            "head_dim": 128,
            "vocab_size": 151_936,
            "native_max_context_tokens": NATIVE_MAX_CONTEXT_TOKENS,
            "max_context_tokens": MAX_CONTEXT_TOKENS,
            "model_safetensors_total_bytes": MODEL_SAFETENSORS_TOTAL_BYTES,
            "scalar_bytes": 2,
            "tensor_parallel_size": 4,
            "pipeline_parallel_size": 1,
            "model_all_reduces_per_layer": 2,
        }
        for field_name, expected in expected_model.items():
            if getattr(self, field_name) != expected:
                raise ValueError(
                    f"Qwen3-32B TP4 requires {field_name}={expected}; "
                    f"got {getattr(self, field_name)}"
                )
        if self.num_attention_heads % self.tensor_parallel_size:
            raise ValueError("attention heads must shard evenly across TP ranks")
        if self.num_kv_heads % self.tensor_parallel_size:
            raise ValueError("KV heads must shard evenly across TP ranks")
        if self.model_safetensors_total_bytes % self.tensor_parallel_size:
            raise ValueError("locked safetensors total_size must divide evenly across TP ranks")

    @property
    def kv_hidden_size(self) -> int:
        return self.num_kv_heads * self.head_dim

    @property
    def query_hidden_size(self) -> int:
        # Qwen3-32B deliberately uses 64 x 128 query heads (8192 projected
        # coordinates) with a 5120-wide residual stream.  Do not substitute
        # hidden_size for the Q/O projection width.
        return self.num_attention_heads * self.head_dim

    @property
    def vocab_size_per_tp_rank(self) -> int:
        return _ceil_div(self.vocab_size, self.tensor_parallel_size)

    @property
    def transformer_matrix_parameters_per_layer(self) -> int:
        # Q is HxQH and O is QHxH; K and V are HxKVH; SwiGLU contains
        # gate, up, and down matrices with total size 3*H*I.
        return (
            2 * self.hidden_size * self.query_hidden_size
            + 2 * self.hidden_size * self.kv_hidden_size
            + 3 * self.hidden_size * self.intermediate_size
        )

    @property
    def transformer_weight_bytes_per_rank(self) -> int:
        return (
            self.num_hidden_layers
            * _ceil_div(
                self.transformer_matrix_parameters_per_layer,
                self.tensor_parallel_size,
            )
            * self.scalar_bytes
        )

    @property
    def lm_head_weight_bytes_per_rank(self) -> int:
        return self.hidden_size * self.vocab_size_per_tp_rank * self.scalar_bytes

    @property
    def analytical_main_matrix_weight_bytes_per_rank(self) -> int:
        """Main matrices counted by the FLOP formula, expressed as BF16 bytes."""

        return self.transformer_weight_bytes_per_rank + self.lm_head_weight_bytes_per_rank

    @property
    def model_weights_bytes_per_rank(self) -> int:
        """Exact locked safetensors index total_size divided evenly by TP4."""

        return self.model_safetensors_total_bytes // self.tensor_parallel_size

    @property
    def non_main_matrix_weight_bytes_per_rank(self) -> int:
        """Index bytes absent from the explicit main-matrix FLOP derivation."""

        delta = (
            self.model_weights_bytes_per_rank - self.analytical_main_matrix_weight_bytes_per_rank
        )
        if delta < 0:
            raise ValueError("analytical main-matrix weights exceed locked safetensors bytes")
        return delta

    @property
    def shared_weight_bytes_per_rank(self) -> int:
        """Exact model bytes scanned once by a non-empty whole scheduler step."""

        return self.model_weights_bytes_per_rank

    def model_document(self) -> dict[str, object]:
        return {
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "source": MODEL_CONFIG_SOURCE,
            "hidden_size": self.hidden_size,
            "intermediate_size": self.intermediate_size,
            "num_hidden_layers": self.num_hidden_layers,
            "num_attention_heads": self.num_attention_heads,
            "num_kv_heads": self.num_kv_heads,
            "head_dim": self.head_dim,
            "query_hidden_size": self.query_hidden_size,
            "kv_hidden_size": self.kv_hidden_size,
            "vocab_size": self.vocab_size,
            "native_max_context_tokens": self.native_max_context_tokens,
            "max_context_tokens": self.max_context_tokens,
            "context_extension_provenance": CONTEXT_EXTENSION_PROVENANCE,
            "kv_layout_status": KV_LAYOUT_STATUS,
            "scalar_bytes": self.scalar_bytes,
            "tensor_parallel_size": self.tensor_parallel_size,
            "pipeline_parallel_size": self.pipeline_parallel_size,
            "safetensors_index_source": MODEL_SAFETENSORS_INDEX_SOURCE,
            "model_safetensors_total_bytes": self.model_safetensors_total_bytes,
            "model_weights_bytes_per_rank": self.model_weights_bytes_per_rank,
            "model_weights_provenance": MODEL_WEIGHTS_PROVENANCE,
        }

    @property
    def model_fingerprint(self) -> str:
        return sha256_json(self.model_document())

    def hardware_document(self) -> dict[str, object]:
        return {
            "hardware_profile_id": HARDWARE_PROFILE_ID,
            "gpu": "NVIDIA-A100-SXM4-80GB",
            "tp_group_placement": "one_complete_tp4_replica_per_node",
            "published_peak_source": HARDWARE_SPEC_SOURCE,
            "dense_bf16_flops_per_second_per_gpu": (self.dense_bf16_flops_per_second_per_gpu),
            "hbm_bandwidth_bytes_per_second_per_gpu": (self.hbm_bandwidth_bytes_per_second_per_gpu),
            "modeled_collective_source": COLLECTIVE_COST_SOURCE,
            "collective_transport": "NVLINK",
            "collective_bandwidth_bytes_per_second_per_rank": (
                self.collective_bandwidth_bytes_per_second_per_rank
            ),
            "collective_setup_ns": self.collective_setup_ns,
        }

    @property
    def hardware_fingerprint(self) -> str:
        return sha256_json(self.hardware_document())

    def formula_document(self) -> dict[str, object]:
        return {
            "schema": "moonkvsim.aegiskv.qwen3_32b_tp4_duration_formula.v1",
            "phase_attention_pairs": ("sum_i(extend_i*past_i + extend_i*(extend_i+1)/2)"),
            "transformer_matmul_flops_per_rank": ("2*layers*tokens*(2*H*QH+2*H*KVH+3*H*I)/TP"),
            "attention_qk_av_flops_per_rank": (
                "4*layers*attention_pairs*attention_heads*head_dim/TP"
            ),
            "lm_head_flops_per_rank": "2*batch_size*H*ceil(vocab_size/TP)",
            "weight_hbm_bytes_per_rank": (
                "locked safetensors index total_size divided by TP4, scanned once per step"
            ),
            "analytical_main_matrix_weight_bytes_per_rank": (
                self.analytical_main_matrix_weight_bytes_per_rank
            ),
            "non_main_matrix_weight_bytes_per_rank": (self.non_main_matrix_weight_bytes_per_rank),
            "dynamic_hbm_bytes_per_rank": [
                "embedding reads",
                "transformer block-boundary activation reads and writes",
                "sharded KV-cache reads for every causal attention pair",
                "sharded KV-cache writes for every extended token",
                "sharded LM-head output writes",
            ],
            "roofline_composition": "max(ceil(FLOPs/peak),ceil(HBM_bytes/peak))",
            "collective_algorithm": ("ring all-reduce; bytes/rank=ceil(2*(TP-1)*payload/TP)"),
            "collective_scope": COLLECTIVE_SCOPE,
            "collective_composition": "roofline_ns + sum(all_reduce_ns)",
            "model_all_reduces_per_layer": self.model_all_reduces_per_layer,
            "lm_head_position_rule": "one logits position per scheduled request",
            "isolated_request_scheduling_rule": ISOLATED_REQUEST_SCHEDULING_RULE,
            "no_empirical_scale_or_shape_factor": True,
            "not_modeled": [
                "RMSNorm RoPE softmax SiLU and other non-GEMM kernel execution",
                "kernel launch CUDA graph cache residency overlap and contention",
                "sampling and inter-rank logits communication",
                "scheduler CPU connector metadata KV transfer recovery and failure control",
            ],
        }

    @property
    def database_sha256(self) -> str:
        return sha256_json(
            {
                "database_mode": DATABASE_MODE,
                "model": self.model_document(),
                "formula": self.formula_document(),
            }
        )

    def provenance_fields(self) -> dict[str, object]:
        return {
            "schema": "moonkvsim.aegiskv.qwen3_32b_tp4_duration_provenance.v1",
            "provider_name": PROVIDER_NAME,
            "provider_version": PROVIDER_VERSION,
            "timing_and_bandwidth": TIMING_AND_BANDWIDTH,
            "calibrated": False,
            "physical_measurement_completed": False,
            "formal_use_allowed": False,
            "allowed_claim": ALLOWED_CLAIM,
            "database_mode": DATABASE_MODE,
            "database_sha256": self.database_sha256,
            "model": {**self.model_document(), "fingerprint": self.model_fingerprint},
            "hardware": {
                **self.hardware_document(),
                "fingerprint": self.hardware_fingerprint,
            },
            "formula": self.formula_document(),
        }


def build_qwen3_32b_tp4_prediction_profile(
    *,
    provider_source_revision: str,
    parameters: Qwen3TP4AnalyticalParameters | None = None,
) -> PredictionProfile:
    """Build the one profile accepted by the Qwen3-32B TP4 provider.

    ``provider_source_revision`` is intentionally mandatory: a caller must bind
    the uncalibrated model to an explicit source commit instead of receiving a
    fabricated or environment-dependent revision.
    """

    resolved = parameters or Qwen3TP4AnalyticalParameters()
    return PredictionProfile(
        provider_name=PROVIDER_NAME,
        provider_version=PROVIDER_VERSION,
        provider_source_revision=provider_source_revision,
        database_mode=DATABASE_MODE,
        database_sha256=resolved.database_sha256,
        hardware_profile_id=HARDWARE_PROFILE_ID,
        hardware_profile_fingerprint=resolved.hardware_fingerprint,
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        tensor_parallel_size=resolved.tensor_parallel_size,
        pipeline_parallel_size=resolved.pipeline_parallel_size,
        forward_boundary=ForwardBoundary(
            includes_model_collectives=True,
            model_collective_scope=COLLECTIVE_SCOPE,
        ),
    )


@dataclass(frozen=True, slots=True)
class Qwen3TP4PhaseDurationBreakdown:
    """Exact analytical work derived from one phase batch."""

    phase: PredictionPhase
    request_ids: tuple[str, ...]
    batch_fingerprint: str
    batch_size: int
    total_extend_tokens: int
    attention_pairs: int
    transformer_matmul_flops_per_rank: int
    attention_flops_per_rank: int
    lm_head_flops_per_rank: int
    total_compute_flops_per_rank: int
    embedding_read_bytes_per_rank: int
    activation_bytes_per_rank: int
    kv_read_bytes_per_rank: int
    kv_write_bytes_per_rank: int
    lm_head_output_bytes_per_rank: int
    dynamic_hbm_bytes_per_rank: int

    def canonical_fields(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "request_ids": list(self.request_ids),
            "batch_fingerprint": self.batch_fingerprint,
            "batch_size": self.batch_size,
            "total_extend_tokens": self.total_extend_tokens,
            "attention_pairs": self.attention_pairs,
            "transformer_matmul_flops_per_rank": (self.transformer_matmul_flops_per_rank),
            "attention_flops_per_rank": self.attention_flops_per_rank,
            "lm_head_flops_per_rank": self.lm_head_flops_per_rank,
            "total_compute_flops_per_rank": self.total_compute_flops_per_rank,
            "embedding_read_bytes_per_rank": self.embedding_read_bytes_per_rank,
            "activation_bytes_per_rank": self.activation_bytes_per_rank,
            "kv_read_bytes_per_rank": self.kv_read_bytes_per_rank,
            "kv_write_bytes_per_rank": self.kv_write_bytes_per_rank,
            "lm_head_output_bytes_per_rank": self.lm_head_output_bytes_per_rank,
            "dynamic_hbm_bytes_per_rank": self.dynamic_hbm_bytes_per_rank,
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        result = self.canonical_fields()
        result["fingerprint"] = self.fingerprint
        return result


@dataclass(frozen=True, slots=True)
class Qwen3TP4StepDurationBreakdown:
    """Auditable cost composition for one complete scheduler step."""

    step_fingerprint: str
    provenance_fingerprint: str
    phases: tuple[Qwen3TP4PhaseDurationBreakdown, ...]
    shared_weight_bytes_per_rank: int
    total_compute_flops_per_rank: int
    total_hbm_bytes_per_rank: int
    compute_ns: int
    hbm_ns: int
    roofline_ns: int
    collective_payload_bytes_per_rank: int
    ring_collective_bytes_per_rank_per_all_reduce: int
    collective_count: int
    collective_ns: int
    duration_ns: int

    def canonical_fields(self) -> dict[str, object]:
        return {
            "schema": "moonkvsim.aegiskv.qwen3_32b_tp4_step_duration.v1",
            "timing_and_bandwidth": TIMING_AND_BANDWIDTH,
            "calibrated": False,
            "physical_measurement_completed": False,
            "formal_use_allowed": False,
            "allowed_claim": ALLOWED_CLAIM,
            "step_fingerprint": self.step_fingerprint,
            "provenance_fingerprint": self.provenance_fingerprint,
            "phases": [phase.to_dict() for phase in self.phases],
            "shared_weight_bytes_per_rank": self.shared_weight_bytes_per_rank,
            "total_compute_flops_per_rank": self.total_compute_flops_per_rank,
            "total_hbm_bytes_per_rank": self.total_hbm_bytes_per_rank,
            "compute_ns": self.compute_ns,
            "hbm_ns": self.hbm_ns,
            "roofline_ns": self.roofline_ns,
            "collective_payload_bytes_per_rank": (self.collective_payload_bytes_per_rank),
            "ring_collective_bytes_per_rank_per_all_reduce": (
                self.ring_collective_bytes_per_rank_per_all_reduce
            ),
            "collective_count": self.collective_count,
            "collective_ns": self.collective_ns,
            "duration_ns": self.duration_ns,
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        result = self.canonical_fields()
        result["fingerprint"] = self.fingerprint
        return result


@dataclass(frozen=True, slots=True)
class Qwen3TP4IsolatedRequestDurationBreakdown:
    """Algorithm-1 isolated duration composed from ordinary scheduler steps."""

    prompt_tokens: int
    output_tokens: int
    max_num_scheduled_tokens: int
    covered_prompt_tokens: int
    prefill_step_count: int
    decode_step_count: int
    steps: tuple[Qwen3TP4StepDurationBreakdown, ...]
    provenance_fingerprint: str
    duration_ns: int

    def __post_init__(self) -> None:
        _positive_int(self.prompt_tokens, "prompt_tokens")
        _positive_int(self.output_tokens, "output_tokens")
        _positive_int(self.max_num_scheduled_tokens, "max_num_scheduled_tokens")
        _positive_int(self.prefill_step_count, "prefill_step_count")
        if type(self.decode_step_count) is not int or self.decode_step_count < 0:
            raise ValueError("decode_step_count must be a non-negative integer")
        if self.covered_prompt_tokens != self.prompt_tokens:
            raise ValueError("isolated request duration must cover every prompt token")
        if self.decode_step_count != self.output_tokens - 1:
            raise ValueError("decode steps must equal output_tokens minus one")
        if len(self.steps) != self.prefill_step_count + self.decode_step_count:
            raise ValueError("isolated request step counts do not cover the step records")
        if self.duration_ns != sum(step.duration_ns for step in self.steps):
            raise ValueError("isolated request duration does not equal the scheduler-step sum")

    def canonical_fields(self) -> dict[str, object]:
        return {
            "schema": "moonkvsim.aegiskv.qwen3_32b_tp4_isolated_request_duration.v1",
            "timing_and_bandwidth": TIMING_AND_BANDWIDTH,
            "calibrated": False,
            "physical_measurement_completed": False,
            "formal_use_allowed": False,
            "allowed_claim": ALLOWED_CLAIM,
            "scheduling_rule": ISOLATED_REQUEST_SCHEDULING_RULE,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "max_num_scheduled_tokens": self.max_num_scheduled_tokens,
            "covered_prompt_tokens": self.covered_prompt_tokens,
            "prefill_step_count": self.prefill_step_count,
            "decode_step_count": self.decode_step_count,
            "scheduler_step_count": len(self.steps),
            "steps": [step.to_dict() for step in self.steps],
            "provenance_fingerprint": self.provenance_fingerprint,
            "duration_ns": self.duration_ns,
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        result = self.canonical_fields()
        result["fingerprint"] = self.fingerprint
        return result


class Qwen3TP4SchedulerStepDurationProvider(SchedulerStepDurationProvider):
    """Qwen3-32B TP4-only uncalibrated analytical duration provider."""

    def __init__(
        self,
        *,
        prediction_profile: PredictionProfile,
        parameters: Qwen3TP4AnalyticalParameters | None = None,
    ) -> None:
        if not isinstance(prediction_profile, PredictionProfile):
            raise TypeError("prediction_profile must be a PredictionProfile")
        self.prediction_profile = prediction_profile
        self.parameters = parameters or Qwen3TP4AnalyticalParameters()
        self._validate_profile(prediction_profile)

    @property
    def provenance(self) -> dict[str, object]:
        fields = {
            **self.parameters.provenance_fields(),
            "prediction_profile": self.prediction_profile.to_dict(),
        }
        return {**fields, "fingerprint": sha256_json(fields)}

    @property
    def provenance_fingerprint(self) -> str:
        fingerprint = self.provenance["fingerprint"]
        assert isinstance(fingerprint, str)
        return fingerprint

    @property
    def evidence(self) -> StepDurationProviderEvidence:
        return StepDurationProviderEvidence(
            provider_name=PROVIDER_NAME,
            provider_version=PROVIDER_VERSION,
            prediction_profile_fingerprint=self.prediction_profile.fingerprint,
            provenance_sha256=self.provenance_fingerprint,
            evidence_class=StepDurationEvidenceClass.UNCALIBRATED_MODEL,
            physically_measured=False,
            formal_use_allowed=False,
        )

    def predict_step_duration_ns(self, step: AdaptedSchedulerStep) -> int:
        return self.predict_step(step).duration_ns

    def predict_isolated_request_duration_ns(
        self,
        *,
        prompt_tokens: int,
        output_tokens: int,
        max_num_scheduled_tokens: int = 4_096,
    ) -> int:
        """Return Algorithm-1 isolated duration using continuous scheduling semantics."""

        return self.predict_isolated_request(
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            max_num_scheduled_tokens=max_num_scheduled_tokens,
        ).duration_ns

    def predict_isolated_request(
        self,
        *,
        prompt_tokens: int,
        output_tokens: int,
        max_num_scheduled_tokens: int = 4_096,
    ) -> Qwen3TP4IsolatedRequestDurationBreakdown:
        """Compose an isolated request from prefill chunks and decode steps.

        The terminal prefill step produces output token one.  Each subsequent
        output requires one ordinary single-token decode step, matching the
        continuous scheduler's ``prompt + max_output - 1`` forward-token
        convention.  Prompt chunks are never padded or truncated.
        """

        _positive_int(prompt_tokens, "prompt_tokens")
        _positive_int(output_tokens, "output_tokens")
        _positive_int(max_num_scheduled_tokens, "max_num_scheduled_tokens")
        if prompt_tokens + output_tokens > self.parameters.max_context_tokens:
            raise ValueError(
                "isolated Qwen3-32B request exceeds the proposed YaRN 131072-token context"
            )

        steps: list[Qwen3TP4StepDurationBreakdown] = []
        covered_prompt_tokens = 0
        prefill_step_count = 0
        while covered_prompt_tokens < prompt_tokens:
            extend_length = min(
                max_num_scheduled_tokens,
                prompt_tokens - covered_prompt_tokens,
            )
            step = self._isolated_step(
                phase=PredictionPhase.PREFILL,
                step_index=prefill_step_count,
                extend_length=extend_length,
                past_kv_length=covered_prompt_tokens,
            )
            steps.append(self.predict_step(step))
            covered_prompt_tokens += extend_length
            prefill_step_count += 1

        decode_step_count = output_tokens - 1
        for decode_index in range(decode_step_count):
            step = self._isolated_step(
                phase=PredictionPhase.DECODE,
                step_index=prefill_step_count + decode_index,
                extend_length=1,
                past_kv_length=prompt_tokens + decode_index,
            )
            steps.append(self.predict_step(step))

        return Qwen3TP4IsolatedRequestDurationBreakdown(
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            max_num_scheduled_tokens=max_num_scheduled_tokens,
            covered_prompt_tokens=covered_prompt_tokens,
            prefill_step_count=prefill_step_count,
            decode_step_count=decode_step_count,
            steps=tuple(steps),
            provenance_fingerprint=self.provenance_fingerprint,
            duration_ns=sum(step.duration_ns for step in steps),
        )

    def predict_step(self, step: AdaptedSchedulerStep) -> Qwen3TP4StepDurationBreakdown:
        if not isinstance(step, AdaptedSchedulerStep):
            raise TypeError("step must be an AdaptedSchedulerStep")
        if not step.has_forward:
            raise ValueError("Qwen3-32B duration provider requires a non-empty forward step")
        phases = tuple(self._phase_breakdown(phase_batch) for phase_batch in step.phase_batches)
        parameters = self.parameters
        total_tokens = sum(phase.total_extend_tokens for phase in phases)
        total_compute_flops = sum(phase.total_compute_flops_per_rank for phase in phases)
        total_hbm_bytes = parameters.shared_weight_bytes_per_rank + sum(
            phase.dynamic_hbm_bytes_per_rank for phase in phases
        )
        compute_ns = _ceil_div(
            total_compute_flops * 1_000_000_000,
            parameters.dense_bf16_flops_per_second_per_gpu,
        )
        hbm_ns = _ceil_div(
            total_hbm_bytes * 1_000_000_000,
            parameters.hbm_bandwidth_bytes_per_second_per_gpu,
        )
        roofline_ns = max(compute_ns, hbm_ns)
        collective_payload = total_tokens * parameters.hidden_size * parameters.scalar_bytes
        ring_collective_bytes = _ceil_div(
            2 * (parameters.tensor_parallel_size - 1) * collective_payload,
            parameters.tensor_parallel_size,
        )
        collective_count = parameters.num_hidden_layers * parameters.model_all_reduces_per_layer
        one_collective_ns = parameters.collective_setup_ns + _ceil_div(
            ring_collective_bytes * 1_000_000_000,
            parameters.collective_bandwidth_bytes_per_second_per_rank,
        )
        collective_ns = collective_count * one_collective_ns
        duration_ns = roofline_ns + collective_ns
        if duration_ns <= 0:
            raise RuntimeError("analytical duration did not produce a positive duration")
        return Qwen3TP4StepDurationBreakdown(
            step_fingerprint=step.fingerprint,
            provenance_fingerprint=self.provenance_fingerprint,
            phases=phases,
            shared_weight_bytes_per_rank=parameters.shared_weight_bytes_per_rank,
            total_compute_flops_per_rank=total_compute_flops,
            total_hbm_bytes_per_rank=total_hbm_bytes,
            compute_ns=compute_ns,
            hbm_ns=hbm_ns,
            roofline_ns=roofline_ns,
            collective_payload_bytes_per_rank=collective_payload,
            ring_collective_bytes_per_rank_per_all_reduce=ring_collective_bytes,
            collective_count=collective_count,
            collective_ns=collective_ns,
            duration_ns=duration_ns,
        )

    def _validate_profile(self, profile: PredictionProfile) -> None:
        parameters = self.parameters
        expected = {
            "provider_name": PROVIDER_NAME,
            "provider_version": PROVIDER_VERSION,
            "database_mode": DATABASE_MODE,
            "database_sha256": parameters.database_sha256,
            "hardware_profile_id": HARDWARE_PROFILE_ID,
            "hardware_profile_fingerprint": parameters.hardware_fingerprint,
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "tensor_parallel_size": parameters.tensor_parallel_size,
            "pipeline_parallel_size": parameters.pipeline_parallel_size,
        }
        for field_name, expected_value in expected.items():
            if getattr(profile, field_name) != expected_value:
                raise ValueError(
                    f"Qwen3-32B TP4 profile mismatch for {field_name}: "
                    f"expected {expected_value!r}, got {getattr(profile, field_name)!r}"
                )
        boundary = profile.forward_boundary
        if (
            not boundary.includes_model_collectives
            or boundary.model_collective_scope != COLLECTIVE_SCOPE
        ):
            raise ValueError("Qwen3-32B TP4 profile must include the exact TP collective scope")

    def _phase_breakdown(self, phase_batch: AdaptedPhaseBatch) -> Qwen3TP4PhaseDurationBreakdown:
        if not isinstance(phase_batch, AdaptedPhaseBatch):
            raise TypeError("phase batch must be an AdaptedPhaseBatch")
        self._validate_batch(phase_batch.batch)
        parameters = self.parameters
        batch = phase_batch.batch
        tokens = batch.shape.total_extend_length
        attention_pairs = sum(
            request.extend_length * request.past_kv_length
            + request.extend_length * (request.extend_length + 1) // 2
            for request in batch.requests
        )
        transformer_matmul_flops = _ceil_div(
            2
            * parameters.num_hidden_layers
            * tokens
            * parameters.transformer_matrix_parameters_per_layer,
            parameters.tensor_parallel_size,
        )
        attention_flops = _ceil_div(
            4
            * parameters.num_hidden_layers
            * attention_pairs
            * parameters.num_attention_heads
            * parameters.head_dim,
            parameters.tensor_parallel_size,
        )
        lm_head_flops = (
            2 * batch.shape.batch_size * parameters.hidden_size * parameters.vocab_size_per_tp_rank
        )
        embedding_read_bytes = tokens * parameters.hidden_size * parameters.scalar_bytes
        activation_bytes = (
            parameters.num_hidden_layers
            * tokens
            * 2
            * parameters.hidden_size
            * parameters.scalar_bytes
        )
        kv_elements_per_rank = _ceil_div(
            parameters.kv_hidden_size,
            parameters.tensor_parallel_size,
        )
        kv_read_bytes = (
            parameters.num_hidden_layers
            * attention_pairs
            * 2
            * kv_elements_per_rank
            * parameters.scalar_bytes
        )
        kv_write_bytes = (
            parameters.num_hidden_layers
            * tokens
            * 2
            * kv_elements_per_rank
            * parameters.scalar_bytes
        )
        lm_head_output_bytes = (
            batch.shape.batch_size * parameters.vocab_size_per_tp_rank * parameters.scalar_bytes
        )
        dynamic_hbm_bytes = (
            embedding_read_bytes
            + activation_bytes
            + kv_read_bytes
            + kv_write_bytes
            + lm_head_output_bytes
        )
        return Qwen3TP4PhaseDurationBreakdown(
            phase=batch.phase,
            request_ids=phase_batch.request_ids,
            batch_fingerprint=batch.fingerprint,
            batch_size=batch.shape.batch_size,
            total_extend_tokens=tokens,
            attention_pairs=attention_pairs,
            transformer_matmul_flops_per_rank=transformer_matmul_flops,
            attention_flops_per_rank=attention_flops,
            lm_head_flops_per_rank=lm_head_flops,
            total_compute_flops_per_rank=(
                transformer_matmul_flops + attention_flops + lm_head_flops
            ),
            embedding_read_bytes_per_rank=embedding_read_bytes,
            activation_bytes_per_rank=activation_bytes,
            kv_read_bytes_per_rank=kv_read_bytes,
            kv_write_bytes_per_rank=kv_write_bytes,
            lm_head_output_bytes_per_rank=lm_head_output_bytes,
            dynamic_hbm_bytes_per_rank=dynamic_hbm_bytes,
        )

    def _validate_batch(self, batch: PredictionBatch) -> None:
        if not isinstance(batch, PredictionBatch):
            raise TypeError("phase batch must contain a PredictionBatch")
        expected = {
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "tensor_parallel_size": self.parameters.tensor_parallel_size,
            "pipeline_parallel_size": self.parameters.pipeline_parallel_size,
            "hardware_profile_id": HARDWARE_PROFILE_ID,
            "hardware_profile_fingerprint": self.parameters.hardware_fingerprint,
            "profile_fingerprint": self.prediction_profile.fingerprint,
        }
        for field_name, expected_value in expected.items():
            if getattr(batch, field_name) != expected_value:
                raise ValueError(
                    f"Qwen3-32B TP4 batch mismatch for {field_name}: "
                    f"expected {expected_value!r}, got {getattr(batch, field_name)!r}"
                )
        for request in batch.requests:
            if request.resulting_context_length > self.parameters.max_context_tokens:
                raise ValueError(
                    "Qwen3-32B scheduler batch exceeds the proposed YaRN 131072-token context"
                )

    def _isolated_step(
        self,
        *,
        phase: PredictionPhase,
        step_index: int,
        extend_length: int,
        past_kv_length: int,
    ) -> AdaptedSchedulerStep:
        request_id = "isolated-request"
        batch = PredictionBatch.for_profile(
            requests=(
                PredictionRequest(
                    extend_length=extend_length,
                    past_kv_length=past_kv_length,
                ),
            ),
            phase=phase,
            profile=self.prediction_profile,
        )
        phase_batch = AdaptedPhaseBatch(request_ids=(request_id,), batch=batch)
        scheduler_output_fingerprint = sha256_json(
            {
                "schema": "moonkvsim.aegiskv.qwen3_32b_tp4_isolated_step.v1",
                "profile_fingerprint": self.prediction_profile.fingerprint,
                "step_index": step_index,
                "phase": phase.value,
                "extend_length": extend_length,
                "past_kv_length": past_kv_length,
            }
        )
        return AdaptedSchedulerStep(
            scheduled_request_ids=(request_id,),
            phase_batches=(phase_batch,),
            scheduler_output_fingerprint=scheduler_output_fingerprint,
        )


__all__ = [
    "ALLOWED_CLAIM",
    "COLLECTIVE_SCOPE",
    "DATABASE_MODE",
    "HARDWARE_PROFILE_ID",
    "MAX_CONTEXT_TOKENS",
    "MODEL_ID",
    "MODEL_REVISION",
    "MODEL_SAFETENSORS_TOTAL_BYTES",
    "NATIVE_MAX_CONTEXT_TOKENS",
    "PROVIDER_NAME",
    "PROVIDER_VERSION",
    "TIMING_AND_BANDWIDTH",
    "Qwen3TP4AnalyticalParameters",
    "Qwen3TP4IsolatedRequestDurationBreakdown",
    "Qwen3TP4PhaseDurationBreakdown",
    "Qwen3TP4SchedulerStepDurationProvider",
    "Qwen3TP4StepDurationBreakdown",
    "build_qwen3_32b_tp4_prediction_profile",
]
