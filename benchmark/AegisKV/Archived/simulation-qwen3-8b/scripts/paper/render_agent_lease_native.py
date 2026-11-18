"""Measured L40S forward / DMA / allocator experiments, separate from DES."""
import json
from pathlib import Path
import numpy as np
import render_paper_story as plot
import agent_lease_style as style
from paper_paths import ROOT
from three_system_data import sha

OUT = ROOT / "output/pdf/aegiskv-agent-lease-20260908"
RUN = ROOT / "output/agent-lease-20260908/native-l40s"
MODES = {"none": ("No copy", "#555D66", "o", "-"),
    "dram_put": ("DRAM write", "#B86B00", "s", "--"),
    "peer_in": ("Peer input", "#0072B2", "^", "-."),
    "peer_out": ("Peer output", "#7952A2", "D", ":")}


def error_line(ax, x, grouped, *, label, color, marker, ls):
    med = np.array([np.median(v) for v in grouped])
    lo = med - [min(v) for v in grouped]
    hi = np.array([max(v) for v in grouped]) - med
    ax.errorbar(x, med, yerr=[lo, hi], label=label, color=color, marker=marker,
        ls=ls, lw=1.35, ms=4, markerfacecolor="white", capsize=2.7, elinewidth=0.8)


def header(ax, columns=2):
    ax.figure.set_figheight(2.9)
    ax.figure.subplots_adjust(top=0.78, bottom=0.205)
    plot.legend(ax, header=True, columns=columns)


