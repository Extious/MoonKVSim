"""Bounded checks of frozen inputs and revised Figure 1/2 encodings; no SDK/GPU runs."""
from pathlib import Path
import collections
import csv
import hashlib
import importlib.util
import json
import re

import pymupdf as fitz
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PAPER = ROOT / 'benchmark/AegisKV/paper'
DATA = ROOT / 'benchmark/AegisKV/experiments/data'
FIG = PAPER / 'figures/motivation-row'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

old_hashes = json.loads((OUT / 'motivation-input-hashes.json').read_text())
assert all(sha(ROOT / p) == h for p, h in old_hashes.items())
audit = json.loads((DATA / 'motivation-fanin-cc/group-audit.json').read_text())
retained = [r for r in audit if r['classification'] == 'retained_temporal_fanin']
assert len(audit) == 292 and len(retained) == 286
assert all(r['overlap_start_s'] < r['overlap_end_s'] and
           r['following_main_start_s'] >= r['last_branch_end_s'] and
           set(r['branch_statuses']) == {'completed'} for r in retained)

def gap_summary(rows):
    maxima = {}
    for r in rows:
        maxima[r['workflow_id']] = max(maxima.get(r['workflow_id'], 0), r['duration_gap_s'])
    vals = list(maxima.values())
    return dict(groups=len(rows), workflows=len(vals), median_workflow_max_s=float(np.median(vals)),
                p90_workflow_max_s=float(np.percentile(vals, 90)),
                median_group_gap_s=float(np.median([r['duration_gap_s'] for r in rows])))

full = gap_summary(retained)
assert full['workflows'] == 121
assert np.isclose(full['median_workflow_max_s'], 137.758)
assert np.isclose(full['p90_workflow_max_s'], 1172.684)
csv_rows = list(csv.DictReader((DATA / 'motivation-fanin-cc/workflow-parallel-gap.csv').open()))
assert np.allclose(sorted(float(r['max_duration_gap_s']) for r in csv_rows),
                   sorted(max(r['duration_gap_s'] for r in retained if r['workflow_id'] == w)
                          for w in {r['workflow_id'] for r in retained}))
lag_sensitivity = {str(limit): gap_summary([r for r in retained if r['last_finish_to_main_s'] <= limit])
                   for limit in [1, 5, 10, 30]}
selection = json.loads((DATA / 'motivation-compact-cc/SELECTION.json').read_text())
# A12: verify the selected active input against the original materialized
# source line, rather than inferring its provenance from derived CSV names.
excerpt = json.loads((DATA / 'motivation-compact-cc/selected-trace-excerpt.json').read_text())
with Path(selection['source_path']).open('rb') as stream:
    for line_number, raw in enumerate(stream, 1):
        if line_number == excerpt['source_line']:
            break
assert hashlib.sha256(raw).hexdigest() == excerpt['source_line_sha256']
workflow = json.loads(raw)
assert workflow['id'] == excerpt['workflow_id']
active_input_checks = []
for branch in excerpt['branches']:
    original = workflow['requests'][branch['top_level_index']]
    index = branch['prefix_request_index']
    request = original['requests'][index]
    assert request == branch['prefix_request']
    assert request['t'] < selection['failure_time_s'] < request['t'] + request['api_time']
    assert request['in'] == len(request['hash_ids']) * workflow['block_size']
    assert index < len(original['requests']) - 1
    active_input_checks.append(dict(request_index=index, input_proxy=request['in'],
                                   last_request_input_proxy=original['requests'][-1]['in']))
eligible = [c for c in selection['candidate_comparison'] if c['eligible']]
assert len(eligible) == 3
assert selection['selected_workflow_id'] + '-fanout-20' == max(eligible, key=lambda c:c['critical_prefix_tokens'])['fanout_id']
costs = json.loads((DATA / 'motivation-compact-cc/recovery-costs.json').read_text())['workflow_costs']
rows = list(csv.DictReader((DATA / 'motivation-compact-cc/compact-example-failure-position.csv').open()))
T = np.array([c['recompute_s'] for c in costs]); S = np.array([float(r['slack_s']) for r in rows])
counterfactual_sensitivity = []
for scale in [0.25, 0.5, 1, 2, 4]:
    losses = np.maximum(0, scale*T-S)
    counterfactual_sensitivity.append(dict(cost_multiplier=scale, losses_s=losses.tolist(),
                                         largest_loss_branch='A'+str(int(np.argmax(losses))+1)))

data = json.loads((DATA / 'reuse-aiconfigurator-max-context-h100/estimates.json').read_text())
assert len(data['rows']) == 25
assert all(q['args']['batch_size'] == 1 and q['memory']['total'] <= 80 for q in data['queries'].values())
figure_hashes = json.loads((OUT / 'motivation-round2-figure-hashes.json').read_text())
assert all(sha(ROOT / p) == h for p, h in figure_hashes.items())
bibliographies = '\n'.join(p.read_text() for p in [PAPER/'references.bib', PAPER/'sections/background_and_motivation.bib'])
for key in ['pan2025kvflow', 'ni2026topas', 'huang2026nosav2']:
    assert len(re.findall(r'@\w+\{' + key + r',', bibliographies)) == 1
