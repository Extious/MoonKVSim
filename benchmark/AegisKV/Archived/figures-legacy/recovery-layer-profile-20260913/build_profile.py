"""Paired placement illustration; analytical event traces, not measurements."""
from pathlib import Path
from fractions import Fraction
import csv
import json
import os

os.environ.setdefault('MPLCONFIGDIR', '/tmp/aegiskv-recovery-profile-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np
import pymupdf

OUT = Path(__file__).resolve().parent
FONT = Path('/home/comp/zhanzhao/.local/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf')
font_manager.fontManager.addfont(FONT)
plt.rcParams.update({'font.family': font_manager.FontProperties(fname=FONT).get_name(),
                     'font.size': 9, 'axes.unicode_minus': False,
                     'pdf.fonttype': 3, 'svg.fonttype': 'none'})
L, M, N = 36, 32768, 512
KV_BYTES = M * 4096
C = Fraction(2*N*192937984 + 4*4096*(M*N + N*(N+1)//2), 100_000_000_000_000)*1000
D = Fraction(KV_BYTES, 25_000_000_000)*1000
PLACEMENTS = [('前六层', set(range(1, 7))), ('后六层', set(range(31, 37)))]
rows, summaries = [], []
for label, resident in PLACEMENTS:
    copy_end = Fraction(0)
    compute_end = Fraction(0)
    wait_total = Fraction(0)
    for layer in range(1, L+1):
        hbm = layer in resident
        copy_start = None if hbm else copy_end
        if not hbm:
            copy_end += D
        arrival = Fraction(0) if hbm else copy_end
        compute_start = max(compute_end, arrival)
        wait = compute_start - compute_end
        rows.append({'placement': label, 'layer': layer,
                     'reused_history_tokens': M, 'suffix_forward_tokens': N,
                     'initial_hbm_bytes': KV_BYTES if hbm else 0,
                     'h2d_bytes': 0 if hbm else KV_BYTES,
                     'copy_start_ms': None if hbm else float(copy_start),
                     'copy_end_ms': None if hbm else float(copy_end),
                     'kv_ready_ms': float(arrival),
                     'wait_start_ms': float(compute_end), 'exposed_wait_ms': float(wait),
                     'compute_start_ms': float(compute_start),
                     'compute_end_ms': float(compute_start+C), 'compute_ms': float(C)})
        wait_total += wait
        compute_end = compute_start + C
    assert compute_end == L*C + wait_total
    summaries.append({'placement': label, 'initial_hbm_mib': len(resident)*128,
                      'h2d_mib': (L-len(resident))*128,
                      'total_compute_ms': float(L*C), 'exposed_wait_ms': float(wait_total),
                      'modeled_forward_completion_ms': float(compute_end)})
assert summaries[0]['initial_hbm_mib'] == summaries[1]['initial_hbm_mib']
assert summaries[0]['h2d_mib'] == summaries[1]['h2d_mib']
with (OUT/'layer-events.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
(OUT/'summary.json').write_text(json.dumps({'evidence': 'analytical_example_not_measurement',
    'model': 'Qwen3-8B', 'history_tokens': M, 'suffix_tokens': N,
    'layers': L, 'layer_kv_bytes': KV_BYTES, 'layer_compute_ms': float(C),
    'layer_h2d_ms': float(D), 'compute_assumption_TFLOP_s': 100,
    'h2d_assumption_GB_s': 25, 'summaries': summaries}, ensure_ascii=False, indent=2)+'\n')

green, blue, orange, gray, pale = '#009E73', '#0072B2', '#D55E00', '#65758B', '#E5EAF0'
fig = plt.figure(figsize=(178/25.4, 210/25.4), facecolor='white')
fig.text(.10, .970, '同样的 HBM 容量，驻留位置改变哪些恢复等待？', fontsize=12, weight='bold')
fig.text(.10, .942, '解析示例，非实测  |  Qwen3-8B  |  32K 历史 + 512 个后缀 token', fontsize=9)
fig.text(.10, .919, '36 层；每层历史 KV 128 MiB；两种放置均为 HBM 768 MiB + H2D 3840 MiB', fontsize=8.5)

ax = fig.add_axes([.18, .766, .77, .085])
matrix = np.array([[int(l in s) for l in range(1, L+1)] for _, s in PLACEMENTS])
ax.imshow(matrix, aspect='auto', cmap=ListedColormap([pale, green]), vmin=0, vmax=1,
          interpolation='none', extent=(.5, L+.5, 1.5, -.5))
ax.set_yticks([0,1], [x[0] for x in PLACEMENTS]); ax.set_xticks([1,6,12,18,24,30,36])
ax.set_xticks(np.arange(.5, 37, 1), minor=True); ax.grid(which='minor', axis='x', color='white', lw=.5)
ax.tick_params(which='minor', length=0)
fig.text(.18, .893, '(a) 故障时的历史 KV 放置：每格大小相同', fontsize=10)
ax.legend(handles=[Patch(facecolor=green, label='接管 DP 的 HBM'), Patch(facecolor=pale, label='DRAM')],
          loc='lower left', bbox_to_anchor=(0,1.02), ncol=2, frameon=False, borderaxespad=0, fontsize=8)

ax = fig.add_axes([.18, .370, .77, .30])
levels = {'前六层': (3.1, 2.35), '后六层': (1.05, .30)}
for label, _ in PLACEMENTS:
    copy_y, calc_y = levels[label]
    rr = [r for r in rows if r['placement']==label]
    for r in rr:
        if r['copy_start_ms'] is not None:
            ax.broken_barh([(r['copy_start_ms'], float(D))], (copy_y, .42),
                          facecolors=blue, edgecolors='white', linewidth=.3)
        if r['exposed_wait_ms']:
            ax.broken_barh([(r['wait_start_ms'], r['exposed_wait_ms'])], (calc_y, .42),
                          facecolors=orange, linewidth=0)
        ax.broken_barh([(r['compute_start_ms'], float(C))], (calc_y, .42),
                      facecolors=gray, edgecolors='white', linewidth=.25)
        if r['layer'] in [1, 6, 12, 18, 24, 30, 36]:
            ax.text(r['compute_start_ms']+float(C)/2, calc_y+.51, str(r['layer']),
                    ha='center', va='bottom', fontsize=6.8, color=gray)
    ss=next(s for s in summaries if s['placement']==label)
    ax.text(.01, (copy_y+.70)/4.10, f"{label}驻留：等待 {ss['exposed_wait_ms']:.2f} ms；完成 {ss['modeled_forward_completion_ms']:.2f} ms",
            transform=ax.transAxes, fontsize=8.5, va='bottom')
ax.set_ylim(0,4.10); ax.set_xlim(0,205)
ax.set_yticks([3.31,2.56,1.26,.51], ['H2D','前向','H2D','前向'])
ax.set_xticks([0,40,80,120,160,200]); ax.set_xlabel('从恢复计划启动起的时间（ms）', labelpad=2)
fig.text(.18, .713, '(b) 同一时钟下的复制与计算；小数字为层号', fontsize=10)
ax.legend(handles=[Patch(facecolor=blue,label='H2D'),Patch(facecolor=gray,label='后缀整层前向'),
                   Patch(facecolor=orange,label='计算流等待 KV')],
          loc='lower left',bbox_to_anchor=(0,1.015),ncol=3,frameon=False,borderaxespad=0,fontsize=8)
ax.grid(axis='x', color='#CCCCCC', alpha=.35, lw=.5); ax.set_axisbelow(True)

ax = fig.add_axes([.18, .148, .77, .115])
for label, _ in PLACEMENTS:
    rr=[r for r in rows if r['placement']==label]
    ax.plot([r['layer'] for r in rr], [r['exposed_wait_ms'] for r in rr],
            color=green if label=='前六层' else orange, marker='o' if label=='前六层' else 's',
            ms=2.8, lw=1.2, label=label+'驻留', clip_on=False)
ax.set_xlim(.5,36.5); ax.set_ylim(-.2,6); ax.set_xticks([1,6,12,18,24,30,36])
ax.set_yticks([0,2,4,6]); ax.set_xlabel('模型层号', labelpad=2); ax.set_ylabel('等待（ms）', labelpad=4)
ax.set_title('(c) 等待具体发生在哪一层', loc='left', fontsize=10, pad=8)
ax.legend(loc='upper right', ncol=2, frameon=False, fontsize=8)
ax.grid(axis='y',color='#CCCCCC',alpha=.35,lw=.5)
for a in fig.axes:
    a.spines[['top','right']].set_visible(False)
    a.tick_params(labelsize=8)
fig.text(.10,.070, f'两种放置的计算均为 {float(L*C):.2f} ms。差异来自暴露等待，不是重算量或传输总字节减少。', fontsize=8)
fig.text(.10,.046, '假设：100 TFLOP/s、H2D 25 GB/s；时间零开始按层提前预取；空间充足，复制与计算无争用。', fontsize=7.5)
fig.text(.10,.027, '整层就绪门模型；未计检测、排队、算子启动及显式访存成本。这是机制示例，不能证明真实系统收益。', fontsize=7.5)
for ext in ['png','pdf','svg']:
    fig.savefig(OUT/f'paired-layer-profile.{ext}', dpi=220, facecolor='white')
plt.close(fig)
doc=pymupdf.open(OUT/'paired-layer-profile.pdf')
doc[0].get_pixmap(matrix=pymupdf.Matrix(1.55,1.55)).save(OUT/'pdf-render.png')
print(json.dumps({'C_ms':float(C),'D_ms':float(D),'summaries':summaries},ensure_ascii=False,indent=2))
