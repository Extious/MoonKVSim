#!/usr/bin/env python3
"""Re-layout existing data for Figure 1(c) and standalone Figure 2.

No model queries or experiments: all 75 recovery estimates and the four
branch counterfactuals are reused unchanged. Source PDFs are archived before
publication; editable SVGs and provenance stay outside the Overleaf folder.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("motivation_row", HERE / "render_motivation_row.py")
row = importlib.util.module_from_spec(spec)
spec.loader.exec_module(row)
base, plt = row.base, row.plt
ROOT = base.ROOT / "benchmark/AegisKV"
OUT = ROOT / "exports/motivation-reordered"
base.OUT = OUT
PAPER = ROOT / "paper/figures"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recovery_panel():
    from matplotlib.lines import Line2D
    data = json.loads(row.REUSE.read_text())
    fig, ax = plt.subplots(figsize=(2.24, 2.25))
    fig.subplots_adjust(left=.285, right=.98, bottom=.205, top=.70)
    paths = [("hbm_ms", "HBM", base.BLUE, "-"),
             ("dram_ms", "DRAM", base.ORANGE, "--"),
             ("recompute_ms", "Recomp.", base.RED, ":")]
    models = [("Qwen3-14B", "Q14B", "o", 4.0),
              ("Llama-3.1-70B", "L70B", "s", 3.7),
              ("Qwen3-235B-A22B-Instruct-2507", "Q235B", "^", 4.0),
              ("DeepSeek-V3.2", "DS-V3.2", "D", 3.7)]
    assert len(data["rows"]) == 25
    assert set(data["models"]) == {m[0] for m in models}
    values = []
    for model, short, marker, size in models:
        rows = sorted((r for r in data["rows"] if r["model"] == model), key=lambda r: r["total_tokens"])
        assert rows[-1]["total_tokens"] == data["models"][model]["context_limit"]
        for key, _, color, style in paths:
            x = [r["total_tokens"] for r in rows]
            y = [r[key] for r in rows]
            line, = ax.plot(x, y, color=color, ls=style, lw=1.05)
            assert list(line.get_xdata()) == x and list(line.get_ydata()) == y
            for r in rows:
                extrapolated = r["dsa_beyond_table_context"] or r["qwen_full_attention_projection"]
                ax.plot(r["total_tokens"], r[key], color=color, marker=marker,
                        ls="none", ms=size, mfc="white" if extrapolated else color, mew=.8)
                values.append([model, key, r["total_tokens"], r[key], extrapolated])
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlim(6800, 1250000)
    ax.set_ylim(7, 500000)
    ax.set_xticks([8192, 131072, 1000000], ["8K", "128K", "1M"])
    ax.set_yticks([10, 1000, 100000], ["10", "1k", "100k"])
    ax.minorticks_off()
    ax.tick_params(length=2.5, pad=2)
    ax.grid(axis="y", color="#E3E7EB", lw=.5)
    ax.set_xlabel("Context (tokens)", labelpad=3)
    ax.set_ylabel("Recovery time (ms)", labelpad=3)
    path_handles = [Line2D([], [], color=c, ls=s, lw=1.5, label=label) for _, label, c, s in paths]
    fig.legend(handles=path_handles, loc="upper center", bbox_to_anchor=(.50, .98),
               ncol=3, borderpad=0, borderaxespad=0, handlelength=1.2,
               columnspacing=.35, handletextpad=.25, fontsize=10)
    model_handles = [Line2D([], [], color=base.INK, marker=m, ms=z,
                            ls="none", label=label) for _, label, m, z in models]
    fig.legend(handles=model_handles, loc="upper center", bbox_to_anchor=(.52, .898),
               ncol=2, borderpad=0, borderaxespad=0, handlelength=1.0,
               columnspacing=.9, handletextpad=.3, labelspacing=.25)
    base.save(fig, "recovery-cost", evidence="static-estimate", width_in=2.24,
              note="Figure 1(c), 2.24 x 2.25 in, all 75 original estimates retained. "
                   "Only layout, legend aliases and tick density changed; units remain milliseconds. "
                   "Filled and hollow markers remain estimates, with hollow markers retaining the original extrapolation flags.",
              sources=[str(row.REUSE.relative_to(base.ROOT))])
    return values


def standalone_exposure():
    row.W, row.H = 3.34, 2.05
    def save(fig, name, evidence, note, sources, **kwargs):
        base.save(fig, "recovery-exposure", evidence=evidence,
                  width_in=3.34, note=note + " Standalone Figure 2; native 3.34-inch width.", sources=sources)
    row.save = save
    return row.exposure()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    values = recovery_panel()
    cases = standalone_exposure()
    sources = [row.REUSE, base.CC_CSV, row.SELECTION, row.EXAMPLE_COSTS]
    manifest = {
        "generator": str(Path(__file__).relative_to(base.ROOT)),
        "generator_sha256": digest(Path(__file__)),
        "source_sha256": {str(p.relative_to(base.ROOT)): digest(p) for p in sources},
        "figure_members": {"1a": "workflow.pdf", "1b": "workflow-gaps.pdf",
                           "1c": "recovery-cost.pdf", "2": "recovery-exposure.pdf"},
        "insertion": {"figure1_panel_width_in": 2.24, "figure1_row_height_in": 2.25,
                      "figure2_width_in": 3.34, "minimum_native_font_pt": 10.0},
        "unchanged_estimates": values, "exposure_cases": cases,
        "figures": base.MANIFEST,
        "evidence": "Re-layout of existing trace-derived and static estimates; no new experiment."
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name in ("recovery-cost", "recovery-exposure"):
        shutil.copy2(OUT / f"{name}.pdf", PAPER / f"{name}.pdf")
    print("Published Figure 1(c) and Figure 2 from unchanged data.")


if __name__ == "__main__":
    main()