def main():
    style.install(plot)
    original_finish = plot.finish
    def finish(fig, name, rows, **kwargs):
        style.polish(fig, name)
        original_finish(fig, name, rows, **kwargs)
    plot.finish = finish
    plot.OUT = OUT
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((RUN / "manifest.json").read_text())
    assert manifest["status"] == "PASS" and manifest["sample_count"] == 360 and manifest["oom_count"] == 0
    assert sha(RUN / "samples.jsonl") == manifest["samples_sha256"]
    rows = [json.loads(line) for line in (RUN / "samples.jsonl").open()]
    by = {(r["repeat"], r["batch"], r["prompt_tokens"], r["backup_occupancy_gib"], r["mode"]): r for r in rows}
    assert len(by) == len(rows)
    for batch in (1, 4):
        fig, ax = plot.canvas("Prompt length (Ki tokens)", "Forward slowdown (×)")
        exported = []
        for mode, (label, color, marker, ls) in MODES.items():
            grouped = []
            for tokens in (512, 2048, 4096):
                vals = []
                for repeat in range(5):
                    row = by[repeat, batch, tokens, 8, mode]
                    base = by[repeat, batch, tokens, 8, "none"]
                    value = row["forward_gpu_ms"] / base["forward_gpu_ms"]
                    vals.append(value)
                    exported.append(dict(repeat=repeat, batch=batch, prompt_tokens=tokens,
                        backup_gib=8, mode=mode, forward_ms=row["forward_gpu_ms"],
                        paired_no_copy_ms=base["forward_gpu_ms"], slowdown=value))
                grouped.append(vals)
            error_line(ax, [0.5, 2, 4], grouped, label=label, color=color, marker=marker, ls=ls)
        ax.set_xticks([0.5, 2, 4]); ax.set_xlim(0.25, 4.25)
        ax.set_yticks([1, 1.1, 1.2, 1.3]); ax.set_ylim(.96, 1.36)
        assert all(.96 <= r["slowdown"] <= 1.36 for r in exported)
        ax.axhline(1, color="#BBC1C7", lw=0.7, zorder=0)
        header(ax)
        plot.finish(fig, f"native-forward-b{batch}", exported, evidence="physical_microbenchmark",
            sources=[str(RUN.relative_to(ROOT) / "samples.jsonl")],
            note=f"Real Qwen3-8B BF16 SDPA; batch={batch}, extra allocated backup=8 GiB; median and min/max of five paired randomized blocks in one exclusive 2xL40S allocation. Not a system-level WCT benchmark.")

    fig, ax = plot.canvas("Extra backup allocation (GiB)", "Forward latency (s)")
    exported = []
    for mode, (label, color, marker, ls) in MODES.items():
        grouped = []
        for gib in (0, 8, 16):
            sample = [by[i, 4, 4096, gib, mode] for i in range(5)]
            grouped.append([x["forward_gpu_ms"] / 1000 for x in sample])
            exported += [dict(repeat=x["repeat"], backup_gib=gib, mode=mode,
                forward_s=x["forward_gpu_ms"] / 1000, allocated_bytes=x["allocated_bytes"]) for x in sample]
        error_line(ax, [0, 8, 16], grouped, label=label, color=color, marker=marker, ls=ls)
    ax.set_xticks([0, 8, 16]); ax.set_xlim(-1, 17)
    header(ax)
    fig.subplots_adjust(left=.24)
    plot.finish(fig, "native-memory-occupancy", exported, evidence="physical_microbenchmark",
        sources=[str(RUN.relative_to(ROOT) / "samples.jsonl")],
        note="Batch 4, prompt 4096; extra allocation is actually touched on the foreground GPU; median and min/max, five blocks; zero OOM here is not a general admission or latency guarantee.")

    fig, ax = plot.canvas("Prompt length (Ki tokens)", "Concurrent copy rate (GB/s)")
    exported = []
    for mode, (label, color, marker, ls) in MODES.items():
        if mode == "none": continue
        grouped = []
        for tokens in (512, 2048, 4096):
            vals = []
            for i in range(5):
                row = by[i, 1, tokens, 8, mode]
                copies = row["copy_samples"]
                value = sum(x["bytes"] for x in copies) / sum(x["wall_ns"] for x in copies)
                vals.append(value)
                exported.append(dict(repeat=i, prompt_tokens=tokens, mode=mode, copy_gbs=value,
                    copy_count=len(copies), bytes=sum(x["bytes"] for x in copies),
                    completion_wall_ns=sum(x["wall_ns"] for x in copies)))
            grouped.append(vals)
        error_line(ax, [.5, 2, 4], grouped, label=label, color=color, marker=marker, ls=ls)
    ax.set_xticks([.5, 2, 4]); ax.set_xlim(.25, 4.25); ax.set_ylim(bottom=0)
    header(ax, 2)
    plot.finish(fig, "native-concurrent-copy", exported, evidence="physical_microbenchmark",
        sources=[str(RUN.relative_to(ROOT) / "samples.jsonl")],
        note="256 MiB copies, batch-1 foreground, extra 8 GiB allocation; per measurement block sum(bytes)/sum(completion wall time), then median and range of five blocks. Copy chunks are not independent repeats.")

    fig, ax = plot.canvas("Prompt length (Ki tokens)", "Process CPU demand (cores)")
    exported = []
    for mode, (label, color, marker, ls) in MODES.items():
        grouped = []
        for tokens in [512, 2048, 4096]:
            samples = [by[i, 1, tokens, 8, mode] for i in range(5)]
            grouped.append([r["process_cpu_ns"] / r["forward_wall_ns"] for r in samples])
            exported.extend(dict(repeat=r["repeat"], prompt_tokens=tokens, mode=mode,
                process_cpu_ns=r["process_cpu_ns"], forward_wall_ns=r["forward_wall_ns"],
                cpu_cores=r["process_cpu_ns"] / r["forward_wall_ns"]) for r in samples)
        error_line(ax, [.5, 2, 4], grouped, label=label, color=color, marker=marker, ls=ls)
    ax.set_xticks([.5, 2, 4]); ax.set_xlim(.25, 4.25); ax.set_ylim(0, 2.2); header(ax)
    plot.finish(fig, "native-copy-cpu", exported, evidence="physical_microbenchmark",
        sources=[str(RUN.relative_to(ROOT) / "samples.jsonl")],
        note="Batch 1, extra 8 GiB, measured process CPU divided by elapsed forward time. Includes the benchmark's copy thread and CUDA synchronization behavior. It is not native AegisKV admission CPU or whole-server utilization; five-block median and min/max.")

    reclaim = json.loads((RUN / "reclaim.json").read_text())
    fig, ax = plot.canvas("Allocation released (GiB)", "Completion latency (ms)")
    for field, label, color, marker, ls in [("fence_ns", "In-flight write fence", "#0072B2", "^", "-"),
            ("allocator_free_ns", "Allocator release", "#B86B00", "s", "--")]:
        grouped = [[r[field] / 1e6 for r in reclaim if r["gib"] == gib] for gib in (1, 4, 8)]
        assert all(len(v) == 20 for v in grouped)
        error_line(ax, [1, 4, 8], grouped, label=label, color=color, marker=marker, ls=ls)
    ax.set_xticks([1, 4, 8]); ax.set_xlim(.6, 8.4); ax.set_ylim(bottom=0)
    header(ax, 1)
    plot.finish(fig, "native-release-ack", reclaim, evidence="physical_microbenchmark",
        sources=[str(RUN.relative_to(ROOT) / "reclaim.json")],
        note="Twenty measurements per size in one allocation; median and min/max. Fence waits for a real asynchronous GPU write; allocator release includes del, empty_cache and device synchronization. This is not a native AegisKV eviction measurement.")
    (OUT / "native-manifest.json").write_text(json.dumps({"figures": plot.RECORDS,
        "input_bindings": {str(p.relative_to(ROOT)): sha(p) for p in (RUN / "manifest.json", RUN / "samples.jsonl", RUN / "reclaim.json", Path(__file__), Path(plot.__file__), Path(__file__).with_name("figure_style.py"), Path(__file__).with_name("three_system_data.py"), Path(style.__file__))}}, indent=2) + "\n")
    print(f"Exported {len(plot.RECORDS)} native figures")


if __name__ == "__main__":
    main()
