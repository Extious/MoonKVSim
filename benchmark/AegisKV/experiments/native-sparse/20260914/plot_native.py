"""Paper motivation figures drawn exclusively from the captured NOSA traces."""
import csv
import json
import os
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR', '/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/runtime-20260914/mpl-cache')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.patches import Patch
import numpy as np

OUT = Path(__file__).resolve().parent
FIG = OUT / 'figures'
FIG.mkdir(exist_ok=True)
FONT = '/home/comp/zhanzhao/.local/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf'
fontManager.addfont(FONT)
plt.rcParams.update({
    'font.family': FontProperties(fname=FONT).get_name(),
    'font.size': 9.5, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'xtick.labelsize': 8.5, 'ytick.labelsize': 8.5,
    'axes.spines.top': False, 'axes.spines.right': False,
    'axes.linewidth': .65, 'pdf.fonttype': 3, 'svg.fonttype': 'none',
    'savefig.dpi': 300, 'axes.unicode_minus': False,
})
BOOKS = ['10146', '10321', '10356']
COLORS = ['#1675a9', '#c46318', '#507d36']
SUMMARY = json.loads((OUT / 'SUMMARY.json').read_text())
STATS = {(r['book_id'], r['M']): r for r in SUMMARY['results']}
WIDTH = 178 / 25.4


def folder(book, m):
    return OUT / 'traces' / f'pg19-{book}-M{m}-N512'


def counts(book, m):
    with np.load(folder(book, m) / 'counts.npz') as f:
        return f['current']


def export(fig, name):
    for ext in ['png', 'pdf', 'svg']:
        fig.savefig(FIG / f'{name}.{ext}', facecolor='white')
    plt.close(fig)


def frequency_map():
    fig = plt.figure(figsize=(WIDTH, 6.4))
    gs = fig.add_gridspec(3, 1, left=.105, right=.965, top=.865, bottom=.235, hspace=.28)
    fig.suptitle('真实原生稀疏模型：不同层的 KV 热点落在不同位置', y=.965, fontsize=12)
    fig.text(.5, .922, 'NOSA-1B · 28 层 · 历史 M=32,768 · 后续 Query N=512 · 64-token 块',
             ha='center', fontsize=9.1)
    for i, book in enumerate(BOOKS):
        ax = fig.add_subplot(gs[i])
        x = counts(book, 32768).sum(axis=1) / (2 * 512)
        im = ax.imshow(x, aspect='auto', interpolation='nearest', cmap='magma_r',
                       vmin=0, vmax=1, extent=[0, 32, 28.5, .5], rasterized=True)
        ax.set_title(f'PG19 文档 {book}', loc='left', pad=5)
        ax.set_yticks([1, 7, 14, 21, 28])
        ax.set_ylabel('Layer')
        ax.set_xticks([0, 8, 16, 24, 32])
        if i < 2:
            ax.tick_params(axis='x', labelbottom=False)
    fig.text(.54, .177, '历史 KV 的原始 token 位置（单位：1,024 tokens；未按热度重排）',
             ha='center', fontsize=9.2)
    cax = fig.add_axes([.24, .108, .53, .018])
    cb = fig.colorbar(im, cax=cax, orientation='horizontal', ticks=[0, .25, .5, .75, 1])
    cb.ax.set_xticklabels(['0', '25', '50', '75', '100'])
    cb.set_label('该层该块被选中的 Query × KV组比例（%）', fontsize=9.1, labelpad=3)
    fig.text(.5, .025, '实测 3 个文档，各 1 次；每格合并该层的 2 个 KV组。颜色表示选块频率。',
             ha='center', fontsize=8.5)
    export(fig, 'native-layer-block-frequency')


