"""Compare layer-i incremental prefill(N | M) with layer-(i+1) H2D(M).

CPU-only arithmetic and plotting. No model execution or latency measurements.
One fused multiply-add counts as two FLOPs. No multiplier for number of layers.
"""
from pathlib import Path
import csv
import hashlib
import json
import math
import os

HERE = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-layerwise-mn-mplconfig")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pymupdf

params = json.loads((HERE / "parameters.json").read_text())
model, scenario = params["model_dimensions"], params["scenario"]
d = model["hidden_size"]
qwidth = model["num_attention_heads"] * model["head_dim"]
kvwidth = model["num_key_value_heads"] * model["head_dim"]
inter = model["intermediate_size"]
M = scenario["history_tokens_M"]
F = scenario["assumed_effective_compute_TFLOP_per_s"] * 1e12
B = scenario["assumed_effective_h2d_GB_per_s"] * 1e9
element_bytes = scenario["kv_bytes_per_element"]
layer_kv_bytes = 2 * M * kvwidth * element_bytes
D_s = layer_kv_bytes / B
# Q and O each use d*qwidth weights, K and V each use d*kvwidth,
# and the gated MLP uses three d*inter weight matrices.
layer_linear_weights = 2*d*qwidth + 2*d*kvwidth + 3*d*inter


def costs(history, new):
    pairs = history*new + new*(new+1)//2
    linear_flops = 2*new*layer_linear_weights
    attention_flops = 4*qwidth*pairs  # QK and AV; GQA still has all query heads.
    return linear_flops, attention_flops


def crossover(history, throughput, bandwidth):
    target = 2*history*kvwidth*element_bytes/bandwidth * throughput
    a = 2*qwidth
    b = 2*layer_linear_weights + 4*qwidth*history + 2*qwidth
    return 2*target/(b + math.sqrt(b*b+4*a*target))


rows = []
for N in scenario["new_tokens_N"]:
    assert M+N <= model["max_position_embeddings"]
    linear, attention = costs(M, N)
    C_s = (linear+attention)/F
    rows.append({
        "history_tokens_M": M, "new_tokens_N": N,
        "next_layer_history_KV_bytes": layer_kv_bytes,
        "current_layer_linear_flops": linear,
        "current_layer_attention_flops": attention,
        "current_layer_prefill_ms": C_s*1000,
        "next_layer_h2d_ms": D_s*1000,
        "whole_layer_window_covers_copy_in_model": C_s >= D_s,
        "current_layer_KV_projection_only_flops": 4*N*d*kvwidth,
    })
