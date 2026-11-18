"""Frozen replay must reject drift and never fill core gaps from live sources."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from moonkvsim.aegiskv.current.__main__ import manifest

SCRIPT = Path(__file__).resolve().parents[2] / (
    "benchmark/AegisKV/experiments/scripts/current_design/run_frozen_profile_campaign.py"
)
spec = importlib.util.spec_from_file_location("frozen_profile_replay", SCRIPT)
replayer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replayer)


@pytest.fixture
def sealed(tmp_path):
    out = tmp_path / "original"
    out.mkdir()
    replayer.write(out / "PLAN.json", {"jobs": [], "workloads": {}})
    replayer.write(out / "PRIORS.json", {})
    frozen = manifest(out)
    frozen["profile_sha256"] = {}
    frozen["control_sha256"] = {
        name: replayer.sha(out / name) for name in ("PLAN.json", "PRIORS.json")
    }
    replayer.write(out / "MANIFEST.json", frozen)
    return out


def test_verification_is_read_only_and_does_not_create_requested_output(sealed):
    before = {str(p.relative_to(sealed)): replayer.sha(p) for p in sealed.rglob("*") if p.is_file()}
    output = sealed.parent / "must-not-be-created"
    result = replayer.replay(sealed, output, verify_only=True)
    assert result["status"] == "VERIFIED" and result["executed_runs"] == 0
    assert not output.exists()
    after = {str(p.relative_to(sealed)): replayer.sha(p) for p in sealed.rglob("*") if p.is_file()}
    assert before == after


def test_corrupt_frozen_source_fails_before_creating_replay(sealed):
    source = sealed / "source_snapshot/python/moonkvsim/aegiskv/current/runtime.py"
    source.write_text(source.read_text() + "\n# changed\n")
    output = sealed.parent / "replay"
    with pytest.raises(ValueError, match="frozen source hash mismatch"):
        replayer.replay(sealed, output)
    assert not output.exists()


def test_missing_core_source_cannot_fall_back_to_existing_live_runtime(sealed):
    frozen = replayer.read(sealed / "MANIFEST.json")
    relative = "python/moonkvsim/aegiskv/current/runtime.py"
    del frozen["source_sha256"][relative]
    (sealed / "source_snapshot" / relative).unlink()
    replayer.write(sealed / "MANIFEST.json", frozen)
    with pytest.raises(ValueError, match="required frozen sources absent"):
        replayer.replay(sealed, verify_only=True)


def test_supplement_cannot_override_protected_module(sealed, tmp_path):
    support = tmp_path / "support"
    path = support / "python/moonkvsim/aegiskv/current/policy.py"
    path.parent.mkdir(parents=True)
    path.write_text("raise AssertionError('live policy must not execute')\n")
    frozen, _ = replayer.verify_artifacts(sealed)
    with pytest.raises(ValueError, match="override frozen source"):
        replayer.build_tree(sealed, frozen, tmp_path / "tree", support=support)


@pytest.mark.parametrize("nested", [False, True])
def test_replay_refuses_existing_or_original_nested_output(sealed, nested):
    output = sealed / "nested" if nested else sealed.parent / "existing"
    if not nested:
        output.mkdir()
        (output / "keep.txt").write_text("unchanged")
    with pytest.raises(FileExistsError, match="new and outside"):
        replayer.replay(sealed, output)
    if not nested:
        assert (output / "keep.txt").read_text() == "unchanged"


def test_replay_refuses_dangling_output_symlink(sealed):
    target = sealed.parent / "nonexistent-target"
    link = sealed.parent / "existing-symlink"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError, match="new and outside"):
        replayer.replay(sealed, link)
    assert link.is_symlink() and not target.exists()
