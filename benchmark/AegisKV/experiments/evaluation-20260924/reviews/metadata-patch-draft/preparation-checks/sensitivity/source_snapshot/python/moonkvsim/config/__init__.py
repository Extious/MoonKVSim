"""Fail-closed configuration and trace-schema validation."""

from .bundle import (
    ConfigBundleError,
    ResolvedConfigBundle,
    load_config_bundle,
    resolve_config_bundle,
)
from .validation import (
    SchemaValidationError,
    load_schema,
    validate_deployment_config,
    validate_failure_config,
    validate_file,
    validate_instance,
    validate_jsonl_trace,
    validate_requests_config,
    validate_run_manifest,
    validate_trace_span,
)

__all__ = [
    "ConfigBundleError",
    "ResolvedConfigBundle",
    "SchemaValidationError",
    "load_config_bundle",
    "load_schema",
    "resolve_config_bundle",
    "validate_deployment_config",
    "validate_failure_config",
    "validate_file",
    "validate_instance",
    "validate_jsonl_trace",
    "validate_requests_config",
    "validate_run_manifest",
    "validate_trace_span",
]
