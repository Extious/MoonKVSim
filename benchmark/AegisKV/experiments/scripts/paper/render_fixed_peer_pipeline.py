#!/usr/bin/env python3
"""Constructed three-stage schedules, using only a previously measured replay mean.

Native block selection is NOT measured here. All four cases have identical
unique history. (c)/(d) have identical demand, differing only in Peer placement.
"""
from pathlib import Path
import csv
import hashlib
import json
import subprocess
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'exports/fixed-peer-lazy-credit-20260921'
MANIFEST = ROOT / 'Archived/paper-overleaf-20260919/paper/figures/design-single/MANIFEST.json'
LAYERS, BLOCKS, K, MISS, PEER_L = 32, 512, 336, 64, 7
BLOCK_BYTES = 65536  # 32 MiB/layer, 512 64-token physical groups
H2D_GBS, STORAGE_GBS = 6.25, 3.125


def simulate(name, compute_ms, sparse=False, peer_l=0, serial=False):
    jobs, done, events = [], set(), []
    layer_deps = [set() for _ in range(LAYERS)]
    demand_created = set()
    running = {r: None for r in ['Storage', 'H2D', 'GPU']}
    starts, ends = [], []
    def add_group(l, kind, blocks):
        for tier in ['DRAM', 'Storage']:
            nbytes = blocks * BLOCK_BYTES // 2
            if not nbytes:
                continue
            ident = f'{l}-{kind}-{tier}'
            deps = set()
            if tier == 'Storage':
                read_id = ident + '-read'
                jobs.append(dict(id=read_id, resource='Storage', layer=l, kind=kind,
                                 bytes=nbytes, deps=set(), duration=nbytes / (STORAGE_GBS * 1e6)))
                deps.add(read_id)
            jobs.append(dict(id=ident, resource='H2D', layer=l, kind=kind,
                             bytes=nbytes, deps=deps, duration=nbytes / (H2D_GBS * 1e6)))
            layer_deps[l].add(ident)
    for l in range(LAYERS):
        add_group(l, 'Preload', 0 if l < peer_l else (K if sparse else BLOCKS))
    now, next_layer = 0., 0
    while len(ends) < LAYERS:
        # A layer's demand miss becomes known only after the preceding compute.
        if sparse and next_layer not in demand_created and running['GPU'] is None:
            add_group(next_layer, 'Demand', MISS)
            demand_created.add(next_layer)
        for resource in ['Storage', 'H2D']:
            if running[resource] is not None:
                continue
            ready = [j for j in jobs if j['resource'] == resource and
                     j['id'] not in done and not j.get('started') and j['deps'] <= done]
            if ready:
                j = min(ready, key=lambda x: (x['kind'] != 'Demand', x['layer'], x['id']))
                j['started'] = True
                running[resource] = (now+j['duration'], j)
                events.append(dict(case=name, resource=resource, kind=j['kind'],
                                   layer=j['layer'], start_ms=now, end_ms=now+j['duration'],
                                   bytes=j['bytes'], job_id=j['id']))
        all_io_done = all(j['id'] in done for j in jobs)
        if (running['GPU'] is None and layer_deps[next_layer] <= done and
                (not serial or all_io_done)):
            starts.append(now)
            running['GPU'] = (now+compute_ms, dict(id=f'compute-{next_layer}'))
            events.append(dict(case=name, resource='GPU', kind='Compute', layer=next_layer,
                               start_ms=now, end_ms=now+compute_ms, bytes=0,
                               job_id=f'compute-{next_layer}'))
        future = [v[0] for v in running.values() if v is not None]
        assert future, 'scheduler deadlock'
        now = min(future)
        for resource, entry in list(running.items()):
            if entry is not None and abs(entry[0]-now) < 1e-8:
                done.add(entry[1]['id'])
                running[resource] = None
                if resource == 'GPU':
                    ends.append(now)
                    next_layer += 1
    # Validate causal dependencies and physical resource serialization.
    by_id = {e['job_id']: e for e in events}
    for j in jobs:
        assert j['id'] in done
        assert all(by_id[d]['end_ms'] <= by_id[j['id']]['start_ms'] + 1e-7 for d in j['deps'])
    for l in range(LAYERS):
        assert all(by_id[d]['end_ms'] <= starts[l]+1e-7 for d in layer_deps[l])
        if l:
            assert starts[l] >= ends[l-1]-1e-7
        for e in events:
            if e['layer'] == l and e['kind'] == 'Demand':
                assert e['start_ms'] >= (ends[l-1] if l else 0)-1e-7
    for resource in running:
        seq = sorted([e for e in events if e['resource'] == resource], key=lambda e:e['start_ms'])
        assert all(a['end_ms'] <= b['start_ms']+1e-7 for a,b in zip(seq,seq[1:]))
    expected = (LAYERS*(K+MISS if sparse else BLOCKS)-peer_l*K)*BLOCK_BYTES
    assert sum(e['bytes'] for e in events if e['resource']=='H2D') == expected
    assert sum(e['bytes'] for e in events if e['resource']=='Storage')*2 == expected
    peer_mib = peer_l*K*BLOCK_BYTES/2**20
    return dict(case=name, total_ms=ends[-1], wait_ms=ends[-1]-LAYERS*compute_ms,
                starts=starts, ends=ends, peer_mib=peer_mib,
                dram_mib=512-peer_mib/2, storage_mib=512-peer_mib/2), events


