#!/usr/bin/env python3
"""Audit current Evaluation sources, aggregations, publication and planned counts.

This is an artifact/data audit, not a serving-system correctness or performance
test. Run after publishing the selected assets and compiling paper/main.pdf.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import fitz
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / 'experiments/eurosys27'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def csv_rows(path):
    with Path(path).open() as stream:
        return list(csv.DictReader(stream))


def close(a, b):
    assert math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-9), (a, b)


def audit_tables(out):
    tables = {p.stem: csv_rows(p) for p in (out / 'plot-data').glob('eval-*.csv')}
    phys = { (r['path'], r['context_tokens']): r for r in csv_rows(
        ROOT/'experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/measured.csv') }
    rows = tables['eval-recovery-paths']
    assert len(rows) == len(phys)
    for r in rows:
        original = phys[(r['path'], r['context_tokens'])]
        close(r['latency_s'], float(original['latency_ms']) / 1000)
        assert int(r['timing_repeats']) == int(original['timing_repeats_per_input'])
        if int(r['timing_repeats']) > 1:
            close(r['min_s'], float(original['trial_min_ms']) / 1000)
            close(r['max_s'], float(original['trial_max_ms']) / 1000)
        else:
            assert r['min_s'] == r['max_s'] == ''

    predictions = {(r['workflow_id'], r['agent_id']): r for r in csv_rows(
        ROOT/'experiments/data/agent-gbdt-steps/primary-landmark.csv')}
    methods = defaultdict(list)
    for r in tables['eval-tracker-errors']:
        original = predictions[(r['workflow_id'], r['agent_id'])]
        assert r['fold'] == original['fold']
        close(r['absolute_error_s'], abs(float(original[r['method']+'_s']) - float(original['actual_remaining_s'])))
        methods[r['method']].append(r)
    for rows in methods.values():
        assert len(rows) == len(predictions)
        assert len({(r['workflow_id'], r['agent_id']) for r in rows}) == len(predictions)
        assert all(float(a['absolute_error_s']) <= float(b['absolute_error_s']) for a, b in zip(rows, rows[1:]))
        for i, r in enumerate(rows):
            close(r['cdf'], (i + 1) / len(rows))

    native = {(r['model'], r['book_id']): r for r in csv_rows(
        ROOT/'experiments/data/design-insights/retry-kv-documents.csv') if float(r['budget_fraction']) == .4}
    for r in tables['eval-sparse-demand']:
        original = native[(r['model'], r['book_id'])]
        close(r['coverage_pct'], 100 * float(original[r['method']]))
        assert int(r['budget_blocks']) == math.ceil(.4 * int(r['total_blocks_per_layer']))
        assert 0 <= float(r['coverage_pct']) <= 100
    horizons = {(r['model'], r['book_id'], r['target_queries']): r for r in csv_rows(
        ROOT/'experiments/data/retry-kv-z512/documents.csv') if int(r['selected_blocks_per_layer']) == 205}
    for r in tables['eval-sparse-horizon']:
        original = horizons[(r['model'], r['book_id'], r['future_queries'])]
        close(r['frequency_coverage_pct'], 100 * float(original['past_frequency']))
        close(r['recent_coverage_pct'], 100 * float(original['recent_first']))
        close(r['coverage_gain_percentage_points'], float(r['frequency_coverage_pct']) - float(r['recent_coverage_pct']))

    scenarios = defaultdict(dict)
    for r in csv_rows(ROOT/'experiments/data/eurosys27/theory/scenario-results.csv'):
        scenarios[r['scenario_id']][r['policy']] = float(r['failure_penalty_s'])
    for r in tables['eval-placement-pairs']:
        original = scenarios[r['scenario_id']]
        close(r['lru_penalty_s'], original['LRU'])
        close(r['historical_value_penalty_s'], original['AegisKV model'])
        close(r['paired_reduction_s'], original['LRU'] - original['AegisKV model'])
    assert len(tables['eval-placement-pairs']) == len(scenarios)

    episodes = defaultdict(list)
    for r in csv_rows(ROOT/'experiments/data/eurosys27/expanded/raw/trace-replay.csv'):
        episodes[r['policy']].append(float(r['penalty_s']))
    for r in tables['eval-trace-tails']:
        values = episodes[r['policy']]
        target = np.mean(values) if r['statistic'] == 'Mean' else np.quantile(values, float(r['statistic'][1:]) / 100)
        close(r['penalty_s'], target)
        assert int(r['recovery_episodes']) == len(values)
    rental = json.loads((ROOT/'exports/rental-diagnosis-20260921/RESULTS.json').read_text())
    for r in tables['eval-rental-diagnostic']:
        for key, value in rental['base'][r['policy']].items():
            close(r[key], value)
        close(r['total'], float(r['miss']) + float(r['movement']))
    return {name: len(rows) for name, rows in tables.items()}


def audit_campaign():
    path = DOC / 'campaign-plan.json'
    if not path.exists():
        return {'status': 'not_yet_present'}
    plan = json.loads(path.read_text())
    cells = plan['cells']
    assert len({r['cell_id'] for r in cells}) == len(cells)
    for r in cells:
        assert r['planned_campaigns'] > 0 and r['conditions']
        assert len(set(r['conditions'])) == len(r['conditions'])
        assert r['run_slots'] == r['planned_campaigns'] * len(r['conditions'])
        assert 0 <= r['actual_runs'] <= r['run_slots']
        if r['status'] == 'planned':
            assert r['actual_runs'] == 0
    selections = {
        'minimum': [r for r in cells if r['suite'] == 'minimum'],
        'extended': [r for r in cells if r['suite'] == 'extended'],
        'minimum_primary': [r for r in cells if r['comparison_block'].startswith('minimum.primary_')],
        'all_explicit_cells': cells,
    }
    computed = {}
    for name, rows in selections.items():
        campaigns = defaultdict(set)
        for r in rows:
            campaigns[r['comparison_block']].add(r['planned_campaigns'])
        assert all(len(v) == 1 for v in campaigns.values())
        values = dict(cells=len(rows), comparison_blocks=len(campaigns),
                      planned_paired_campaigns=sum(next(iter(v)) for v in campaigns.values()),
                      planned_run_slots=sum(r['run_slots'] for r in rows), actual_runs=sum(r['actual_runs'] for r in rows))
        assert values == plan['counts'][name], (name, values, plan['counts'][name])
        computed[name] = values
    if plan['status'] == 'planned_not_executed':
        assert not any(r['actual_runs'] for r in cells)
        assert plan['statistics']['physical_run_count'] == 0
    return dict(status=plan['status'], sha256=sha(path), checked='plan arithmetic and declared status only', counts=computed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact-only', action='store_true', help='Skip current-paper publication/build checks.')
    args = parser.parse_args()
    selection = json.loads((DOC / 'main-figures.json').read_text())
    out = (DOC / selection['export_directory']).resolve()
    manifest_path = (DOC / selection['figure_manifest']).resolve()
    manifest = json.loads(manifest_path.read_text())
    selected = selection['main'] + selection['supplementary']
    assert len(set(selected)) == len(selected)
    assert set(selected) == set(manifest['figures'])
    for name, digest in manifest['sources'].items():
        assert sha(ROOT / name) == digest, 'Changed source: ' + name
    assert sha(ROOT / manifest['renderer']) == manifest['renderer_sha256']
    figures = []
    for name in selected:
        entry = manifest['figures'][name]
        assert sha(out / 'plot-data' / (name + '.csv')) == entry['table_sha256']
        for artifact in entry['artifacts'].values():
            assert sha(out / artifact['path']) == artifact['sha256']
        doc = fitz.open(out / entry['artifacts']['pdf']['path'])
        assert len(doc) == 1
        page = doc[0]
        assert math.isclose(page.rect.width / 72, entry['width_in'], abs_tol=1e-6)
        spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans'] if s['text'].strip()]
        assert spans and min(s['size'] for s in spans) >= 10
        figures.append(dict(figure=name, native_minimum_font_pt=min(s['size'] for s in spans)))
    rows = audit_tables(out)
    campaign = audit_campaign()
    paper_report = {'checked': False}
    if not args.artifact_only:
        paper = ROOT / 'paper'
        assert re.search(r'\\input\{evaluation\}', (paper/'main.tex').read_text())
        evaluation = (paper/'evaluation.tex').read_text()
        assets = re.findall(r'\\includegraphics\[width=\\columnwidth\]\{([^}]+)\}', evaluation)
        assert [Path(p).stem for p in assets] == selection['main']
        assert len(assets) == 6
        log = (ROOT/'exports/latex-build/main.log').read_text(errors='replace')
        errors = [line for line in log.splitlines() if re.search(r'Overfull|undefined references|undefined citations|LaTeX Error|Emergency stop', line)]
        assert not errors, errors
        placed = {m.group(1): float(m.group(2))*72/72.27 for m in re.finditer(
            r'Package pdftex.def Info: (figures/\S+\.pdf)\s+used.*?Requested size: ([0-9.]+)pt', log, re.S)}
        placed_fonts = []
        for asset in assets:
            name = Path(asset).stem
            assert sha(paper/asset) == manifest['figures'][name]['artifacts']['pdf']['sha256']
            doc = fitz.open(paper/asset); page = doc[0]
            assert asset in placed, 'Missing placement in build log: ' + asset
            scale = placed[asset]/page.rect.width
            sizes = [s['size']*scale for b in page.get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans'] if s['text'].strip()]
            assert min(sizes) >= 10, (asset, min(sizes))
            placed_fonts.append(dict(asset=asset, placed_width_bp=placed[asset], min_font_bp=min(sizes)))
        compiled = fitz.open(paper/'main.pdf')
        paper_report = dict(checked=True, root_input='evaluation.tex', figures=len(assets),
                            paper_sha256=sha(paper/'main.pdf'), pages=len(compiled), placed_fonts=placed_fonts)
    report = dict(status='PASS', scope='Current artifact/data/provenance and optional manuscript audit; no serving execution',
                  figure_manifest_sha256=sha(manifest_path), selection_sha256=sha(DOC/'main-figures.json'),
                  main_figures=len(selection['main']), supplementary_figures=len(selection['supplementary']),
                  row_counts=rows, fonts=figures, campaign=campaign, paper=paper_report,
                  native_source_audit='Previously verified 400-source audit retained in figure-manifest; not rerun here')
    (out/'CHECKS-evaluation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
