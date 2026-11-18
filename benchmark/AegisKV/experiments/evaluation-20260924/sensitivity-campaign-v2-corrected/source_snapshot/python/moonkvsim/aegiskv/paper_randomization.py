"""Validate the executed randomization, rather than seed labels, in paper pairs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from moonkvsim.common.hash import sha256_json

ADMISSION_POLICY = "observed_submit_then_seeded_sha256_workflow_permutation"


def paired_admission_fingerprint(
    runs: Mapping[str, Mapping[str, Any]],
    *,
    seed: int,
    workflow_ids: set[str],
) -> str:
    """Require one realized, complete admission permutation shared by every arm.

    Callers must additionally verify distinct returned fingerprints across their
    predeclared seeds. A fixed Peer-placement seed isolates admission order as
    the randomized input. None of these checks use observed performance.
    """
    if len(runs) < 2:
        raise ValueError("admission audit requires at least two paired arms")
    fingerprints: set[str] = set()
    for system, run in runs.items():
        admission = run.get("workflow_admission")
        randomization = run.get("randomization")
        if not isinstance(admission, Mapping) or not isinstance(randomization, Mapping):
            raise ValueError(f"{system}: missing executed admission/randomization evidence")
        if admission.get("order_policy") != ADMISSION_POLICY or admission.get("seed") != seed:
            raise ValueError(f"{system}: admission policy or seed mismatch")
        if (
            randomization.get("workflow_admission_seed") != seed
            or randomization.get("peer_binding_seed") != 0
        ):
            raise ValueError(f"{system}: admission seed must vary with fixed Peer seed zero")
        order = admission.get("realized_workflow_order")
        if (
            not isinstance(order, Sequence)
            or isinstance(order, (str, bytes))
            or any(not isinstance(value, str) for value in order)
            or len(order) != len(workflow_ids)
            or set(order) != workflow_ids
        ):
            raise ValueError(f"{system}: admission order is not the complete workflow permutation")
        observed = sha256_json(list(order))
        if admission.get("realized_workflow_order_sha256") != observed:
            raise ValueError(f"{system}: admission order fingerprint mismatch")
        fingerprints.add(observed)
    if len(fingerprints) != 1:
        raise ValueError("paired systems executed different workflow admission orders")
    return next(iter(fingerprints))


def require_distinct_admissions(fingerprints: Sequence[str]) -> None:
    if len(set(fingerprints)) != len(fingerprints):
        raise ValueError("seed labels did not produce distinct realized admission permutations")
