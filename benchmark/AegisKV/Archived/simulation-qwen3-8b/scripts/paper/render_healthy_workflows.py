#!/usr/bin/env python3
"""Plot workflow-level healthy outcomes for one matched admission order.

The default is the first numbered order (seed 0), not a benefit-based
selection. Other seeds remain available in the CSV and sensitivity table.
These are descriptive views; workflows do not become independent run repeats.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

from figure_style import BLUE, ORANGE, GRAY, ROOT, plt, save, sha
from render_healthy_review import CAMPAIGN, inputs


DEFAULT_OUT = ROOT / 'output/pdf/aegiskv-healthy-workflows-20260908'
FIGURES = ('healthy-workflow-wct-cdf', 'healthy-workflow-paired-wct')


def collect(seed):
    data = inputs()
    rows, by_seed = [], {}
    for order in range(5):
        summaries = {}
        for arm in ('unprotected', 'dram', 'full'):
            path = CAMPAIGN / f'runs/base/seed{order}/F0-{arm}.json'
            assert sha(path) == data['input_bindings'][str(path.relative_to(ROOT))]
            summaries[arm] = json.loads(path.read_text())['summary']
        workflow_ids = sorted(summaries['full']['wct_ns'])
        assert len(workflow_ids) == 160
        assert all(set(s['wct_ns']) == set(workflow_ids) for s in summaries.values())
        assert len({s['workflow_admission']['realized_workflow_order_sha256']
                    for s in summaries.values()}) == 1
        assert summaries['dram']['wct_ns'] == summaries['unprotected']['wct_ns']
        differences_ns = []
        for workflow in workflow_ids:
            values = {arm: s['wct_ns'][workflow] for arm, s in summaries.items()}
            delta = values['full']-values['dram']
            differences_ns.append(delta)
            rows.append(dict(seed=order, workflow_id=workflow,
                             unprotected_wct_s=values['unprotected']/1e9,
                             dram_wct_s=values['dram']/1e9,
                             full_wct_s=values['full']/1e9,
                             full_minus_dram_s=delta/1e9,
                             full_vs_dram_percent=100*delta/values['dram']))
        delta = np.asarray(differences_ns)
        by_seed[str(order)] = dict(
            workflows=160, faster=int(np.sum(delta < 0)),
            unchanged=int(np.sum(delta == 0)), slower=int(np.sum(delta > 0)),
            mean_delta_s=float(delta.mean()/1e9),
            min_delta_s=float(delta.min()/1e9), max_delta_s=float(delta.max()/1e9))
        assert np.isclose(delta.mean()/1e9, data['arms']['full']['endpoints']['mean_wct_s'][order]
                          - data['arms']['dram']['endpoints']['mean_wct_s'][order],
                          rtol=0, atol=1e-12)
    data.update(schema='aegiskv.healthy_workflow_view.v1',
                status='descriptive_workflow_figures_from_legacy_simulation',
                displayed_seed=seed,
                display_selection='Explicit CLI seed; default is lowest numbered seed 0, without selecting on benefit',
                comparison_unit='Same workflow ID in matched strategy executions with the same admission order',
                point_unit='One workflow, not one run',
                inference='No workflow-level confidence interval; these workflows share scheduler and memory resources',
                change_count_definition='Strict sign of the integer nanosecond difference; includes arbitrarily small changes',
                seed_sensitivity=by_seed, workflow_observations=rows)
    for path in (Path(__file__), Path(__file__).with_name('figure_style.py')):
        data['input_bindings'][str(path.resolve().relative_to(ROOT))] = sha(path)
    return data


def canvas():
    fig, ax = plt.subplots(figsize=(3.45, 3.2))
    fig.subplots_adjust(left=.21, right=.94, bottom=.20, top=.80)
    return fig, ax


def render(data, output):
    rows = [r for r in data['workflow_observations'] if r['seed'] == data['displayed_seed']]
    assert len(rows) == 160
    control = np.asarray([r['dram_wct_s'] for r in rows])
    full = np.asarray([r['full_wct_s'] for r in rows])
    limit = float(np.ceil(max(control.max(), full.max())/20)*20)
    ticks = np.linspace(0, limit, 4)

    fig, ax = canvas()
    cdf = np.arange(1, len(rows)+1)/len(rows)
    for values, label, color, style in (
        (control, 'Unprotected / DRAM-only', ORANGE, '--'),
        (full, 'Full', BLUE, '-')):
        ordered = np.sort(values)
        ax.step(np.r_[0, ordered, limit], np.r_[0, cdf, 1], where='post',
                color=color, linestyle=style, lw=1.5, label=label)
    fig.legend(loc='upper center', bbox_to_anchor=(.55, .995), frameon=False,
               handlelength=1.8, handletextpad=.5, labelspacing=.35)
    ax.set(xlim=(0, limit), ylim=(0, 1.02),
           xlabel='Workflow completion time (s)', ylabel='Fraction of workflows')
    ax.set_xticks(ticks)
    ax.set_yticks([0, .25, .5, .75, 1], ['0', '0.25', '0.5', '0.75', '1'])
    ax.grid(color='#ECEFF1', lw=.7)
    save(fig, FIGURES[0], directory=output)

    fig, ax = canvas()
    scatter = ax.scatter(control, full, marker='o', s=18, facecolor='none',
                         edgecolor=BLUE, linewidth=.8, label='Workflow', zorder=3)
    equality, = ax.plot([0, limit], [0, limit], '--', lw=.9, color=GRAY,
                        label='Equal WCT', zorder=1)
    fig.legend([scatter, equality], ['Workflow', 'Equal WCT'], loc='upper center',
               bbox_to_anchor=(.55, .995), ncol=2, frameon=False,
               handlelength=1.6, handletextpad=.4, columnspacing=.8)
    ax.set(xlim=(0, limit), ylim=(0, limit),
           xlabel='DRAM-only WCT (s)', ylabel='Full WCT (s)')
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)
    ax.grid(color='#ECEFF1', lw=.7)
    save(fig, FIGURES[1], directory=output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=0, choices=range(5))
    parser.add_argument('--output', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    data = collect(args.seed)
    output = args.output/f'seed{args.seed}'
    render(data, output)
    csv_path = output/'healthy-workflow-observations.csv'
    with csv_path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data['workflow_observations'][0]))
        writer.writeheader()
        writer.writerows(data['workflow_observations'])
    data['output_files'] = {f'{name}.{ext}': sha(output/f'{name}.{ext}')
                            for name in FIGURES for ext in ('png', 'svg', 'pdf')}
    data['output_files'][csv_path.name] = sha(csv_path)
    (output/'healthy-workflow-review.json').write_text(json.dumps(data, indent=2, sort_keys=True)+'\n')
    print(f'Wrote 160-workflow views for seed {args.seed} and all 800 matched workflow observations to {output}')


if __name__ == '__main__':
    main()
