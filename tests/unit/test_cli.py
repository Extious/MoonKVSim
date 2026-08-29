import json

from moonkvsim.cli import main


def test_empty_cli_is_successful() -> None:
    assert main([]) == 0


def test_cli_validates_discriminator_selected_config(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "failure.json"
    path.write_text(
        json.dumps(
            {
                "schema": "moonkvsim.failure.v1",
                "enabled": False,
                "events": [],
            }
        ),
        encoding="utf-8",
    )

    assert main(["validate", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "schema": "moonkvsim.failure.v1",
        "status": "pass",
    }


def test_cli_rejects_non_gpu_failure_before_runtime(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "failure.json"
    path.write_text(
        json.dumps(
            {
                "schema": "moonkvsim.failure.v1",
                "enabled": True,
                "events": [
                    {
                        "failure_id": "f0",
                        "type": "NODE_FAILURE",
                        "at_s": 0,
                        "target": {"node_id": "n0", "gpu_id": 0},
                        "detection_delay_ms": 0,
                        "repair_after_s": None,
                        "semantics": "fail_stop_hbm_lost",
                        "affected_resource_ids": ["gpu:n0:0"],
                        "reroute": {
                            "rule": "healthy_dp_rank",
                            "on_no_healthy_target": "fail_request",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["validate", str(path)]) == 2
    assert "GPU_FAILURE" in capsys.readouterr().out
