"""Fixed-quota baseline must recover its target while honoring live ownership."""

import pytest

from moonkvsim.aegiskv.current.model import Agent, Config, Invocation
from moonkvsim.aegiskv.evaluation_quota import FixedQuotaRuntime


def fixture():
    config = Config(
        hosts=(0, 1),
        tp=1,
        layers=1,
        depth=1,
        hbm_bytes_per_rank=1024**2,
        reserve_bytes=1024,
        hbm_cap_bytes=8192,
        initial_quota_bytes=4096,
    )
    agent = Agent("wf", "a", (), (Invocation((1,), (2,), output_limit_tokens=1),), 10**9)
    return config, agent


def test_target_returns_after_pressure_but_never_uses_foreground_reserve():
    config, agent = fixture()
    runtime = FixedQuotaRuntime(config, (agent,), fixed_quota_bytes=8192)
    worker, held = 0, config.hbm_bytes_per_rank - config.reserve_bytes - 2048
    runtime._hbm_move(worker, "FREE", "primary:test", held, "TEST_FOREGROUND_RESERVE")
    runtime._apply_fixed_ceiling()
    assert runtime.adapters[worker, 0].quota == 2048
    assert runtime.ledgers["hbm:0:0"].bytes_in("primary:test") == held
    runtime._hbm_move(worker, "primary:test", "FREE", held, "TEST_FOREGROUND_RELEASE")
    runtime._apply_fixed_ceiling()
    assert runtime.adapters[worker, 0].quota == 8192
    assert runtime.ledgers["hbm:0:0"].bytes_in("FREE") == config.hbm_bytes_per_rank


def test_dead_worker_quota_is_not_readmitted():
    config, agent = fixture()
    runtime = FixedQuotaRuntime(config, (agent,), fixed_quota_bytes=8192)
    runtime.alive.remove(0)
    runtime.adapters[0, 0].quota = 0
    runtime._apply_fixed_ceiling()
    assert runtime.adapters[0, 0].quota == 0


@pytest.mark.parametrize("quota", [-1, 8193, 1.5])
def test_invalid_quota_is_rejected(quota):
    config, agent = fixture()
    with pytest.raises(ValueError, match="quota"):
        FixedQuotaRuntime(config, (agent,), fixed_quota_bytes=quota)
