#!/usr/bin/env python3
"""Render separate healthy-execution figures and audit available mechanism data.

Reuses the existing 15 F0 runs. Every export has one axes object, explicit
legends, and no embedded caption, panel letter, seed key, or scope footer.
No native Mooncake result, CPU measurement, or link-utilization claim is inferred.
"""
import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from figure_style import BLUE, ORANGE, GRAY, ROOT, save, sha, plt
from render_healthy_review import CAMPAIGN, TIMING, estimate, inputs


DEFAULT_OUT = ROOT / 'output/pdf/aegiskv-healthy-standalone-20260908'
FROZEN = CAMPAIGN.parent / 'source-v2'
NAMES = ('healthy-service-impact', 'healthy-protection-traffic',
         'healthy-request-start-wait', 'healthy-peer-hbm-footprint')


def mechanism_data(data):
    rows = []
    for seed in range(5):
        for arm in ('unprotected', 'dram', 'full'):
            path = CAMPAIGN / f'runs/base/seed{seed}/F0-{arm}.json'
            assert sha(path) == data['input_bindings'][str(path.relative_to(ROOT))]
            run = json.loads(path.read_text())
            summary = run['summary']
            metrics = summary['metrics']
            resource = metrics['resource_cost']
            spans = summary['span_details']
            assert len(spans) == 1304
            # compute_start_ns can reset during recomputation. These F0 records
            # have no reroute/recompute, so it denotes the first forward start.
            assert all(s['recompute_tokens'] == 0 and s['route_version'] == 0
                       and s['prompt_recompute_start_ns'] is None for s in spans)
            for tier, field in (('normal_hbm', 'reused_primary_tokens'),
                                ('peer_hbm', 'reused_peer_tokens'),
                                ('store_dram', 'reused_store_tokens')):
                assert sum(s[field] for s in spans) == metrics['cache_reuse_tokens'][tier]
            wait = np.array([(s['compute_start_ns']-s['released_ns'])/1e9 for s in spans])
            assert np.all(wait >= 0)
            assert metrics['virtual_end_ns'] == metrics['workload_end_ns']
            rows.append(dict(
                seed=seed, arm=arm,
                start_wait_mean_s=float(wait.mean()),
                start_wait_p95_s=float(sorted(wait)[math.ceil(.95*len(wait))-1]),
                start_wait_max_s=float(wait.max()),
                reused_primary_tokens=metrics['cache_reuse_tokens']['normal_hbm'],
                reused_peer_tokens=metrics['cache_reuse_tokens']['peer_hbm'],
                reused_dram_tokens=metrics['cache_reuse_tokens']['store_dram'],
                peer_time_avg_GiB=resource['peer_hbm_byte_ns']/metrics['workload_end_ns']/2**30,
                peer_committed_peak_GiB=resource['peer_hbm_peak_bytes']/2**30,
                aimd_enabled=metrics['policy_effects']['aimd_enabled'],
                aimd_pressure_observations=metrics['policy_effects']['hbm_pressure_observation_count'],
                peer_headroom_defer_count=metrics['policy_effects']['protection_path_bypasses'].get(
                    'PEER_HBM_FOREGROUND_HEADROOM_DEFERRED', 0),
                protection_transfer_wait_s=sum(resource['queue_wait_ns_by_cause'].values())/1e9,
                protection_transfer_service_s=sum(resource['service_time_ns_by_cause'].values())/1e9,
                simulator_wall_seconds=run['wall_seconds']))
    wait_effect = {}
    for key in ('start_wait_mean_s', 'start_wait_p95_s'):
        full = [r[key] for r in rows if r['arm'] == 'full']
        dram = [r[key] for r in rows if r['arm'] == 'dram']
        wait_effect[key] = estimate(np.asarray(full)-np.asarray(dram))
    data['mechanism_observations'] = rows
    data['all_normal_reuse_tokens_zero'] = all(
        r[k] == 0 for r in rows
        for k in ('reused_primary_tokens', 'reused_peer_tokens', 'reused_dram_tokens'))
    data['pressure_counts_comparable_across_arms'] = False
    data['full_minus_dram_start_wait_s'] = wait_effect
    data['peer_time_avg_GiB'] = {
        arm: estimate([r['peer_time_avg_GiB'] for r in rows if r['arm'] == arm])
        for arm in ('unprotected', 'dram', 'full')}
    data['definitions'].update(
        request_start_wait='compute_start_ns - released_ns; time before first forward; not TTFT, pure HBM allocation stall, or admission-slot waiting',
        peer_time_average='peer_hbm_byte_ns / workload_end_ns / 2^30; committed plus pending; sum over all 8 GPUs',
        peer_peak='peer_hbm_peak_bytes / 2^30; simultaneous committed occupancy only; excludes pending',
        aimd_pressure='observation collection is enabled only with AIMD; zero in disabled arms is not a comparable zero-pressure measurement',
        simulator_wall='includes simulation, evidence serialization and auditing; not native serving CPU overhead',
        transfer_wait='sum of transfer start minus ready; not foreground request queue delay',
        resource_busy='cause-wise busy durations sum multiple resources; cannot divide by one run duration to infer per-link utilization')
    data['missing_evidence'] = [
        'Independent vanilla Mooncake arm in this campaign',
        'Nonzero normal reuse and a controlled shared-prefix/reuse-distance workload',
        'Common HBM-stall instrumentation across all arms',
        'Native admission/controller/process CPU timings',
        'Per-link foreground/background bandwidth and copy-contention measurements',
        'Revision-3 workload runs and physical integration']
    for path in (Path(__file__), Path(__file__).with_name('figure_style.py'),
                 FROZEN/'python/moonkvsim/aegiskv/experiment.py',
                 FROZEN/'benchmark/AegisKV/experiments/scripts/run_mooncake_aligned_paper.py'):
        data['input_bindings'][str(path.resolve().relative_to(ROOT))] = sha(path)
    return data