spec = importlib.util.spec_from_file_location('motivation_renderer', ROOT / 'benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
figures = {}
mod.save = lambda fig, name, *a, **kw: figures.setdefault(name, fig)
mod.recompute(); mod.branch_gap()
fig = figures['motivation-recompute']; ax = fig.axes[0]
assert len(fig.axes) == 1 and np.allclose(fig.get_size_inches(), [3.34, 2.35])
curves = [l for l in ax.lines if not l.get_label().startswith('_')]
markers = [l for l in ax.lines if l.get_marker() in ['o', 's', '^', 'D']]
assert len(curves) == 12 and len(markers) == 75
keys = {'HBM reuse':'hbm_ms', 'DRAM reuse':'dram_ms', 'Recompute':'recompute_ms'}
styles = {'HBM reuse':'-', 'DRAM reuse':'--', 'Recompute':':'}
shape = {'Qwen3-14B':'o', 'Llama-3.1-70B':'s', 'Qwen3-235B-A22B-Instruct-2507':'^', 'DeepSeek-V3.2':'D'}
for curve in curves:
    model, path = curve.get_label().split(': ')
    rr = sorted([r for r in data['rows'] if r['model'] == model], key=lambda r:r['total_tokens'])
    assert np.allclose(curve.get_xdata(), [r['total_tokens'] for r in rr])
    assert np.allclose(curve.get_ydata(), [r[keys[path]] for r in rr])
    assert curve.get_linestyle() == styles[path]
    assert rr[-1]['total_tokens'] == data['models'][model]['context_limit']
for r in data['rows']:
    hollow = r['dsa_beyond_table_context'] or r['qwen_full_attention_projection']
    assert r['total_tokens'] == r['context_tokens'] + 64
    assert np.isclose(r['dram_ms']-r['hbm_ms'], r['h2d_ms'])
    for k in keys.values():
        matches = [m for m in markers if m.get_marker() == shape[r['model']] and
                   m.get_xdata()[0] == r['total_tokens'] and np.isclose(m.get_ydata()[0], r[k])]
        assert len(matches) == 1 and (matches[0].get_markerfacecolor() == 'white') == hollow
    # Check the isolated-delay bound introduced in section 2.4.
    d,h = r['dram_ms'],r['hbm_ms']
    for slack in [0, h/2, h, (d+h)/2, d, 2*d]:
        benefit=max(0,d-slack)-max(0,h-slack)
        assert -1e-8 <= benefit <= d-h+1e-8
        if slack >= d: assert benefit == 0

renders = OUT / 'motivation-renders'; renders.mkdir(exist_ok=True)
pdf_checks = {}
for filename, width in [('motivation-branch-gap.pdf',2.24),('motivation-workflow.drawio.pdf',2.24),
                        ('motivation-recovery-exposure.pdf',2.24),('motivation-recompute.pdf',3.33402)]:
    doc = fitz.open(FIG / filename); page=doc[0]
    spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
    # Workflow also has a keepaspectratio height constraint in the TeX input.
    scale = width*72/page.rect.width
    if 'workflow' in filename: scale=min(scale, 1.85*72/page.rect.height)
    minimum=min(s['size']*scale for s in spans)
    assert minimum >= 10
    assert all(page.rect.contains(fitz.Rect(s['bbox'])) for s in spans)
    pdf_checks[filename]=dict(effective_min_font_pt=minimum,sha256=sha(FIG/filename),width_pt=page.rect.width,height_pt=page.rect.height)
    page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(renders/(filename+'.png'))
    page.get_pixmap(matrix=fitz.Matrix(2,2),colorspace=fitz.csGRAY,alpha=False).save(renders/(filename+'.gray.png'))

preview_path=OUT/'motivation-preview/motivation-preview.pdf'
preview=fitz.open(preview_path)
for i,p in enumerate(preview):
    p.get_pixmap(matrix=fitz.Matrix(1.4,1.4),alpha=False).save(renders/f'preview-page-{i+1}.png')
figure2_page=[i+1 for i,p in enumerate(preview)
              if 'Static recovery estimates, compared within each model.' in ' '.join(p.get_text().split())][0]
log=(preview_path.with_suffix('.log')).read_text()
assert not re.search(r'Overfull|undefined|LaTeX Warning|Package .* Warning|^!', log, re.M)
result=dict(status='numerical_and_metadata_checks_passed_visual_review_separate',
            frozen_input_files_unchanged=len(old_hashes), trace_population=full,
            main_activity=dict(submissions=sum(r['main_requests_submitted_during_branches']>0 for r in retained),
                               executing=sum(r['main_requests_executing_during_branches']>0 for r in retained)),
            temporal_proxy_lag_limit_sensitivity=lag_sensitivity,
            sensitivity_boundary='Post-hoc temporal filters, not verified dependencies or population slack; figure data unchanged.',
            eligible_illustration_candidates=len(eligible), cost_scale_sensitivity=counterfactual_sensitivity,
            active_request_input_provenance=active_input_checks,
            rank_capacity=dict(queried_shapes=len(data['queries']),batch_size=1,
                               maximum_static_gib_per_rank=max(q['memory']['total'] for q in data['queries'].values())),
            final_round_figure_files_unchanged=len(figure_hashes),
            closest_work_citations_unique=True,
            cost_scale_boundary='Uniformly scaled static costs, with same offline slack; not new measurements or recalibrated models.',
            figure2=dict(configurations=25,paths=3,unchanged_values=75,curves=12,marker_points=75,
                         hollow_values=sum(r['dsa_beyond_table_context'] or r['qwen_full_attention_projection'] for r in data['rows'])*3,
                         single_axis=True,size_inches=[3.34,2.35]),
            figure_pdf_checks=pdf_checks, preview=dict(path=str(preview_path.relative_to(ROOT)),sha256=sha(preview_path),
            pages=len(preview),figure2_page=figure2_page,overfull=0,undefined_citations=0,
            underfull_hboxes=len(re.findall(r'Underfull \\hbox',log))),main_pdf_built=False,gpu_or_sdk_runs=False)
(OUT/'motivation-checks.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
