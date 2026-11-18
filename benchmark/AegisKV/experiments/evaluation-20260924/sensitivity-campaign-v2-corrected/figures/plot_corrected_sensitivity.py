#!/usr/bin/env python3
"""Reuse the reviewed sensitivity layout with explicitly selected new inputs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    out = args.out.resolve() if args.out else source / "figures"
    out.mkdir(parents=True, exist_ok=True)
    local_style = Path(__file__).with_name("render_sensitivity_style.py")
    style = (
        local_style
        if local_style.exists()
        else Path(__file__).with_name("plot_sensitivity_campaign.py")
    )
    pinned = out / "render_sensitivity_style.py"
    if pinned.exists():
        assert sha(pinned) == sha(style)
    else:
        shutil.copy2(style, pinned)
    if Path(__file__).resolve() != out / Path(__file__).name:
        shutil.copy2(Path(__file__), out / Path(__file__).name)
    spec = importlib.util.spec_from_file_location("pinned_sensitivity_style", pinned)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    engine.SOURCE, engine.OUT = source, out
    engine.main()
    metadata = json.loads((out / "EXPORT_METADATA.json").read_text())
    metadata.update(
        input_campaign=str(source),
        design_version=json.loads((source / "MANIFEST.json").read_text())["design_version"],
        manifest_sha256=sha(source / "MANIFEST.json"),
        wrapper_sha256=sha(Path(__file__)),
        pinned_style_sha256=sha(pinned),
        evidence="corrected matched replacement; not extra statistical samples",
        old_figures_unchanged=True,
    )
    (out / "EXPORT_METADATA.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
