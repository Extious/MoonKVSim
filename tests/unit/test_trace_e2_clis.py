from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _load_cli(name: str) -> ModuleType:
    path = REPOSITORY_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load CLI {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_vanilla_trace_e2 = _load_cli("run_vanilla_trace_e2")
run_vanilla_failure_trace_e2 = _load_cli("run_vanilla_failure_trace_e2")


@pytest.mark.parametrize(
    ("module", "failure_enabled", "expected"),
    [
        (run_vanilla_trace_e2, True, "failure-enabled configs require"),
        (run_vanilla_failure_trace_e2, False, "failure CLI requires"),
    ],
)
def test_trace_e2_clis_reject_the_other_protocol_before_running(
    module: ModuleType,
    failure_enabled: bool,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        module,
        "load_harness_config",
        lambda _path: SimpleNamespace(failure_enabled=failure_enabled),
    )
    monkeypatch.setattr(
        module,
        "run_harness",
        lambda *_args: pytest.fail("wrong protocol must fail before the harness runs"),
    )

    status = module.main(["--config", "fixture.json", "--output", "/tmp/out"])

    assert status == 2
    assert expected in capsys.readouterr().out
