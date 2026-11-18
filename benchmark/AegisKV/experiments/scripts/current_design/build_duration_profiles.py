"""Freeze AIConfigurator shape estimates for the current DES (no GPU execution).

Run with the existing AIConfigurator virtualenv. The grid is an explicit
interpolation model, not an end-to-end calibration. Source and per-op provenance
are retained alongside all queried shapes, including memory warnings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--aic", type=Path, default=Path("/home/comp/zhanzhao/aiconfigurator"))
    parser.add_argument("--max-context", type=int, default=98_304)
    parser.add_argument("--context-stride", type=int, default=2048)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    from aiconfigurator.cli.api import cli_estimate

    root = Path(__file__).resolve().parents[5]
    models = {
        "Qwen3-8B": (1, "b968826d9c46dd6066d109eabc6255188de91218"),
        "Qwen3-32B": (4, "9216db5781bf21249d130ec9da846c4624c16137"),
    }
    sources = [Path(__file__), args.aic / "src/aiconfigurator/systems/a100_sxm.yaml"]
    sources += list((args.aic / "src/aiconfigurator/sdk").rglob("*.py"))
    sources += [args.aic / "src/aiconfigurator/cli/api.py"]
    sources += [
        p for p in (args.aic / "src/aiconfigurator/systems/data/a100_sxm").rglob("*") if p.is_file()
    ]
    contexts = list(range(0, args.max_context + 1, args.context_stride))
    assert contexts[-1] == args.max_context
    for model, (tp, revision) in models.items():
        config_dir = args.out / model
        config_dir.mkdir()
        config_path = config_dir / "config.json"
        url = f"https://huggingface.co/Qwen/{model}/resolve/{revision}/config.json"
        if model == "Qwen3-8B":
            shutil.copy2(
                root
                / "benchmark/AegisKV/experiments/data/reuse-aiconfigurator-a100/configs"
                / "Qwen3-8B/config.json",
                config_path,
            )
        else:
            with urllib.request.urlopen(url, timeout=60) as response:
                config_path.write_bytes(response.read())
        cfg = json.loads(config_path.read_text())
        assert cfg["max_position_embeddings"] == 40_960
        rows = []
        for context in contexts:
            for stage, extend in [("prefill", 1), ("prefill", 64), ("prefill", 256), ("decode", 1)]:
                # SDK static_gen performs OSL-1 decode steps. Its first
                # generation query has s=ISL+1, so ISL=context is exact here.
                kwargs = dict(isl=context + extend, prefix=context, osl=1)
                if stage == "decode":
                    kwargs = dict(isl=max(context, 1), prefix=0, osl=2)
                result = cli_estimate(
                    str(config_dir),
                    "a100_sxm",
                    mode="static_ctx" if stage == "prefill" else "static_gen",
                    backend_name="vllm",
                    backend_version="0.14.0",
                    database_mode="HYBRID",
                    batch_size=1,
                    tp_size=tp,
                    pp_size=1,
                    gemm_quant_mode="bfloat16",
                    kvcache_quant_mode="bfloat16",
                    fmha_quant_mode="bfloat16",
                    **kwargs,
                )
                summary = result.summary
                ops = (
                    summary.get_context_latency_dict()
                    if stage == "prefill"
                    else summary.get_generation_latency_dict()
                )
                op_sources = (
                    summary.get_context_source_dict()
                    if stage == "prefill"
                    else summary.get_generation_source_dict()
                )
                latency_ms = sum(ops.values())
                assert latency_ms > 0, (model, stage, context)
                rows.append(
                    dict(
                        stage=stage,
                        context=context,
                        extend=extend,
                        latency_ns=round(latency_ms * 1e6),
                        ops_ms=dict(ops),
                        op_sources=op_sources,
                        memory=summary.get_memory(),
                        kv_warning=result.kv_cache_warning,
                        sdk_args=kwargs,
                    )
                )
            print(model, context, "profiled", flush=True)
        payload = dict(
            schema="aegiskv.duration-grid.v1",
            model=f"Qwen/{model}",
            revision=revision,
            tp=tp,
            config=cfg,
            rows=rows,
            context_grid=contexts,
            prefill_extend_grid=[1, 64, 256],
            native_max_context=40_960,
            max_profile_context=args.max_context,
            physical_execution=False,
            calibrated=False,
            timing_evidence="AIConfigurator HYBRID operator estimates; not end-to-end measurements",
            extended_context=(
                "Beyond 40960: performance shapes only; no quality or runtime validation"
            ),
            interpolation=(
                "linear in prefix and extend, no extrapolation; decode summed at integer positions"
            ),
            decoding_convention="one step per accepted output ID; terminal output KV materialized",
            hardware="a100_sxm",
            batch_size=1,
            backend="vllm",
            backend_version="0.14.0",
            database_mode="HYBRID",
            config_source=url,
            config_sha256=digest(config_path),
            created_utc=datetime.now(UTC).isoformat(),
        )
        (args.out / f"{model}.json").write_text(json.dumps(payload, indent=2, default=float) + "\n")
    manifest = dict(
        created_utc=datetime.now(UTC).isoformat(),
        aic_commit=subprocess.check_output(
            ["git", "-C", str(args.aic), "rev-parse", "HEAD"], text=True
        ).strip(),
        source_sha256={str(p): digest(p) for p in sorted(sources)},
        output_sha256={str(p.relative_to(args.out)): digest(p) for p in args.out.rglob("*.json")},
        claim="modeled operator costs only; source tags do not validate complete recovery",
    )
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
