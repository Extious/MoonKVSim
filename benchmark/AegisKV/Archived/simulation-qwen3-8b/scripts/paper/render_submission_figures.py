#!/usr/bin/env python3
"""Redraw all data figures without changing any accepted experiment outcome.

The portable JSON input freezes descriptive ECDFs extracted from accepted
run summaries and exact-token workload counts. Statistics remain bound to
the independently audited 170-run campaign. No simulation is launched here.
"""
import argparse, csv, json
from collections import Counter
from pathlib import Path
import numpy as np
from matplotlib.ticker import FixedLocator, NullLocator
from figure_style import *
from paper_paths import DATA, TOOLS, DOCS, BUILD, DELIVERY, TEMPLATE, ARTIFACTS

from paper_paths import ROOT
CAMPAIGN = ROOT / 'output/paper-simulation-8b/20260906-alignment/campaign-v2'
INPUT = DATA/'publication-figure-inputs.json'

def freeze_inputs():
    acceptance = CAMPAIGN / 'ACCEPTANCE.json'
    accepted = json.loads(acceptance.read_text())
    assert accepted['status'] == 'PASS' and accepted['measured_runs'] == 170
    records = {tuple(x['job']): x for x in accepted['accepted_runs']}
    bindings = {}; cdfs = {}
    for arm in ('unprotected', 'dram', 'full'):
        cdfs[arm] = []
        for seed in range(5):
            p = CAMPAIGN / 'runs/base' / f'seed{seed}' / f'F1-{arm}.json'
            d = json.loads(p.read_text())
            assert d['raw_evidence']['sha256'] == records['base', seed, 'F1', arm]['raw_sha256']
            assert d['identity']['job'] == ['base', seed, 'F1', arm]
            cdfs[arm].append(sorted(t/1e9 for t in d['summary']['wct_ns'].values()))
            assert len(cdfs[arm][-1]) == 160
            bindings[str(p.relative_to(ROOT))] = sha(p)
    work = ROOT / 'benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl'
    rows = [json.loads(l) for l in work.open() if l.strip()]
    bindings[str(work.relative_to(ROOT))] = sha(work)
    data = dict(schema='moonkvsim.publication_figure_inputs.v1',
                acceptance_sha256=sha(acceptance), input_bindings=bindings,
                failure_wct_s=cdfs,
                prompt_tokens=[r['prompt_tokens'] for r in rows],
                context_tokens=[r['prompt_tokens']+r['output_tokens'] for r in rows],
                workflow_call_counts=list(Counter(r['workflow_id'] for r in rows).values()))
    INPUT.write_text(json.dumps(data, indent=2, sort_keys=True)+'\n')

def workload(data):
    fig, ax = panels(3, 2.75, left=.085, bottom=.33, gap=.55)
    for a, values, title, label, color in (
        (ax[0], np.array(data['prompt_tokens'])/1024, '(a) Prompt length', 'Prompt tokens (Ki)', BLUE),
        (ax[1], data['workflow_call_counts'], '(b) Workflow size', 'Calls per workflow', GREEN)):
        x = np.sort(values); a.step(x, np.arange(1, len(x)+1)/len(x), where='post', lw=1.6, color=color)
        a.set(title=title, xlabel=label, ylabel='Empirical CDF', ylim=(0, 1.03))
        a.set_yticks([0, .5, 1]); a.grid(axis='y', alpha=.18)
        a.text(.98, .12, f'n = {len(x):,}', transform=a.transAxes, ha='right', color=color)
    ax[0].set_xticks([0, 40, 80]); ax[1].set_xticks([5, 10, 15])
    counts = np.histogram(data['context_tokens'], bins=np.array([0, 8, 16, 32, 64, 96, 128])*1024)[0]
    ax[2].bar(range(6), counts, color=GREEN, width=.72, edgecolor='white')
    for x, count in enumerate(counts): ax[2].text(x, count+(35 if x % 2 == 0 else 10), str(count), ha='center', rotation=0)
    ax[2].set(title='(c) Context bins', ylabel='Calls', xlabel='Context upper bound\n(Ki tokens)', ylim=(0, 580))
    ax[2].set_xticks(range(6), ['8', '16', '32', '64', '96', '128'], rotation=45, ha='right')
    save(fig, 'aligned-workload')

