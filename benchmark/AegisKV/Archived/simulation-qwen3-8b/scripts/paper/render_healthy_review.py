#!/usr/bin/env python3
"""Create a Figure 6 review candidate from existing, frozen F0 results.

Does not run experiments or update the paper figure/acceptance manifests.
The output includes the observations, definitions, and input file hashes.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from figure_style import BLUE, ORANGE, GRAY, MARKERS, ROOT, save, sha


CAMPAIGN = ROOT / 'output/paper-simulation-8b/20260906-alignment/campaign-v2'
DATA = ROOT / 'benchmark/AegisKV/experiments/results/paper/data'
DEFAULT_OUT = ROOT / 'output/pdf/aegiskv-healthy-review-20260908'
NAME = 'healthy-service-traffic-candidate'
T95_DF4 = 2.7764451051977987
TIMING = ('mean_wct_s', 'p95_wct_s', 'batch_s')


def estimate(values):
    values = np.asarray(values, dtype=float)
    assert len(values) == 5
    avg = float(values.mean())
    half = float(T95_DF4 * values.std(ddof=1) / np.sqrt(5))
    return dict(samples=values.tolist(), mean=avg, low=avg-half, high=avg+half)


def inputs():
    manifest_path = DATA / 'figure-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    bindings = {str(manifest_path.relative_to(ROOT)): sha(manifest_path)}
    for path in (DATA/'aligned-statistics.json', CAMPAIGN/'PROTOCOL.json',
                 CAMPAIGN/'ACCEPTANCE.json'):
        key = str(path.relative_to(ROOT))
        assert sha(path) == manifest['input_bindings'][key], key
        bindings[key] = sha(path)
    stats = json.loads((DATA/'aligned-statistics.json').read_text())
    protocol = json.loads((CAMPAIGN/'PROTOCOL.json').read_text())
    accepted = json.loads((CAMPAIGN/'ACCEPTANCE.json').read_text())
    accepted_runs = {tuple(r['job']): r for r in accepted['accepted_runs']}
    assert accepted['status'] == 'PASS' and protocol['seeds'] == list(range(5))
    arms = {}
    for arm in ('unprotected', 'dram', 'full'):
        endpoints = {key: [] for key in TIMING}
        hbm, dram = [], []
        for seed in range(5):
            path = CAMPAIGN / f'runs/base/seed{seed}/F0-{arm}.json'
            run = json.loads(path.read_text())
            job = ['base', seed, 'F0', arm]
            assert run['identity']['job'] == job
            assert run['identity']['contract'] == protocol['fingerprint']
            assert run['raw_evidence']['sha256'] == accepted_runs[tuple(job)]['raw_sha256']
            summary = run['summary']
            assert not summary['failure_events']
            assert len(summary['wct_ns']) == 160 and len(summary['span_details']) == 1304
            assert summary['workflow_admission']['seed'] == seed
            assert summary['workflow_admission']['workflow_concurrency'] == 16
            wct = np.asarray(list(summary['wct_ns'].values()), dtype=float)/1e9
            metrics = summary['metrics']
            values = dict(mean_wct_s=float(wct.mean()),
                          p95_wct_s=float(sorted(wct)[math.ceil(.95*len(wct))-1]),
                          batch_s=metrics['workload_end_ns']/1e9)
            traffic = metrics['resource_cost']['cause_bytes']
            h = traffic.get('AEGIS_PEER_HBM_PROTECTION', 0)/2**40
            d = traffic.get('AEGIS_STORE_DRAM_PROTECTION', 0)/2**40
            for key, value in {**values, 'protection_GiB': (h+d)*1024}.items():
                assert np.isclose(value, stats['endpoints'][arm]['F0'][key][seed],
                                  rtol=0, atol=1e-9), (arm, seed, key)
            for key, value in values.items():
                endpoints[key].append(value)
            hbm.append(h)
            dram.append(d)
            bindings[str(path.relative_to(ROOT))] = sha(path)
        arms[arm] = dict(endpoints=endpoints, peer_hbm_TiB=hbm, store_dram_TiB=dram,
                         total_TiB=estimate(np.asarray(hbm)+np.asarray(dram)))
    relative = {}
    for key in TIMING:
        base = np.asarray(arms['unprotected']['endpoints'][key])
        assert np.array_equal(base, arms['dram']['endpoints'][key])
        full = np.asarray(arms['full']['endpoints'][key])
        relative[key] = estimate(100*(full-base)/base)
    bindings[str(Path(__file__).resolve().relative_to(ROOT))] = sha(__file__)
    return dict(
        schema='aegiskv.healthy_figure_review.v1',
        status='review_candidate_not_current_paper_figure',
        evidence='Uncalibrated CPU GlobalDES; legacy SlackLandlord/HBMQuotaAIMD policy',
        validation_scope='15 run summaries and 60 endpoint values checked; raw event logs not replayed',
        paired_seeds=list(range(5)), workflow_count_per_run=160,
        workflow_concurrency=16, measured_runs_reused=15,
        definitions=dict(
            relative_timing='100 * (full_s - unprotected_s) / unprotected_s, then mean across 5 seeds',
            p95='nearest rank ceil(0.95 * 160), separately within each run',
            wct='first request release to workflow completion; excludes admission-slot waiting',
            batch='metrics.workload_end_ns: complete-workload makespan',
            traffic='resource_cost.cause_bytes, including transferred work on later-aborted copies; TiB=2^40 bytes',
            intervals='two-sided 95% Student-t, df=4; exploratory, no multiplicity adjustment',
            traffic_increase='ratio of the two mean total traffic volumes, minus one'),
        input_bindings=bindings, arms=arms,
        full_vs_unprotected_percent=relative,
        dram_equals_unprotected_all_timing_endpoints=True,
        traffic_increase_percent=100*(arms['full']['total_TiB']['mean']/arms['dram']['total_TiB']['mean']-1))


def render(data, output):
    fig, (left, right) = plt.subplots(1, 2, figsize=(7, 3.2))
    fig.subplots_adjust(left=.145, right=.985, bottom=.30, top=.90, wspace=.62)

    for key, y in zip(TIMING, (2, 1, 0)):
        e = data['full_vs_unprotected_percent'][key]
        for seed, (value, offset) in enumerate(zip(e['samples'], np.linspace(-.21, .21, 5))):
            left.scatter(value, y+offset, marker=MARKERS[seed], s=24,
                         facecolor='white', edgecolor=BLUE, linewidth=.9, zorder=3)
        left.errorbar(e['mean'], y-.35,
                      xerr=[[e['mean']-e['low']], [e['high']-e['mean']]],
                      fmt='D', ms=4, capsize=3, color=BLUE, lw=1.2, zorder=4)
    left.axvline(0, color=GRAY, ls=(0, (2, 2)), lw=.9, zorder=1)
    left.set_yticks([2, 1, 0], ['Mean WCT', 'P95 WCT', 'Workload\nmakespan'])
    left.set_xticks([-1.5, -1, -.5, 0, .5, 1], ['-1.5', '-1', '-0.5', '0', '0.5', '1'])
    left.set(xlim=(-1.85, 1.15), ylim=(-.7, 2.5),
             title='(a) Full AegisKV impact', xlabel='Change vs. unprotected (%)')
    left.grid(axis='x', color='#ECEFF1', linewidth=.7)

    for x, arm in enumerate(('dram', 'full')):
        d = data['arms'][arm]
        dram, hbm = np.mean(d['store_dram_TiB']), np.mean(d['peer_hbm_TiB'])
        right.bar(x, dram, width=.60, color='#F4DFC3', edgecolor=ORANGE, lw=.9, zorder=2)
        right.text(x, dram/2, 'DRAM', ha='center', va='center')
        if hbm:
            right.bar(x, hbm, bottom=dram, width=.60, color='#B6D7E8',
                      edgecolor=BLUE, hatch='///', lw=.9, zorder=2)
            right.text(x, dram+hbm/2, 'Peer\nHBM', ha='center', va='center',
                       bbox=dict(facecolor='#B6D7E8', edgecolor='none', pad=1))
        e = d['total_TiB']
        for seed, (value, offset) in enumerate(zip(e['samples'], np.linspace(-.18, .18, 5))):
            right.scatter(x+offset, value, marker=MARKERS[seed], s=24,
                          facecolor='white', edgecolor=GRAY, linewidth=.9, zorder=3)
        right.errorbar(x+.40, e['mean'],
                       yerr=[[e['mean']-e['low']], [e['high']-e['mean']]],
                       fmt='D', ms=4, capsize=3, color=GRAY, lw=1.2, zorder=4)
        right.text(x, e['mean']+.22, f"{e['mean']:.3f}", ha='center', va='bottom')
    right.set_xticks([0, 1], ['DRAM-only', 'Full AegisKV'])
    right.set_yticks([0, 2, 4, 6])
    right.set(xlim=(-.48, 1.62), ylim=(0, 6.8), title='(b) Protection traffic',
              ylabel='Transferred TiB / workload')
    right.grid(axis='y', color='#ECEFF1', linewidth=.7)
    right.text(.02, .97, f"Full: +{data['traffic_increase_percent']:.1f}% total",
               transform=right.transAxes, va='top', color=GRAY)
    fig.text(.145, .105, 'DRAM-only: 0% on all three metrics', color=GRAY)
    fig.text(.72, .105, 'Unprotected: 0 TiB', ha='center', color=GRAY)
    fig.text(.5, .025, 'Modeled F0 | Legacy policy | 5 paired admission orders',
             ha='center', va='bottom', color=GRAY)
    save(fig, NAME, directory=output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    data = inputs()
    render(data, args.output)
    data['output_files'] = {ext: sha(args.output/f'{NAME}.{ext}') for ext in ('png', 'svg', 'pdf')}
    (args.output/f'{NAME}.json').write_text(json.dumps(data, indent=2, sort_keys=True)+'\n')
    print(f'Wrote review candidate and checked input data to {args.output}')


if __name__ == '__main__':
    main()