def query_trace():
    m, shown = 32768, 128
    fig = plt.figure(figsize=(WIDTH, 6.5))
    gs = fig.add_gridspec(3, 2, left=.115, right=.975, top=.865, bottom=.20,
                          hspace=.35, wspace=.19)
    fig.suptitle('同一请求、同一组 Query：逐层原生选块轨迹', y=.965, fontsize=12)
    fig.text(.5, .922, 'NOSA-1B · PG19 文档 10146 · M=32,768 · 每列对应 64 个历史 tokens',
             ha='center', fontsize=9.0)
    cmap = ListedColormap(['#ffffff', '#166ba0', '#d79a25'])
    for row, layer in enumerate([1, 14, 28]):
        with np.load(folder('10146', m) / f'layer-{layer:02d}.npz') as f:
            selected = f['selected_blocks'][:, m:m+shown].astype(np.int32)
        for group in range(2):
            ax = fig.add_subplot(gs[row, group])
            matrix = np.zeros((shown, m//64), dtype=np.uint8)
            for q in range(shown):
                blocks = selected[group, q]
                blocks = blocks[(blocks >= 0) & (blocks < m//64)]
                matrix[q, blocks] = 1
                qblock = (m+q)//64
                forced = (blocks < 1) | ((blocks <= qblock) & (qblock <= blocks+16))
                matrix[q, blocks[forced]] = 2
            ax.imshow(matrix, aspect='auto', interpolation='nearest', cmap=cmap,
                      vmin=-.5, vmax=2.5, extent=[0, 32, shown-.5, -.5], rasterized=True)
            ax.set_title(f'Layer {layer}  ·  KV组 {group}', loc='left', fontsize=10, pad=5)
            ax.set_xticks([0, 8, 16, 24, 32])
            ax.set_yticks([0, 64, 127])
            if row < 2:
                ax.tick_params(axis='x', labelbottom=False)
            if group == 1:
                ax.set_yticklabels([])
    fig.text(.023, .535, '后续 Query 偏移 q − M', rotation=90, va='center', fontsize=10)
    fig.text(.54, .144, '历史 KV 的原始 token 位置（单位：1,024 tokens）', ha='center', fontsize=9.5)
    fig.legend(handles=[Patch(facecolor='#166ba0', label='原生非局部选块'),
                        Patch(facecolor='#d79a25', label='原生首块 / 局部窗'),
                        Patch(facecolor='white', edgecolor='#999999', label='未选中')],
               loc='lower center', bbox_to_anchor=(.54, .065), ncol=3,
               frameon=False, fontsize=9, handlelength=1.1, columnspacing=1.4)
    fig.text(.5, .025, '层与文档在运行前固定；图示前 128 个后续 Query，完整逐层索引均已保存。',
             ha='center', fontsize=8.4)
    export(fig, 'native-query-block-traces')


def concentration():
    fig = plt.figure(figsize=(WIDTH, 5.8))
    gs = fig.add_gridspec(2, 3, left=.115, right=.978, top=.80, bottom=.21,
                          wspace=.23, hspace=.34)
    fig.suptitle('少量 KV 是否覆盖大量访问：备份粒度决定可达到的集中度', y=.965, fontsize=11.4)
    fig.text(.5, .923, 'NOSA-1B · 固定后续 512 个 Query · 三个真实文档 · 按观测频率离线排序',
             ha='center', fontsize=8.9)
    fig.legend(handles=[plt.Line2D([0], [0], color=c, lw=1.7, label=f'文档 {b}')
                        for c, b in zip(COLORS, BOOKS)],
               loc='upper center', bbox_to_anchor=(.55, .905), ncol=3,
               frameon=False, fontsize=8.7, columnspacing=1.25)
    definitions = [
        ('层 × KV组 × 块', '32 KiB / 单元', lambda x: x.ravel()),
        ('层 × 块（含全部KV组）', '64 KiB / 单元', lambda x: x.sum(axis=1).ravel()),
        ('token 段（含全部层）', '1.75 MiB / 单元', lambda x: x.sum(axis=(0, 1)).ravel()),
    ]
    curve_rows = []
    for i, m in enumerate([16384, 32768]):
        for j, (title, size, aggregate) in enumerate(definitions):
            ax = fig.add_subplot(gs[i, j])
            for book, color in zip(BOOKS, COLORS):
                values = aggregate(counts(book, m))
                order = np.argsort(-values, kind='stable')
                x = np.arange(len(values)+1) / len(values)
                y = np.r_[0, np.cumsum(values[order])] / values.sum()
                ax.plot(x*100, y*100, color=color, lw=1.4)
                k = int(.2 * len(values))
                ax.scatter([x[k]*100], [y[k]*100], color=color, s=11, zorder=4)
                for xx, yy in zip(x, y):
                    curve_rows.append({'book_id': book, 'M': m, 'granularity': j,
                                       'byte_fraction': float(xx), 'access_coverage': float(yy)})
            ax.plot([0, 100], [0, 100], color='#999999', lw=.85, ls='--', zorder=0)
            ax.axhline(80, color='#aaaaaa', lw=.6, ls=':', zorder=0)
            ax.set(xlim=(0, 100), ylim=(0, 103), xticks=[0, 20, 50, 100], yticks=[0, 40, 80, 100])
            ax.tick_params(labelsize=8)
            if i == 0:
                ax.set_title(title + '\n' + size, fontsize=8.7, pad=7)
            if j > 0:
                ax.set_yticklabels([])
            else:
                ax.set_ylabel(f'{m//1024}K 历史\n累计访问覆盖（%）', fontsize=8.7)
            ax.grid(axis='y', alpha=.13, lw=.6)
    fig.text(.55, .145, '按观测频率排序后，累计历史主 KV 字节比例（%）', ha='center', fontsize=9.2)
    fig.text(.5, .075, '实心点：20% 字节预算；灰色斜线：均匀随机选择的期望；横虚线：80% 访问。',
             ha='center', fontsize=8.3)
    fig.text(.5, .028, '每个文档 × 长度运行 1 次；这是选块观测，不是实际备份、H2D 流量或恢复时延。',
             ha='center', fontsize=8.3)
    export(fig, 'native-access-concentration')
    with (OUT / 'concentration_curves.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=curve_rows[0].keys())
        writer.writeheader()
        writer.writerows(curve_rows)


if __name__ == '__main__':
    frequency_map()
    query_trace()
    concentration()
