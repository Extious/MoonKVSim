"""Parallel raw checks retain deterministic ordering and propagate failure."""
import pytest

from moonkvsim.aegiskv.paper_audit_parallel import audit_map


def _square(value: int) -> int:
    return value * value


def _reject(value: int) -> int:
    if value == 2:
        raise ValueError("invalid evidence")
    return value


def test_parallel_results_preserve_input_order(monkeypatch):
    monkeypatch.setenv("MOONKVSIM_AUDIT_WORKERS", "3")
    assert audit_map(_square, [4, 1, 3, 2]) == [16, 1, 9, 4]


def test_parallel_failure_reaches_acceptance_caller(monkeypatch):
    monkeypatch.setenv("MOONKVSIM_AUDIT_WORKERS", "2")
    with pytest.raises(ValueError, match="invalid evidence"):
        audit_map(_reject, [1, 2, 3])


@pytest.mark.parametrize("workers", ["0", "9", "-1", "invalid"])
def test_invalid_parallelism_fails_closed(monkeypatch, workers):
    monkeypatch.setenv("MOONKVSIM_AUDIT_WORKERS", workers)
    with pytest.raises(ValueError):
        audit_map(_square, [1, 2])