def canvas(left=.29, top=.82):
    fig, ax = plt.subplots(figsize=(3.45, 3.2))
    fig.subplots_adjust(left=left, right=.975, bottom=.20, top=top)
    return fig, ax


def statistic_legend(ax, horizontal=False, color=GRAY, paired=False):
    run = Line2D([], [], marker='o', color='none', markerfacecolor='white',
                 markeredgecolor=color, markersize=4)
    kwargs = {'xerr': [.2]} if horizontal else {'yerr': [.2]}
    mean = ax.errorbar([np.nan], [np.nan], fmt='D', color=color, ms=4,
                      capsize=3, lw=1.1, **kwargs)
    return [run, mean], ['Paired sample' if paired else 'Run', 'Mean (95% CI)']


def top_legend(fig, handles, labels):
    fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(.54, .995),
               ncol=2, frameon=False, handlelength=1.5, handletextpad=.4,
               columnspacing=.85, borderaxespad=0, labelspacing=.45)


def horizontal_observations(ax, e, y, color=BLUE):
    ax.scatter(e['samples'], y+np.linspace(-.21, .21, 5), s=19,
               marker='o', facecolor='white', edgecolor=color, linewidth=.9, zorder=3)
    ax.errorbar(e['mean'], y-.35,
                xerr=[[e['mean']-e['low']], [e['high']-e['mean']]],
                fmt='D', ms=4, capsize=3, color=color, lw=1.2, zorder=4)


def vertical_observations(ax, e, x, color=GRAY):
    ax.scatter(x+np.linspace(-.15, .15, 5), e['samples'], s=19, marker='o',
               facecolor='white', edgecolor=color, linewidth=.9, zorder=3)
    ax.errorbar(x+.32, e['mean'],
                yerr=[[e['mean']-e['low']], [e['high']-e['mean']]],
                fmt='D', ms=4, capsize=3, color=color, lw=1.2, zorder=4)