def cost():
    fig, ax = panels(2, 3.1, left=.085, bottom=.22, top=.79, gap=.42)
    x = np.linspace(0, 96, 193); one = x*1024*147456/2**30
    budget = (40*2**30-16381470720-2*2**30)/2**30
    ax[0].plot(x, one, color=BLUE, lw=1.7, label='One copy')
    ax[0].plot(x, 2*one, color=ORANGE, lw=1.7, ls='--', label='Two copies')
    ax[0].axhline(budget, color=RED, ls=':', lw=1.3, label='Post-reserve HBM')
    ax[0].set(title='(a) Analytical capacity cost', xlabel='Prompt tokens (Ki)', ylabel='KV footprint (GiB)', xlim=(0, 96), ylim=(0, 29))
    ax[0].set_xticks([0, 32, 64, 96]); ax[0].grid(alpha=.15)
    ax[0].text(4, 24, 'Post-reserve HBM', color=RED)
    ax[0].text(24, 18.5, 'Two copies', color=ORANGE)
    ax[0].text(51, 4.8, 'One copy', color=BLUE)
    profile = json.loads((DATA/'physical-pilot/pilot-cost-profile.json').read_text())
    labels = ['HBM write', 'DRAM write', 'HBM load', 'DRAM load']
    keys = ['hbm_protection', 'dram_protection', 'hbm_recovery', 'dram_recovery']
    for i, (key, label) in enumerate(zip(keys, labels)):
        samples = np.asarray(profile['physical_samples'][key])
        rates = samples[:, 0]/samples[:, 1]/1e6
        aggregate = samples[:, 0].sum()/samples[:, 1].sum()/1e6
        assert abs(aggregate-profile['values'][key+'_bandwidth_bytes_per_ms']/1e6)<1e-10
        color = BLUE if key.startswith('hbm') else ORANGE
        ax[1].hlines(i, 0, aggregate, color=color, lw=1)
        ax[1].scatter(rates, i+np.linspace(-.11, .11, len(rates)) if len(rates)>1 else [i],
                      facecolor='white', edgecolor=color, s=28, zorder=3)
        ax[1].scatter([aggregate], [i], color=color, marker='D', s=23, zorder=4)
        ax[1].text(3.1, i, f'n={len(rates)}', va='center', ha='right')
    ax[1].set_yticks(range(4), labels); ax[1].invert_yaxis()
    ax[1].set(title='(b) Physical pilot samples', xlabel='Effective rate (GB/s)', xlim=(0, 3.25), ylim=(3.55, -.55))
    ax[1].set_xticks([0, 1, 2, 3]); ax[1].grid(axis='x', alpha=.15)
    fig.text(.99, .97, 'RTX4090: host-staged paths; diamonds = aggregate rates', ha='right', va='top', color=GRAY)
    save(fig, 'aligned-motivation-cost')

def healthy(s):
    fig, ax = panels(2, 2.85, left=.105, bottom=.25, top=.78, gap=.44)
    seed_note(fig)
    for i, arm in enumerate(('unprotected', 'dram')):
        observations(ax[0], s['healthy'][arm]['samples'], i, COLORS[arm], summary=s['healthy'][arm])
    baseline(ax[0]); ax[0].set_xticks([0, 1], ['vs none', 'vs DRAM'])
    ax[0].set(title='(a) Healthy mean WCT', ylabel='Full minus control (s)', xlim=(-.5, 1.5))
    for i, arm in enumerate(('unprotected', 'dram', 'full')):
        observations(ax[1], np.asarray(s['endpoints'][arm]['F0']['protection_GiB'])/1024, i, COLORS[arm])
    ax[1].set_xticks(range(3), ['None', 'DRAM', 'Full'])
    ax[1].set(title='(b) Healthy copy traffic', ylabel='Transferred TiB / workload', ylim=(-.15, 6), xlim=(-.5, 2.5))
    ax[1].grid(axis='y', alpha=.15)
    save(fig, 'aligned-healthy')

