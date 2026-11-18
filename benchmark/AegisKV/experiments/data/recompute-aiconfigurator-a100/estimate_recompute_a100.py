#!/usr/bin/env python3
"""Estimate full-prefix prefill (recompute) latency on A100-SXM with NVIDIA AIConfigurator.

Runs the locked AIConfigurator checkout (`/home/comp/zhanzhao/aiconfigurator`, see
`reference/aiconfigurator-notes.md`) in `cli estimate --estimate-mode static` for the
Figure 4 reference models, batch 1, TP 1 (single-GPU-equivalent), and records TTFT,
memory, and the per-op latency / data-source breakdown for both HYBRID (silicon
tables where available, SOL + empirical factor elsewhere) and SOL (speed-of-light
lower bound) database modes.

MiniCPM4-8B (InfLLM-V2 native sparse attention) is NOT modelled by AIConfigurator; the
SDK has no MiniCPM / InfLLM-V2 architecture, so that curve has to come from measurement.

Outputs (next to this script): estimates.json (full provenance) and estimates.csv.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AIC_ROOT = Path("/home/comp/zhanzhao/aiconfigurator")
AIC_CLI = AIC_ROOT / ".venv/bin/aiconfigurator"

SYSTEM = "a100_sxm"
BACKEND = "vllm"
ISLS = [8192, 16384, 32768, 65536, 131072]
MODES = ["HYBRID", "SOL"]

# tag -> (model path resolvable offline by the tool, extra CLI args, notes)
MODELS = {
    "Qwen3-8B": (
        "Qwen/Qwen3-8B",
        [],
        "Dense, 36 layers, GQA 32/8, 128K via YaRN (factor 4); cost is independent of the RoPE recipe.",
    ),
    "Qwen3-30B-A3B": (
        "Qwen/Qwen3-30B-A3B",
        ["--moe-tp-size", "1", "--moe-ep-size", "1"],
        "MoE 30.5B total / 3.3B active, 48 layers, GQA 32/4, 128 experts top-8. Architecturally identical "
        "to Qwen3-30B-A3B-Instruct-2507 (262K native); the built-in config is used because HF config "
        "download is blocked on this node. TP1 memory exceeds 80 GiB at 128K: a real deployment splits "
        "layers over two GPUs, the TP1 estimate is the single-GPU-equivalent time.",
    ),
}

OP_ROW = re.compile(
    r"^\s+(context_\w+)\s+([\d.]+) ms\s+([\d.]+) ms\s+([\d.]+)%\s+[░█]+\s+([\d.]+)%\s+\[(\w+)\]\s*$"
)


def run_cli(model_path: str, extra: list[str], isl: int, mode: str) -> tuple[list[str], str]:
    cmd = [
        str(AIC_CLI), "cli", "estimate", "--estimate-mode", "static",
        "--model-path", model_path, "--system", SYSTEM, "--backend", BACKEND,
        "--isl", str(isl), "--osl", "1", "--batch-size", "1", "--tp-size", "1",
        *extra, "--database-mode", mode, "--detail", "time,source",
    ]
    proc = subprocess.run(cmd, cwd=AIC_ROOT, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
    return cmd, proc.stdout + proc.stderr


def grab(pattern: str, text: str, cast=float):
    m = re.search(pattern, text, re.M)
    return cast(m.group(1)) if m else None


def parse(text: str) -> dict:
    ops = []
    in_ctx = False
    for line in text.splitlines():
        if line.startswith("Context phase"):
            in_ctx = True
            continue
        if in_ctx:
            if not line.strip():
                in_ctx = False
                continue
            m = OP_ROW.match(line)
            if m:
                ops.append({
                    "op": m.group(1), "latency_ms": float(m.group(2)), "sol_ms": float(m.group(3)),
                    "sol_pct": float(m.group(4)), "share_pct": float(m.group(5)), "source": m.group(6),
                })
    attn = next((o for o in ops if o["op"] == "context_attention"), None)
    return {
        "ttft_ms": grab(r"^\s+TTFT:\s+([\d.]+) ms", text),
        "memory_gb": grab(r"^\s+Memory \(GPU\):\s+([\d.]+) GB", text),
        "backend_version": grab(r"^\s+Backend:\s+\w+ \(([^)]+)\)", text, str),
        "context_total_ms": grab(r"^Context phase \(total = ([\d.]+) ms", text),
        "context_sol_ms": grab(r"^Context phase \(total = [\d.]+ ms, SOL = ([\d.]+) ms", text),
        "attention_ms": attn["latency_ms"] if attn else None,
        "attention_source": attn["source"] if attn else None,
        "ops": ops,
    }


def tool_provenance() -> dict:
    commit = subprocess.run(["git", "-C", str(AIC_ROOT), "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=True).stdout.strip()
    version = grab(r'^version\s*=\s*"([^"]+)"', (AIC_ROOT / "pyproject.toml").read_text(), str)
    spec = (AIC_ROOT / f"src/aiconfigurator/systems/{SYSTEM}.yaml").read_text()
    gpu = {
        "mem_bw_bytes_per_s": grab(r"^\s+mem_bw:\s+(\d+)", spec, int),
        "mem_capacity_bytes": grab(r"^\s+mem_capacity:\s+(\d+)", spec, int),
        "bfloat16_tc_flops": grab(r"^\s+bfloat16_tc_flops:\s+(\d+)", spec, int),
    }
    return {"repo": str(AIC_ROOT), "commit": commit, "version": version, "cli": str(AIC_CLI),
            "system": SYSTEM, "system_gpu_spec": gpu}


def main() -> int:
    result = {
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "tool": tool_provenance(),
        "protocol": {
            "estimate_mode": "static", "backend": BACKEND, "batch_size": 1, "osl": 1, "tp_size": 1,
            "database_modes": MODES,
            "meaning": "TTFT of a single request = full-prefix prefill of `isl` tokens on one A100-SXM "
                       "(GPU forward only; no scheduler, transfer or queueing time). HYBRID = measured "
                       "kernel tables where the tool has them, otherwise SOL / empirical efficiency; "
                       "SOL = speed-of-light lower bound.",
        },
        "unsupported": {
            "MiniCPM4-8B": "AIConfigurator has no MiniCPM / InfLLM-V2 architecture; the sparse-attention "
                           "curve must be measured (see native-sparse/20260915 for the RTX 4090 data)."
        },
        "models": {},
        "commands": [],
    }
    rows = []
    for tag, (path, extra, notes) in MODELS.items():
        points = []
        for isl in ISLS:
            for mode in MODES:
                cmd, text = run_cli(path, extra, isl, mode)
                parsed = parse(text)
                if parsed["ttft_ms"] is None:
                    raise RuntimeError(f"could not parse TTFT for {tag} isl={isl} mode={mode}:\n{text[-2000:]}")
                points.append({"isl": isl, "mode": mode, **parsed})
                result["commands"].append(" ".join(cmd))
                rows.append([tag, isl, mode, parsed["ttft_ms"], parsed["memory_gb"],
                             parsed["attention_ms"], parsed["attention_source"]])
                print(f"{tag:14s} isl={isl:6d} {mode:6s} TTFT={parsed['ttft_ms']:10.1f} ms "
                      f"mem={parsed['memory_gb']:6.2f} GB attention={parsed['attention_ms']:9.1f} ms "
                      f"[{parsed['attention_source']}]", file=sys.stderr)
        result["models"][tag] = {"model_path": path, "notes": notes, "points": points}

    (HERE / "estimates.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    with (HERE / "estimates.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "isl", "database_mode", "ttft_ms", "memory_gb", "attention_ms", "attention_source"])
        w.writerows(rows)
    print(f"wrote {HERE / 'estimates.json'} and {HERE / 'estimates.csv'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