def render(data, output):
    fig, ax = canvas()
    for key, y in zip(TIMING, (2, 1, 0)):
        horizontal_observations(ax, data['full_vs_unprotected_percent'][key], y)
    top_legend(fig, *statistic_legend(ax, horizontal=True, color=BLUE, paired=True))
    ax.axvline(0, color=GRAY, ls='--', lw=.8)
    ax.set_yticks([2, 1, 0], ['Mean WCT', 'P95 WCT', 'Workload\nmakespan'])
    ax.set_xticks([-1.5, -.75, 0, .75], ['-1.5', '-0.75', '0', '0.75'])
    ax.set(xlim=(-1.85, 1.15), ylim=(-.7, 2.5), xlabel='Full vs. unprotected (%)')
    ax.grid(axis='x', color='#ECEFF1', lw=.7)
    save(fig, NAMES[0], directory=output)

    fig, ax = canvas(left=.22, top=.74)
    for x, arm in enumerate(('dram', 'full')):
        d = data['arms'][arm]
        dram, hbm = np.mean(d['store_dram_TiB']), np.mean(d['peer_hbm_TiB'])
        ax.bar(x, dram, width=.48, color='#F4DFC3', edgecolor=ORANGE, lw=.9, zorder=2)
        if hbm:
            ax.bar(x, hbm, bottom=dram, width=.48, color='#B6D7E8',
                   edgecolor=BLUE, hatch='///', lw=.9, zorder=2)
        vertical_observations(ax, d['total_TiB'], x)
    handles = [Patch(facecolor='#F4DFC3', edgecolor=ORANGE),
               Patch(facecolor='#B6D7E8', edgecolor=BLUE, hatch='///')]
    stats_h, stats_l = statistic_legend(ax)
    # Column-major legend gives tiers in row one and statistical keys in row two.
    top_legend(fig, [handles[0], stats_h[0], handles[1], stats_h[1]],
               ['DRAM', stats_l[0], 'Peer HBM', stats_l[1]])
    ax.set_xticks([0, 1], ['DRAM-only', 'Full'])
    ax.set_yticks([0, 2, 4, 6])
    ax.set(xlim=(-.4, 1.5), ylim=(0, 6.1), ylabel='Protection traffic (TiB)')
    ax.grid(axis='y', color='#ECEFF1', lw=.7)
    save(fig, NAMES[1], directory=output)

    fig, ax = canvas(left=.29)
    for key, y in zip(('start_wait_mean_s', 'start_wait_p95_s'), (1, 0)):
        horizontal_observations(ax, data['full_minus_dram_start_wait_s'][key], y)
    top_legend(fig, *statistic_legend(ax, horizontal=True, color=BLUE, paired=True))
    ax.axvline(0, color=GRAY, ls='--', lw=.8)
    ax.set_yticks([1, 0], ['Mean wait', 'P95 wait'])
    ax.set_xticks([-.3, 0, .3, .6, .9, 1.2], ['-0.3', '0', '0.3', '0.6', '0.9', '1.2'])
    ax.set(xlim=(-.39, 1.26), ylim=(-.7, 1.5), xlabel='Full minus DRAM-only (s)')
    ax.grid(axis='x', color='#ECEFF1', lw=.7)
    save(fig, NAMES[2], directory=output)

    fig, ax = canvas(left=.22)
    for x, arm in enumerate(('unprotected', 'dram', 'full')):
        vertical_observations(ax, data['peer_time_avg_GiB'][arm], x, color=BLUE)
    top_legend(fig, *statistic_legend(ax, color=BLUE))
    ax.set_xticks([0, 1, 2], ['None', 'DRAM-only', 'Full'])
    ax.set_yticks([0, 10, 20, 30])
    ax.set(xlim=(-.4, 2.55), ylim=(-1, 30), ylabel='Time-averaged Peer HBM (GiB)')
    ax.grid(axis='y', color='#ECEFF1', lw=.7)
    save(fig, NAMES[3], directory=output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    data = mechanism_data(inputs())
    data['schema'] = 'aegiskv.healthy_standalone_review.v1'
    data['status'] = 'standalone_review_candidates_and_legacy_diagnostics'
    render(data, args.output)
    data['output_files'] = {f'{name}.{ext}': sha(args.output/f'{name}.{ext}')
                            for name in NAMES for ext in ('png', 'svg', 'pdf')}
    with (args.output/'healthy-mechanism-observations.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data['mechanism_observations'][0]))
        writer.writeheader()
        writer.writerows(data['mechanism_observations'])
    data['output_files']['healthy-mechanism-observations.csv'] = sha(args.output/'healthy-mechanism-observations.csv')
    (args.output/'healthy-standalone-review.json').write_text(json.dumps(data, indent=2, sort_keys=True)+'\n')
    print(f'Wrote four independent figures and the 15-run mechanism audit to {args.output}')


if __name__ == '__main__':
    main()