def failure(s, data):
    fig, ax = panels(3, 2.9, left=.085, bottom=.26, top=.77, gap=.65)
    seed_note(fig)
    for arm, ls in zip(('unprotected', 'dram', 'full'), (':', '--', '-')):
        values = np.sort(np.asarray(data['failure_wct_s'][arm]).ravel())
        ax[0].step(values, np.arange(1, len(values)+1)/len(values), where='post', color=COLORS[arm], ls=ls, lw=1.6,
                   label={'unprotected':'None', 'dram':'DRAM', 'full':'Full'}[arm])
    ax[0].set(title='(a) WCT distribution', xlabel='WCT (s)', ylabel='Empirical CDF', ylim=(0, 1.02))
    ax[0].set_yticks([0, .5, 1]); ax[0].set_xticks([0, 60, 120])
    ax[0].legend(frameon=False, loc='lower right', handlelength=1.4, labelspacing=.15)
    for a, cohort, title in zip(ax[1:], ('all', 'focus'), ('(b) All workflows', '(c) Focus workflow')):
        for i, control in enumerate(('unprotected', 'dram')):
            d = s['primary'][control][cohort]
            observations(a, d['samples'], i, COLORS[control], summary=d)
        baseline(a); a.set_xticks([0, 1], ['None', 'DRAM'])
        a.set(title=title, xlabel='Control arm', ylabel='Penalty: full - control (s)', xlim=(-.5, 1.5))
    save(fig, 'aligned-failure')

def recovery(s):
    fig, ax = panels(3, 3.0, left=.085, bottom=.25, top=.74, gap=.64)
    rec = {(r['seed'], r['arm']): r for r in s['focus_recovery']}
    for j, arm in enumerate(('dram', 'full')):
        rows = [rec[i, arm] for i in range(5)]
        values = np.asarray([r['tokens'] for r in rows], dtype=float)
        values = values/values.sum(axis=1)[:, None]*100
        pos = np.arange(5)+(j-.5)*.38; bottom = np.zeros(5)
        for k, (label, color, hatch) in enumerate(zip(('HBM copy', 'DRAM load', 'Recompute'), (BLUE, ORANGE, RED), ('..', '//', ''))):
            ax[0].bar(pos, values[:, k], bottom=bottom, width=.35, color=color,
                      edgecolor='white', lw=.35, hatch=hatch, label=label if j else None)
            bottom += values[:, k]
        ax[1].plot(range(5), [r['materialization_s'] for r in rows],
                   color=COLORS[arm], marker='s' if arm=='dram' else 'o',
                   ls='none', lw=1.2, label='DRAM' if arm=='dram' else 'Full')
    for seed in range(5):
        ax[1].vlines(seed, rec[seed, 'full']['materialization_s'], rec[seed, 'dram']['materialization_s'], color=GRAY, lw=.9, zorder=0)
    ax[0].set(title='(a) Token sources', ylabel='Focus prompt tokens (%)', ylim=(0, 100), xlabel='Seed (DRAM / full)')
    ax[1].set(title='(b) Prefix ready', ylabel='Fault to prefix ready (s)', ylim=(0, 8.2), xlabel='Admission seed')
    for a in ax[:2]: a.set_xticks(range(5))
    for seed, penalty in enumerate(s['primary']['dram']['focus']['samples']):
        saving = rec[seed, 'dram']['materialization_s']-rec[seed, 'full']['materialization_s']
        ax[2].scatter(saving, penalty, color=BLUE, marker=MARKERS[seed], s=30, zorder=3)
        if seed in (0, 4):
            ax[2].annotate(str(seed), (saving, penalty), xytext=(5, 5), textcoords='offset points')
    ax[2].annotate('1, 2, 3', (0, 0), xytext=(9, -27), textcoords='offset points', arrowprops={'arrowstyle':'-', 'color':GRAY, 'lw':.7})
    baseline(ax[2]); baseline(ax[2], False)
    ax[2].set(title='(c) WCT penalty', ylabel='Full - DRAM penalty (s)', xlabel='Prefix-ready saving (s)', xlim=(-.3, 2.5), ylim=(-4, 10))
    fig.legend(*ax[0].get_legend_handles_labels(), loc='upper left', bbox_to_anchor=(.035, .995), ncol=3,
               frameon=False, handlelength=1, columnspacing=.8)
    ax[1].legend(frameon=False, loc='upper left', bbox_to_anchor=(0, 1.36), ncol=2, handlelength=1, columnspacing=.7)
    save(fig, 'aligned-recovery')

