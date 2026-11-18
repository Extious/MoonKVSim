#!/usr/bin/env python3
"""Print paired healthy/failed differences for the scale campaign."""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "evaluation-20260924/blsc-scale-v1/runs"


def load() -> list[dict]:
    return [json.loads(path.read_text()) for path in sorted(OUT.glob("*.json"))]


def main() -> None:
    rows = load()
    index = {
        (row["model"], row["document"], row["prompt_tokens"], row["policy"], row["fault"]): row
        for row in rows
    }
    keys = sorted({key[:-2] for key in index})
    for model, document, prompt, policy in keys:
        if policy == "none":
            continue
        healthy = index.get((model, document, prompt, policy, "healthy"))
        failed = index.get((model, document, prompt, policy, "failed"))
        base_h = index.get((model, document, prompt, "none", "healthy"))
        base_f = index.get((model, document, prompt, "none", "failed"))
        if not all((healthy, failed, base_h, base_f)):
            continue
        healthy_delta = max(
            abs(a["wct_ns"] - b["wct_ns"])
            for a, b in zip(healthy["workflows"], base_h["workflows"])
        )
        victim = failed["workflows"][4]
        base_victim = base_f["workflows"][4]
        recovery = failed["recovery"]
        base_recovery = base_f["recovery"]
        print(
            f"{model} pg19-{document} p{prompt} {policy} "
            f"healthy_max_abs_ns {healthy_delta} "
            f"victim_saved_ms {(base_victim['wct_ns'] - victim['wct_ns']) / 1e6:.3f} "
            f"retry_ms {recovery['latency_ns'] / 1e6:.3f} "
            f"restart_retry_ms {base_recovery['latency_ns'] / 1e6:.3f} "
            f"ckpt {recovery['checkpoint_tokens']} rebuild {recovery['rebuild_tokens']} "
            f"hbm {recovery['hbm_blocks']}"
        )


if __name__ == "__main__":
    main()
