"""Figures from local SGLang source and a labeled CPU-reference fixture."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR', '/tmp/aegiskv-sglang-sparse-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch, Rectangle, FancyBboxPatch, FancyArrowPatch
import numpy as np
import pymupdf

OUT = Path(__file__).resolve().parent
DATA = json.loads((OUT / 'reference_trace.json').read_text())
FONT = Path('/home/comp/zhanzhao/.local/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf')
font_manager.fontManager.addfont(FONT)
plt.rcParams.update({
    'font.family': font_manager.FontProperties(fname=FONT).get_name(),
    'font.size': 8.5, 'axes.titlesize': 9.5, 'axes.labelsize': 8.5,
    'axes.unicode_minus': False, 'pdf.fonttype': 3, 'svg.fonttype': 'none',
    'axes.spines.top': False, 'axes.spines.right': False,
    'axes.linewidth': 0.6,
})
BLUE, GREEN, ORANGE, PURPLE = '#0072B2', '#009E73', '#D55E00', '#8064A2'
GRAY, PALE, INK = '#DCE1E6', '#F3F6F9', '#25364B'
WIDTH_MM = 178
M = DATA['config']['M_history_tokens']
N = DATA['config']['N_replayed_tokens']
EXPORTS = []


def header(fig, title, subtitle):
    fig.text(.06, .972, title, fontsize=11, color=INK, va='top')
    fig.text(.06, .916, subtitle, fontsize=8, color='#555555', va='top')


def export(fig, name):
    for suffix in ('png', 'pdf', 'svg'):
        fig.savefig(OUT / f'{name}.{suffix}', dpi=240, facecolor='white')
    pdf = pymupdf.open(OUT / f'{name}.pdf')
    page = pdf[0]
    assert abs(page.rect.width / 72 * 25.4 - WIDTH_MM) < .02
    preview = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
    preview.save(OUT / f'{name}.pdf-preview.png')
    spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
    EXPORTS.append({
        'name': name, 'width_mm': WIDTH_MM,
        'height_mm': page.rect.height / 72 * 25.4,
        'minimum_extracted_font_pt': min(s['size'] for s in spans),
        'visual_review_pending': True,
    })
    pdf.close()
    plt.close(fig)


def selection_figure():
    fig = plt.figure(figsize=(WIDTH_MM / 25.4, 139 / 25.4))
    header(fig, '逐 Query 选取的 KV，可以随层和位置变化',
           '本机 SGLang Top-k 参考函数输出；分数是手工构造输入，未运行训练好的模型')
    fig.text(.06, .863, '固定状态：M = 16，N = 8，k = 4；两组独立层输入；图中位置从 1 起编号', fontsize=8)
    for layer_id, x in enumerate((.085, .555)):
        layer = DATA['layers'][layer_id]
        ax = fig.add_axes([x, .405, .405, .33])
        values = np.zeros((N, M + N), dtype=int)
        for i, indices in enumerate(layer['logical_selected_indices']):
            values[i, M + i + 1:] = 3
            for j in indices:
                values[i, j] = 1 if j < M else 2
        cmap = ListedColormap(['white', BLUE, GREEN, GRAY])
        ax.imshow(values, aspect='auto', interpolation='nearest', cmap=cmap,
                  norm=BoundaryNorm(np.arange(-.5, 4), cmap.N))
        ax.axvline(M - .5, color=INK, linestyle='--', linewidth=.8)
        ax.set_xticks([0, 3, 7, 11, 15, 19, 23], [1, 4, 8, 12, 16, 20, 24])
        ax.set_yticks(np.arange(N), np.arange(M + 1, M + N + 1))
        ax.set_xlabel('Key 的逻辑位置')
        ax.set_ylabel('Query 位置' if layer_id == 0 else '')
        ax.set_title(f'({chr(97 + layer_id)}) 层 {layer_id + 1} 的选择', loc='left', pad=9)
        # Thin cell guides distinguish one logical token from a kernel tile.
        ax.set_xticks(np.arange(-.5, M + N), minor=True)
        ax.set_yticks(np.arange(-.5, N), minor=True)
        ax.grid(which='minor', color='#DFE6EC', linewidth=.25)
        ax.tick_params(which='minor', bottom=False, left=False)
        ax.tick_params(labelsize=7.8)

        bar = fig.add_axes([x, .125, .405, .155])
        counts = np.array(layer['selection_count_by_position'][:M])
        bar.bar(np.arange(1, M + 1), counts, color=BLUE, width=.72)
        bar.set_xlim(.3, M + .7)
        bar.set_ylim(0, N + .5)
        bar.set_yticks([0, 4, 8])
        bar.set_xticks([1, 4, 8, 12, 16])
        bar.set_xlabel('旧历史 KV 的逻辑位置')
        bar.set_ylabel('被选 Query 数' if layer_id == 0 else '')
        bar.set_title(f'({chr(99 + layer_id)}) 同一输入的历史访问频次', loc='left', pad=8)
        bar.grid(axis='y', color=GRAY, linewidth=.5)
        bar.set_axisbelow(True)
    fig.legend(handles=[Patch(facecolor=BLUE, label='选中旧历史'),
                        Patch(facecolor=GREEN, label='选中重放状态'),
                        Patch(facecolor=GRAY, label='未来位置，不可见')],
               loc='upper center', bbox_to_anchor=(.51, .835), ncol=3, frameon=False, fontsize=8)
    fig.text(.06, .022, '高频由本例输入构造；图可解释选择语义，不能证明真实模型的热点集中或备份收益。', fontsize=8, color=INK)
    export(fig, 'sglang-per-query-selection')


def physical_figure():
    fig = plt.figure(figsize=(WIDTH_MM / 25.4, 127 / 25.4))
    header(fig, '逻辑稀疏率，还不是需要装入的物理 KV 比例',
           '沿用层 1 的同一参考输出；1 / 4 / 8-token 为对照假设，不是本机 HiSparse 的三种实测配置')
    first = sorted(j + 1 for j in DATA['layers'][0]['logical_selected_indices'][0] if j < M)
    fig.text(.06, .854, f'首个 Query = 17：选中旧历史 {first}，另选中当前位置 17；以下只统计旧历史', fontsize=8)
    ax = fig.add_axes([.13, .535, .63, .245])
    ax.set_xlim(.5, M + .5)
    ax.set_ylim(-.55, 2.65)
    ax.set_xticks([1, 4, 8, 12, 16])
    ax.set_xlabel('旧历史 KV 的逻辑位置')
    ax.set_yticks([2, 1, 0], ['1-token 块', '4-token 块', '8-token 块'])
    for row, item in enumerate(DATA['physical_block_assumption_examples']):
        y = 2 - row
        block = item['transport_block_tokens_ASSUMED']
        needed = set(item['first_query_materialized_history_positions'])
        for j in range(M):
            color = BLUE if j + 1 in first else '#F6C58F' if j in needed else 'white'
            ax.add_patch(Rectangle((j + .5, y - .28), 1, .56, facecolor=color, edgecolor=GRAY, linewidth=.45))
        for start in range(0, M, block):
            ax.add_patch(Rectangle((start + .5, y - .28), block, .56, fill=False, edgecolor=INK, linewidth=.75))
        ax.text(M + 1.1, y, f"装入 {item['first_query_transfer_tokens']}/16 个\n历史 token 的 KV", va='center', fontsize=8, clip_on=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(axis='y', length=0)
    fig.legend(handles=[Patch(facecolor=BLUE, label='确实被选中'),
                        Patch(facecolor='#F6C58F', label='整块装入带入的其他 KV')],
               loc='upper center', bbox_to_anchor=(.50, .474), ncol=2, frameon=False, fontsize=8)
    ax2 = fig.add_axes([.10, .142, .82, .235])
    styles = [(BLUE, 'o', '-'), (ORANGE, 's', '--'), (PURPLE, '^', ':')]
    for item, (color, marker, style) in zip(DATA['physical_block_assumption_examples'], styles):
        ax2.step(np.arange(1, N + 1), item['window_union_tokens_by_query'], where='post',
                 color=color, marker=marker, markersize=3.7, linestyle=style,
                 label=f"{item['transport_block_tokens_ASSUMED']}-token 块")
    ax2.set_ylim(0, 17)
    ax2.set_yticks([0, 4, 8, 12, 16])
    ax2.set_xticks(np.arange(1, N + 1))
    ax2.set_xlabel('已处理的重放 Query 数')
    ax2.set_ylabel('历史 KV 需求并集\n（以 token 数计）')
    ax2.grid(axis='y', color=GRAY, linewidth=.5)
    ax2.legend(loc='lower right', frameon=False, ncol=3, fontsize=8)
    fig.text(.06, .021, '并集假定按需整块装入且装入后不逐出；它表示工作集，不是时延或 WCT。', fontsize=8, color=INK)
    export(fig, 'sglang-selection-to-physical-blocks')


def box(ax, x, y, w, h, text, color=PALE, edge=INK, dashed=False, fontsize=8.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.006,rounding_size=.009',
                               facecolor=color, edgecolor=edge, linewidth=.8,
                               linestyle='--' if dashed else '-'))
    ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=fontsize, color=INK)


def arrow(ax, start, end, color=INK, dashed=False):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle='-|>', mutation_scale=10,
                                linewidth=.85, color=color, linestyle='--' if dashed else '-'))


def path_figure():
    fig = plt.figure(figsize=(WIDTH_MM / 25.4, 154 / 25.4))
    header(fig, '本机 SGLang：稀疏选择之后，仍要满足 KV 就绪依赖',
           '基于 dce5a12be0 源码的机制图；实线为已读代码路径，虚线为拟议的 Retry Prefill 扩展')
    ax = fig.add_axes([.055, .035, .895, .84])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    ax.text(0, .975, '(a) 选择器先产生逻辑位置；辅助 index-K 状态也必须可用', fontsize=9.5, va='top')
    box(ax, .01, .81, .26, .10, '本层 Query\n+ index-K / scale 状态')
    box(ax, .37, .81, .25, .10, '索引打分\n+ 因果可见范围')
    box(ax, .73, .81, .25, .10, '每 Query 的 Top-k\n逻辑 token 位置')
    arrow(ax, (.277, .86), (.36, .86))
    arrow(ax, (.627, .86), (.723, .86))
    ax.text(.01, .771, '这里的索引分数不是主 attention 的概率；HiSparse Decode 保留未融合的逻辑索引。', fontsize=8)

    ax.text(0, .708, '(b) 已有 Decode 路径：逐层解析驻留位置，缺失项从 Host 装入', fontsize=9.5, va='top')
    box(ax, .01, .49, .24, .13, 'Top-k + request ID\n+ layer ID\n检查本层设备缓存')
    box(ax, .37, .595, .28, .068, 'HBM 命中 → 直接用', color='#E0F0FA', edge=BLUE)
    box(ax, .37, .494, .28, .068, 'HBM 未命中 → Host 装入', color='#FFF0DF', edge=ORANGE, fontsize=8)
    box(ax, .37, .393, .28, .068, '当前新 token → 本地槽', color='#E2F4EC', edge=GREEN)
    arrow(ax, (.257, .585), (.363, .629), BLUE)
    arrow(ax, (.257, .553), (.363, .528), ORANGE)
    arrow(ax, (.257, .515), (.363, .427), GREEN)
    box(ax, .77, .49, .20, .13, '所需 KV 已就绪\nSparse attention')
    arrow(ax, (.657, .629), (.763, .585), BLUE)
    arrow(ax, (.657, .528), (.763, .553), ORANGE)
    arrow(ax, (.657, .427), (.763, .515), GREEN)
    ax.text(.01, .338, '构造例：S = {1,4,6,7}，Top-k = {1,4,9,17} → 2 个旧 KV 命中、1 个 Host 装入、1 个本地新 KV。', fontsize=7.8)

    ax.text(0, .274, '(c) Retry Prefill 的缺口：现有 forward_extend 没有调用同一 swap-in 接口', fontsize=9.2, va='top')
    box(ax, .01, .104, .26, .094, '本机 Prefill：\n已有设备 KV / 位置映射', fontsize=8.3)
    box(ax, .37, .104, .27, .094, '稀疏 Prefill attention\n消费已有设备 KV', fontsize=8.3)
    arrow(ax, (.277, .151), (.363, .151))
    box(ax, .75, .089, .23, .124, '拟扩展：M 历史选块\n装入 / 预取 / 就绪\n与 N-token 重放衔接', color='white', edge=ORANGE, dashed=True, fontsize=8)
    arrow(ax, (.743, .152), (.647, .152), ORANGE, dashed=True)
    ax.text(.01, .018, '源路径未提供固定 Retry DP 的故障恢复协议；本图不表示已经测得 Peer HBM 的恢复收益。', fontsize=8)
    export(fig, 'sglang-hisparse-recovery-path')


def main():
    selection_figure()
    physical_figure()
    path_figure()
    (OUT / 'export_metadata.json').write_text(json.dumps(EXPORTS, indent=2) + '\n')
    print(json.dumps(EXPORTS, indent=2))


if __name__ == '__main__':
    main()