with (HERE / "layerwise-times.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader(); writer.writerows(rows)

# This dimensional check has a hand-derived expected result: 4 KiB/token/layer.
assert layer_kv_bytes == 128*1024**2
assert layer_kv_bytes//M == 4096
assert abs(D_s*1000 - 5.36870912) < 1e-9
N_star = crossover(M, F, B)
assert sum(costs(M, math.floor(N_star)))/F < D_s
assert sum(costs(M, math.ceil(N_star)))/F >= D_s

font = Path("/home/comp/zhanzhao/.local/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf")
font_manager.fontManager.addfont(font)
plt.rcParams.update({
    "font.family": font_manager.FontProperties(fname=font).get_name(),
    "font.size": 10, "axes.unicode_minus": False,
    "pdf.fonttype": 3, "svg.fonttype": "none",
})
width_mm, height_mm = 168, 106
fig = plt.figure(figsize=(width_mm/25.4, height_mm/25.4), facecolor="white")
ax = fig.add_axes([.16, .30, .79, .39])
orange, blue = "#D55E00", "#0072B2"
for i, row in enumerate(rows):
    y = 4-2*i
    ax.barh(y+.23, row["current_layer_prefill_ms"], height=.36,
            color=orange, label="第 1 层：N token Prefill" if i==0 else None)
    ax.barh(y-.23, row["next_layer_h2d_ms"], height=.36,
            color=blue, hatch="///", edgecolor="#005989", linewidth=.5,
            label="第 2 层：M token KV 的 H2D" if i==0 else None)
    for yv,key,color in [(y+.23,"current_layer_prefill_ms",orange),
                         (y-.23,"next_layer_h2d_ms",blue)]:
        value = row[key]
        ax.text(value+.13, yv, f"{value:.2f} ms", va="center", color=color, fontsize=9.5)
ax.set_yticks([4,2,0], [f"N = {r['new_tokens_N']}" for r in rows])
ax.tick_params(axis="y", length=0, pad=8)
ax.set_ylim(-.65,4.65)
ax.set_xlim(0,11.25)
ax.set_xticks([0,2,4,6,8,10])
ax.set_xlabel("单层时间（ms）", labelpad=5)
ax.set_axisbelow(True)
ax.grid(axis="x", color="#DADFE4", linewidth=.65)
for spine in ["top","right","left"]: ax.spines[spine].set_visible(False)
ax.spines["bottom"].set_color("#9BA2A8")
ax.legend(loc="lower left", bbox_to_anchor=(-.12,1.02), frameon=False,
          ncol=2, fontsize=9, columnspacing=1.5, handlelength=1.8)
fig.text(.035,.94,"逐层比较：计算 N 个 token，与搬运 M 个 token",fontsize=12,color="#172B3A")
fig.text(.035,.862,"第 1 层已有 M 个历史 KV；N 个 token 以它们为前缀做增量 Prefill。",fontsize=9.5)
fig.text(.035,.803,"解析假设：Qwen3-8B / BF16 KV / TP=1 / M=32K / 100 TFLOP/s / H2D 25 GB/s",fontsize=8.5,color="#485664")
fig.text(.035,.128,f"本例下一层需搬运 128 MiB；N ≈ {N_star:.0f} 时计算与传输等时。",fontsize=9.5)
fig.text(.035,.072,"Prefill 含本层 QKV、Attention、输出投影和 FFN；M=32K 表示 32768 token。",fontsize=8.5,color="#485664")
fig.text(.035,.022,"非实测；速率是假设值，未计传输竞争与算子开销；模型结构来源：Qwen 官方 config。",fontsize=8.5,color="#485664")
for ext in ["png","pdf","svg"]:
    fig.savefig(HERE / f"layerwise-prefill-vs-h2d.{ext}",dpi=300,facecolor="white")
plt.close(fig)

pdf=pymupdf.open(HERE / "layerwise-prefill-vs-h2d.pdf")
assert abs(pdf[0].rect.width*25.4/72-width_mm)<.05
review=Path('/tmp/aegiskv-layerwise-mn-review'); review.mkdir(exist_ok=True)
pdf[0].get_pixmap(matrix=pymupdf.Matrix(2,2)).save(review/'pdf-at-168mm.png')
pdf[0].get_pixmap(matrix=pymupdf.Matrix(2,2),colorspace=pymupdf.csGRAY).save(review/'gray-at-168mm.png')
summary={
    "evidence_type":params["evidence_type"],
    "experiments_executed":0,
    "n_replicates":None,
    "statistical_unit":"not applicable; rows are deterministic parameter scenarios",
    "single_layer_only":True,
    "kv_bytes_per_token_per_layer":layer_kv_bytes//M,
    "layer_kv_MiB":layer_kv_bytes/1024**2,
    "layer_linear_weight_count":layer_linear_weights,
    "nominal_crossover_N":N_star,
    "sensitivity_crossover_N":{
        f"F={f}TF_B={b}GB":crossover(M,f*1e12,b*1e9)
        for f in [50,100,200] for b in [12.5,25,50]
    },
    "visual_review":"pending",
    "placed_size_mm":[width_mm,height_mm],
    "rows":rows,
    "hashes":{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
              for p in HERE.iterdir() if p.is_file() and p.name!='REVIEW.json'},
}
(HERE/'REVIEW.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({"rows":rows,"crossover_N":N_star},ensure_ascii=False))