def main():
    old = json.loads(MANIFEST.read_text())
    compute = old['C_ms']
    cases, events = [], []
    for name, kw in [('Serial full KV',dict(serial=True)),
                     ('Pipelined full KV',{}),
                     ('Sparse, DRAM/storage',dict(sparse=True)),
                     ('Sparse + Peer',dict(sparse=True,peer_l=PEER_L))]:
        case, ev = simulate(name, compute, **kw)
        cases.append(case); events.extend(ev)
    for fname in ['LinLibertine_R.otf','LinLibertine_RB.otf']:
        font_manager.fontManager.addfont(subprocess.check_output(['kpsewhich',fname],text=True).strip())
    plt.rcParams.update({'font.family':'Linux Libertine O','font.size':10.3,
                         'pdf.fonttype':42,'svg.fonttype':'none'})
    colors = {'Preload':'#23688D','Demand':'#9B6428','Compute':'#566168','Wait':'#E3B9BC'}
    fig = plt.figure(figsize=(3.33465,4.15))
    fig.legend(handles=[Patch(facecolor=colors[k],label=k,hatch='///' if k=='Demand' else None)
                        for k in colors],loc='upper center',bbox_to_anchor=(.5,1.005),
               ncol=2,frameon=False,handlelength=1,handletextpad=.4,columnspacing=.8)
    max_t = max(c['total_ms'] for c in cases)*1.03
    for i,c in enumerate(cases):
        y = .69-i*.183
        ax = fig.add_axes([.21,y,.76,.108])
        for e in events:
            if e['case'] != c['case']:continue
            row = {'Storage':2,'H2D':1,'GPU':0}[e['resource']]
            ax.barh(row,e['end_ms']-e['start_ms'],left=e['start_ms'],height=.74,
                    color=colors[e['kind']],hatch='///' if e['kind']=='Demand' else None,
                    edgecolor='white',lw=.12)
        for l,start in enumerate(c['starts']):
            prev = c['ends'][l-1] if l else 0
            if start > prev:
                ax.barh(0,start-prev,left=prev,height=.74,color=colors['Wait'])
        ax.set(xlim=(0,max_t),ylim=(-.6,2.6),yticks=[0,1,2],yticklabels=['GPU','H2D','Store'])
        ax.tick_params(axis='y',length=0,pad=3)
        ax.tick_params(axis='x',bottom=i==3,labelbottom=i==3,length=3,pad=3)
        for sp in ax.spines.values():sp.set_visible(False)
        ax.spines['bottom'].set_visible(i==3)
        fig.text(.02,y+.132,f'({chr(97+i)}) {c["case"]}',ha='left')
        fig.text(.975,y+.112,f'{c["total_ms"]:.1f} / {c["wait_ms"]:.1f} ms',ha='right',fontsize=10.3)
        if i==3:ax.set_xlabel('Time after takeover (ms)',labelpad=2)
    fig.text(.97,.86,'Completion / exposed wait',ha='right',fontsize=10.3)
    for ext in ['pdf','png','svg']:
        fig.savefig(OUT/'figures'/f'recovery-pipeline.{ext}',dpi=220,facecolor='white')
    plt.close(fig)
    with (OUT/'data/pipeline-events.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=events[0]);w.writeheader();w.writerows(events)
    record = dict(evidence='constructed analytical three-resource schedules',new_physical_runs=0,
                  layers=LAYERS,history_tokens=32768,tail_tokens=64,block_tokens=64,
                  layer_block_bytes=BLOCK_BYTES,blocks_per_layer=BLOCKS,
                  preload_K=K,constructed_miss_blocks=MISS,peer_L=PEER_L,
                  assumed_storage_gbs=STORAGE_GBS,assumed_h2d_gbs=H2D_GBS,
                  calibrated_replay_ms=compute,unique_mib=1024,cases=cases,
                  scheduling='nonpreemptible I/O groups; revealed demand before preload; layer order',
                  endpoint='tail completion; unselected cold KV not loaded before this endpoint',
                  assumptions=['independent storage reader and H2D stream','sufficient staging/workspace',
                               'no foreground queues','steady placement before fault',
                               'preload and missed IDs are constructed, not native predictions',
                               'mean replay time reused; no per-layer timing variation'],
                  calibration_source=str(MANIFEST.relative_to(ROOT)),
                  calibration_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
                  upstream_source_hashes=old['source_hashes'])
    (OUT/'data/pipeline-provenance.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps([{k:v for k,v in c.items() if k not in ['starts','ends']} for c in cases],indent=2))


if __name__=='__main__':
    main()