def ablations(s):
    fig, ax = panels(3, 2.95, left=.105, bottom=.27, top=.78, gap=.7)
    seed_note(fig)
    arms = ('no_slack', 'no_aimd', 'lru_eviction')
    for a, cohort, title in zip(ax[:2], ('all', 'focus'), ('(a) All workflows', '(b) Focus workflow')):
        for i, arm in enumerate(arms):
            d = s['ablations'][arm][cohort]
            observations(a, d['samples'], i, COLORS[arm], summary=d)
        baseline(a); a.set_xticks(range(3), ['Slack', 'AIMD', 'LRU'])
        a.set(title=title, xlabel='Removed / replaced', ylabel='Ablation - full penalty (s)', xlim=(-.5, 2.5))
    full = np.asarray(s['endpoints']['full']['F0']['protection_GiB'])
    for i, arm in enumerate(arms):
        delta = (np.asarray(s['endpoints'][arm]['F0']['protection_GiB'])-full)/1024
        observations(ax[2], delta, i, COLORS[arm])
    baseline(ax[2]); ax[2].set_xticks(range(3), ['Slack', 'AIMD', 'LRU'])
    ax[2].set(title='(c) Copy traffic', xlabel='Removed / replaced', ylabel='Ablation - full traffic (TiB)', xlim=(-.5, 2.5))
    save(fig, 'aligned-ablations')

def sensitivity(s):
    fig, ax = panels(2, 3.5, left=.20, bottom=.20, top=.81, gap=.45)
    seed_note(fig)
    names = ('base', 'concurrency8', 'concurrency32', 'serial500', 'serial1000', 'bandwidth5', 'failures2')
    labels = ('Base: C=16', 'C=8', 'C=32', 'Serial mix: 0.5', 'Serial mix: 1', 'Path: 5 GB/s', 'Two faults')
    for a, cohort, title in zip(ax, ('all', 'focus'), ('(a) All-workflow mean', '(b) Focus workflow')):
        for i, name in enumerate(names):
            if i%2==0: a.axhspan(i-.45, i+.45, color='#F3F5F7', zorder=0)
            d = s['sensitivity'][name][cohort]
            observations(a, d['samples'], i, BLUE, horizontal=True, summary=d)
        baseline(a, False); a.set_yticks(range(7), labels if a is ax[0] else ['']*7)
        a.set(title=title, xlabel='Full - DRAM penalty (s)', ylim=(6.6, -.6))
    save(fig, 'aligned-sensitivity')

