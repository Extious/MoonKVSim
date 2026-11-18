#!/usr/bin/env python3
"""Render audited existing evidence; never execute a serving experiment.

Fixed native single-column canvases. Original observations remain immutable.
The old placement/queue/rental models are explicitly historical diagnostics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT.parents[1]
DEFAULT_OUT = ROOT / 'exports/evaluation-rework-20260922T170350Z'
WIDTH = 3.33465
FONT = 10.3
BLUE, ORANGE, GREEN, GRAY = '#25678E', '#B7753E', '#427E72', '#646B73'
COLORS = [BLUE, ORANGE, GREEN, GRAY]
MODELS = ['NOSA-3B', 'MiniCPM4-8B', 'SeerAttention-Qwen3-8B']


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_csv(path):
    with Path(path).open() as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with Path(path).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def setup():
    path = Path(subprocess.check_output(['kpsewhich', 'LinLibertine_R.otf'], text=True).strip())
    if not path.is_file():
        raise RuntimeError('The manuscript Libertine font is required.')
    font_manager.fontManager.addfont(str(path))
    family = font_manager.FontProperties(fname=path).get_name()
    plt.rcParams.update({
        'font.family': family, 'font.size': FONT, 'axes.labelsize': FONT,
        'xtick.labelsize': FONT, 'ytick.labelsize': FONT, 'legend.fontsize': FONT,
        'pdf.fonttype': 42, 'ps.fonttype': 42, 'svg.fonttype': 'none',
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.linewidth': .65, 'axes.labelpad': 3,
        'xtick.major.size': 2.6, 'ytick.major.size': 2.6,
        'xtick.major.pad': 2.5, 'ytick.major.pad': 2.5,
        'axes.axisbelow': True, 'lines.linewidth': 1.3,
        'text.color': '#22272B', 'axes.labelcolor': '#22272B',
        'axes.edgecolor': '#55616A', 'hatch.linewidth': .4,
        'savefig.dpi': 220,
    })
    return family


def canvas(badge, height=2.65, left=.18, top=.72, bottom=.19):
    fig, ax = plt.subplots(figsize=(WIDTH, height))
    fig.subplots_adjust(left=left, right=.975, bottom=bottom, top=top)
    fig.text(.5, .982, badge, ha='center', va='top', color='#515A61')
    ax.grid(axis='y', color='#E1E6EA', linewidth=.45)
    return fig, ax


def legend(fig, ax, cols=1, y=.912, **kwargs):
    return fig.legend(*ax.get_legend_handles_labels(), loc='upper center',
                      bbox_to_anchor=(.52, y), ncol=cols, frameon=False,
                      labelspacing=.18, columnspacing=.85, handlelength=1.7,
                      handletextpad=.4, borderaxespad=0, **kwargs)


def plain_log(ax, axis, ticks):
    target = ax.xaxis if axis == 'x' else ax.yaxis
    target.set_major_locator(FixedLocator(ticks))
    target.set_major_formatter(FuncFormatter(lambda v, _: f'{v/1000:g}k' if v >= 1000 else f'{v:g}'))
    target.set_minor_locator(NullLocator())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--verify-native-sources', action='store_true',
                        help='Verify all 400 upstream native trace hashes once and save the result.')
    args = parser.parse_args()
    out = args.out
    figures, tables = out / 'figures', out / 'plot-data'
    figures.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)
    family = setup()
    manifest = {'evidence': 'Reanalysis of existing evidence; zero new physical runs',
                'renderer': str(Path(__file__).relative_to(ROOT)),
                'renderer_sha256': sha(__file__), 'font_family': family,
                'native_width_in': WIDTH, 'font_pt': FONT, 'new_physical_runs': 0,
                'figures': {}, 'sources': {}}

    def source(path):
        path = Path(path)
        key = str(path.relative_to(ROOT))
        manifest['sources'][key] = sha(path)
        return key

    def finish(name, fig, rows, **metadata):
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        bounds = fig.bbox
        outside = []
        unpainted_ticks = set()
        for axis in fig.axes:
            for ticks, limits in [(axis.xaxis.get_major_ticks(), axis.get_xlim()),
                                  (axis.yaxis.get_major_ticks(), axis.get_ylim())]:
                lo, hi = sorted(limits)
                for tick in ticks:
                    if not lo <= tick.get_loc() <= hi:
                        unpainted_ticks.update([tick.label1, tick.label2])
        for item in fig.findobj(matplotlib.text.Text):
            if not item.get_visible() or not item.get_text() or item in unpainted_ticks:
                continue
            box = item.get_window_extent(renderer)
            if box.x0 < -.5 or box.y0 < -.5 or box.x1 > bounds.x1 + .5 or box.y1 > bounds.y1 + .5:
                outside.append(item.get_text())
        if outside:
            raise ValueError(f'{name}: text outside fixed canvas: {outside}')
        write_csv(tables / f'{name}.csv', rows)
        artifacts = {}
        for extension in ['pdf', 'svg', 'png']:
            p = figures / f'{name}.{extension}'
            fig.savefig(p, facecolor='white')
            artifacts[extension] = {'path': str(p.relative_to(out)), 'sha256': sha(p)}
        manifest['figures'][name] = dict(metadata, width_in=WIDTH,
                                       height_in=float(fig.get_size_inches()[1]),
                                       table_sha256=sha(tables / f'{name}.csv'), artifacts=artifacts)
        plt.close(fig)

    # Physical same-allocation restoration paths; min/max is timing spread only.
    physical = ROOT / 'experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208'
    pdoc = json.loads((physical / 'measured.json').read_text())
    assert pdoc['evidence'] == 'physical_worker_microbenchmark'
    inputs = [source(physical / 'measured.json'), source(physical / 'measured.csv')]
    for name, digest in pdoc['source_sha256'].items():
        p = physical / name
        assert sha(p) == digest, name
        inputs.append(source(p))
    rows = read_csv(physical / 'measured.csv')
    assert len(rows) == 16 and all(r['status'] == 'measured' for r in rows)
    fig, ax = canvas('Physical microbenchmark', height=2.8, left=.18, top=.72, bottom=.18)
    plotted = []
    for method, label, color, marker, style in [
        ('FullPrefill', 'Full prefill', GRAY, 'D', '--'),
        ('SharedFS_no_overlap', 'Shared FS', ORANGE, '^', '-.'),
        ('DRAM_no_overlap', 'DRAM', GREEN, 's', '--'), ('HBM', 'Resident HBM', BLUE, 'o', '-')]:
        values = sorted([r for r in rows if r['path'] == method], key=lambda r: int(r['context_tokens']))
        assert len(values) == 4, (method, values)
        x = [int(r['context_tokens']) for r in values]
        y = [float(r['latency_ms']) / 1000 for r in values]
        ax.plot(x, y, color=color, marker=marker, linestyle=style, markersize=4, label=label)
        for r, xx, yy in zip(values, x, y):
            n = int(r['timing_repeats_per_input'])
            lo, hi = float(r['trial_min_ms'])/1000, float(r['trial_max_ms'])/1000
            if n > 1:
                ax.errorbar(xx, yy, yerr=[[yy-lo], [hi-yy]], fmt='none', ecolor=color, capsize=2, lw=.9)
            plotted.append(dict(path=method, context_tokens=xx, latency_s=yy,
                                min_s=lo if n > 1 else '', max_s=hi if n > 1 else '',
                                timing_repeats=n, independent_input_streams=1))
    ax.set(xscale='log', yscale='log', xlabel='Context (tokens)',
           ylabel='KV reconstruction time (s)', xlim=(6500, 1300000), ylim=(.06, 950))
    ax.set_xticks([8192, 65536, 262144, 1010000], ['8K', '64K', '256K', '1.01M'])
    ax.xaxis.set_minor_locator(NullLocator())
    plain_log(ax, 'y', [.1, 1, 10, 100])
    legend(fig, ax, 2)
    finish('eval-recovery-paths', fig, plotted, evidence='physical_worker_microbenchmark',
           sources=inputs, n={'allocation': 1, 'input_streams': 1, 'timed_trials': 32},
           statistics='HBM/DRAM median of three timings and min-max; Shared FS/full prefill one timing each; no confidence intervals',
           scope='Qwen2.5-7B-Instruct-1M, 2xA100 PCIe40GB, TP2/BF16/batch1, one-token EXTEND after M historical tokens',
           limitations=['Single synthetic text stream, not independent workloads', 'Serial DRAM and shared-FS restoration; no transfer/compute overlap',
                        'DPC shared filesystem; server cache uncontrolled, not a cold-SSD measurement',
                        'Resident HBM is not a finite Peer policy; no end-to-end fault campaign'],
           caption='Measured reconstruction paths on one fixed input stream. Points use three timing repeats for resident HBM and serial DRAM (whiskers: min-max), and one timing for full prefill and DPC shared filesystem. All paths end at the same KV-ready endpoint; this is a worker microbenchmark, not a Peer-policy comparison.')

    # Existing out-of-fold predictions: every eligible agent and every error retained.
    pred = ROOT / 'experiments/data/agent-gbdt-steps/primary-landmark.csv'
    protocol = ROOT / 'experiments/data/agent-gbdt-steps/protocol.json'
    old_evidence = ROOT / 'exports/design-evidence-review-20260921/data/EVIDENCE.json'
    rs = read_csv(pred)
    groups = defaultdict(set)
    for r in rs:
        groups[r['workflow_id']].add(r['fold'])
    assert len(rs) == 1443 and len(groups) == 170 and all(len(v) == 1 for v in groups.values())
    fig, ax = canvas('Held-out trace diagnostic', height=2.7, top=.66, bottom=.19)
    plotted, statistics = [], {}
    for method, label, color, style in [('median', 'Training-fold median', GRAY, ':'),
            ('gbdt_basic', 'GBDT: basic', BLUE, '-'), ('gbdt_history', 'GBDT: history', ORANGE, '--')]:
        values = sorted((abs(float(r[method+'_s'])-float(r['actual_remaining_s'])), r) for r in rs)
        errors = np.array([v[0] for v in values])
        assert np.all(errors > 0)
        ax.step(errors, np.arange(1, len(errors)+1)/len(errors), where='post', label=label, color=color, linestyle=style)
        statistics[method] = dict(mae_s=float(errors.mean()), median_ae_s=float(np.median(errors)),
                                  p95_ae_s=float(np.quantile(errors, .95)), max_ae_s=float(errors.max()))
        for i, (error, r) in enumerate(values):
            plotted.append(dict(method=method, workflow_id=r['workflow_id'], agent_id=r['agent_id'], fold=r['fold'],
                                absolute_error_s=error, cdf=(i+1)/len(values)))
    ax.set(xscale='log', xlabel='Absolute remaining-time error (s)', ylabel='Agent fraction',
           xlim=(min(r['absolute_error_s'] for r in plotted)*.75, 200000), ylim=(0, 1.025))
    fig.subplots_adjust(right=.95)
    plain_log(ax, 'x', [.1, 1, 10, 100, 1000, 10000, 100000])
    ax.set_yticks([0, .5, 1], ['0', '0.5', '1'])
    legend(fig, ax, 1)
    prior = json.loads(old_evidence.read_text())
    finish('eval-tracker-errors', fig, plotted, evidence='held-out recorded-trace prediction',
           sources=[source(pred), source(protocol), source(old_evidence)],
           n={'agents': 1443, 'workflows': 170, 'workflow_disjoint_folds': 5},
           statistics=statistics, paired_mae_difference_s_ci95=prior['tracker']['paired_mae_difference_s_ci95'],
           limitations=['Whole-Agent remaining seconds, not residual-DAG segment or Slack accuracy',
                        'Completed Subagents only; recorded proxy lengths and mixed queue/tool/service delays',
                        'Workflow-disjoint validation, not chronological generalization; fixed fitted predictors'],
           caption='Complete held-out absolute-error distributions at the second request: 1,443 completed Subagents from 170 workflows, split into five workflow-disjoint folds. The target is whole-Agent remaining time; all long-tail errors remain visible. This does not validate residual-segment Slack.')

    # Native selector captures, historical occurrence-frequency baseline, not current p(x).
    native = ROOT / 'experiments/data/design-insights/retry-kv-documents.csv'
    native_meta = ROOT / 'experiments/data/design-insights/retry-kv-summary.json'
    ns = json.loads(native_meta.read_text())
    audit_path = out / 'native-source-audit.json'
    if args.verify_native_sources:
        failures = []
        for name, digest in ns['source_sha256'].items():
            p = REPO / name
            if not p.is_file() or sha(p) != digest:
                failures.append(name)
        audit = {'manifest_sha256': sha(native_meta), 'source_count': len(ns['source_sha256']),
                 'hash_mismatches_or_missing': failures, 'all_verified': not failures}
        audit_path.write_text(json.dumps(audit, indent=2)+'\n')
        assert not failures, failures
    else:
        audit = json.loads(audit_path.read_text())
        assert audit['manifest_sha256'] == sha(native_meta) and audit['all_verified']
    manifest['native_source_audit'] = audit
    fig, ax = canvas('Native-trace diagnostic', height=2.75, top=.67, bottom=.22)
    native_rows = [r for r in read_csv(native) if r['model'] in MODELS and float(r['budget_fraction']) == .4]
    plotted, statistics = [], {}
    methods = [('past_frequency', 'Past frequency', BLUE, 'o'), ('recent_first', 'Recent first', ORANGE, 's'), ('oracle', 'Oracle bound', GRAY, 'D')]
    for j, (method, label, color, marker) in enumerate(methods):
        for i, model in enumerate(MODELS):
            rr = [r for r in native_rows if r['model'] == model]
            assert len(rr) == 3
            values = np.array([float(r[method])*100 for r in rr])
            x = i + (j-1)*.23
            ax.vlines(x, values.min(), values.max(), color=color, linewidth=.8)
            ax.scatter(x+np.array([-.027, 0, .027]), values, s=14, marker=marker,
                       facecolors='white', edgecolors=color, linewidths=.7, zorder=3)
            ax.hlines(values.mean(), x-.07, x+.07, color=color, linewidth=2.0, zorder=4,
                      label=label if i == 0 else None)
            statistics.setdefault(model, {})[method] = dict(mean_pct=float(values.mean()), min_pct=float(values.min()), max_pct=float(values.max()))
            for r, value in zip(rr, values):
                plotted.append(dict(model=model, book_id=r['book_id'], method=method, coverage_pct=float(value), budget_blocks=205, total_blocks_per_layer=512, future_queries=64))
    ax.set(xticks=range(3), xticklabels=['NOSA-3B', 'MiniCPM4\n8B', 'Seer\nQwen3-8B'],
           ylabel='Future KV objects covered (%)', ylim=(0, 103), xlim=(-.5, 2.5))
    ax.set_yticks([0, 25, 50, 75, 100])
    handles = [Line2D([], [], color=c, marker=m, markerfacecolor='white', markersize=4, label=l) for _, l, c, m in methods]
    fig.legend(handles=handles, loc='upper center', bbox_to_anchor=(.52, .916), frameon=False, labelspacing=.15, borderaxespad=0)
    finish('eval-sparse-demand', fig, plotted, evidence='offline causal analysis of native selector captures',
           sources=[source(native), source(native_meta)], n={'documents_per_model': 3, 'checkpoints_per_document': 1},
           statistics=statistics, history_tokens=32768, observed_queries=[32257, 32768], future_queries=[32769, 32832],
           budget='205 of 512 all-head physical 64-token blocks per layer; mandatory sink/local reservations included',
           denominator='Distinct future-needed historical layer/block objects; sum hits/needed over layers within document, then equal document mean',
           limitations=['Historical occurrence-frequency baseline counts selector-group/head occurrences; not current deduplicated visibility-normalized ranking',
                        'Previously inspected PG19 documents; not a new holdout dataset or agentic workload',
                        'No transfer timing, physical failure, recovery, or WCT measurement', 'Seer is a pinned experimental native gate configuration'],
           caption='Future-demand coverage at K=205 of 512 physical blocks per layer. A ranking from the previous 512 queries predicts the next 64; mandatory blocks count toward the same budget. Open points are three documents; horizontal marks are their means. The historical-frequency baseline is distinct from the current visibility-normalized policy; the oracle knows future demand.')

    # Keep each deterministic grid case paired; do not imply repeated experiments.
    placement = ROOT / 'experiments/data/eurosys27/theory/scenario-results.csv'
    grouped = defaultdict(dict)
    for r in read_csv(placement):
        grouped[r['scenario_id']][r['policy']] = float(r['failure_penalty_s'])
    pairs = sorted((v['LRU']-v['AegisKV model'], k, v) for k, v in grouped.items())
    assert len(pairs) == 36
    win, tie, loss = sum(p[0] > 1e-8 for p in pairs), sum(abs(p[0]) <= 1e-8 for p in pairs), sum(p[0] < -1e-8 for p in pairs)
    assert (win, tie, loss) == (17, 19, 0)
    plotted = [dict(scenario_id=k, lru_penalty_s=v['LRU'], historical_value_penalty_s=v['AegisKV model'],
                    paired_reduction_s=d, cdf=(i+1)/36) for i, (d, k, v) in enumerate(pairs)]
    fig, ax = canvas('Historical placement model', height=2.35, top=.84, bottom=.23)
    x = np.array([p[0] for p in pairs]); y = np.arange(1, 37)/36
    ax.step(np.r_[0, x], np.r_[0, y], where='post', color=BLUE)
    ax.scatter([0], [tie/36], color=BLUE, s=18, zorder=4)
    ax.axvline(0, color=GRAY, ls=':', lw=.7)
    ax.text(.97, .12, '17 improve\n19 tie; 0 regress', transform=ax.transAxes, ha='right', va='bottom')
    ax.set(xlabel='Paired penalty reduction (s)', ylabel='Configuration fraction',
           xlim=(-.04*max(x), max(x)*1.055), ylim=(0, 1.03))
    ax.set_xticks([v for v in [0, 2, 4, 6, 8, 10, 12] if v <= max(x)])
    ax.set_yticks([0, .5, 1], ['0', '0.5', '1'])
    finish('eval-placement-pairs', fig, plotted, evidence='historical deterministic analytical model',
           sources=[source(placement), source(ROOT/'experiments/eurosys27/config.json'), source(ROOT/'experiments/scripts/eurosys27/theory.py')],
           n={'declared_configurations': 36, 'independent_runs': 0},
           statistics={'improve': win, 'tie': tie, 'regress': loss, 'max_reduction_s': float(max(x))},
           limitations=['Peer-disabled whole-checkpoint allocator, not current controller', 'LRU and reuse order coincide by construction in this instance',
                        'Generic assumed rates and failure probability; no hardware calibration', 'The grid is not a workload population or a worst-case guarantee'],
           caption='Paired LRU-minus-workflow-value failure penalties in 36 declared historical model configurations. Every case uses identical rates, bytes and resources for both policies: 17 improve and 19 tie. This deterministic Peer-disabled whole-checkpoint allocator is not the current online controller.')

    # Trace arrivals + old fixed service model: make tail regressions visible.
    trace = ROOT / 'experiments/data/eurosys27/expanded/raw/trace-replay.csv'
    trace_rows = read_csv(trace)
    fig, ax = canvas('Historical trace-driven model', height=2.65, top=.68, bottom=.18)
    plotted, statistics = [], {}
    for j, (method, label, color, marker) in enumerate([('Storage only', 'Storage only', GRAY, 'D'),
            ('LRU', 'LRU', ORANGE, 's'), ('AegisKV model', 'Workflow value', BLUE, 'o')]):
        values = np.array([float(r['penalty_s']) for r in trace_rows if r['policy'] == method])
        assert len(values) == 21738
        ys = [float(values.mean()), *np.quantile(values, [.5, .95, .99]).tolist()]
        statistics[method] = dict(zip(['mean_s', 'p50_s', 'p95_s', 'p99_s'], ys))
        for i, (metric, value) in enumerate(zip(['Mean', 'p50', 'p95', 'p99'], ys)):
            ax.scatter(i+(j-1)*.21, value, color=color, marker=marker, s=29, label=label if i == 0 else None, zorder=3)
            plotted.append(dict(policy=method, statistic=metric, penalty_s=value, recovery_episodes=len(values)))
    ax.set(yscale='log', xticks=range(4), xticklabels=['Mean', 'p50', 'p95', 'p99'],
           ylabel='Workflow penalty (s)', ylim=(1, 450), xlim=(-.5, 3.5))
    plain_log(ax, 'y', [1, 10, 100])
    legend(fig, ax, 1)
    finish('eval-trace-tails', fig, plotted, evidence='historical trace-driven queue model',
           sources=[source(trace), source(ROOT/'experiments/data/eurosys27/expanded/summary.json'), source(ROOT/'experiments/scripts/eurosys27/expanded.py')],
           n={'source_systems': 22, 'cleaned_intervals_per_policy': 21738, 'independent_campaigns': 0}, statistics=statistics,
           limitations=['LANL recorded start times feed one FIFO spare pool per system; no production serving replay',
                        'Service durations use the old four-branch model; outage repair durations do not govern capacity',
                        'One-minute timestamp resolution; pinned redistribution differs by two rows from official count',
                        'Mean improves while p95/p99 regress; not an availability measurement'],
           caption='Mean and tail penalties from the historical LANL-start-driven FIFO model (21,738 cleaned intervals in 22 systems). Workflow value reduces the mean but increases p95 and p99 versus LRU. Points are deterministic summaries of modeled episodes, without confidence intervals or physical serving claims.')

    rental = ROOT / 'exports/rental-diagnosis-20260921/RESULTS.json'
    rd = json.loads(rental.read_text())
    choices = [('Direct value', 'Direct'), ('Original rent', 'Original rent'),
               ('Rent + current-value refresh + two victims', 'Repaired rent')]
    fig, ax = canvas('Historical rental diagnosis', height=2.45, left=.28, top=.73, bottom=.23)
    plotted = []
    for i, (key, label) in enumerate(choices):
        r = rd['base'][key]
        ax.barh(i, r['miss'], .48, color=BLUE, edgecolor='#43505A', lw=.45, label='Miss cost' if i == 0 else None)
        ax.barh(i, r['movement'], .48, left=r['miss'], color=ORANGE, hatch='///', edgecolor='#43505A', lw=.45, label='Movement' if i == 0 else None)
        ax.text(r['total']+8, i, f"{r['total']:.2f}", va='center')
        plotted.append(dict(policy=key, **r))
    ax.set(yticks=range(3), yticklabels=[p[1] for p in choices], ylim=(2.55, -.55), xlim=(0, 630),
           xlabel='Cumulative cost (model units)')
    ax.set_xticks([0, 200, 400, 600])
    ax.grid(False); ax.grid(axis='x', color='#E1E6EA', lw=.45)
    legend(fig, ax, 2)
    finish('eval-rental-diagnostic', fig, plotted, evidence='historical constructed additive rental diagnosis',
           sources=[source(rental), source(ROOT/'exports/rental-diagnosis-20260921/base-events.csv'), source(ROOT/'experiments/scripts/eurosys27/diagnose_rental.py')],
           n={'objects': 24, 'equal_byte_slots': 8, 'candidate_opportunities': 512, 'independent_runs': 0},
           statistics={k: rd['base'][k] for k, _ in choices},
           limitations=rd['limitations']+['Repaired rent is not the current lazy, multi-Agent, exclusive three-tier controller'],
           caption='Preserved rental regression in a deterministic equal-byte model. Direct, original rent and repaired rent cost 462.96, 506.39 and 466.76 abstract units. The repair refreshes current value without refunding paid rent and examines two victims; it still exceeds direct cost and performs more scalar checks. These are neither CPU times nor current-controller results.')

    # Supporting horizon view: paired document differences retain weak effects.
    horizons = ROOT / 'experiments/data/retry-kv-z512/documents.csv'
    hrs = [r for r in read_csv(horizons) if int(r['selected_blocks_per_layer']) == 205]
    fig, ax = canvas('Native-trace diagnostic', height=2.7, top=.66, bottom=.19)
    plotted, statistics = [], {}
    for model, label, color, marker, style in [('NOSA-3B', 'NOSA-3B', BLUE, 'o', '-'),
            ('MiniCPM4-8B', 'MiniCPM4-8B', ORANGE, 's', '--'), ('SeerAttention-Qwen3-8B', 'Seer-Qwen3-8B', GREEN, '^', ':')]:
        xx, yy, low, high = [], [], [], []
        for target in [64, 128, 256, 512]:
            rr = [r for r in hrs if r['model'] == model and int(r['target_queries']) == target]
            assert len(rr) == 3
            values = np.array([100*(float(r['past_frequency'])-float(r['recent_first'])) for r in rr])
            xx.append(target); yy.append(values.mean()); low.append(values.min()); high.append(values.max())
            for r, value in zip(rr, values):
                plotted.append(dict(model=model, book_id=r['book_id'], future_queries=target,
                                    coverage_gain_percentage_points=float(value),
                                    frequency_coverage_pct=100*float(r['past_frequency']), recent_coverage_pct=100*float(r['recent_first']),
                                    blocks_per_layer=205))
        ax.plot(xx, yy, color=color, marker=marker, linestyle=style, ms=4, label=label)
        ax.fill_between(xx, low, high, color=color, alpha=.12, linewidth=0)
        ax.errorbar(xx, yy, yerr=[np.array(yy)-low, np.array(high)-yy], fmt='none', ecolor=color, lw=.7, capsize=2)
        statistics[model] = {str(x): dict(mean_pp=float(y), min_pp=float(a), max_pp=float(b)) for x, y, a, b in zip(xx, yy, low, high)}
    ax.axhline(0, color=GRAY, ls=':', lw=.8)
    ax.set(xscale='log', xlabel='Future queries', ylabel='Coverage gain (percentage points)', xlim=(54, 600))
    ax.set_xticks([64, 128, 256, 512], ['64', '128', '256', '512']); ax.xaxis.set_minor_locator(NullLocator())
    legend(fig, ax, 1)
    finish('eval-sparse-horizon', fig, plotted, evidence='offline native-trace horizon sensitivity',
           sources=[source(horizons), source(ROOT/'experiments/data/retry-kv-z512/protocol.json'), source(ROOT/'experiments/data/retry-kv-z512/source-sha256.json')],
           n={'documents_per_model': 3, 'checkpoints_per_document': 1}, statistics=statistics,
           aggregation='Paired document-level frequency minus recency coverage, then three-document mean and min-max',
           limitations=['Reused PG19 documents, not a new holdout', 'Historical occurrence frequency is not current visibility-normalized ranking',
                        'A fixed 205-block set per layer across each entire future window; no online refresh/recovery timing'],
           caption='Supporting horizon sensitivity at the same K=205 quota. Lines show the mean paired coverage gain of historical frequency over recent-first; bands and whiskers are three-document min-max. The fixed ranking uses the previous 512 queries and never sees target selections. Near-zero long-window gains are retained.')

    manifest['reproduction'] = f'python3 {Path(__file__).relative_to(REPO)} --out {out} --verify-native-sources'
    (out / 'figure-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({'figures': len(manifest['figures']), 'out': str(out), 'native_source_audit': audit}, indent=2))


if __name__ == '__main__':
    main()
