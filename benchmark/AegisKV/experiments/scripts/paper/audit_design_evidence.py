#!/usr/bin/env python3
"""Scoped arithmetic/provenance and final-width review for Design figures."""
from pathlib import Path
import csv, json, hashlib, re, xml.etree.ElementTree as ET
import pymupdf as fitz
import numpy as np
from model_storage_overlap import validate, schedule
BASE=Path(__file__).resolve().parents[3]
OUT=BASE/'exports/design-evidence-review-20260921'


def main():
    evidence=json.loads((OUT/'data/EVIDENCE.json').read_text())
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    for path,h in evidence['source_hashes'].items():
        assert sha(BASE/path)==h
    summary=json.loads((BASE/'experiments/data/design-insights/retry-kv-summary.json').read_text())
    docrows=list(csv.DictReader((BASE/'experiments/data/design-insights/retry-kv-documents.csv').open()))
    for model in summary['main_figure_models']:
        rows=[r for r in docrows if r['model']==model and float(r['budget_fraction'])==.4]
        assert len(rows)==len({r['book_id'] for r in rows})==3
        for key in ['past_frequency','recent_first','oracle','needed_fraction']:
            x=np.array([float(r[key]) for r in rows])
            assert np.all((0<=x)&(x<=1))
            for name,fun in [('mean',np.mean),('min',np.min),('max',np.max)]:
                assert abs(fun(x)-summary['summary'][model][key][name])<1e-10
    rows=list(csv.DictReader((BASE/'experiments/data/agent-prefix-reuse/same-model-reuse-scope.csv').open()))
    for r in rows:
        total=int(r['input_tokens'])
        assert sum(int(r[k]) for k in ['same_agent_tokens','cross_agent_only_tokens','new_tokens'])==total
        for raw,percent in [('same_agent_tokens','same_agent_share_pct'),('raw_cross_overlap_tokens','raw_cross_overlap_share_pct'),('cross_agent_only_tokens','cross_agent_only_share_pct')]:
            assert abs(100*int(r[raw])/total-float(r[percent]))<1e-6
    allrow=next(r for r in rows if r['request_class']=='all')
    assert int(allrow['requests'])==98827 and int(allrow['agents'])==2090 and int(allrow['workflows'])==393
    assert sum(int(r['requests']) for r in rows if r['request_class']!='all')==98827
    native=ET.parse(OUT/'sources/system-overview.drawio')
    cells=native.findall('.//mxCell');ids={c.get('id') for c in cells};assert len(ids)==len(cells)
    for c in cells:
        for k in ['parent','source','target']:
            assert c.get(k) is None or c.get(k) in ids
    assert {'application','controller','engine','cost','rental','joint-check','directory'}<=ids
    pipeline_checks=validate()
    for r in csv.DictReader((BASE/'exports/system-design-dram-ssd-20260920/data/overlap-frontier.csv').open()):
        assert schedule(range(1,int(r['dram_groups'])+1),float(r['compute_ms']))[1]==float(r['total_ms'])
    stage_rows=list(csv.DictReader((BASE/'exports/design-figure-revision-20260920/data/pipeline-events.csv').open()))
    for name,res in [('All groups on SSD',set()),('Layer 4 in DRAM',{4}),('Layer 1 in DRAM',{1})]:
        jobs,total=schedule(res)
        got=[(r['stage'],int(r['layer']),float(r['start']),float(r['end'])) for r in stage_rows if r['case']==name]
        expected=[(r['stage'],r['layer'],r['start'],r['end']) for r in jobs]
        assert got==expected
    text=(BASE/'paper/system_design.tex').read_text()
    stems=re.findall(r'includegraphics\[width=\\columnwidth\]\{figures/([^}]+)\.pdf\}',text)
    widths=(505.89-24)/2*72/72.27
    fonts={}
    for stem in stems:
        pth=BASE/f'paper/figures/{stem}.pdf'; doc=fitz.open(pth);p=doc[0];scale=widths/p.rect.width
        spans=[s for b in p.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
        fonts[stem]={'width_mm':widths*25.4/72,'height_mm':p.rect.height*scale*25.4/72,
                     'min_text_pt':min(s['size'] for s in spans)*scale,'sha256':sha(pth)}
        assert fonts[stem]['min_text_pt']>=10, (stem,fonts[stem])
        for suffix,colorspace in [('column',fitz.csRGB),('gray',fitz.csGRAY)]:
            p.get_pixmap(matrix=fitz.Matrix(scale*160/72,scale*160/72),colorspace=colorspace).save(OUT/f'review/{stem}-{suffix}.png')
    report={'arithmetic_checks':{'native_means_ranges_and_oracle':True,'prefix_denominators_and_counts':True,
             'matched_tracker_ids_targets_and_metrics':'checked in render_design_evidence.py',
             'pipeline_resource_schedules':pipeline_checks,'frontier_curves_match_scheduler':True,
             'native_overview_ids_and_edges':True},
      'scope':'existing recorded tables and analytical schedules; no native-model rerun, model refit or fault injection',
      'no_claim':['rent superiority','validated segment Slack','end-to-end recovery speedup','backend correctness'],
      'font_and_size':fonts}
    (OUT/'review/AUDIT.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