def motivation_panels():
    dat = DATA/'motivation-real-cc'
    inputs = json.loads((dat/'IMPORT.json').read_text())
    for f in inputs['files']: assert sha(dat/f['copy']) == f['sha256']
    gaps = list(csv.DictReader((dat/'real-cc-workflow-parallel-gap.csv').open()))
    rows = sorted(csv.DictReader((dat/'real-cc-example-failure-position.csv').open()), key=lambda r:int(r['branch_index']))
    x = np.sort([float(r['max_duration_gap_s']) for r in gaps]); assert len(x)==124
    assert len({r['workflow_id'] for r in gaps})==124
    assert {r['selection_rule'] for r in gaps}=={'max_within_fanout_duration_gap_per_workflow'}
    assert {r['parallel_definition'] for r in gaps}=={'max_start_lt_min_end'}
    assert np.allclose(np.quantile(x, [.5, .9]), [140.611, 1570.290], atol=.00051)
    parts = OUT/'motivation-panels'; parts.mkdir(exist_ok=True)
    fig, a = plt.subplots(figsize=(3.4, 2.3)); fig.subplots_adjust(left=.18, right=.985, bottom=.26, top=.79)
    a.step(x, np.arange(1, len(x)+1)/len(x), where='post', color=GREEN, lw=1.7)
    for value, quant, ls in zip(np.quantile(x, [.5, .9]), (.5, .9), ('--', ':')):
        a.vlines(value, 0, quant, colors=GRAY, linestyles=ls, lw=1)
        a.scatter([value], [quant], facecolor='white', edgecolor=GREEN, s=28, zorder=3)
    a.text(.02, .96, '124 workflows', transform=a.transAxes, va='top')
    a.text(.98, .10, 'Median: 140.6 s\nP90: 1,570.3 s', transform=a.transAxes, va='bottom', ha='right', bbox={'facecolor':'white','edgecolor':'none','alpha':.95,'pad':1})
    a.set(xscale='log', xlim=(.3, 20000), ylim=(0, 1.03), xlabel='Max. parallel duration gap (s)', ylabel='Workflow ECDF', title='(a) Observed branch imbalance')
    a.xaxis.set_major_locator(FixedLocator([1, 10, 100, 1000, 10000])); a.set_xticklabels(['1', '10', '100', '1k', '10k']);a.xaxis.set_minor_locator(NullLocator())
    a.set_yticks([0, .5, 1]); a.grid(alpha=.18)
    save(fig, 'observed-gap', parts)
    fig, a = plt.subplots(figsize=(3.4, 2.3)); fig.subplots_adjust(left=.13, right=.985, bottom=.26, top=.79)
    delay = np.array([float(r['recompute_s']) for r in rows]); slack = np.array([float(r['slack_s']) for r in rows]); harm = np.array([float(r['delta_wct_s']) for r in rows])
    assert np.allclose(np.maximum(delay-slack, 0), harm, atol=1e-6)
    absorbed = delay-harm
    a.barh(range(5), absorbed, height=.58, color='#D5EAE1', edgecolor=GREEN, hatch='//', linewidth=.7, label='Absorbed')
    a.barh(range(5), harm, left=absorbed, height=.58, color=RED, edgecolor=RED, linewidth=.7, label='Exposed')
    for i, (d, h) in enumerate(zip(delay, harm)): a.text(d+.8, i, f'{h:.1f}', va='center')
    a.set_yticks(range(5), ['A1', 'A2', 'A3', 'A4', 'A5']);a.invert_yaxis()
    a.set(xlim=(0, 58), xlabel='Modeled recomputation (s)', title='(c) Branch-dependent harm')
    a.set_xticks([0, 20, 40]); a.grid(axis='x', alpha=.15)
    fig.legend(*a.get_legend_handles_labels(), loc='upper center', bbox_to_anchor=(.55, 1.015), frameon=False, ncol=2, handlelength=1, columnspacing=.8)
    save(fig, 'modeled-harm', parts)
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--freeze-inputs', action='store_true');a=p.parse_args()
    if a.freeze_inputs: freeze_inputs()
    data=json.loads(INPUT.read_text());s=json.loads((DATA/'aligned-statistics.json').read_text())
    assert s['status']=='PASS' and data['acceptance_sha256']==s['acceptance_sha256']
    workload(data);cost();healthy(s);failure(s,data);recovery(s);ablations(s);sensitivity(s);motivation_panels()
    print('Seven quantitative figures and two Motivation panels regenerated from bound inputs.')

if __name__=='__main__':main()
