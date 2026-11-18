#!/usr/bin/env python3
"""Compare the same workflow at C64; retain the original C16 plotting order."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pymupdf

import agent_lease_style as style
from paper_paths import ROOT

OUT=ROOT/'output/pdf/aegiskv-revision-20260909'
ART=ROOT/'output/aegiskv-revision-20260909/scaling'
NAME='eval-concurrency-workflow'
SYSTEMS=('mooncake','dram','aegis')


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def write_csv(path, rows):
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def main():
    inputs={}
    def bind(path):
        inputs[str(path.relative_to(ROOT))]=sha(path)
        return path
    order_path=bind(OUT/'eval-workflow-delay.csv')
    with order_path.open() as f:original=list(csv.DictReader(f))
    order=sorted([r for r in original if r['system']=='mooncake'],key=lambda r:int(r['workflow_rank']))
    assert len(order)==160 and [int(r['workflow_rank']) for r in order]==list(range(1,161))
    ids=[r['workflow_id'] for r in order]
    assert len(set(ids))==160
    order_values={r['workflow_id']:float(r['wct_s']) for r in order}
    points=json.loads(bind(ART/'points.json').read_text())
    audit=json.loads(bind(ART/'RUN_AUDIT.json').read_text())
    assert audit['status']=='PASS' and audit['new_runs']==audit['reused_runs']==6
    rows=[]
    for c in (8,16,32,64):
        data={}
        for system in SYSTEMS:
            p=next(r for r in points if r['concurrency']==c and r['system']==system)
            path=ROOT/p['data_path'];assert sha(path)==p['data_sha256']
            d=json.loads(bind(path).read_text())
            assert d['audit']['status']=='PASS' and d['manifest']['workload']['concurrency']==c
            assert d['manifest']['failure_schedule'] is None
            data[system]={r['workflow_id']:float(r['wct_s']) for r in d['workflows']}
            assert set(data[system])==set(ids)
        if c==16:
            assert data['mooncake']==order_values, 'The ordering reference is not C16 Mooncake F0'
        for rank,wid in enumerate(ids,1):
            baseline=data['mooncake'][wid]
            for system in SYSTEMS:
                value=data[system][wid]
                rows.append(dict(concurrency=c,workflow_rank=rank,workflow_id=wid,system=system,
                                 wct_s=value,mooncake_wct_s=baseline,delta_wct_s=value-baseline,
                                 order_reference_c16_mooncake_wct_s=order_values[wid]))
    assert len(rows)==1920
    selected=[r for r in rows if r['concurrency']==64]
    assert len(selected)==480
    style.install(style)
    fig,ax=style.canvas('Workflow (fixed C16 Mooncake order)','WCT − Mooncake WCT (s)',wide=True,height=3.1)
    fig.subplots_adjust(left=.14,right=.975,top=.80,bottom=.205)
    for system in SYSTEMS:
        sub=[r for r in selected if r['system']==system]
        assert [r['workflow_rank'] for r in sub]==list(range(1,161))
        style.line(ax,system,[r['workflow_rank'] for r in sub],[r['delta_wct_s'] for r in sub],thin=True)
    ax.set_xlim(.5,160.5)
    ax.set_xticks([1,40,80,120,160])
    low=min(r['delta_wct_s'] for r in selected);high=max(r['delta_wct_s'] for r in selected)
    padding=(high-low)*.08
    ax.set_ylim(low-padding,high+padding)
    ax.set_yticks([-400,-200,0,200,400])
    ax.axhline(0,color=style.GRAY,lw=.85,zorder=0)
    leg=style.legend(ax)
    leg.set_bbox_to_anchor((.55,.976),transform=fig.transFigure)
    fig.canvas.draw()
    files={}
    for ext in ('pdf','svg','png'):
        path=OUT/f'{NAME}.{ext}'
        metadata=({'Creator':'AegisKV paired-workflow concurrency renderer','CreationDate':None,'ModDate':None}
                  if ext=='pdf' else {'Date':None} if ext=='svg' else None)
        fig.savefig(path,dpi=220,metadata=metadata)
        files[ext]=sha(path)
    plt.close(fig)
    write_csv(OUT/f'{NAME}.csv',selected)
    files['csv']=sha(OUT/f'{NAME}.csv')
    extra=OUT/f'{NAME}-all-concurrency.csv';write_csv(extra,rows)
    with pymupdf.open(OUT/f'{NAME}.pdf') as doc:
        assert len(doc)==1 and abs(doc[0].rect.width-504)<.01
        spans=[s for b in doc[0].get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans'] if s['text'].strip()]
        assert min(s['size'] for s in spans)>=9.9
        assert all(s['bbox'][0]>=-.1 and s['bbox'][1]>=-.1 and s['bbox'][2]<=doc[0].rect.width+.1 and s['bbox'][3]<=doc[0].rect.height+.1 for s in spans)
        doc[0].get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False).save(OUT/f'{NAME}-pdf-preview.png')
    statistics={}
    for system in SYSTEMS:
        sub=[r for r in selected if r['system']==system]
        d=np.asarray([r['delta_wct_s'] for r in sub])
        statistics[system]=dict(faster=int((d<0).sum()),equal=int((d==0).sum()),slower=int((d>0).sum()),
                                minimum_delta_s=float(min(d)),maximum_delta_s=float(max(d)))
    caption=('最高并发 C=64 时，同一无故障配置下全部 160 个 Workflow 的配对 WCT 差值：每个系统减去同 ID、同 C64 的 Mooncake WCT，负值更快。横轴为 C16 Mooncake 无故障 WCT 固定排序的 Workflow，不是并发轴；排序与正常开销图一致。三系统每个各执行一次，两轮精确输入复访；连线仅连接对象，无跨重复置信区间。AegisKV 有 65 个 Workflow 更快、95 个更慢，全部正负尾部均保留；CSV 保存绝对 WCT 与差值。')
    english=('At maximum concurrency C=64, compare all 160 matched workflows in the same fault-free configuration. Each ordinate subtracts Mooncake WCT at C64 for the same workflow ID; negative is faster. The abscissa is workflow identity in the fixed C16 Mooncake no-failure order used by the healthy-overhead plot, not concurrency. One simulation per system with two exact-input visits; connecting segments are not temporal evolution or replicate intervals. AegisKV is faster on 65 workflows and slower on 95; all positive and negative tails are retained. CSV includes absolute WCTs and paired differences.')
    record=dict(name=NAME,title='并发64下同一 Workflow 的 WCT 差值',caption=caption,caption_en=english,
                width_in=7.,height_in=3.1,evidence='uncalibrated_frozen_algorithm_paired_workflow_simulation',
                files=files,plotted_rows=480,paired_workflows=160,systems=3,complete_runs=3,
                new_experiments_in_renderer=0,statistics=statistics,visual_review='PENDING')
    manifest=dict(figures=[record],inputs=inputs,script_sha256=sha(Path(__file__)),
                  additional_csv={'path':str(extra.relative_to(ROOT)),'sha256':sha(extra),'rows':1920,'concurrency':[8,16,32,64]},
                  ordering_source=str(order_path.relative_to(ROOT)),comparison='same workflow and same concurrency; C16 values are used only for order',
                  all_original_p95_columns_preserved_in_source=True,visual_review='PENDING')
    (OUT/'concurrency-workflow-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'name':NAME,'statistics':statistics,'rows':480,'all_concurrency_rows':1920},indent=2))


if __name__=='__main__':main()
