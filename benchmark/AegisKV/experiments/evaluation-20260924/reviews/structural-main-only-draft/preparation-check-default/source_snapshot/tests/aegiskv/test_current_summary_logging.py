"""Logging detail must not change modeled service, recovery, or byte accounting."""

from dataclasses import replace

import pytest

from moonkvsim.aegiskv.current.model import Config, Failure
from moonkvsim.aegiskv.current.runtime import CurrentRuntime
from moonkvsim.aegiskv.current.workload import mechanism_workload


def fixed_profile(config, invocation, start, end, stage):
    """Pure deterministic profile with a fixed prefill-forward cost."""
    del invocation
    if start == end:
        return 0
    if stage == "prefill":
        return 7_000 + (end - start) * config.prefill_ns_per_token
    return (end - start) * config.decode_ns_per_token


@pytest.mark.parametrize("failure", [None, Failure("wf00/slow")])
def test_summary_logging_preserves_full_summary_except_retention_flag(failure):
    config = replace(Config(), layers=4, depth=2)
    agents = mechanism_workload(workflows=1)
    detailed = CurrentRuntime(
        config, agents, failure=failure, duration_profile=fixed_profile, retain_detailed_logs=True
    )
    light = CurrentRuntime(
        config, agents, failure=failure, duration_profile=fixed_profile, retain_detailed_logs=False
    )
    expected, actual = detailed.run(), light.run()
    assert expected.pop("detailed_event_and_flow_logs_retained") is True
    assert actual.pop("detailed_event_and_flow_logs_retained") is False
    assert actual == expected
    assert any(event["kind"] == "policy_sample" for event in detailed.events)
    assert all(event["kind"] != "policy_sample" for event in light.events)
    assert detailed.flow_model.intervals and not light.flow_model.intervals
    assert detailed.des.journal.records and not light.des.journal.records
